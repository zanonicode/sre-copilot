# DESIGN: SRE Copilot

> Technical design for a kind-native, locally-runnable SRE Copilot platform: streaming LLM log analysis + postmortem generation, full LGTM observability, GitOps via ArgoCD, progressive delivery via Argo Rollouts, target cold-start <5 min on M3/16 GB MacBook.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | sre-copilot |
| **Date** | 2026-04-26 |
| **Author** | design-agent |
| **Phase** | 2 — Design |
| **Status** | S5 Complete (Built) — v1.7 — ready for /ship |
| **Source** | `.claude/sdd/features/DEFINE_sre-copilot.md` (14/15 clarity, all FRs/NFRs/ATs locked) |
| **Sprint Span** | S1 (Foundations) → S2 (Kubernetes Native) → S3 (GitOps & Observability) → S4 (Polish) → S5 (TLS, Observability Pipeline, Dashboards, Canary, Bootstrap, Eval) |

---

## Table of Contents

1. Architecture Overview
2. Architecture Decision Records (ADR-001 → ADR-013)
3. File Manifest (per-sprint, module-level)
4. Code Patterns (copy-paste skeletons)
5. Testing Strategy (AT-001 → AT-013 mapping)
6. Memory Budget Plan
7. Cold-Start Performance Plan
8. Demo Script Design (`make demo`)
9. Carried-Forward Design Items (resolved)
10. Open Questions Carried to /build
11. Known Environmental Gotchas (S1 runtime discoveries)
12. Known Issues / Tech Debt (Sprint 2 cleanup items)

---

## 1. Architecture Overview

### 1.1 Hero Diagram (refined: Lean kit + 2-replica backend + ExternalName host hop)

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       Reviewer Browser  (desktop Chrome)                        │
│                          https://sre-copilot.localtest.me                       │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │  HTTPS  +  SSE (text/event-stream)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                kind cluster: sre-copilot   (3 nodes — Docker Desktop)           │
│                                                                                 │
│  control-plane                worker-platform                worker-apps        │
│  ┌────────────┐              ┌─────────────────────┐        ┌──────────────┐    │
│  │ apiserver  │              │ argocd              │        │ frontend ×1  │    │
│  │ etcd       │              │ sealed-secrets      │        │ (Next.js)    │    │
│  │ scheduler  │              │ argo-rollouts       │        │              │    │
│  └────────────┘              │ traefik (ingress)   │◀──────▶│ backend ×2   │    │
│                              │ otel-collector      │  REST/ │ (FastAPI)    │    │
│                              │ loki / tempo / prom │   SSE  │ + PDB + HPA  │    │
│                              │ grafana             │        │ + Rollout    │    │
│                              └──────────┬──────────┘        │              │    │
│                                         │                   └──────┬───────┘    │
│                                         │  OTLP push                            │
│                                         │                          │            │
│                                         │                          │ HTTP       │
│                                         │                          ▼            │
│                                         │             ┌────────────────────┐    │
│                                         │             │ Service: ollama    │    │
│                                         │             │ type: ExternalName │    │
│                                         │             │ → host.docker      │    │
│                                         │             │   .internal:11434  │    │
│                                         │             └─────────┬──────────┘    │
└─────────────────────────────────────────┼───────────────────────┼───────────────┘
                                          │                       │
                                          │   NetworkPolicy:      │
                                          │   egress allow-list   │
                                          │   = DNS + 11434 +     │
                                          │     in-cluster only   │
                                          ▼                       ▼
                          ┌───────────────────────────────────────────────┐
                          │             macOS host (M3 / 16 GB)           │
                          │                                               │
                          │   ┌─────────────────────────────────────────┐ │
                          │   │ Ollama  (port 11434, OpenAI-compatible) │ │
                          │   │   model:  qwen2.5:7b-instruct-q4_K_M    │ │
                          │   │   judge:  llama3.1:8b-instruct-q4_K_M   │ │
                          │   │   accel:  Apple Metal / MPS (native)    │ │
                          │   └─────────────────────────────────────────┘ │
                          └───────────────────────────────────────────────┘
```

### 1.2 Component Inventory

| Layer | Component | Replicas | Node | Memory (target RSS) |
|-------|-----------|----------|------|---------------------|
| **kind nodes** | control-plane | 1 | — | 600 MB |
| | worker-platform | 1 | — | 400 MB (kubelet only) |
| | worker-apps | 1 | — | 400 MB (kubelet only) |
| **Namespaces** | `sre-copilot` (apps), `platform` (ingress, GitOps), `observability` (LGTM, OTel), `kube-system` | — | — | — |
| **Workloads (apps)** | frontend (Next.js) | 1 | apps | 250 MB |
| | backend (FastAPI) | 2 | apps | 350 MB each = 700 MB |
| **Workloads (platform)** | traefik | 1 | platform | 120 MB |
| | argocd (server + repo + controller) | 1 each | platform | 600 MB |
| | sealed-secrets-controller | 1 | platform | 60 MB |
| | argo-rollouts-controller | 1 | platform | 80 MB |
| **Workloads (observability)** | otel-collector | 1 (DaemonSet→1 worker) | platform | 150 MB |
| | loki (single-binary) | 1 | platform | 350 MB |
| | tempo (monolithic) | 1 | platform | 250 MB |
| | prometheus (Mimir-replaced for memory) | 1 | platform | 500 MB |
| | grafana | 1 | platform | 180 MB |
| **Host services** | Ollama + Qwen 2.5 7B Q4 (loaded) | 1 | host | 5.5 GB |
| | Llama 3.1 8B (judge, on-demand) | — | host | 5.8 GB (only during eval) |
| **Total committed (steady)** | | | | **~10.5 GB** + Chrome (~1.5 GB) + Docker overhead (~1.5 GB) = **~13.5 GB** |

### 1.3 Request Flow — LLM Streaming (browser → host Ollama → SSE back)

```text
[Browser]  POST /api/analyze/logs
    │     Content-Type: application/json
    │     Accept: text/event-stream
    │     traceparent: 00-<trace_id>-<span_id>-01
    ▼
[Traefik Ingress]  TLS terminate, route to svc/frontend or svc/backend
    │     (UI calls go to frontend; /api/* are proxied direct to backend)
    ▼
[backend pod]  FastAPI /analyze/logs handler
    │     1. otel middleware extracts traceparent → opens span "http.server"
    │     2. validate Pydantic input → 400 on malformed (AT-008)
    │     3. open child span "prompt.assemble"  (loads few-shot template)
    │     4. open child span "ollama.host_call" (synthetic — see §9.2)
    │         attributes: llm.model, llm.input_tokens, llm.endpoint
    │     5. async iterator from openai.AsyncOpenAI(base_url=ollama_svc)
    ▼
[Service ollama  type: ExternalName]
    │     DNS CNAME → host.docker.internal
    ▼
[host:11434]  Ollama → Qwen 2.5 7B Q4 on Metal
    │     streams OpenAI-compatible chunks (data: {"choices":[...]})
    ▼
[backend pod]  async-for chunk in stream:
    │     - increment llm_tokens_output_total
    │     - emit SSE frame:  data: {"token":"...", "type":"delta"}\n\n
    │     - on first chunk: record llm.ttft_seconds histogram
    │     - on cancel (client disconnect): aclose() upstream → close span "cancelled" (AT-009)
    ▼
[Browser]  EventSource consumes SSE; React state appends tokens; final
           data: {"type":"done", "json":{...5 fields...}} closes the stream.
```

### 1.4 Trace Propagation Diagram (incl. synthetic Ollama span)

```text
trace_id = T1   (W3C traceparent injected by browser fetch)
│
├─ span: http.server  (FastAPI middleware, kind=SERVER)         [backend pod]
│   ├─ span: input.validate   (Pydantic)                        [backend pod]
│   ├─ span: prompt.assemble  (template + few-shot)             [backend pod]
│   ├─ span: ollama.host_call  kind=CLIENT                      [backend pod]
│   │       attrs: peer.service=ollama-host
│   │              net.peer.name=host.docker.internal
│   │              net.peer.port=11434
│   │              llm.model=qwen2.5:7b-instruct-q4_K_M
│   │              llm.input_tokens=412
│   │       events: [first_token@420ms, last_token@3.2s]
│   │   │
│   │   └─ span: ollama.inference  kind=INTERNAL  (SYNTHETIC)   [backend pod]
│   │           attrs: llm.output_tokens=287
│   │                  llm.ttft_seconds=0.42
│   │                  llm.duration_seconds=2.78
│   │                  llm.tokens_per_second=103.2
│   │           (See §9.2 — created by backend after stream end,
│   │            with start/end timestamps from chunk arrival times.
│   │            This is the only way to attribute host-side latency
│   │            without modifying Ollama.)
│   │
│   └─ span: sse.stream    (per-chunk events)                   [backend pod]
│
OTLP → otel-collector → Tempo (storage) ── Grafana (Tempo data source) view
```

### 1.5 Grounding-Data Flow (datasets → prompt → eval)

```text
datasets/                          src/backend/prompts/       tests/eval/
├── loghub/hdfs/                   ├── log_analyzer.j2  ◀──┐  ├── structural/
│   ├── HDFS.log                   ├── postmortem.j2       │  │   test_schema.py
│   └── anomaly_label.csv          └── few_shots/          │  │   test_sse.py
│        │                              hdfs_datanode.txt  │  └── judge/
│        │ (subset selector)            cloudflare_pm.txt  │      run_judge.py
│        ▼                                                  │      rubric.yaml
│   sample_loader.py                                        │
│        │                                                  │
│        ▼                              ┌──────────────────┘
│   ground_truth/                       │
│        hdfs_001.json  ◀───── compare ─┤  (eval ground truth references
│        hdfs_002.json  ◀───── compare ─┤   the same incident IDs the UI
│                                       │   sample buttons load)
└── postmortems/                        │
    ├── real/cloudflare_2024.md  ──────┤   (few-shot exemplar)
    ├── real/github_2024.md      ──────┤
    ├── synth/incident_001.md    ──────┘
    └── synth/incident_002.md
```

---

## 2. Architecture Decision Records

### ADR-001: kind-native runtime from day 1 (no docker-compose detour)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |
| **Supersedes** | Sprint-1 plan-§7 (which proposed docker-compose first) |

**Context.** The project is a portfolio signal for Kubernetes / SRE / platform-engineering literacy. Sprint 1 of the original plan proposed a docker-compose foundation followed by a kind migration in Sprint 2. This double-builds the deployment artefact for no narrative gain.

**Choice.** Use kind from day 1. Tilt closes the inner-loop developer experience that compose was supposed to solve (file-watch → image rebuild → pod replace). All workloads are deployed via Helm from the first commit; ArgoCD is layered on in S3.

**Rationale.**
- Compose hides exactly what we want to demonstrate: Pods, Services, Ingress, NetworkPolicy, PDB, Rollouts.
- A mid-project rewrite from compose to k8s is throwaway work that competes with Sprint-2 deliverables.
- Tilt provides hot-reload for backend/frontend equivalent to compose's UX.
- Reviewers won't see compose anyway — they see `make up` → kind.

**Alternatives rejected.**
1. **Docker Compose first, kind later (original plan).** Rejected: doubles work, hides the signal.
2. **k3d instead of kind.** Rejected: kind has stronger Docker Desktop integration on macOS and is the conventional choice in CNCF training material reviewers will recognise.
3. **minikube.** Rejected: heavier resource footprint, less Docker-native, slower cold start.

**Consequences.**
- Sprint 1 must include a minimal Helm chart (not "just run uvicorn") — slightly higher S1 cost.
- All developers need Docker Desktop / OrbStack 4.30+. Documented in README prerequisites.
- Tilt becomes a required (not optional) inner-loop tool — `Tiltfile` ships in repo root.

---

### ADR-002: Lean platform kit (Sealed Secrets + Argo Rollouts deployed; Kyverno / Trivy Operator / Chaos Mesh documented-only)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

**Context.** The 16 GB RAM budget cannot accommodate the full "Maximal" platform kit (ArgoCD + Sealed Secrets + Argo Rollouts + Kyverno + Trivy Operator + Chaos Mesh + LGTM + OTel + 2 backend replicas + Ollama). BRAINSTORM §2 selected the Lean variant. Reviewers also cannot absorb a tour of every CNCF project in a 10-minute walkthrough — components without a *visible moment* in the demo dilute the signal.

**Choice.** Deploy: ArgoCD, Sealed Secrets, Argo Rollouts, Traefik, full LGTM, OTel Collector. Document only (in `docs/policy.md`, `docs/security.md`, `docs/chaos.md`): Kyverno, Trivy Operator, Chaos Mesh. Keep one-shot `trivy image` in CI as a low-cost visible signal.

**Rationale.**
- Each *deployed* component has a narrated demo moment: ArgoCD sync (GitOps), Sealed Secrets (kubeseal flow), Argo Rollouts (canary panel), LGTM (every dashboard), OTel (traces tab).
- Documented-only components prove awareness without paying memory or demo-time tax.
- Trivy as a CI step (vs Operator) shows supply-chain literacy in PR checks — reviewers see it without it consuming cluster RAM.

**Alternatives rejected.**
1. **Maximal kit.** Rejected: blows RAM budget; no narrative room.
2. **Security-forward (Kyverno + Trivy Operator).** Rejected: continuous admission control has no visible moment in 10 min.
3. **Resilience-forward (Chaos Mesh).** Rejected: chaos experiments are flaky on stage; canary tells a stronger, deterministic resilience story.

**Consequences.**
- README must explicitly state which platform components are deployed vs documented, to pre-empt "you skipped Kyverno" critique.
- `docs/policy.md`, `docs/security.md`, `docs/chaos.md` become first-class deliverables, not afterthoughts.
- The repo gets a clean v1.1 expansion path: each documented component already has a stub doc explaining where it would slot in.

---

### ADR-003: Ollama on host via `ExternalName` Service (no in-cluster GPU containers)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

**Context.** Apple Silicon GPUs are accessed through Metal Performance Shaders (MPS). MPS is **not** exposed inside Docker containers on macOS — there is no equivalent of `nvidia-container-runtime` for Metal. Running Ollama in the cluster would force CPU-only inference on Qwen 2.5 7B, which exceeds the 30-second p90 latency SLO by an order of magnitude.

**Choice.** Run Ollama as a host process (started by `make seed-models` and a launchd-style helper). Expose into the cluster via a Kubernetes `Service` of `type: ExternalName` whose `externalName` field is `host.docker.internal`. Backend pods address it as `http://ollama.sre-copilot.svc.cluster.local:11434` — standard service-discovery code path, identical to what would target a vLLM Service in EKS.

**Rationale.**
- Native Metal acceleration is the only way to hit TTFT ≤2s p95 and full-response ≤30s p90 on this hardware.
- `ExternalName` keeps the application code production-shaped: backend doesn't know "Ollama is on the host" — it just resolves a Service name. Migrating to in-cluster vLLM later is a Service swap, not a code change.
- This pattern mirrors a real-world topology where inference runs on GPU nodes managed separately from the application plane (different node pool, different lifecycle, different scaling).

**Alternatives rejected.**
1. **In-cluster Ollama (CPU).** Rejected: violates latency SLOs; fans-out memory across container layers.
2. **In-cluster Ollama with hostNetwork + GPU passthrough.** Rejected: no GPU passthrough exists for Metal.
3. **Direct host URL hard-coded in backend (no Service).** Rejected: breaks the "production-shaped" invariant; every test would need env-var overrides; ADR loses its teaching moment.

**Consequences.**
- The `host.docker.internal` hop is the brittlest seam in the stack (BRAINSTORM §5). Mitigated by: (a) `make smoke` healthcheck targeting Ollama through the Service, (b) explicit failure mode in AT-007, (c) NetworkPolicy explicitly *allows* this egress.
- OpenTelemetry cannot auto-instrument across the host hop. Mitigated by **synthetic span** pattern (§9.2).
- A Linux fork of the project would need a different ADR — noted in the ADR's "Portability" footnote.

---

### ADR-004: Hybrid eval strategy (pytest structural + local Llama judge + manual spot-check)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

**Context.** Eval needs to run at three different cadences (per-commit, nightly, per-sprint) with three different cost/signal profiles. A single layer (judge-only or structural-only) fails one of those cadences.

**Choice.** Three-layer eval:
- **Layer 1 — pytest structural** (every commit, seconds): JSON shape, required fields, token bounds, no obvious malformations. CI gate (AT-010).
- **Layer 2 — Local Llama 3.1 8B judge** (nightly, ~minutes): scores Qwen output against ground truth on a fixed rubric (root-cause match, remediation soundness, hallucination check). Llama is loaded on-demand via `ollama run` and unloaded after, so it doesn't compete with primary inference for steady-state RAM. AT-011.
- **Layer 3 — Manual spot-check** (per sprint, ~30 min): 5 cases against a markdown checklist. Calibrates the judge.

**Rationale.**
- Llama is a different model family from Qwen → reduces self-preference bias in judging.
- Local judge preserves NFR6 (zero external API spend).
- Layer 3 is the calibration loop: if Llama-judge agreement with humans drifts <80%, escalate to user (per OQ-4 trip-wire).

**Alternatives rejected.**
1. **Judge-only.** Rejected: no protection against output-shape regressions; too slow for per-commit feedback.
2. **Structural-only.** Rejected: tells you JSON parses, not whether analysis is good.
3. **API judge (GPT-4 / Claude as judge).** Rejected: violates NFR6.

**Consequences.**
- Llama judge cold-load adds ~30s to nightly eval; acceptable.
- Manual layer is process discipline, not code — must appear in the per-sprint checklist (`docs/eval/manual_checklist.md`).
- The judge rubric (`tests/eval/judge/rubric.yaml`) is a versioned artefact — changes need PR review.

---

### ADR-005: Hybrid grounding data (Loghub HDFS + synthetic backend logs; 2 real + 2 synthetic postmortems)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

**Context.** The system needs grounding data both for the *demo* (curated samples behind one-click UI buttons) and for *eval* (held-out incidents with labeled ground truth). Pure-real data lacks the controllability for clean demo narratives; pure-synthetic data risks looking unrealistic.

**Choice.**
- **Logs:** Loghub HDFS subset (canonical SRE failure modes — DataNode crashes, replication failures, well-labeled) + synthetic backend logs generated by an in-process **anomaly injector** (§9.4). The injector creates *live* demo moments where the reviewer analyzes logs the cluster itself just produced.
- **Postmortems:** 2 real public PMs (Cloudflare 2024, GitHub 2024) for stylistic grounding + 2 hand-written PMs that match the demo incidents one-for-one for in-distribution exemplars.
- **Ground truth:** Per demo incident, a labeled JSON record in `datasets/eval/ground_truth/` with expected root cause, severity, candidate remediations, and "must-not-hallucinate" assertions.

**Rationale.**
- HDFS is the most labeled and best-known Loghub dataset; reviewers familiar with Loghub recognise it instantly.
- Synthetic logs let the demo include a "watch the system analyze a problem it just had" moment — uniquely powerful for live walkthrough.
- 2-real-2-synthetic postmortem split: real PMs anchor stylistic credibility; synthetic PMs ensure the LLM has in-distribution exemplars for the actual demo incidents.

**Alternatives rejected.**
1. **Loghub-only (no synthetic).** Rejected: loses the live-anomaly demo moment.
2. **Pull all 5 Loghub datasets (HDFS + BGL + Thunderbird + OpenSSH + Hadoop).** Rejected: labeling cost compounds; AT-005 reveals diversity needs are met by HDFS alone.
3. **Real PMs only.** Rejected: stylistic match is good but no in-distribution exemplar for the specific demo incident → worse few-shot performance.

**Consequences.**
- The anomaly injector is a backend module that must be carefully gated (off in production paths, on for `make demo`) — designed in §9.4.
- Real-PM attribution must be preserved (`datasets/postmortems/real/SOURCES.md`).
- Ground-truth labeling is a perpetual maintenance cost — capped at 10–20 incidents for MVP.

---

### ADR-006: Backend statelessness + per-request SSE (no sticky sessions, no Redis-backed session state)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — **partially superseded in v1.6 (Redis removed entirely; statelessness retained)** |
| **Date** | 2026-04-26 |

**Context.** With 2 backend replicas behind a Service, any cross-request session state requires either (a) ingress sticky sessions, or (b) a shared store like Redis. Both add complexity and (a) is incompatible with the canary-rollout story (sticky sessions strand users on a draining replica).

**Choice.** Backend is **fully stateless**. Each SSE stream is bound to a single replica for its lifetime (a single TCP connection). No session ID. No cross-request server-side state. Redis is **deployed but unused for sessions** — reserved for a future caching layer (e.g., prompt-result cache for repeated demo inputs) without holding up MVP.

**Rationale.**
- Matches the canary story: any replica can serve any request mid-rollout; no drain coordination.
- Eliminates an entire category of bugs (session leaks, store consistency, TTL).
- SSE-per-TCP-connection is the right granularity: if a client reconnects, they start a new analysis — that's correct UX (analysis is cheap, idempotent, and re-running with the same input gives consistent-shaped output).

**Alternatives rejected.**
1. **Ingress sticky sessions (Traefik affinity cookie).** Rejected: breaks canary; cookie pinning conflicts with traffic-weight shifts.
2. **Redis-backed session store.** Rejected: speculative; no MVP requirement needs cross-request server state.
3. **No Redis at all.** Rejected: keeps the "future caching" door open at near-zero memory cost (80 MB) and shows infra literacy in the manifest.

**Consequences.**
- Frontend must handle SSE reconnect gracefully (start a fresh analysis; do not attempt mid-stream resume).
- Redis is a "loaded gun" — must be documented in `docs/redis.md` to explain it's intentionally unused for MVP, with a note explaining the future caching path. Otherwise reviewers will ask "why is Redis here?"

**v1.6 supersede note:** Reviewer (the very first one) asked "why is Redis here?" within hours of the build, exactly as predicted. The "future caching" door was never opened, the `docs/redis.md` apology was never written, and the 80 MB cost was real on a 16 GB Mac. Redis was **removed entirely in v1.6** per YAGNI. The statelessness decision (no sticky sessions, per-request SSE bound to a single replica) remains in force — it never depended on Redis. If/when prompt-result caching becomes a real demo requirement (e.g., S4 polish: "second click on the same Loghub sample returns sub-100ms"), re-introduce Redis (or an in-memory LRU if a network hop seems wasteful).
- Backend Pods can be killed at any time without user-visible damage beyond the in-flight stream → makes AT-006 (PDB) easy.

---

### ADR-007: Configurable Docker host bridge CIDR (portability across container runtimes)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 (post-S2 portability hardening) |

**Context.** Backend pods reach Ollama on the host via a NetworkPolicy egress rule that allows TCP 11434 to a specific IP block — the Docker host bridge CIDR. The `host.docker.internal` hostname resolves to different IPs depending on the container runtime in use:

| Runtime | `host.docker.internal` resolves to | Bridge CIDR |
|---------|-------------------------------------|-------------|
| Docker Desktop (macOS) | `192.168.65.254` | `192.168.65.0/24` |
| OrbStack | `198.19.249.1` | `198.19.249.0/24` |
| Colima | `192.168.106.1` | `192.168.106.0/24` |
| Linux native Docker | `172.17.0.1` | `172.17.0.0/16` |

After S1 the CIDR was introduced as a chart value (`ollamaHostCIDR`) but defaulted to Docker Desktop only and carried no override path through the deploy toolchain. This made the demo silently fail on OrbStack, Colima, and Linux — connection timeouts with no obvious cause.

**Choice.** Three-part solution:

1. **Helm value `hostBridgeCIDR`** in `helm/platform/ollama-externalname/values.yaml` (default `192.168.65.0/24`), consumed by the NetworkPolicy template in the same chart (`{{ .Values.hostBridgeCIDR }}`). Single-responsibility: the chart that defines the ExternalName bridge owns the CIDR for it; the general-purpose `networkpolicies` chart carries no runtime-specific value.
2. **Helmfile env-templating** for zero-friction override: `value: {{ env "HOST_BRIDGE_CIDR" | default "192.168.65.0/24" }}` in the `ollama-externalname` release stanza. Override at deploy time with `HOST_BRIDGE_CIDR=198.19.249.0/24 make up`; persist across sessions via direnv `.envrc`.
3. **`make detect-bridge` target** that spins up a one-shot Alpine container to resolve `host.docker.internal` and computes the `/24` CIDR automatically, printing the suggested value and the exact `export` command to use.

**Rationale.**
1. **Portability is a real success-criterion concern.** NFR7 says a stranger reproduces in <10 min. "Stranger" includes OrbStack users and Linux developers — currently broken before this fix. The fix directly defends that criterion.
2. **Auto-detect via Docker is more reliable than a hardcoded table.** `make detect-bridge` works on unknown future runtimes without a doc update; the README table is a fallback, not the primary path.
3. **Single-responsibility.** `ollama-externalname` owns the bridge concept end-to-end (ExternalName Service + NetworkPolicy + CIDR). The `networkpolicies` chart becomes strictly runtime-agnostic (default-deny, DNS allow, same-namespace allow, observability allow — no host-specific CIDR).
4. **Env-templated helmfile values are easier to override than `--set` flags.** A single shell env var persists across multiple `make up` invocations; `--set` must be re-specified each time.

**Alternatives rejected.**
1. **Hardcode `0.0.0.0/0` egress for port 11434.** Rejected: defeats the NetworkPolicy entirely; violates the zero-egress guarantee (NFR6) in spirit.
2. **Detect CIDR at chart-render time via Helm template hooks / lookup function.** Rejected: `helm lookup` is disabled in offline/local rendering; makes `helm template` non-deterministic across environments.
3. **Per-runtime values files (`values-orbstack.yaml`, `values-colima.yaml`, etc.).** Rejected: proliferates files that diverge silently; doesn't help auto-detect; requires the user to know their runtime before they know the problem.
4. **Document the variation in README only, no template support.** Rejected: re-introduces the silent-failure mode for users who skim the README or who are on an unlisted runtime.

**Consequences.**
- (+) Demo works on 4 known runtimes out of the box (Docker Desktop, OrbStack, Colima, Linux native Docker).
- (+) Single point of override (env var) is easy to document in README and persist via direnv `.envrc`.
- (+) `make detect-bridge` is a reusable diagnostic for any future host-runtime-dependent value (DNS resolver IP, host gateway CIDR, etc.).
- (+) `networkpolicies` chart becomes fully runtime-agnostic — cleaner separation of concerns.
- (–) Adds one prerequisite step for non-Docker-Desktop users: set `HOST_BRIDGE_CIDR` or run `make detect-bridge`. Mitigated by the README "Configuring the Docker host bridge" section with the runtime table.
- (–) Requires understanding helmfile env-templating syntax to extend. Mitigated: the pattern is already established and documented here (§4.8).

---

### ADR-008: Per-machine env-overridable settings via Makefile + Helmfile + Helm values

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 (post-S2 portability iteration v2) |

**Context.** ADR-007 introduced `HOST_BRIDGE_CIDR` as the first env-overridable setting. A subsequent audit identified four more genuinely-machine-or-user-dependent settings that were hardcoded across multiple files:

- **Ollama URL** — duplicated in `analyze.py` + `postmortem.py` (in-cluster service name); blocked local backend dev (running uvicorn outside kind).
- **LLM model name** — duplicated 5 places (`analyze.py`, `postmortem.py`, `observability/spans.py`, `Makefile` × 2); RAM-tier dependent (8 GB users want `phi3:mini`, 32 GB users may want `qwen2.5:14b`).
- **LLM judge model name** — same shape as LLM_MODEL; some users want to skip the judge entirely (`SKIP_JUDGE=1`).
- **Ingress hostname** (`sre-copilot.localtest.me`) — hardcoded in 4 places; corporate DNS sometimes blocks `localtest.me`.

The audit also identified things NOT to externalize (deliberate reproducibility anchors): cluster name `sre-copilot`, K8s version pin (`kindest/node:v1.31.0`), image names, Pod CIDR. Forecloses the slippery slope where every value becomes a config knob.

**Choice.** Standardize a 4-layer pattern for any per-machine setting:

1. **Makefile** — declare with `?=` default and `export VAR_NAME` so child processes inherit:
   ```makefile
   LLM_MODEL ?= qwen2.5:7b-instruct-q4_K_M
   export LLM_MODEL
   ```
2. **Helmfile** — `set:` block with `{{ env "VAR_NAME" | default "<value>" }}`:
   ```yaml
   set:
     - name: llm.model
       value: {{ env "LLM_MODEL" | default "qwen2.5:7b-instruct-q4_K_M" }}
   ```
3. **Helm chart values.yaml** — declare a structured value:
   ```yaml
   llm:
     model: "qwen2.5:7b-instruct-q4_K_M"
   ```
4. **Helm template** — render into ConfigMap (or directly into pod env):
   ```yaml
   data:
     LLM_MODEL: {{ .Values.llm.model | quote }}
   ```

The 5 settings now externalized: `HOST_BRIDGE_CIDR`, `LLM_MODEL`, `LLM_JUDGE_MODEL`, `INGRESS_HOST`, `OLLAMA_BASE_URL` (last is backend-only — no helmfile path needed since the in-cluster default is correct for the production runtime; override via env only for local Tilt-style dev).

**Rationale.**
1. **Single override mechanism across the stack.** Users learn one pattern, not five (env-templating, --set, values files, init containers, etc.).
2. **Defaults are the happy path.** Overrides are opt-in and never required for the canonical Docker-Desktop / 16-GB scenario.
3. **`direnv` / `.envrc` provides persistence** without polluting global shell state.
4. **Bounded externalization.** Five settings only, with explicit "do not externalize" guidance for cluster name / K8s version / image names / Pod CIDR — these are reproducibility anchors that defend bug reports ("on what cluster?" → always `sre-copilot`).

**Alternatives rejected.**
1. **Per-environment values files** (`values-low-ram.yaml`, `values-corp.yaml`). Rejected: proliferates files; doesn't compose when 2+ overrides combine (low-RAM + Colima needs both).
2. **Single mega-config file at repo root.** Rejected: loses Helm's value validation and templating.
3. **Externalize *everything*.** Rejected: every override is a future bug ("why doesn't your demo work?" → "did you remember to export X, Y, Z, and Q?"). Trade reproducibility for flexibility nobody asked for.

**Consequences.**
- (+) Demo works on 4 Docker runtimes × 3 RAM tiers × custom DNS scenarios with a single env-export step per non-canonical setting.
- (+) Local backend dev (Tilt-style, uvicorn outside kind) now possible via `OLLAMA_BASE_URL=http://localhost:11434/v1`.
- (+) Pattern documented in README "Per-machine configuration" section with a verify-after-`make-up` snippet.
- (–) 5 env vars to know — mitigated by README override matrix table, all with defaults.
- (–) Pattern requires changes in 4 layers per setting — mitigated by small-N (5 settings, not growing).

---

---

### ADR-009: mkcert local CA + Traefik TLSStore default

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-27 |

**Context.** Browser blocks cross-subdomain fetch when a self-signed cert isn't trusted per-subdomain. The UX dance of per-subdomain certificate acceptance is unacceptable for demos and breaks frontend→api fetch silently — Chrome does not surface a `NetworkError` unless DevTools is open.

**Choice.** mkcert installs a local root CA in the macOS Keychain and browser NSS DBs. Mint a wildcard cert covering `*.localtest.me` and `*.sre-copilot.localtest.me`. Apply the cert as a Kubernetes Secret in the platform namespace. A Traefik `TLSStore` resource with `name: default` makes that cert serve every IngressRoute that does not specify its own TLS configuration.

**Rationale.**
- Single trust decision at `mkcert -install` time instead of N per-subdomain decisions.
- Standard local-dev pattern widely understood by platform engineers.
- Works in any browser (Chrome, Firefox, Safari) on macOS without per-site exceptions.
- Self-heals if the cert Secret is recreated — the TLSStore picks up the new Secret immediately.

**Alternatives rejected.**
1. **Per-subdomain manual cert acceptance.** Rejected: UX cost is prohibitive for demos; Chrome hides the accept button behind an advanced flow; silently breaks fetch without DevTools.
2. **cert-manager + ACME (Let's Encrypt DNS-01 or HTTP-01).** Rejected: overkill for local dev; requires DNS-01 delegation or a publicly reachable HTTP-01 challenge responder — neither exists in a kind cluster.
3. **Host the API under the same hostname as the frontend (path-based routing only).** Rejected: eliminates the cross-subdomain issue but breaks the GitOps-style "each service has its own subdomain" pattern that is a deliberate demo signal.

**Consequences.**
- One-time `sudo mkcert -install` required on each developer machine (installs root CA into macOS Keychain). Documented in README prerequisites.
- `.certs/` directory must be gitignored — wildcard private key must never be committed.
- Browser restart is required after CA install for Chrome/Firefox to pick up the new trust anchor.
- Cert renewal is manual; the mkcert CA is valid for approximately 10 years, so this is not a practical concern for the project lifetime.

---

### ADR-010: OTel Logs SDK with `loki.resource.labels` hint

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-27 |

**Context.** Backend originally logged JSON to stdout only. The Grafana panel for "Backend Logs" showed "No data" because Loki had no streams labeled `service_name=sre-copilot-backend`. Adding the OTel Logs SDK alone is insufficient — resource attributes must be promoted to Loki stream labels for Loki queries to filter on them. Without promoted stream labels, logs arrive in Loki's default stream and cannot be queried by service.

**Choice.** `init_observability_providers()` now sets up a `LoggerProvider` + `OTLPLogExporter` + `LoggingHandler` attached to the root Python logger. The OTel resource includes the attribute `loki.resource.labels: "service.name,deployment.environment"` as a hint. The Loki exporter in the otel-collector reads this hint and promotes those resource attributes to Loki stream labels on export.

**Rationale.**
- Stays entirely within the OTel ecosystem — no Promtail DaemonSet, no Alloy sidecar.
- The same SDK that handles traces and metrics now handles logs: single init path, single resource definition, single exporter endpoint.
- Resource label promotion is uniform across all services that include the hint — adding a second service requires only the same Resource attribute, not a new pipeline configuration.

**Subtle bug documented for future contributors.** Python's `logging.root.handlers = [...]` assignment **replaces** all existing handlers. Calling `configure_logging()` after `init_observability_providers()` silently wiped the OTel `LoggingHandler` that had just been installed, resulting in logs flowing to stdout only and disappearing from Loki. Fixed by making `configure_logging()` **append** handlers with an idempotent marker (`_otel_handler_installed`) instead of replacing. Any future contributor who modifies the logging setup must preserve this append-not-replace contract or Loki logs will silently stop appearing.

**Alternatives rejected.**
1. **Promtail / Alloy DaemonSet scraping pod stdout.** Rejected: adds an extra component to the cluster, breaks the pure-OTel story, and requires separate configuration outside the SDK.
2. **fluent-bit sidecar or DaemonSet.** Rejected: same objection as Promtail; adds operational surface area.
3. **Loki JSON log parsing pipeline (no OTel SDK).** Rejected: Loki regex/JSON parsing can extract fields but cannot reconstruct OTel resource attributes like `trace_id` / `span_id` with the same fidelity; loses the trace↔log correlation in Grafana.

**Consequences.**
- Backend pods require the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable (already set via ConfigMap in `helm/backend/`).
- Loki must be configured with `max_label_names_per_series` high enough to accept the promoted labels. Already configured at `30` in `helm/observability/lgtm/loki-values.yaml`.
- The `warning` filter for benign async-context noise (a spurious `RuntimeWarning` emitted when the OTel LoggingHandler flushes outside an active async context) is added in `init.py` to prevent log spam.

---

### ADR-011: Tempo local-blocks metricsGenerator for TraceQL search

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-27 |

**Context.** Tempo on filesystem storage does not support TraceQL backend search by default. Grafana 11's Tempo datasource plugin reports "backend TraceQL search queries are not supported" even when `/api/search` via curl returns results. The Grafana plugin uses the backend search code path; without a searchable index only exact trace-id lookup works. This makes the "explore traces by service/duration/status" UX unavailable.

**Choice.** Enable Tempo's `metricsGenerator` with the `local-blocks` processor. Set `overrides.defaults.metrics_generator.processors: [local-blocks]` so that in single-tenant mode it applies to all incoming traces. The `local-blocks` processor builds an in-process searchable index over recent blocks without requiring object storage.

**Rationale.** Enables TraceQL search through the Grafana UI without requiring an object storage backend (S3/GCS) or an external search index (OpenSearch/Elasticsearch). Acceptable memory overhead for local dev. Consistent with the "no external dependencies beyond Docker" design constraint.

**Subtle gotchas documented for future contributors.**

1. **Chart key is camelCase; rendered config is snake_case.** The Helm chart key is `tempo.metricsGenerator` (camelCase) but Tempo's config file renders it as `metrics_generator` (snake_case). Placing values at the wrong YAML path causes Helm to silently drop them — Tempo starts without the metricsGenerator enabled, with no error in the chart rendering output.

2. **Tempo refuses to start with an empty `remoteWriteUrl`.** The metricsGenerator always requires a non-empty `remoteWriteUrl` even when the `local-blocks` processor does not use remote-write for its search functionality. Point at `prometheus-server` (already deployed) to satisfy the requirement. Connection errors from Prometheus not having remote-write receiver enabled are benign and do not affect TraceQL search.

3. **Grafana plugin streaming causes "http2: frame too large" errors.** The Grafana Tempo datasource attempts gRPC streaming against the Tempo HTTP port (3200) for search queries. Disable streaming via `jsonData.streamingEnabled: { search: false, metrics: false }` in the Grafana datasource configuration. Trace-id lookups via plain HTTP work correctly without streaming.

**Alternatives rejected.**
1. **S3-compatible MinIO backend.** Rejected: adds an extra in-cluster component for local dev; increases memory budget and setup complexity.
2. **Skip TraceQL search; rely only on Loki→Tempo derived field link.** Rejected: derived field links require a known `traceid` in a log line — useful but not a substitute for ad-hoc TraceQL exploration by service name, duration, or status code.

**Consequences.**
- Slight memory overhead in Tempo for the `local-blocks` in-process index (estimated +30–50 MB; within the 250 MB Tempo budget).
- The `remote_write` connection to Prometheus may log periodic connection errors if Prometheus's remote-write receiver endpoint is not enabled. These are benign and can be suppressed by adding a `--web.enable-remote-write-receiver` flag to Prometheus; left as-is since the errors are informational only.

---

### ADR-012: Dashboard JSON as source-of-truth + regen tooling

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-27 |

**Context.** Hand-maintaining `configmaps.yaml` that wraps embedded JSON dashboards causes drift. Edits made in the Grafana UI export to JSON but do not propagate to the YAML. Edits to the YAML are not re-imported by Grafana's provisioner because the provisioner caches the in-database version once a dashboard UID has been registered — subsequent ConfigMap updates are ignored unless the dashboard is force-deleted from the database.

**Choice.** `*.json` files in `observability/dashboards/` are the source of truth. `observability/dashboards/regen-configmaps.py` reads each JSON file, wraps it in a Kubernetes ConfigMap with the `grafana_dashboard: "1"` label, and writes `configmaps.yaml`. `make dashboards` runs the regen script and applies via `kubectl apply --server-side --force-conflicts --field-manager=sre-copilot-dashboards`. Critically, the apply step performs a **delete-then-recreate** of the ConfigMaps rather than an in-place update — Grafana's content-comparison sometimes decides "no change" even when JSON has changed substantively, leaving stale panels in place.

**Rationale.**
- Single command (`make dashboards`) that always lands the intended change regardless of Grafana's internal cache state.
- Server-side apply with a named field manager (`sre-copilot-dashboards`) keeps ownership tracking consistent across CLI application and ArgoCD reconcile — both can apply without conflict storms.
- Delete-then-recreate is the canonical force-reload pattern for Grafana provisioned dashboards; the brief absence triggers a fresh import from the ConfigMap.

**Alternatives rejected.**
1. **Edit `configmaps.yaml` directly (no regen script).** Rejected: JSON embedded in YAML is error-prone and drifts from what Grafana exports.
2. **A Helm chart for dashboards.** Rejected: overkill for four dashboards; Helm templating adds indirection for what is essentially a data file.
3. **Grafana Terraform provider (`grafana_dashboard` resource).** Rejected: adds a runtime dependency on Terraform state; syncs only at explicit `terraform apply` time; does not integrate with the GitOps ArgoCD reconcile loop.

**Consequences.**
- Brief gap (~6 seconds) where dashboards do not exist in the cluster during the delete-recreate cycle. Acceptable for local dev; not suitable for production.
- ArgoCD treats `configmaps.yaml` as the source of truth on its reconcile loop. Out-of-band `make dashboards` runs may temporarily diverge from ArgoCD's desired state but ArgoCD will re-apply on the next sync cycle — net effect is idempotent.
- `observability/dashboards/regen-configmaps.py` must be re-run whenever a dashboard JSON is edited. Recommend adding it to a pre-commit hook or at minimum to the `make dashboards` workflow documentation.

---

### ADR-013: Single-platform image loading for kind

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-27 |

**Context.** `kind load docker-image` fails on multi-arch images with `"ctr: content digest ... not found"` because it uses `ctr import --all-platforms` internally and attempts to import every platform variant from the manifest list. However, `docker pull` only fetches the host-architecture variant. ArgoCD, Traefik, and other upstream multi-arch images all hit this failure. The problem is compounded by kind nodes' containerd not trusting the corporate CA chains that the host Docker daemon trusts, so direct image pulls from inside kind fail with x509 certificate errors — meaning pre-pulling on the host and then loading is the only reliable path.

**Choice.** The canonical pattern is: pre-pull on the host (avoids kind nodes' broken TLS chain) → `docker save --platform=linux/<host-arch>` (Docker 27+ feature; strips the manifest list and produces a single-platform archive) → `kind load image-archive`. Host architecture is detected at runtime via `uname -m` (`arm64` on Apple Silicon, `x86_64`/`amd64` on Intel/AMD). This pattern is applied to the ArgoCD image and any other multi-arch upstream image the `seed-models` target depends on.

**Rationale.** Sidesteps both the kind-node TLS trust issue and the multi-arch manifest list issue with a single pattern. Robust across Apple Silicon (`arm64`) and Intel/AMD (`amd64`) hosts without requiring separate Makefiles or CI matrix logic.

**Alternatives rejected.**
1. **Trust corporate CA inside kind nodes via bind-mount of `/etc/ssl/certs`.** Rejected: fragile across Docker Desktop versions; requires modifying the kind node image or using a custom kind node configuration that breaks the `kindest/node` version pin.
2. **Use a local Docker registry mirror inside kind.** Rejected: adds an extra in-cluster component; requires configuring kind's `containerdConfigPatches` to point at the mirror; increases cold-start complexity.
3. **Build single-arch images via `docker buildx` and tag locally.** Rejected: works for project-owned images but does not help with upstream images (ArgoCD, Traefik) that we do not build.

**Consequences.**
- Requires Docker 27+ for the `--platform` flag on `docker save`. Docker 27 was released in 2024-09 and is the current stable release; this is a reasonable minimum version.
- The `seed-models` Makefile target now pre-pulls the ArgoCD image alongside kind/Traefik images to amortize the pull cost before cluster creation (when the kind nodes' broken TLS chain would otherwise block it).
- Host-arch detection (`uname -m`) is added inline in the Makefile; no external script required.

---

## 3. File Manifest (sprint-organized, module-level)

> **Granularity rule:** entries are *modules* / *charts* / *directories*, not individual YAML or dashboard JSON files. `/build` will expand each into concrete files via the suggested agent.

### Sprint 1 — Foundations (Weeks 1–2)

**Goal:** end-to-end FastAPI + Next.js running in a kind cluster (no GitOps, no LGTM yet) reachable through Traefik. Streaming SSE proven against host Ollama.

| # | Path | Action | Purpose | Dependencies | Suggested Agent |
|---|------|--------|---------|--------------|-----------------|
| 1 | `Makefile` | Create | Top-level UX: `up`, `down`, `demo`, `seed-models`, `smoke`, `lint`, `test`, `seal`, `detect-bridge`. Top-of-file `?=` env-overridable vars (`LLM_MODEL`, `LLM_JUDGE_MODEL`, `INGRESS_HOST`, `HOST_BRIDGE_CIDR`) with `export` for child processes. See ADR-008. | none | @ci-cd-specialist |
| 2 | `Tiltfile` | Create | Inner-loop dev: file-watch, image-rebuild, k8s_resource maps | 1 | @ci-cd-specialist |
| 3 | `terraform/local/` | Create | Terraform module: kind 3-node cluster (control-plane + worker-platform + worker-apps) with node labels, kubeconfig export | none | @k8s-platform-engineer |
| 4 | `src/backend/` | Create | FastAPI service module: `/analyze/logs` (SSE), `/generate/postmortem`, `/healthz`, Pydantic schemas, Ollama OpenAI client wrapper, anomaly injector stub. Reads `OLLAMA_BASE_URL` and `LLM_MODEL` from env with defaults (in-cluster ExternalName URL + `qwen2.5:7b-instruct-q4_K_M`); see ADR-008. | 5 | @python-developer |
| 5 | `src/backend/prompts/` | Create | Jinja2 prompt templates (log_analyzer.j2, postmortem.j2) + few-shot exemplar files | none | @llm-specialist |
| 6 | `src/backend/Dockerfile` | Create | Multi-stage Python 3.12 slim build, non-root user, healthcheck | 4 | @ci-cd-specialist |
| 7 | `src/frontend/` | Create | Next.js 14 App Router app: two pages (analyzer, postmortem), shared SSE chat component, sample-buttons component, shadcn/ui + Tailwind setup | none | @frontend-architect |
| 8 | `src/frontend/Dockerfile` | Create | Multi-stage Node 20 build, standalone output, non-root | 7 | @ci-cd-specialist |
| 9 | `helm/backend/` | Create | Helm chart: Deployment×2, Service, HPA (min 2 max 4), PDB (minAvailable=1), ServiceAccount, ConfigMap. ConfigMap exposes `OLLAMA_BASE_URL`, `LLM_MODEL`, `LLM_JUDGE_MODEL`, `OTEL_EXPORTER_OTLP_ENDPOINT`; consumed by pod via `envFrom`. New `llm.model` + `llm.judgeModel` chart values. See ADR-008. *Argo Rollouts swap happens in S4.* | 6 | @k8s-platform-engineer |
| 10 | `helm/frontend/` | Create | Helm chart: Deployment×1, Service, ConfigMap (`NEXT_PUBLIC_API_URL`). New `ingressHost` chart value (default `sre-copilot.localtest.me`); ConfigMap renders `NEXT_PUBLIC_API_URL: https://{{ .Values.ingressHost }}` via `tpl`. See ADR-008. | 8 | @k8s-platform-engineer |
| 11 | ~~`helm/redis/`~~ | ~~Create~~ | **REMOVED in v1.6** — Redis was deployed but never wired up by application code. Removed per YAGNI; ADR-006 superseded. Re-add if/when prompt-result caching becomes a real requirement. | none | — |
| 12 | `helm/platform/traefik/` | Create | Helm values for traefik (Ingress, IngressRoute for SSE, self-signed TLS via traefik default cert) | 3 | @k8s-platform-engineer |
| 13 | `helm/platform/ollama-externalname/` | Create | Tiny chart: Service type=ExternalName → `host.docker.internal:11434`, plus a NetworkPolicy companion (`allow-ollama-host-hop`). Exposes `hostBridgeCIDR` value (default `192.168.65.0/24`); helmfile templates it from `HOST_BRIDGE_CIDR` env var (`{{ env "HOST_BRIDGE_CIDR" \| default "192.168.65.0/24" }}`). NetworkPolicy template consumes `{{ .Values.hostBridgeCIDR }}`. See ADR-007. | 3 | @k8s-platform-engineer |
| 14 | `helmfile.yaml.gotmpl` | Create | Orchestrates release order: traefik → ollama-externalname → backend → frontend. Per-machine env-templating via `set:` blocks: passes `LLM_MODEL` / `LLM_JUDGE_MODEL` to backend, `INGRESS_HOST` to frontend, `HOST_BRIDGE_CIDR` to ollama-externalname. `.gotmpl` extension required by Helmfile v1+ for Go template evaluation in YAML. See ADR-008. | 9,10,11,12,13 | @k8s-platform-engineer |
| 15 | `datasets/loghub/hdfs/` | Create | Loghub HDFS subset (~5 MB) + label CSV + LICENSE.md attribution | none | @python-developer |
| 16 | `datasets/eval/ground_truth/` | Create | 10 labeled JSON ground-truth records (5 HDFS + 5 synthetic-backend) | 15 | @llm-specialist |
| 17 | `tests/backend/unit/` | Create | pytest unit tests: prompt assembly, Pydantic schema validation, anomaly injector | 4 | @test-generator |
| 18 | `.github/workflows/ci.yml` | Create | Lint (ruff, mypy, eslint, tflint, helm lint, kubeconform) + unit tests + structural eval | 17 | @ci-cd-specialist |
| 19 | `README.md` (S1 draft) | Create | Quick-start, architecture diagram placeholder, prerequisites | 1 | @python-developer |

**S1 Exit:** `make seed-models && make up` produces a working URL with streaming SSE; `make smoke` exits 0; CI green.

---

### Sprint 2 — Kubernetes Native (Weeks 3–4)

**Goal:** harden the cluster surface — proper probes, NetworkPolicy egress denial, Sealed Secrets in flow, smoke tests cover failure modes.

| # | Path | Action | Purpose | Dependencies | Suggested Agent |
|---|------|--------|---------|--------------|-----------------|
| 20 | `helm/platform/sealed-secrets/` | Create | Helm values for sealed-secrets-controller; `make seal` Makefile target wraps `kubeseal` | 14 | @k8s-platform-engineer |
| 21 | `deploy/secrets/` | Create | Sealed manifests (sample: a dummy API token sealed for the controller) committed to repo as documentation pattern | 20 | @k8s-platform-engineer |
| 22 | `helm/platform/networkpolicies/` | Create | Per-namespace NetworkPolicy bundle: strictly runtime-agnostic policies — default-deny egress, DNS allow (kube-system UDP/TCP 53), same-namespace allow, observability egress allow (→ `observability` namespace). The host-bridge-specific `allow-ollama-host-hop` policy lives in entry #13 (`ollama-externalname`) because it is tied to that chart's runtime-dependent CIDR. See §9.3 and ADR-007. | 13 | @k8s-platform-engineer |
| 23 | `src/backend/middleware/` | Update | Add request-ID middleware, structured JSON logger (matches §5.3 schema), error handler returning structured 400/503 (AT-007, AT-008) | 4 | @python-developer |
| 24 | `helm/backend/` | Update | Add resource limits (250m / 350Mi req, 500m / 500Mi limit), liveness / readiness / startup probes, securityContext (non-root, readOnlyRootFilesystem) | 9 | @k8s-platform-engineer |
| 25 | `helm/frontend/` | Update | Same probes / securityContext / resource limits as backend | 10 | @k8s-platform-engineer |
| 26 | `tests/integration/` | Create | pytest-based integration: spin up backend with mocked Ollama, assert SSE shape, 503 on Ollama-down (AT-007), 400 on bad input (AT-008), cancel on client disconnect (AT-009) | 23 | @test-generator |
| 27 | `make smoke` (Makefile target) | Update | Wall-clock cold-start timer; 1 analyzer request → assert Tempo trace exists with ≥4 spans (S3 ext); memory snapshot via `docker stats` | 1 | @ci-cd-specialist |

**S2 Exit:** All probes green, NetworkPolicy denies egress beyond allow-list (AT-012 prep), smoke target runs in CI.

---

### Sprint 3 — GitOps & Observability (Weeks 5–6)

**Goal:** the cluster manages itself from Git; every signal (metric / log / trace) flows through OTel into LGTM; dashboards and alerts shipped.

| # | Path | Action | Purpose | Dependencies | Suggested Agent |
|---|------|--------|---------|--------------|-----------------|
| 28 | `argocd/bootstrap/` | Create | ArgoCD install + root Application (app-of-apps pattern) — ApplicationSet generates Applications from `argocd/applications/` | 14 | @k8s-platform-engineer |
| 29 | `argocd/applications/` | Create | One Application per Helm release (backend, frontend, traefik, sealed-secrets, argo-rollouts, otel-collector, loki, tempo, prometheus, grafana). Sync waves enforce ordering. | 28 | @k8s-platform-engineer |
| 30 | `helm/observability/lgtm/` | Create | Helm release set: loki (single-binary), tempo (monolithic), prometheus (replaces Mimir for memory), grafana — with persistence disabled (ephemeral) | 28 | @observability-engineer |
| 31 | `helm/observability/otel-collector/` | Create | Helm values for opentelemetry-collector (deployment mode, OTLP receiver, exporters: prometheus / loki / tempo) | 30 | @observability-engineer |
| 32 | `src/backend/observability/` | Create | Module: OTel SDK init (FastAPI auto-instrumentation + manual tracer for `ollama.host_call` + synthetic `ollama.inference` span — see §9.2), metric definitions (llm_ttft_seconds histogram, llm_tokens_*, llm_request_duration), Loki log handler | 23 | @observability-engineer |
| 33 | `helm/backend/` | Update | Inject OTEL_EXPORTER_OTLP_ENDPOINT env, add ServiceMonitor for Prometheus scrape | 32 | @observability-engineer |
| 34 | `src/frontend/observability/` | Update | Browser OTel SDK: web vitals + fetch instrumentation propagating traceparent into backend requests | 32 | @observability-engineer |
| 35 | `observability/dashboards/` | Create | 4 Grafana dashboards as ConfigMaps auto-loaded via grafana sidecar: Overview, LLM Performance, Cluster Health, Cost & Capacity | 30 | @observability-engineer |
| 36 | `observability/alerts/` | Create | Prometheus rules + multi-window multi-burn-rate alert definitions for the 3 SLOs (availability, TTFT, full-response) | 30 | @observability-engineer |
| 37 | `tests/integration/test_egress_denied.py` | Create | AT-012: `kubectl exec backend -- curl -m 3 https://api.openai.com` must fail | 22 | @test-generator |
| 38 | `tests/smoke/test_trace_visible.py` | Update | AT-001 final assertion: trace exists in Tempo within 5s with ≥4 spans including the synthetic ollama.inference | 27,32 | @test-generator |

**S3 Exit:** ArgoCD owns all workloads; every request produces a trace; dashboards display live data; alerts fire on burn.

---

### Sprint 4 — Polish (Weeks 7–8) — MVP-only items per OQ-1

**Goal:** the canary moment, the demo script, the ADRs, and the README final pass that turns the repo into a portfolio piece.

| # | Path | Action | Purpose | Dependencies | Suggested Agent |
|---|------|--------|---------|--------------|-----------------|
| 39 | `helm/platform/argo-rollouts/` | Create | Helm values for argo-rollouts-controller | 28 | @k8s-platform-engineer |
| 40 | `helm/backend/` | Update | Swap Deployment → Argo Rollouts `Rollout` with canary strategy (25% → 50% → 100% with Prometheus AnalysisTemplate gating on error-rate + p95 latency) | 39 | @k8s-platform-engineer |
| 41 | `deploy/rollouts/analysis-templates/` | Create | AnalysisTemplate manifests (Prom queries — see §4.5) | 40 | @k8s-platform-engineer |
| 42 | `make demo-canary` (Makefile target) | Create | Builds backend:v2 image (deliberately adds a new field `confidence: float` to JSON output → visibly different), `kind load`, bumps Rollout image, watches progression | 40 | @ci-cd-specialist |
| 43 | `make demo` (Makefile target) | Create | The full demo script (see §8): seeds an anomaly via injector, opens dashboards, triggers analyzer, then triggers canary | 42 | @ci-cd-specialist |
| 44 | `tests/eval/structural/` | Create | Layer-1 pytest eval: SSE event shape, JSON schema, token bounds | 16 | @test-generator |
| 45 | `tests/eval/judge/` | Create | Layer-2 Llama-judge runner: loads judge via Ollama on demand, scores against ground truth, writes `datasets/eval/judge_runs/<timestamp>.json` | 16 | @llm-specialist |
| 46 | `.github/workflows/nightly-eval.yml` | Create | Nightly schedule: run Layer-2 judge on held-out set, commit results, fail if root-cause-match <80% | 45 | @ci-cd-specialist |
| 47 | `.github/workflows/release.yml` | Create | Tag, changelog, image build + `trivy image` scan (one-shot, MVP per OQ-1), GHCR push | 18 | @ci-cd-specialist |
| 48 | `docs/adr/` | Create | The 6 ADRs from §2 of this doc, exported as standalone files for `docs/adr/0001-…md` linking | none | @code-reviewer |
| 49 | `docs/policy.md`, `docs/security.md`, `docs/chaos.md` | Create | Documented-only platform-kit components (Kyverno / Trivy Operator / Chaos Mesh) — explains what + why-deferred + how-to-add | none | @code-reviewer |
| 50 | `docs/aws-migration.md` | Create | Reference: how this would run on EKS (vLLM swap, Karpenter for GPU nodes, AWS Load Balancer Controller, IRSA, Secrets Manager replaces Sealed Secrets) | none | @k8s-platform-engineer |
| 51 | `docs/runbooks/` | Create | 3 runbooks: ollama-host-down, backend-pod-loss, eval-judge-drift | none | @code-reviewer |
| 52 | `docs/eval/manual_checklist.md` | Create | The Layer-3 manual spot-check checklist | 45 | @llm-specialist |
| 53 | `README.md` (final) | Update | Hero diagram, GIF, screenshots, 8-section structure (plan §8), badges, ADR links, "what I learned" | 48,49,50 | @code-reviewer |
| 54 | `docs/loom-script.md` + Loom upload | Create | 3-minute walkthrough script + recording link in README (MVP per OQ-1) | 53 | @code-reviewer |

**S4 v1.1 backlog (deferred per OQ-1):** k6 load tests, multi-arch builds, Trivy Operator continuous scanning, Chaos Mesh experiments. Tracked in `docs/v1.1-backlog.md`.

**S4 Exit:** `make demo` produces the full narrative beat-for-beat; AT-001 through AT-013 all pass; ADRs published; tag v1.0.0.

---

### Sprint 5 — TLS, Observability Pipeline, Dashboards, Canary, Bootstrap, Eval (36-commit session)

**Goal:** harden the full stack for demo-readiness — trusted HTTPS, working Loki log streams, TraceQL search, dashboard regen tooling, reliable kind image loading, and an improved eval pipeline.

| # | Path | Action | Purpose | Dependencies | Sprint |
|---|------|--------|---------|--------------|--------|
| 55 | `helm/backend/templates/analysistemplate.yaml` | Create (relocated) | AnalysisTemplate now ships inside the backend Helm chart behind `.Values.useArgoRollouts` gate; was an orphan at `deploy/rollouts/analysis-templates/`. `deploy/rollouts/analysis-templates/backend-canary-health.yaml` is deleted. See ADR-013 canary context. | ADR-012 canary strategy | S5 |
| 56 | `observability/dashboards/regen-configmaps.py` | Create | Regen script: reads each `*.json` dashboard, wraps in ConfigMap with `grafana_dashboard=1` label, writes `configmaps.yaml`. Invoked by `make dashboards`. See ADR-012. | none | S5 |
| 57 | `.certs/` (gitignored) | Create | mkcert wildcard cert (`*.localtest.me`, `*.sre-copilot.localtest.me`) lands here as a Kubernetes Secret applied to the platform namespace. Gitignored — private key must never be committed. See ADR-009. | none | S5 |
| 58 | `Makefile` | Update | New targets: `trust-certs` (mkcert install + Secret apply), `dashboards` (regen + delete-recreate apply), `restart-backend`, `clean-replicasets`. `ARGOCD_VERSION` variable for pinned ArgoCD image. Multi-arch image strip in `seed-models` via `docker save --platform` (ADR-013). `demo` target paced via `read -p` prompts (no fake timestamps). `demo-canary` runs background load generator. | ADR-009, ADR-013 | S5 |
| 59 | `src/backend/observability/init.py` | Update | `LoggerProvider` + `OTLPLogExporter` + `LoggingHandler` wired to root logger. Resource gains `loki.resource.labels: "service.name,deployment.environment"` hint. Warning-filter added for benign async-context noise from OTel flush. See ADR-010. | ADR-010 | S5 |
| 60 | `src/backend/observability/logging.py` | Update | `configure()` must **append** not replace root handlers (idempotent-marker guard `_otel_handler_installed`) to coexist with OTel `LoggingHandler`. See ADR-010 subtle bug note. | ADR-010 | S5 |
| 61 | `helm/backend/templates/hpa.yaml` | Update | Conditional `scaleTargetRef.kind`: `Rollout` when `.Values.useArgoRollouts` is true, `Deployment` otherwise. Prevents HPA targeting a non-existent resource kind. | S4 canary | S5 |
| 62 | `helm/observability/lgtm/grafana-values.yaml` | Update | Loki `derivedFields`: primary regex matches OTel convention `traceid=(\w+)`; fallback regex matches legacy `trace_id=(\w+)`. Tempo datasource gains `jsonData.streamingEnabled: { search: false, metrics: false }` to suppress gRPC frame-too-large errors. See ADR-011. | ADR-011 | S5 |
| 63 | `helm/observability/lgtm/tempo-values.yaml` | Update | `tempo.metricsGenerator.enabled: true`, `tempo.metricsGenerator.remoteWriteUrl` set to prometheus-server URL, `tempo.overrides.defaults.metrics_generator.processors: [local-blocks]`. See ADR-011. | ADR-011 | S5 |
| 64 | All chart values (backend rollout/deployment, frontend, traefik, sealed-secrets, grafana, prometheus, otel-collector) | Update | `revisionHistoryLimit: 3` added to all workload-bearing chart values. Caps idle ReplicaSet accumulation which was cluttering `kubectl get rs` output and consuming etcd storage. | none | S5 |
| 65 | `argocd/applications/*.yaml` (all 9 workload-bearing Applications) | Update | `ignoreDifferences` for `/status/terminatingReplicas` cascaded from prometheus.yaml to all 9 Applications. Loki Application gains additional `ignoreDifferences` entry for `/spec/persistentVolumeClaimRetentionPolicy` (Loki StatefulSet field that ArgoCD cannot manage). | S3 GitOps | S5 |
| 66 | `helm/observability/otel-collector/values.yaml` | Verify | Logs pipeline (OTLP receiver → Loki exporter with `loki.resource.labels` attribute processor) verified present and consistent with ADR-010 resource label promotion. | ADR-010 | S5 |
| 67 | `tests/eval/judge/run_judge.py` | Update | `JUDGE_SAMPLE_SIZE` env var with stratified-by-prefix sampling. Avoids running the full ground-truth set on every nightly eval cycle when iteration speed is more important than coverage. | S4 eval | S5 |
| 68 | `.github/workflows/nightly-eval.yml` | Update | Workflow timeout bumped to 45 min. `PYTHONUNBUFFERED=1` added to prevent log buffering. `sample_size` added as a `workflow_dispatch` input for manual runs. | ADR-004 eval | S5 |
| 69 | `src/backend/prompts/log_analyzer.j2` | Update | Evidence-grounding requirement added to system instruction: model must cite specific log lines. Explicit "the example shows ONE failure mode — do not copy its conclusion to unrelated inputs" anti-overfit warning added to the few-shot block. | ADR-005 grounding | S5 |

**Removed in S5:**
- `deploy/rollouts/analysis-templates/backend-canary-health.yaml` — relocated into `helm/backend/templates/analysistemplate.yaml` (entry #55).

**S5 Exit:** HTTPS works in-browser with no cert warnings; Loki shows `service_name=sre-copilot-backend` stream; TraceQL search works in Grafana; `make dashboards` reliably reloads all four dashboards; `make seed-models` reliably loads multi-arch upstream images; nightly eval runs with configurable sample size.

---

### Manifest Summary

- **Total entries:** 69 modules (54 original S1–S4 + 15 Sprint 5)
- **By suggested agent (S1–S4):** @k8s-platform-engineer (15), @observability-engineer (7), @ci-cd-specialist (10), @python-developer (4), @frontend-architect (2), @test-generator (5), @llm-specialist (5), @code-reviewer (6)
- **Agent reassignment note (post-design):** Original DESIGN dispatched 20 entries to `@infra-deployer` (GCP/Cloud-Run-focused) and 5 OTel/observability entries to general-purpose agents. To improve domain fit, two new agents were created (`k8s-platform-engineer`, `observability-engineer`) backed by 4 new KBs (`helm-helmfile`, `otel-lgtm`, `ollama-local-serving`, `argo-rollouts`). All Helm/kind/ArgoCD/Argo-Rollouts/NetworkPolicy/Sealed-Secrets/Traefik work routed to `k8s-platform-engineer`; all OTel SDK / LGTM / dashboards / SLO alerts routed to `observability-engineer`.
- **Coverage:** every AT-00x in §5 maps to one or more manifest entries
- **Sprint distribution:** S1=19, S2=8, S3=11, S4=16, S5=15

---

## 4. Code Patterns

### 4.1 FastAPI SSE streaming handler (async generator + Ollama OpenAI-compatible client)

```python
# src/backend/api/analyze.py
import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI, APIConnectionError
from opentelemetry import trace

from backend.schemas import LogAnalysisRequest, LogAnalysisDelta
from backend.prompts import render_log_analyzer
from backend.observability.metrics import LLM_TTFT, LLM_OUTPUT_TOKENS
from backend.observability.spans import synthetic_ollama_span

router = APIRouter()
tracer = trace.get_tracer(__name__)
client = AsyncOpenAI(
    base_url="http://ollama.sre-copilot.svc.cluster.local:11434/v1",
    api_key="ollama",  # required by SDK; ignored by Ollama
)

async def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()

@router.post("/analyze/logs")
async def analyze_logs(req: LogAnalysisRequest, request: Request):
    prompt = render_log_analyzer(req.log_payload, req.context)

    async def stream() -> AsyncIterator[bytes]:
        with tracer.start_as_current_span(
            "ollama.host_call",
            attributes={
                "llm.model": "qwen2.5:7b-instruct-q4_K_M",
                "llm.input_tokens": req.estimated_tokens(),
                "peer.service": "ollama-host",
                "net.peer.name": "host.docker.internal",
                "net.peer.port": 11434,
            },
        ) as span:
            try:
                stream_resp = await client.chat.completions.create(
                    model="qwen2.5:7b-instruct-q4_K_M",
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                    response_format={"type": "json_object"},
                )
            except APIConnectionError as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, "ollama unreachable")
                yield await _sse({"type": "error", "code": "ollama_unreachable",
                                  "message": "LLM backend is unavailable"})
                raise HTTPException(503) from None

            t0 = asyncio.get_event_loop().time()
            first_token_seen = False
            output_tokens = 0
            try:
                async for chunk in stream_resp:
                    if await request.is_disconnected():
                        await stream_resp.aclose()
                        span.set_status(trace.StatusCode.ERROR, "cancelled")
                        return
                    delta = chunk.choices[0].delta.content or ""
                    if not delta:
                        continue
                    if not first_token_seen:
                        ttft = asyncio.get_event_loop().time() - t0
                        LLM_TTFT.observe(ttft)
                        span.add_event("first_token", {"ttft_seconds": ttft})
                        first_token_seen = True
                    output_tokens += 1
                    yield await _sse({"type": "delta", "token": delta})
            finally:
                duration = asyncio.get_event_loop().time() - t0
                LLM_OUTPUT_TOKENS.inc(output_tokens)
                # Synthetic span: see §9.2
                synthetic_ollama_span(
                    parent=span, t0=t0, duration=duration,
                    output_tokens=output_tokens,
                    input_tokens=req.estimated_tokens(),
                )
                yield await _sse({"type": "done", "output_tokens": output_tokens})

    return StreamingResponse(stream(), media_type="text/event-stream")
```

### 4.2 Pydantic v2 schema for postmortem structured output

```python
# src/backend/schemas/postmortem.py
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    sev1 = "SEV1"
    sev2 = "SEV2"
    sev3 = "SEV3"
    sev4 = "SEV4"


class TimelineEvent(BaseModel):
    at: datetime
    actor: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=400)


class ActionItem(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    owner: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    due_window: Literal["this_sprint", "next_sprint", "next_quarter"]


class Postmortem(BaseModel):
    """Google SRE Workbook–shaped postmortem. All fields required."""
    summary: str = Field(min_length=20, max_length=500,
                         description="One paragraph; what happened, when, who was affected.")
    impact: str = Field(min_length=10,
                        description="Users affected, duration, severity dimensions.")
    severity: Severity
    detection: str
    root_cause: str = Field(min_length=20)
    trigger: str
    resolution: str
    timeline: list[TimelineEvent] = Field(min_length=1)
    what_went_well: list[str] = Field(min_length=1, max_length=10)
    what_went_wrong: list[str] = Field(min_length=1, max_length=10)
    action_items: list[ActionItem] = Field(min_length=1, max_length=15)
    lessons_learned: list[str] = Field(min_length=1, max_length=10)

    @field_validator("timeline")
    @classmethod
    def chronological(cls, v: list[TimelineEvent]) -> list[TimelineEvent]:
        if v != sorted(v, key=lambda e: e.at):
            raise ValueError("timeline must be chronological")
        return v


class LogAnalysis(BaseModel):
    """The 5-field log analyzer contract — see FR1 / AT-001."""
    severity: Literal["info", "warning", "critical"]
    summary: str = Field(min_length=10, max_length=400)
    root_cause: str = Field(min_length=10)
    runbook: list[str] = Field(min_length=1, max_length=10)
    related_metrics: list[str] = Field(default_factory=list, max_length=10)
```

### 4.3 OTel instrumentation (FastAPI middleware + manual span around Ollama)

```python
# src/backend/observability/init.py
from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import os

def init_otel(app):
    resource = Resource.create({
        "service.name": "sre-copilot-backend",
        "service.version": os.environ.get("APP_VERSION", "dev"),
        "deployment.environment": "kind-local",
    })
    endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(tp)

    mp = MeterProvider(resource=resource, metric_readers=[
        PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint, insecure=True),
                                      export_interval_millis=10_000),
    ])
    metrics.set_meter_provider(mp)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz,/metrics")
    HTTPXClientInstrumentor().instrument()


# src/backend/observability/metrics.py
from opentelemetry.metrics import get_meter
m = get_meter("sre_copilot.backend")
LLM_TTFT = m.create_histogram("llm.ttft_seconds", unit="s",
    description="Time to first token from Ollama")
LLM_RESPONSE = m.create_histogram("llm.response_seconds", unit="s",
    description="Full LLM response time")
LLM_OUTPUT_TOKENS = m.create_counter("llm.tokens_output_total")
LLM_INPUT_TOKENS = m.create_counter("llm.tokens_input_total")
LLM_ACTIVE = m.create_up_down_counter("llm.active_requests")
```

### 4.4 Structured JSON log schema (matches plan §5.3)

```python
# src/backend/observability/logging.py
import json
import logging
import sys
from datetime import datetime, timezone
from opentelemetry import trace

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "backend",
            "trace_id": f"{ctx.trace_id:032x}" if ctx and ctx.trace_id else None,
            "span_id":  f"{ctx.span_id:016x}"  if ctx and ctx.span_id  else None,
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for k in ("model", "input_tokens", "output_tokens", "duration_ms",
                 "endpoint", "user_session"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))

def configure():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(logging.INFO)
```

### 4.5 Argo Rollouts canary spec (with Prometheus AnalysisTemplate)

```yaml
# helm/backend/templates/rollout.yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: backend
spec:
  replicas: 2
  selector: { matchLabels: { app: backend } }
  template:
    metadata: { labels: { app: backend } }
    spec:
      containers:
        - name: backend
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          ports: [{ containerPort: 8000 }]
  strategy:
    canary:
      maxSurge: 1
      maxUnavailable: 0
      analysis:
        templates: [{ templateName: backend-canary-health }]
        startingStep: 1
        args:
          - name: service-name
            value: backend
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - analysis: { templates: [{ templateName: backend-canary-health }] }
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: { name: backend-canary-health }
spec:
  args: [{ name: service-name }]
  metrics:
    - name: error-rate
      interval: 15s
      successCondition: result[0] < 0.05
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.observability.svc:9090
          query: |
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend",
                  http_status_code=~"5.."}[1m]))
            /
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend"}[1m]))
    - name: p95-latency
      interval: 15s
      successCondition: result[0] < 2.0
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.observability.svc:9090
          query: |
            histogram_quantile(0.95,
              sum by (le) (rate(llm_ttft_seconds_bucket[1m])))
```

### 4.6 Sealed Secrets workflow

```bash
# Developer creates a normal Secret locally (never committed):
kubectl create secret generic backend-config \
  --from-literal=ANOMALY_INJECTOR_TOKEN=devsecret \
  --dry-run=client -o yaml > /tmp/secret.yaml

# Seal it for the cluster's Sealed-Secrets controller (committed):
kubeseal --controller-namespace=platform \
         --controller-name=sealed-secrets \
         --format yaml \
         < /tmp/secret.yaml \
         > deploy/secrets/backend-config.sealed.yaml

git add deploy/secrets/backend-config.sealed.yaml  # safe to commit
```

```yaml
# Resulting deploy/secrets/backend-config.sealed.yaml (excerpt)
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: backend-config
  namespace: sre-copilot
spec:
  encryptedData:
    ANOMALY_INJECTOR_TOKEN: AgB9c... (ciphertext)
  template:
    metadata: { name: backend-config, namespace: sre-copilot }
```

### 4.7 Kind cluster Terraform module sketch (3 nodes with labels)

```hcl
# terraform/local/main.tf
terraform {
  required_providers {
    kind = { source = "tehcyx/kind", version = "~> 0.4" }
  }
}

resource "kind_cluster" "sre_copilot" {
  name           = "sre-copilot"
  wait_for_ready = true
  kubeconfig_path = pathexpand("~/.kube/sre-copilot.config")

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
      kubeadm_config_patches = [yamlencode({
        kind = "InitConfiguration"
        nodeRegistration = { kubeletExtraArgs = { "node-labels" = "ingress-ready=true" } }
      })]
      extra_port_mappings {
        container_port = 80;  host_port = 80;  protocol = "TCP"
      }
      extra_port_mappings {
        container_port = 443; host_port = 443; protocol = "TCP"
      }
    }

    node {
      role = "worker"
      kubeadm_config_patches = [yamlencode({
        kind = "JoinConfiguration"
        nodeRegistration = { kubeletExtraArgs = { "node-labels" = "workload=platform" } }
      })]
    }

    node {
      role = "worker"
      kubeadm_config_patches = [yamlencode({
        kind = "JoinConfiguration"
        nodeRegistration = { kubeletExtraArgs = { "node-labels" = "workload=apps" } }
      })]
    }
  }
}

output "kubeconfig" { value = kind_cluster.sre_copilot.kubeconfig_path }
```

### 4.8 Helmfile structure (ordered releases)

```yaml
# helmfile.yaml
repositories:
  - name: traefik;        url: https://traefik.github.io/charts
  - name: argo;           url: https://argoproj.github.io/argo-helm
  - name: bitnami;        url: https://charts.bitnami.com/bitnami
  # NOTE (Fix 1 — bitnami Docker Hub migration): Bitnami removed public images from
  # the `bitnami/*` Docker Hub namespace in late 2025. Container images now live at
  # `bitnamilegacy/*`. The Helm chart repo URL above (charts.bitnami.com) is unchanged —
  # only the image.repository values in chart overrides must be updated to bitnamilegacy.
  # See helm/redis/values.yaml and the Known Environmental Gotchas section (§11).
  - name: open-telemetry; url: https://open-telemetry.github.io/opentelemetry-helm-charts
  - name: grafana;        url: https://grafana.github.io/helm-charts
  - name: sealed-secrets; url: https://bitnami-labs.github.io/sealed-secrets

releases:
  # --- platform (sync wave 0) ---
  - name: traefik;        namespace: platform;       chart: traefik/traefik
  - name: sealed-secrets; namespace: platform;       chart: sealed-secrets/sealed-secrets
                          needs: [platform/traefik]
  - name: argo-rollouts;  namespace: platform;       chart: argo/argo-rollouts
                          needs: [platform/sealed-secrets]
  # --- observability (sync wave 1) ---
  - name: loki;       namespace: observability;  chart: grafana/loki
                      needs: [platform/traefik]
  - name: tempo;      namespace: observability;  chart: grafana/tempo
                      needs: [platform/traefik]
  - name: prometheus; namespace: observability;  chart: prometheus-community/prometheus
                      needs: [platform/traefik]
  - name: grafana;    namespace: observability;  chart: grafana/grafana
                      needs: [observability/loki, observability/tempo, observability/prometheus]
  - name: otel-collector; namespace: observability; chart: open-telemetry/opentelemetry-collector
                      needs: [observability/loki, observability/tempo, observability/prometheus]
  # --- networking (wave 1) ---
  - name: networkpolicies; namespace: sre-copilot; chart: ./helm/platform/networkpolicies
                      needs: [platform/traefik]
  # --- apps (sync wave 2) ---
  - name: ollama-externalname; namespace: sre-copilot; chart: ./helm/platform/ollama-externalname
                      needs: [sre-copilot/networkpolicies]
                      # HOST_BRIDGE_CIDR env-templating (ADR-007) — see §4.15
                      set:
                        - name: hostBridgeCIDR
                          value: {{ env "HOST_BRIDGE_CIDR" | default "192.168.65.0/24" }}
  - name: redis;    namespace: sre-copilot; chart: bitnami/redis
                    needs: [sre-copilot/ollama-externalname]
  - name: backend;  namespace: sre-copilot; chart: ./helm/backend
                    needs: [sre-copilot/redis, observability/otel-collector]
  - name: frontend; namespace: sre-copilot; chart: ./helm/frontend
                    needs: [sre-copilot/backend]
```

### 4.15 Host bridge CIDR env-templating pattern (ADR-007)

Any chart value that is runtime-dependent (varies by container runtime or host environment) should follow this three-part pattern rather than being hardcoded.

**`helm/platform/ollama-externalname/values.yaml`** — declare the default with a runtime table comment:
```yaml
# CIDR of the Docker host bridge — varies by runtime.
# Docker Desktop: 192.168.65.0/24 | OrbStack: 198.19.249.0/24
# Colima: 192.168.106.0/24 | Linux Docker: 172.17.0.0/16
# Override at deploy time via env: HOST_BRIDGE_CIDR=...  make up
# Detect with: make detect-bridge
hostBridgeCIDR: "192.168.65.0/24"
```

**`helmfile.yaml`** — template the value from an env var with default fallback:
```yaml
- name: ollama-externalname
  namespace: sre-copilot
  chart: ./helm/platform/ollama-externalname
  set:
    - name: hostBridgeCIDR
      value: {{ env "HOST_BRIDGE_CIDR" | default "192.168.65.0/24" }}
```

**`helm/platform/ollama-externalname/templates/networkpolicy.yaml`** — consume the value:
```yaml
- to:
    - ipBlock:
        cidr: {{ .Values.hostBridgeCIDR }}
  ports:
    - protocol: TCP
      port: 11434
```

**`Makefile`** — auto-detect helper (`make detect-bridge`):
```bash
detect-bridge: ## Print the Docker host bridge CIDR for the current runtime
	@echo "==> Detecting Docker host bridge CIDR..."
	@HOST_IP=$$(docker run --rm --add-host=host.docker.internal:host-gateway alpine getent hosts host.docker.internal 2>/dev/null | awk '{print $$1}'); \
	if [ -z "$$HOST_IP" ]; then echo "Could not resolve host.docker.internal"; exit 1; fi; \
	CIDR=$$(echo "$$HOST_IP" | awk -F. '{print $$1"."$$2"."$$3".0/24"}'); \
	echo "Detected host IP : $$HOST_IP"; \
	echo "Suggested CIDR   : $$CIDR"; \
	echo ""; \
	echo "To use it: export HOST_BRIDGE_CIDR=$$CIDR && make up"
```

**Reuse guidance:** this same three-part pattern (chart value + helmfile env-template + `make detect-*` target) applies to any future host-runtime-dependent config, such as DNS resolver IP or host gateway CIDR.

### 4.9 Tilt Tiltfile (inner-loop dev)

```python
# Tiltfile
load('ext://restart_process', 'docker_build_with_restart')

# Backend hot-reload
docker_build_with_restart(
    'sre-copilot/backend',
    'src/backend',
    entrypoint=['uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'],
    live_update=[
        sync('src/backend', '/app'),
        run('pip install -r requirements.txt', trigger=['src/backend/requirements.txt']),
    ],
)

docker_build('sre-copilot/frontend', 'src/frontend', live_update=[
    sync('src/frontend/src', '/app/src'),
    run('npm install', trigger=['src/frontend/package.json']),
])

k8s_yaml(helm('helm/backend',  values=['helm/backend/values-dev.yaml']))
k8s_yaml(helm('helm/frontend', values=['helm/frontend/values-dev.yaml']))

k8s_resource('backend',  port_forwards=['8000:8000'], labels=['apps'])
k8s_resource('frontend', port_forwards=['3000:3000'], labels=['apps'])
k8s_resource('grafana',  port_forwards=['3001:3000'], labels=['obs'])
```

### 4.10 Prompt template for log analyzer (one Loghub HDFS few-shot slot)

```jinja
{# src/backend/prompts/log_analyzer.j2 #}
You are an SRE assistant. Analyze the log payload below and produce STRICT JSON
matching this schema (no prose, no markdown):
{
  "severity": "info" | "warning" | "critical",
  "summary": "<one sentence, ≤400 chars>",
  "root_cause": "<concise reasoning>",
  "runbook": ["<step 1>", "<step 2>", ...],
  "related_metrics": ["<promql or metric name>", ...]
}

### Example (HDFS DataNode failure)
LOGS:
{{ few_shot_hdfs_logs }}
ANALYSIS:
{{ few_shot_hdfs_analysis }}

### Now analyze
LOGS:
{{ user_logs }}
{% if context %}CONTEXT: {{ context }}{% endif %}
ANALYSIS:
```

### 4.11 Pytest structural assertion (SSE shape + JSON contract)

```python
# tests/eval/structural/test_sse_contract.py
import json
import pytest
from httpx import AsyncClient
from backend.main import app
from backend.schemas import LogAnalysis

@pytest.mark.asyncio
async def test_sse_emits_valid_final_payload(hdfs_sample):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        async with ac.stream("POST", "/analyze/logs",
                             json={"log_payload": hdfs_sample}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")

            events, accumulated = [], ""
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                evt = json.loads(line.removeprefix("data: "))
                events.append(evt)
                if evt["type"] == "delta":
                    accumulated += evt["token"]
                elif evt["type"] == "done":
                    break

    assert any(e["type"] == "delta" for e in events), "must stream tokens"
    assert events[-1]["type"] == "done"
    parsed = json.loads(accumulated)
    LogAnalysis.model_validate(parsed)  # raises if any FR1 field missing
```

### 4.12 Llama-judge evaluation script skeleton

```python
# tests/eval/judge/run_judge.py
import json
import pathlib
from datetime import datetime
from openai import OpenAI

JUDGE = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
RUBRIC = pathlib.Path("tests/eval/judge/rubric.yaml").read_text()

PROMPT = """You are an SRE eval judge. Score the CANDIDATE analysis against
the GROUND TRUTH using this rubric:
{rubric}

GROUND TRUTH:
{ground_truth}

CANDIDATE:
{candidate}

Respond as STRICT JSON:
{{
  "root_cause_match": 0|1,
  "remediation_soundness": 0..3,
  "hallucination": 0|1,
  "rationale": "<≤200 chars>"
}}
"""

def score_one(gt: dict, cand: dict) -> dict:
    resp = JUDGE.chat.completions.create(
        model="llama3.1:8b-instruct-q4_K_M",
        messages=[{"role": "user", "content": PROMPT.format(
            rubric=RUBRIC, ground_truth=json.dumps(gt), candidate=json.dumps(cand))}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(resp.choices[0].message.content)

def main():
    gts = list(pathlib.Path("datasets/eval/ground_truth").glob("*.json"))
    cands = pathlib.Path("datasets/eval/candidate_runs/latest")
    results = []
    for gt_path in gts:
        gt = json.loads(gt_path.read_text())
        cand = json.loads((cands / gt_path.name).read_text())
        results.append({"id": gt_path.stem, **score_one(gt, cand)})
    out = pathlib.Path(f"datasets/eval/judge_runs/{datetime.utcnow():%Y%m%dT%H%M%S}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": results,
        "root_cause_match_rate": sum(r["root_cause_match"] for r in results) / len(results),
    }, indent=2))

if __name__ == "__main__":
    main()
```

### 4.13 Redis values.yaml — flat structure when chart is referenced directly in helmfile (Fix 5) — **REMOVED in v1.6, retained as reference**

> **Note:** Redis was removed from the deployment in v1.6 (see ADR-006 supersede note). This section is retained because the **flat-values pattern itself** still applies to any future bitnami subchart consumed directly via `chart: bitnami/<name>` in helmfile (vs. as a Helm subchart dependency).

When a chart is consumed directly via `chart: bitnami/redis` in helmfile (not as a subchart of a
wrapper chart), values must live at the **root level** — not nested under the chart name.

```yaml
# helm/redis/values.yaml  (correct — flat structure)
#
# Rule: values.yaml at root level when chart is referenced directly in helmfile.
# Nest under subchart name ONLY when used as a Helm subchart (chart.yaml dependencies block).
# Nesting under `redis:` when using chart directly causes values to be silently ignored.

architecture: standalone

image:
  registry: docker.io
  # bitnamilegacy/* namespace — see §11 Known Environmental Gotchas (Fix 1)
  repository: bitnamilegacy/redis
  tag: "7.2.5-debian-12-r4"

auth:
  enabled: false

master:
  persistence:
    enabled: false
  resources:
    requests:
      memory: 64Mi
      cpu: 50m
    limits:
      memory: 128Mi
      cpu: 200m
```

Incorrect pattern to avoid:
```yaml
# WRONG — values silently ignored when chart is referenced directly
redis:
  architecture: standalone
  image:
    repository: bitnamilegacy/redis
```

### 4.14 Backend Dockerfile — corrected COPY layout + tiktoken cache pre-baking (Fixes 6 & 7)

Two runtime bugs were fixed in the backend Dockerfile during S1 smoke testing:

**Fix 6 — Source layout:** The original `COPY . .` into `/app` flattened `src/backend/*` into
`/app/*`, making `from backend.X` imports fail (PYTHONPATH was `/app/src`, so it expected
`/app/src/backend/`). Fixed by copying into the correct target path.

**Fix 7 — tiktoken cache:** `tiktoken.get_encoding('cl100k_base')` lazy-downloads at import time.
Inside the cluster it fails due to DNS race / NetworkPolicy / offline runs. Pre-warm in the builder
stage. Generalise: **any dep that lazy-downloads at import** (tiktoken, transformers,
sentence-transformers, certain HF tokenizers) must be pre-warmed in the builder stage with an
explicit cache dir env var.

```dockerfile
# src/backend/Dockerfile  (corrected pattern)

# ── builder ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /install
COPY src/backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-warm tiktoken cache so the pod never tries a lazy-download at runtime.
# Set cache dir explicitly; final stage inherits the env var.
ENV TIKTOKEN_CACHE_DIR=/install/tiktoken_cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONPATH=/app/src \
    TIKTOKEN_CACHE_DIR=/install/tiktoken_cache

WORKDIR /app

# Copy installed packages and tiktoken cache from builder
COPY --from=builder /install /install

# CRITICAL: preserve package directory structure.
# COPY . /app/src/backend/ places the package at the path Python looks for:
#   /app/src/backend/__init__.py → `from backend.X` works.
# DO NOT use `COPY . .` into /app — that flattens to /app/*.py and breaks imports.
COPY src/backend/ /app/src/backend/

# Verify imports resolve cleanly inside the image before shipping.
# If this fails, the build fails — better than a CrashLoopBackOff.
RUN python -c "from backend.main import app; print('import OK')"

RUN useradd -u 1001 -m appuser
USER 1001

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Companion `.dockerignore` (prevents cache dirs from inflating context):

```
# src/backend/.dockerignore
__pycache__/
*.pyc
*.pyo
.ruff_cache/
.mypy_cache/
.pytest_cache/
*.egg-info/
dist/
.env
```

---

## 5. Testing Strategy (AT mapping)

| AT | Scenario | Test type | Tooling | Where it runs | Runtime budget |
|----|----------|-----------|---------|---------------|----------------|
| AT-001 | Happy-path log analysis (sample button → SSE → JSON → trace in Tempo ≤5s) | e2e (smoke) | `make smoke` (curl + tempo HTTP API) | `make smoke`, CI nightly | 10s |
| AT-002 | Postmortem from timeline returns 8-section markdown | integration | pytest + httpx + Pydantic markdown extractor | CI per-PR | 30s |
| AT-003 | Bridge UX pipes analyzer output into postmortem flow | e2e | Playwright (Next.js) | CI per-PR | 45s |
| AT-004 | Cold-start ≤10 min from clean clone | smoke (timed) | `make up` wall-clock + `make smoke` | CI nightly (slow runner), local | <10 min hard cap |
| AT-005 | Canary rollout 25→50→100 with no 5xx | integration | `kubectl argo rollouts get rollout` + Prometheus query | manual per-sprint, `make demo-canary` | <2 min |
| AT-006 | Backend pod loss covered by PDB | chaos (manual) | `kubectl delete pod` + curl loop + `kubectl get pod -w` | `make demo`, manual | 60s |
| AT-007 | Ollama unreachable → 503 + structured error + trace span "cancelled" | integration | pytest + mocked Ollama down + Tempo query | CI per-PR | 20s |
| AT-008 | Empty/malformed input → 400, no LLM call | unit + integration | pytest with httpx | CI per-PR | 5s |
| AT-009 | Streaming disconnect cancels upstream within 2s | integration | httpx `stream()` + abort + check Ollama active_requests | CI per-PR | 15s |
| AT-010 | Layer-1 pytest structural eval green | unit (eval) | pytest `tests/eval/structural/` | CI per-PR (gate) | 30s |
| AT-011 | Layer-2 Llama judge ≥80% root-cause match | eval | `tests/eval/judge/run_judge.py` | nightly GH Actions | ~3 min |
| AT-012 | Egress denied to api.openai.com | integration | `kubectl exec ... curl` | CI per-PR (post-deploy) | 5s |
| AT-013 | Reviewer 10-min path (clean clone → demo) | e2e (manual) | timed run by an actual stranger | per-release manual | <10 min |

**Local quick gate:** `make test` runs unit + structural eval (AT-008, AT-010 + a subset). ~45s.
**Local full gate:** `make smoke` includes AT-001/004/006/007/009/012. ~3 min.
**CI per-PR:** unit + integration + structural eval. ~5 min.
**CI nightly:** above + Layer-2 judge eval + cold-start timer. ~15 min.

---

## 6. Memory Budget Plan

| Workload | Target RSS | Justification |
|----------|-----------|---------------|
| kind nodes (3× kubelet/runtime overhead) | 1.4 GB | Empirical on Docker Desktop M-series |
| Traefik | 120 MB | Single ingress |
| ArgoCD (server + repo + controller) | 600 MB | Trim to `--insecure` UI; single repo |
| Sealed Secrets controller | 60 MB | Tiny |
| Argo Rollouts controller | 80 MB | Tiny |
| OTel Collector | 150 MB | Single replica, batch processor |
| Loki (single-binary) | 350 MB | Filesystem store, retention 24h |
| Tempo (monolithic) | 250 MB | Local backend, retention 24h |
| Prometheus (subbed for Mimir) | 500 MB | 12h retention, scrape interval 30s |
| Grafana | 180 MB | 4 dashboards |
| Frontend (Next.js standalone) | 250 MB | 1 replica |
| Backend × 2 | 700 MB | 350 MB per pod (FastAPI + OTel SDK) |
| **Cluster subtotal** | **~4.7 GB** | |
| Ollama + Qwen 2.5 7B Q4 (loaded) | 5.5 GB | Model weights + KV cache headroom |
| Docker Desktop overhead | 1.5 GB | LinuxKit VM + virtiofsd |
| Chrome (reviewer browser) | 1.5 GB | Conservative |
| **Host total committed (steady)** | **~13.2 GB** | |
| **Slack on a 16 GB machine** | **~2.8 GB** | Above the >2 GB safety floor |
| **Llama 3.1 8B (judge, on-demand)** | +5.8 GB | **Loaded only during nightly eval; Qwen unloaded first via `ollama stop`. Never co-resident.** |

**Risk and mitigation.** The plan assumes Mimir → Prometheus substitution (saves ~700 MB), Loki single-binary (saves ~400 MB vs distributed), and Tempo monolithic (saves ~300 MB). If any of these creep, the first cuts in order are: Promtail (skip; OTel collector forwards logs directly), then drop frontend Next.js to plain Vite SPA (saves ~150 MB).

---

## 7. Cold-Start Performance Plan (`make up`)

| # | Step | Budget | What happens | Optimization |
|---|------|--------|--------------|--------------|
| 1 | `kind create cluster` (Terraform) | 60s | 3-node cluster up, kubeconfig written | kind images pre-pulled by `make seed-models` |
| 2 | `kind load docker-image` × N | 30s | Pre-built backend / frontend images side-loaded (no registry pulls) | Images built once and cached in `~/.cache/sre-copilot/images/` |
| 3 | `helmfile sync` — platform releases (traefik, sealed-secrets, argo-rollouts) | 45s | Charts cached locally; only template + apply | `helm dep update` cached |
| 4 | `helmfile sync` — observability (loki, tempo, prometheus, grafana, otel-collector) | 60s | Heaviest step; OTel collector blocks on Loki/Tempo/Prom Ready | Parallelize via helmfile `needs:` graph |
| 5 | `helmfile sync` — apps (ollama-externalname, backend×2, frontend) | 30s | App images already loaded → near-instant Pod start | Readiness probe tuned to 3s initial delay |
| 6 | Ollama warmup ping | 15s | `curl http://localhost:11434/api/generate` with 1-token prompt to force model load | Already loaded if `make seed-models` was run with `OLLAMA_KEEP_ALIVE=24h` |
| 7 | `make smoke` validation | 20s | Trace round-trip, memory snapshot | — |
| **Total** | | **~4.3 min** | | Stretch target met (<5 min) |

**Hard budget:** 10 min. **Stretch target:** <5 min. Both tracked by the wall-clock timer in `make smoke`.

**Pre-step (NOT counted):** `make seed-models` runs once on first install — pulls Ollama Qwen 2.5 7B Q4 (~4.1 GB) and Llama 3.1 8B Q4 (~4.7 GB), pulls all platform/observability container images, builds backend/frontend images. Documented prominently in README.

**Runtime gotcha — Ollama pull silent failure (Fix 2):** `ollama pull` returns exit code 0 on
TCP throttle/abort events but does not complete the phase-3 manifest write. Partial downloads
are GC'd between invocations. If `make seed-models` completes without error but the model is
missing on the next `ollama list`, the pull silently failed. The canonical mitigation is a
retry loop that keeps partials alive within a single process:

```bash
# Makefile seed-models target pattern
until ollama pull qwen2.5:7b-instruct-q4_K_M; do
    echo "pull failed or incomplete — retrying in 5s"; sleep 5
done
```

This keeps the download process alive across TCP retries so partial state is preserved.
Never assume a zero-exit `ollama pull` means the model is present — verify with `ollama list`.

**Prerequisite version pin — kind (Fix 3):** kind v0.20 fails `kind load docker-image` with
"failed to detect containerd snapshotter" when paired with Docker Desktop 29+ (which ships
modern containerd). **kind v0.23 or later is required.** kind 0.20 is broken with current
Docker Desktop on macOS and will cause cryptic failures at image load time, not cluster
creation time — making it hard to diagnose. Upgrade with `brew upgrade kind` and verify with
`kind version` before running `make up`.

---

## 8. Demo Script Design (`make demo`)

`make demo` is a scripted 7-minute narrative that lands the canary moment + LLM streaming + observability in the right beats. It assumes `make up` already ran.

```text
┌─────────────┬────────────────────────────────────────────────────────────┐
│ Beat (time) │ What happens (and what `make demo` automates)              │
├─────────────┼────────────────────────────────────────────────────────────┤
│ 0:00–0:30   │ Open https://sre-copilot.localtest.me in default browser   │
│             │ Open Grafana (port-forward 3001) in second tab             │
│             │ Open `kubectl argo rollouts dashboard` in third tab        │
├─────────────┼────────────────────────────────────────────────────────────┤
│ 0:30–2:00   │ ANOMALY INJECTOR FIRES                                     │
│             │ make demo POSTs to backend `/admin/inject?scenario=cascade │
│             │   _retry_storm` — backend emits 50 fake 5xx logs over 30s  │
│             │ Reviewer clicks "Try this live anomaly" sample button      │
│             │ → SSE tokens stream into UI in real time (TTFT visible)    │
│             │ → Grafana panel "Live LLM Activity" shows ttft + tokens/s  │
├─────────────┼────────────────────────────────────────────────────────────┤
│ 2:00–3:30   │ TRACE TAB                                                  │
│             │ Reviewer clicks the trace_id in the JSON output → Tempo    │
│             │   pane in Grafana opens directly to the trace              │
│             │ Shows: http.server → ollama.host_call → SYNTHETIC          │
│             │   ollama.inference span with TTFT + token count attrs      │
├─────────────┼────────────────────────────────────────────────────────────┤
│ 3:30–4:30   │ POSTMORTEM BRIDGE                                          │
│             │ Reviewer clicks "Generate postmortem from this incident"   │
│             │ → Postmortem flow streams the 8-section Google-SRE PM      │
├─────────────┼────────────────────────────────────────────────────────────┤
│ 4:30–6:30   │ CANARY MOMENT (`make demo-canary` invoked)                 │
│             │ make demo-canary triggers backend:v2 image (adds           │
│             │   "confidence": float field — VISIBLY different output)    │
│             │ kubectl argo rollouts dashboard shows traffic shift:       │
│             │   25% → analysis pause (Prom AnalysisTemplate green)       │
│             │   → 50% → 100%                                             │
│             │ Reviewer reloads UI: ~half of requests start returning the │
│             │   confidence field; then all of them                       │
│             │ Grafana SLO panel stays green throughout                   │
├─────────────┼────────────────────────────────────────────────────────────┤
│ 6:30–7:00   │ RESILIENCE BEAT                                            │
│             │ make demo runs `kubectl delete pod -l app=backend`         │
│             │   on one of the two replicas                               │
│             │ PDB keeps service available; in-flight curl loop never     │
│             │   sees a 5xx; replacement Ready in <30s                    │
└─────────────┴────────────────────────────────────────────────────────────┘
```

`make demo` is idempotent: it stops the anomaly injector at the end and reverts the canary so the next run is clean. A `make demo-reset` target is provided in case a beat goes sideways live.

---

## 9. Carried-Forward Design Items (resolved)

### 9.1 Long-log chunking strategy for Qwen 2.5 7B

**Decision: summarize-then-analyze with map-reduce fallback.**

Qwen 2.5 7B has a 32K context window in theory but practical quality degrades above ~8K input tokens for structured-output tasks. Strategy:

1. **Tokenize input.** Use `tiktoken` (cl100k_base is close enough for budget estimation; Ollama's exact tokenizer differs by ~10%, which we treat as headroom).
2. **If ≤6,000 tokens:** single-pass analysis (the common case for the demo's HDFS samples).
3. **If 6,000–18,000 tokens:** *summarize-then-analyze.* Split into 4K-token chunks; run a "summarize this log slice into 200 tokens preserving anomalies, error codes, and timestamps" pass per chunk; concatenate summaries; run the standard analyzer on the concatenation.
4. **If >18,000 tokens:** *map-reduce.* Per-chunk analysis (each producing a partial JSON), then a final "merge these N partial analyses into one consolidated analysis preserving the most severe root cause" pass.

Why summarize-then-analyze (not sliding window): sliding windows lose cross-chunk causality (the symptom in chunk 3 references the cause in chunk 1). Summarization preserves the causal thread at the cost of one extra LLM round-trip — acceptable since long-log inputs are rare in the demo path.

Implementation lives in `src/backend/chunking/strategy.py`; the strategy is selected by token count alone, deterministic, and unit-tested with synthetic inputs at the boundary sizes.

### 9.2 Synthetic span design for the Ollama host hop

**Problem.** OTel cannot auto-instrument across the kind-cluster → host-process boundary (no trace context propagation through Ollama's HTTP API). We need to attribute latency between "backend asked Ollama" and "Ollama returned" without modifying Ollama itself.

**Decision: emit a synthetic `INTERNAL` span retroactively from the backend with start/end times derived from chunk arrival timestamps.**

Implementation:

```python
# src/backend/observability/spans.py
from opentelemetry import trace
from opentelemetry.trace import Link, SpanKind

_tracer = trace.get_tracer(__name__)

def synthetic_ollama_span(parent, t0: float, duration: float,
                          input_tokens: int, output_tokens: int):
    """Create a child INTERNAL span representing host-side Ollama work,
    using already-elapsed wall time. Reconstructed from chunk timestamps."""
    end_time_ns = int((t0 + duration) * 1e9)
    start_time_ns = int(t0 * 1e9)
    with _tracer.start_as_current_span(
        "ollama.inference",
        kind=SpanKind.INTERNAL,
        start_time=start_time_ns,
        attributes={
            "llm.model": "qwen2.5:7b-instruct-q4_K_M",
            "llm.input_tokens": input_tokens,
            "llm.output_tokens": output_tokens,
            "llm.duration_seconds": duration,
            "llm.tokens_per_second": output_tokens / duration if duration else 0,
            "synthetic": True,  # discoverable in Tempo for honesty
        },
    ) as span:
        span.end(end_time=end_time_ns)
```

Attribute `synthetic=true` is set so anyone clicking the span in Tempo immediately sees it's a backend-reconstructed approximation, not a true Ollama-side measurement. This honesty is itself a portfolio signal — it shows literacy about the limits of distributed tracing across process boundaries.

### 9.3 NetworkPolicy egress-denial spec

**Decision: per-namespace default-deny with explicit allow-list. Runtime-portable via `hostBridgeCIDR` (see ADR-007).**

**Critical runtime finding (Fix 8 — S1 post-build iteration):** The original design used
`ipBlock: { cidr: 0.0.0.0/0, except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16] }` to
allow port 11434 egress to "public" IPs only. This was textbook-correct for a production
cluster where `host.docker.internal` would resolve to a non-RFC1918 ALB or VPC endpoint.

**However, on Docker Desktop for macOS, `host.docker.internal` resolves to `192.168.65.254`
— which falls inside `192.168.0.0/16`, the very CIDR in the `except` list.** The policy
silently blocked the Ollama hop it was designed to allow. Additionally, the original policy
omitted DNS egress (UDP/53) and same-namespace egress (for Redis), causing backend pods to
lose DNS resolution entirely — cascading into ImagePullBackOff and total connectivity loss.

**Local vs production target mismatch — the underlying design issue:**

| Target | `host.docker.internal` resolves to | Bridge CIDR |
|--------|-------------------------------------|-------------|
| Docker Desktop (macOS) | `192.168.65.254` (RFC1918, Docker bridge) | `192.168.65.0/24` |
| OrbStack | `198.19.249.1` | `198.19.249.0/24` |
| Colima | `192.168.106.1` | `192.168.106.0/24` |
| Linux native Docker | `172.17.0.1` | `172.17.0.0/16` |
| AWS EKS (production) | Non-RFC1918 ALB / VPC endpoint | `0.0.0.0/0 except RFC1918` or specific VPC CIDR |

The intent (default-deny, allow Ollama only) was correct. The CIDR math was wrong for any
runtime other than Docker Desktop. The fix is to parameterise the Ollama host CIDR as a
Helm value (`hostBridgeCIDR`) overridable via `HOST_BRIDGE_CIDR` env through helmfile. See
ADR-007 for the full decision rationale and §4.15 for the reusable pattern.

**Policy ownership split (post-S2 portability iteration):**
- `helm/platform/networkpolicies/` — runtime-agnostic policies: default-deny, DNS allow, same-namespace allow, observability egress allow.
- `helm/platform/ollama-externalname/` — the `allow-ollama-host-hop` policy lives here because it is tied to `hostBridgeCIDR`, a value owned by this chart. Single-responsibility: the chart that defines the bridge owns the CIDR for it.

**Policy set — runtime-agnostic policies** (`helm/platform/networkpolicies/`):

```yaml
# 1. Default deny all egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny-egress, namespace: sre-copilot }
spec:
  podSelector: {}  # all pods
  policyTypes: [Egress]
  egress: []       # deny everything by default
---
# 2. Allow DNS — UNIVERSAL, was missing in original design.
# Without this, kube-dns is unreachable → no service discovery → everything fails.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-dns, namespace: sre-copilot }
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: kube-system } }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
---
# 3. Allow same-namespace egress — UNIVERSAL, was missing in original design.
# Backend must reach Redis within sre-copilot namespace.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-same-namespace, namespace: sre-copilot }
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector: {}  # any pod in the same namespace
---
# 4. Allow observability egress (backend → otel-collector)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-observability-egress, namespace: sre-copilot }
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: observability } }
```

**Runtime-specific policy** (`helm/platform/ollama-externalname/templates/networkpolicy.yaml`):

```yaml
# Allow Ollama host hop — CIDR is runtime-dependent; see ADR-007 for the 4-runtime table.
# hostBridgeCIDR is set via helmfile from HOST_BRIDGE_CIDR env var (default: Docker Desktop).
# Auto-detect: make detect-bridge
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ollama-host-hop
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: backend
  policyTypes:
    - Egress
  egress:
    # Allow DNS to kube-system CoreDNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Allow egress to other pods within the same namespace (e.g., redis)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ .Release.Namespace }}
    # Allow egress to host.docker.internal — bridge CIDR is runtime-dependent.
    # (Docker Desktop / OrbStack / Colima / Linux differ.) See README "Configuring
    # the Docker host bridge" for detection and override instructions.
    - to:
        - ipBlock:
            cidr: {{ .Values.hostBridgeCIDR }}
      ports:
        - protocol: TCP
          port: 11434
```

**Values default** (`helm/platform/ollama-externalname/values.yaml`):
```yaml
# CIDR of the Docker host bridge — varies by runtime.
# Docker Desktop: 192.168.65.0/24 | OrbStack: 198.19.249.0/24
# Colima: 192.168.106.0/24 | Linux Docker: 172.17.0.0/16
# Override at deploy time via env: HOST_BRIDGE_CIDR=...  make up
# Detect with: make detect-bridge
hostBridgeCIDR: "192.168.65.0/24"
```

**Why `192.168.65.0/24` specifically:** Docker Desktop on macOS allocates the
`192.168.65.0/24` subnet for its internal bridge network. `host.docker.internal` is
consistently `192.168.65.254` on Docker Desktop. This CIDR is stable across Docker Desktop
versions and distinct from typical LAN ranges (`192.168.0.0/24`, `192.168.1.0/24`), making
it a safe specific allow rather than a broad RFC1918 opening.

AT-012 verifies the deny side: `kubectl exec backend -- curl -m 3 https://api.openai.com`
must time out (port 443 not in allow-list). The allow side is verified by `make smoke`
(Ollama reachability through the ExternalName Service).

### 9.4 Anomaly injector design

**Purpose.** Generate realistic backend log anomalies on demand for the live-demo "watch the system analyze a problem it just had" beat (per ADR-005).

**Design.** A guarded admin endpoint inside the backend:

```python
# src/backend/admin/injector.py
import asyncio, logging, random, os
from fastapi import APIRouter, Header, HTTPException

router = APIRouter(prefix="/admin", include_in_schema=False)
log = logging.getLogger("backend.injector")

SCENARIOS = {
    "cascade_retry_storm": [
        ("error", "downstream.timeout", "GET /upstream/api timed out after 5000ms"),
        ("error", "retry.attempt", "retrying GET /upstream/api (attempt 2/3)"),
        ("error", "retry.attempt", "retrying GET /upstream/api (attempt 3/3)"),
        ("critical", "circuit.open", "circuit breaker OPEN for upstream-api"),
    ],
    "memory_leak": [
        ("warning", "gc.long_pause", "GC pause 1.4s, heap=82%"),
        ("warning", "gc.long_pause", "GC pause 1.8s, heap=89%"),
        ("critical", "oom.imminent", "heap=96%, eviction failed"),
    ],
}

@router.post("/inject")
async def inject(scenario: str, x_inject_token: str = Header(default=None)):
    if x_inject_token != os.environ.get("ANOMALY_INJECTOR_TOKEN"):
        raise HTTPException(403)
    if scenario not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario: {scenario}")
    pattern = SCENARIOS[scenario]
    # Emit each line several times with realistic jitter:
    for _ in range(15):
        for level, event, msg in pattern:
            getattr(log, level if level != "critical" else "error")(
                msg, extra={"event": event, "synthetic_anomaly": True})
            await asyncio.sleep(random.uniform(0.05, 0.35))
    return {"status": "injected", "scenario": scenario, "events": 15 * len(pattern)}
```

Guards:
- `ANOMALY_INJECTOR_TOKEN` is a Sealed Secret, mounted as env. Without the right header, returns 403.
- Endpoint is hidden from OpenAPI schema (`include_in_schema=False`).
- Each emitted log line carries `synthetic_anomaly: true` so eval / production filters can exclude them.

Why this design: it produces *real* logs that flow through Loki and the analyzer endpoint just like organic logs would — the demo isn't replaying a canned file, it's analyzing the cluster's live output.

---

## 10. Open Questions Carried to /build

Only one remains, and it's a small one:

**OQ-B1 — Loghub HDFS subset size.** The full HDFS dataset is ~1.5 GB. We need a representative subset of ~5 MB to commit to Git (git-lfs avoided to keep the clone fast for AT-013). The exact subset selection (which time range, which anomaly classes to over-represent) is best made empirically during S1 by `/build` while it can iterate against the actual Pydantic schema and prompt template. Recommended approach: start with the first 50,000 lines including all `BLOCK*` anomaly events from the labeled set; if Layer-2 judge variance is too high, expand. Tracked in `datasets/loghub/hdfs/SUBSET.md`.

Everything else is decided. `/build` should not need to ask the user any clarifying question outside this single empirical tuning loop.

---

## 11. Known Environmental Gotchas

These are not project bugs — they are external runtime conditions that affect any developer
running this stack. Each was surfaced during S1 smoke testing on Docker Desktop + kind on an
M3 Mac and is documented here so future readers have the escape hatch without a debugging
session.

---

### 11.1 bitnami → bitnamilegacy Docker Hub migration (Fix 1)

**What happened:** Bitnami removed all images from the `bitnami/*` Docker Hub namespace in
late 2025. Images are now served from `bitnamilegacy/*`. The Helm chart repository URL
(`charts.bitnami.com/bitnami`) is unaffected — only the container image `repository` field in
chart overrides must be updated.

**Affected files in this repo:**
- `helm/redis/values.yaml`: `image.repository: bitnamilegacy/redis`
- `Makefile` `seed-models` target: `docker pull bitnamilegacy/redis:7.2.5-debian-12-r4`

**Future maintenance note:** `bitnamilegacy` is itself a transitional namespace — Bitnami's
stated path is migration to `oci://registry-1.docker.io/bitnamicharts`. When `bitnamilegacy`
is eventually retired, update `image.repository` and the Makefile pull command to the new
location. Check https://github.com/bitnami/containers for current guidance. This is
*external drift*, not a project bug — pin the tag (`7.2.5-debian-12-r4`) and update
deliberately.

---

### 11.2 kind 0.20 containerd-snapshotter bug — require kind 0.23+ (Fix 3)

**What happened:** kind v0.20 fails `kind load docker-image` with:
```
failed to detect containerd snapshotter
```
when paired with Docker Desktop 29+ (which ships a modern containerd version). This is a kind
bug fixed in kind v0.23.

**Affected step:** `make up` calls `kind load docker-image` to side-load backend/frontend
images. With kind 0.20 this fails *after* cluster creation, making it look like an image or
Makefile problem.

**Resolution:** `brew upgrade kind` → verify `kind version` shows `0.23.0` or later.
kind 0.20 is broken with current Docker Desktop on macOS. There is no workaround within
the project — the tool version must be upgraded.

---

### 11.3 Ollama silent pull failure (Fix 2)

**What happened:** `ollama pull` returns exit code 0 on TCP throttle or abort events but does
not complete the phase-3 manifest write. Idle partials are GC'd between invocations. The
result is a successful-looking `make seed-models` that leaves no usable model.

**Detection:** Always verify with `ollama list` after `make seed-models`. If the model is
absent despite a clean exit, the pull silently failed.

**Mitigation (canonical):** The `seed-models` Makefile target wraps the pull in a retry loop:
```bash
until ollama pull qwen2.5:7b-instruct-q4_K_M; do
    echo "pull incomplete — retrying in 5s"; sleep 5
done
```
Keeping the process alive across retries preserves partial download state in Ollama's internal
store. Splitting into separate invocations (e.g., `make seed-models && make seed-models`)
does NOT help — each new invocation discards partials.

---

### 11.4 Corporate VPN + multi-platform image flatten workaround (Fix 4)

**What happened:** When a corporate TLS-inspecting VPN (e.g. Sophos) is active, kind nodes
cannot pull from Docker Hub directly (cert chain interception causes TLS errors inside the
container). Additionally, `kind load docker-image` rejects multi-platform manifest images
with attestation layers — it chokes on the manifest list format used by many upstream images.

**Preferred resolution:** Disable the VPN during `make seed-models` and `make up`. The
cluster is local-only; there is no security reason to have VPN active during local dev setup.

**When VPN cannot be disabled — image flatten recipe:**
```bash
# Flatten a multi-platform upstream image to a single-arch local image
# suitable for `kind load`.
# Replace <upstream>:<tag> and <name>:<ver> with actual values.

cat > /tmp/Dockerfile.flatten <<'EOF'
FROM <upstream>:<tag>
EOF

docker build \
  --platform linux/arm64 \
  --provenance=false \
  --sbom=false \
  -t local/<name>:<ver> \
  -f /tmp/Dockerfile.flatten \
  /tmp

kind load docker-image local/<name>:<ver> --name sre-copilot
```

Flags explained:
- `--platform linux/arm64`: selects the arm64 variant only, producing a single-arch manifest
- `--provenance=false --sbom=false`: strips attestation layers that confuse `kind load`
- The resulting `local/<name>:<ver>` image is safe to side-load

**Note:** This workaround was developed during S1 debugging but not committed as persistent
code — the VPN-disable path was used instead. Document this here so the next reviewer on a
corporate network has the escape hatch.

---

### 11.5 Docker host bridge CIDR varies by runtime — now solved (was Fix 8, extended post-S2)

**Previously a gotcha; now solved via configurable `hostBridgeCIDR` (ADR-007).**

**What happened (v1.2 era):** The NetworkPolicy egress rule for the Ollama host hop hardcoded `192.168.65.0/24` (Docker Desktop's bridge CIDR). On OrbStack (`198.19.249.0/24`), Colima (`192.168.106.0/24`), and Linux native Docker (`172.17.0.0/16`), the policy silently blocked all connections to Ollama — connection timeouts with no obvious cause since the ExternalName Service resolves correctly but the NetworkPolicy drops the packet.

**Resolution (post-S2 portability iteration):**
- `hostBridgeCIDR` value in `helm/platform/ollama-externalname/values.yaml` (default `192.168.65.0/24` for Docker Desktop).
- Overridable at deploy time via `HOST_BRIDGE_CIDR` env var: `HOST_BRIDGE_CIDR=198.19.249.0/24 make up`.
- `make detect-bridge` auto-detects the CIDR for the current runtime by resolving `host.docker.internal` inside a one-shot Docker container.
- README "Configuring the Docker host bridge" section documents the runtime-to-CIDR table and the `export` + `make up` workflow.

**For future contributors:** if you add another host-runtime-dependent configuration value (e.g., DNS resolver IP, host gateway CIDR), reuse the env-templated-helmfile-value-with-detect-target pattern documented in §4.15 and ADR-007.

---

### 11.6 Local backend dev needs `OLLAMA_BASE_URL` override (post-S2 — solved)

**Previously a friction point; now solved via ADR-008.**

When running the backend outside the kind cluster (e.g., `cd src/backend && uvicorn backend.main:app` for inner-loop dev or debugging), the default `OLLAMA_BASE_URL=http://ollama.sre-copilot.svc.cluster.local:11434/v1` doesn't resolve — that's an in-cluster service name only reachable from pods.

**Fix:** export `OLLAMA_BASE_URL=http://localhost:11434/v1` before starting uvicorn. The backend reads this env at module load time and points the OpenAI client at the host's local Ollama directly. No code change needed.

```bash
cd src/backend
OLLAMA_BASE_URL=http://localhost:11434/v1 uvicorn backend.main:app --reload
```

This composes with `LLM_MODEL` overrides too — e.g., `LLM_MODEL=phi3:mini OLLAMA_BASE_URL=http://localhost:11434/v1 uvicorn ...` for low-RAM local dev. See ADR-008 for the full pattern.

---

## 12. Known Issues / Tech Debt (Sprint 2 Cleanup Items)

These were discovered during S1 runtime validation and require resolution before or during S2.

| # | Item | Impact | Resolution |
|---|------|--------|------------|
| TD-1 | Helm release records out-of-sync for backend | `helmfile sync` may conflict on `readOnlyRootFilesystem` field due to `kubectl patch` applied during S1 debugging. Subsequent helmfile sync has field-manager ownership conflicts on that field. | Run `helm upgrade backend helm/backend -n sre-copilot --force` to reset field manager ownership, OR revert the patch via `kubectl patch deployment backend -n sre-copilot --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem","value":true}]'`. Sprint 2 cleanup before NetworkPolicy work. |
| TD-2 | Ingress full path through Traefik unverified | The S1 smoke test used `kubectl port-forward deploy/backend 8000:8000` for the SSE e2e check. The `https://sre-copilot.localtest.me` path through Traefik ingress has not been smoke-tested end-to-end. This is the path a real reviewer would use. | Add an explicit `make smoke` step that exercises the ingress URL (not the port-forward URL). Verify TLS termination, SSE framing through Traefik, and the `/api/*` proxy path. Sprint 2 item alongside the AT-012 egress-deny test. |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-26 | design-agent | Initial DESIGN from DEFINE_sre-copilot.md (clarity 14/15). 6 ADRs written inline (OQ-5). Sprint-organized 54-entry module-level manifest. All 4 carried-forward design items from DEFINE resolved (chunking, synthetic span, NetworkPolicy, anomaly injector). |
| 1.1 | 2026-04-26 | build-agent | Updated status to S1 Complete after Sprint 1 build phase. 19 manifest entries built, 35/35 tests pass, ruff clean. |
| 1.3 | 2026-04-26 | build-agent | S2 build complete. Entries #20–#27 built. TD-1 resolved. §9.3 NetworkPolicy implemented (corrected CIDR spec). Middleware (#23) wired into main.py. Backend analyze.py bug fixed (HTTPException-in-generator → return). seccompProfile RuntimeDefault added to backend+frontend. Integration tests AT-007/008/009 passing (41/41). New tech debt: TD-3 (SSE error contract), TD-4 (AT-009 disconnect), TD-5 (detect-bridge linter addition).
| 1.2 | 2026-04-26 | iterate-agent | Phase-bridging back-port of 7 S1 runtime discoveries before S2 /build begins. Fix 1: §4.8 bitnami→bitnamilegacy Docker Hub migration note + §11.1 gotcha. Fix 2: §7 Ollama silent-pull retry-loop pattern + §11.3 gotcha. Fix 3: §7 kind 0.23+ version pin + §11.2 gotcha. Fix 4: §11.4 corporate VPN + image flatten recipe. Fix 5: §4.13 Redis flat values structure rule. Fix 6: §4.14 backend Dockerfile corrected COPY layout + .dockerignore. Fix 7: §4.14 tiktoken cache pre-baking in builder stage. Fix 8: §9.3 NetworkPolicy egress spec rewritten — local/prod CIDR mismatch root-cause documented, `ollamaHostCIDR` value introduced, DNS + same-namespace allows added. Added §11 Known Environmental Gotchas, §12 Known Issues / Tech Debt (TD-1 helm field-manager conflict, TD-2 ingress unverified). Status updated to S1 Complete (Built + Iterated post-build — v1.2). DEFINE not touched. |
| 1.4 | 2026-04-26 | iterate-agent | Phase-bridging portability back-port (post-S2). ADR-007 added (Configurable Docker host bridge CIDR — portability across Docker Desktop / OrbStack / Colima / Linux). §3 manifest #13 updated: `ollama-externalname` now described with `hostBridgeCIDR` value + helmfile env-templating. §3 manifest #22 updated: `networkpolicies` clarified as strictly runtime-agnostic (host-bridge policy relocated to #13). §4.8 helmfile sketch updated with `networkpolicies` wave + `ollama-externalname` `set:` block for env-template. §4.15 new pattern section: host bridge CIDR env-templating (chart value + helmfile template + `make detect-bridge`). §9.3 renamed `ollamaHostCIDR` → `hostBridgeCIDR`, relocated from networkpolicies chart to ollama-externalname, added 4-runtime table (Docker Desktop / OrbStack / Colima / Linux), updated YAML to match actual implementation, split policy ownership (runtime-agnostic in networkpolicies chart, bridge-specific in ollama-externalname). §11.5 new gotcha entry: Docker host bridge CIDR — previously a gotcha, now solved; pattern reuse guidance for future contributors. Table of Contents ADR range updated to ADR-001 → ADR-007. Status bumped to v1.4. |
| 1.5 | 2026-04-26 | iterate-agent + manual | Per-machine configurability cascade (post-S2 v2). ADR-008 added (Per-machine env-overridable settings via Makefile + Helmfile + Helm values; 4-layer pattern with 5 settings: HOST_BRIDGE_CIDR, LLM_MODEL, LLM_JUDGE_MODEL, INGRESS_HOST, OLLAMA_BASE_URL). §3 manifest #1 (Makefile) updated with `?=` env-overridable vars + `export`. §3 manifest #4 (src/backend/) updated with env-driven OLLAMA_BASE_URL + LLM_MODEL. §3 manifest #9 (helm/backend/) updated with new ConfigMap entries + llm.* values. §3 manifest #10 (helm/frontend/) updated with `ingressHost` value + `tpl`-templated NEXT_PUBLIC_API_URL. §3 manifest #14 (helmfile.yaml.gotmpl) updated with `set:` blocks + `.gotmpl` extension note (Helmfile v1+ requirement). §11.6 new gotcha entry: local backend dev OLLAMA_BASE_URL override pattern. Table of Contents ADR range updated to ADR-001 → ADR-008. Status bumped to v1.5. Sealed-secrets chart pin bumped (~2.0 → ~2.17) to escape v0.17.1/quay.io image (parallel external-drift issue, same family as bitnamilegacy). |
| 1.6 | 2026-04-26 | manual | **Redis removed entirely** per YAGNI. Reviewer asked the exact ADR-006-predicted question ("why is Redis here?") within hours; the "future caching" door was never opened; 80 MB cost was real on 16 GB Mac. ADR-006 marked partially superseded (statelessness retained, Redis-backed-session rejection retained, "deployed but unused" choice reversed). §1.1 hero diagram: redis box removed. §1.2 component inventory: redis row removed. §3 manifest #11 (helm/redis/) marked REMOVED. §3 manifest #14 (helmfile.gotmpl) and #29 (argocd applications) text scrubbed of redis references. §6 memory budget: redis row removed (frees 80 MB). §7 cold-start: helmfile sync step text scrubbed. §4.13 (Redis flat-values pattern) marked REMOVED but retained as reference for future bitnami subchart use. Code: `helm/redis/` directory deleted, helmfile.gotmpl release entry deleted, bitnami repo entry deleted (now unused since sealed-secrets uses bitnami-labs not bitnami), Makefile redis pre-pull + helm-lint entries removed, NetworkPolicy comments scrubbed of redis examples. Live cluster: `helm uninstall redis` + PVC deletion. |
| 1.7 | 2026-04-27 | iterate-agent | Sprint 5: TLS, observability pipeline, dashboards, canary, bootstrap, eval. ADR-009 (mkcert local CA + Traefik TLSStore default), ADR-010 (OTel Logs SDK with loki.resource.labels hint, append-not-replace handler bug documented), ADR-011 (Tempo local-blocks metricsGenerator for TraceQL search, three gotchas documented), ADR-012 (dashboard JSON as source-of-truth + regen tooling), ADR-013 (single-platform image loading for kind via docker save --platform). §3 Sprint 5 manifest section added (entries #55–#69, 15 new modules). Manifest Summary updated (total 69 entries, S5=15 sprint distribution). Table of Contents ADR range updated to ADR-001 → ADR-013. Metadata status bumped to S5 Complete — v1.7. |

---

## Next Step

**Sprint 1 built:** `/build` completed S1 (entries #1–#19). All 35 unit tests pass. ruff clean.

**Post-build iteration complete:** `/iterate` back-ported 7 S1 runtime fixes into DESIGN v1.2.

**Sprint 2 built:** `/build` completed S2 (entries #20–#27). 41/41 tests pass (35 unit + 6 integration). ruff clean. TD-1 resolved. §9.3 corrected NetworkPolicy spec implemented. See BUILD_REPORT_sre-copilot_S2.md.

**Post-S2 portability iteration complete:** `/iterate` back-ported configurable host bridge CIDR work into DESIGN v1.4 (ADR-007, §4.15, §9.3 rename/relocate, §11.5, manifest #13 + #22). DEFINE amended (A-002, NFR7). Code files already done by user — not touched.

**S3 built:** `/build` completed S3 (entries #28–#38). ArgoCD app-of-apps pattern, LGTM stack (Loki/Tempo/Prometheus/Grafana), OTel Collector, backend OTel wiring, frontend OTel SDK, 4 Grafana dashboards, MWMBR SLO alerts, AT-012 egress test, AT-001 Tempo trace assertion. See BUILD_REPORT_sre-copilot_S3.md.

**S4 built:** `/build` completed S4 (entries #39–#54). Argo Rollouts canary strategy, demo script, ADRs published, README final pass. Tag v1.0.0.

**Sprint 5 iterated:** `/iterate` back-ported 36-commit Sprint 5 session into DESIGN v1.7. ADR-009 through ADR-013 added. Sprint 5 manifest (entries #55–#69) added. File manifest deltas: `helm/backend/templates/analysistemplate.yaml` (relocated), `observability/dashboards/regen-configmaps.py` (new), `.certs/` (gitignored), plus updates to Makefile, backend observability init + logging, HPA template, Grafana + Tempo values, ArgoCD Applications, eval judge runner, nightly-eval workflow, and log_analyzer prompt.

**Next step:** `/ship` to cut the portfolio release, or `/iterate` for further polish on any remaining demo gaps.
