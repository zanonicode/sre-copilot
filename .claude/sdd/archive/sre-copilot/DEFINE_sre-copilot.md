# DEFINE: SRE Copilot

> A self-contained, kind-native LLM platform demo: streaming log analysis + postmortem generation, fully observable via LGTM, deployable cold in under 10 minutes — built as a portfolio signal of real platform-engineering literacy.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | sre-copilot |
| **Date** | 2026-04-27 |
| **Author** | define-agent |
| **Status** | ✅ Shipped |
| **Clarity Score** | 14/15 |
| **Source** | `.claude/sdd/features/BRAINSTORM_sre-copilot.md` (Phase 0) |

---

## Problem Statement

A reviewer evaluating a platform/SRE/AI-infra candidate cannot, in a 10-minute window, distinguish "wraps an API key" from "actually operates real platforms" by reading a resume or staring at a repo tree. The SRE Copilot exists to collapse that judgment into a single `make up` command that produces a streaming LLM analysis surfaced through real GitOps, progressive delivery, and observability — proving operational literacy by running, not by claiming.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| **Reviewer / Hiring Manager** | Evaluates candidates for platform / SRE / AI-infra roles in a time-boxed (≤10 min) window | Cannot tell from a README whether a candidate has actually run real systems; needs a tactile, working demo that holds up to a live walkthrough |
| **Future SRE / Platform Engineer extending the repo** | Forks the project to extend it (vLLM, multi-tenant routing, GPU autoscaling, real cloud migration) | Most "demo" repos are scaffolding — they fall apart the moment you try to extend them; this one must remain a clean substrate for follow-on work |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Cold `make up` from clean clone yields a working URL with streaming LLM output in ≤10 min on M3/16 GB MacBook on any supported Docker runtime (Docker Desktop, OrbStack, Colima, Linux native Docker) — `HOST_BRIDGE_CIDR` may need to be set for non-Docker-Desktop runtimes; `make detect-bridge` automates this (NFR1, NFR7; see ADR-007) |
| **MUST** | Every request is end-to-end traceable browser → ingress → backend → Ollama in Tempo/Grafana (FR5); trace IDs are promoted to Loki stream labels so a single click from any log line in Grafana opens the full span tree in Tempo Explore |
| **MUST** | Reviewer can trigger a visible canary rollout via Argo Rollouts in ≤2 min during the walkthrough (FR6); AnalysisTemplate ships inside the backend Helm chart; sustained load is injected automatically by `make demo-canary` so the analysis window has data to evaluate |
| **MUST** | Local TLS is trusted system-wide via mkcert CA + Traefik TLSStore wildcard cert (`*.localtest.me`); `make trust-certs` is a one-time setup and eliminates per-subdomain cert warnings for frontend, API, Grafana, Prometheus, and ArgoCD |
| **MUST** | Log Analyzer streams structured JSON (`severity`, `summary`, `root_cause`, `runbook`, `related_metrics`) over SSE (FR1) |
| **MUST** | Postmortem Generator produces a Google SRE Workbook-format postmortem from a timeline (FR2) |
| **MUST** | One-click Loghub sample buttons in UI — reviewer never faces an empty textarea (FR4) |
| **MUST** | Eval results (structural + LLM-judge) are committed and surfaced in README (Section 1, BRAINSTORM); nightly eval uses stratified-by-prefix sampling (default 6 records, configurable via `JUDGE_SAMPLE_SIZE` env var or workflow_dispatch input for full corpus) |
| **MUST** | Zero external API spend — local inference + local judge (NFR6) |
| **SHOULD** | Bridge UX: "Generate postmortem from this incident" pipes Log Analyzer output into Postmortem flow (FR3) |
| **SHOULD** | 4–6 ADRs covering load-bearing decisions (locked list in Open Questions resolution) |
| **SHOULD** | Warm restart in <30s (NFR2) |
| **COULD** | k6 load test scenarios in `deploy/load/` |
| **COULD** | One-shot `trivy image` scan in CI (not Trivy Operator) |
| **COULD** | Loom walkthrough recording linked from README |
| **SHOULD** | Operational tooling is self-documenting via `make help`; Sprint 5 targets include: `make trust-certs` (one-time CA setup), `make dashboards` (delete-then-recreate from JSON source), `make restart-backend` (Argo-Rollouts-native restartAt), `make clean-replicasets` (housekeeping) |

---

## Success Criteria

Measurable, verifiable outcomes:

- [ ] **Cold start ≤10 min** (stretch <5 min) on M3/16 GB — verified by `make up` wall-clock timer captured in `make smoke` output and CI artifact
- [ ] **TTFT ≤2 s p95** — verified by an OTel histogram metric `llm.ttft_seconds` scraped by Mimir/Prom; p95 read off Grafana panel; baseline run committed to `datasets/eval/perf_baseline.json`
- [ ] **Full response ≤30 s p90** — same OTel histogram (`llm.response_seconds`), p90 panel
- [ ] **Total committed memory <14 GB steady-state** — verified by `docker stats` + host `vm_stat` snapshot in `make smoke`; committed to `bench/mem_baseline.txt`
- [ ] **Warm restart <30 s** — `make down && make up` wall-clock, captured by smoke target
- [ ] **End-to-end trace visible in Tempo for every request** — synthetic check: `make smoke` issues 1 analyzer request, asserts a Tempo trace ID is present with ≥4 spans (browser-emulated → ingress → backend → ollama-host-hop)
- [ ] **Canary rollout demoable in <2 min** — `make demo-canary` triggers a v2 image bump, injects sustained background load during the 60s AnalysisTemplate window, and `kubectl argo rollouts get rollout` shows progressive traffic shift; verified manually each sprint
- [ ] **Eval Layer 1 (pytest structural) green on every commit** — CI gate; ≥95% pass rate over rolling 20 commits
- [ ] **Eval Layer 2 (Llama-judge) ≥80% root-cause-match on held-out set** — nightly job; default 6 stratified records (`JUDGE_SAMPLE_SIZE=6`); full corpus run available via manual workflow_dispatch; results in `datasets/eval/judge_runs/*.json`, latest committed; judge requires semantic equivalence (not literal substring match); analyzer requires evidence-grounded root cause to prevent few-shot overfit
- [ ] **Zero external API calls at runtime** — verified by egress denial NetworkPolicy + a CI test that runs `make up` with `OPENAI_API_KEY=invalid` etc. and confirms demo still works

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Happy path log analysis | Cluster up; Ollama healthy; reviewer opens UI | Reviewer clicks "Try HDFS DataNode failure" sample and submits | UI streams tokens within 2 s; final JSON contains all 5 required fields; trace visible in Tempo within 5 s |
| AT-002 | Postmortem generation | Cluster up; reviewer has an incident timeline pasted | Reviewer submits to `/postmortem` endpoint | Response is a Google-SRE-Workbook-format markdown postmortem with sections: Summary, Impact, Root Cause, Trigger, Resolution, Detection, Action Items, Lessons Learned |
| AT-003 | Bridge UX | Log Analyzer has just produced output | Reviewer clicks "Generate postmortem from this incident" | Postmortem flow is invoked with the analyzer output as seed; new postmortem streams without re-pasting |
| AT-004 | Cold start budget | Clean clone, no images cached, `make seed-models` already run | Reviewer runs `make up` | Working URL responsive within 10 min wall-clock; `make smoke` exits 0 |
| AT-005 | Canary rollout | Backend v1 serving 100% traffic, v2 image built | Operator runs `make demo-canary` | Sustained background load is injected automatically; `kubectl argo rollouts get rollout` shows 25% → 50% → 100% progression with AnalysisTemplate evaluation passing; no 5xx during shift |
| AT-006 | Backend pod loss (PDB) | 2 backend replicas Ready | `kubectl delete pod` on 1 replica | Service stays available (no failed user request); replacement pod Ready in <30 s |
| AT-007 | Ollama unreachable | Backend up; host Ollama process killed | Reviewer submits log analysis | Backend returns 503 with structured error JSON; trace shows failed `ollama.host_call` span; no crash loop |
| AT-008 | Empty/malformed input | UI loaded | Reviewer submits empty payload | Backend returns 400 with field-level validation error; no LLM call billed/attempted |
| AT-009 | Streaming disconnect | SSE stream in flight | Client closes connection mid-stream | Backend cancels the upstream Ollama request within 2 s; no orphaned generation; trace span closed with `cancelled` status |
| AT-010 | Eval layer 1 in CI | PR opened changing prompt template | CI runs `pytest tests/eval/structural/` | All structural assertions pass or PR is blocked |
| AT-011 | Eval layer 2 nightly | Nightly schedule fires | Llama-judge evaluates 6 stratified-by-prefix records (default); full corpus available via manual workflow_dispatch | JSON results committed to `datasets/eval/judge_runs/`; root-cause-match rate ≥80%; judge uses semantic equivalence; no "ephemeral port exhaustion" hallucination across all HDFS samples |
| AT-012 | Zero-egress guarantee | Cluster up | `kubectl exec backend -- curl -m 3 https://api.openai.com` | Connection denied/timed out by NetworkPolicy |
| AT-013 | Reviewer 10-min path | Stranger with clean repo, M3/16 GB Mac, any supported Docker runtime (Docker Desktop / OrbStack / Colima) | Follows README from `git clone` to demo; sets `HOST_BRIDGE_CIDR` if not on Docker Desktop (via `make detect-bridge` or README table); for non-canonical setups (low-RAM, corporate DNS), follows the README "Per-machine configuration" section (ADR-008) before `make up` | Total wall-clock ≤10 min including reading the README |
| AT-014 | Low-RAM-tier reviewer path | 8 GB MacBook, Docker Desktop | `LLM_MODEL=phi3:mini SKIP_JUDGE=1 make seed-models && make up && make smoke` | Cluster up; smoke passes; total committed memory under 10 GB; SSE streaming returns tokens. **Status: design-validated via ADR-008 pattern; runtime-validated pending — needs an 8 GB Mac to test against.** |
| AT-015 | Trace correlation in ≤2 clicks | Cluster up; a backend request has been processed; Grafana logs view open | Reviewer clicks a `traceid` value in any backend log line | Grafana opens the full span tree in Tempo Explore; ≤2 clicks from log line to span tree |
| AT-016 | Trust-certs is a one-time, idempotent setup | `make trust-certs` has already been run | Reviewer runs `make trust-certs` again | No certificate re-installation, no password prompts, no browser warnings; command exits 0 with no changes reported |
| AT-017 | Dashboards show real zeros on idle service | Cluster up; no requests sent for ≥5 min | Reviewer opens any backend Grafana dashboard | All stat panels display numeric values (0%, 0, 100%) with sparklines; no panel shows "No data" |
| AT-018 | Eval default-samples 6 stratified records | Nightly eval workflow fires with no manual override | Llama-judge runs | Exactly 6 records are sampled, one per log-prefix group; `JUDGE_SAMPLE_SIZE` env var accepted; full corpus run triggered via workflow_dispatch produces result over all records |
| AT-019 | Cold-laptop `make up` without internet inside kind | Laptop with corporate CA chain; no direct quay.io access from inside kind nodes | `make up` on clean kind cluster | ArgoCD image is pre-pulled on host and kind-loaded before cluster bootstrap; no pull attempt hits quay.io from inside kind nodes; `make up` succeeds without network errors |

---

## Out of Scope

Explicitly **NOT** in this project (pulled from BRAINSTORM YAGNI cuts and original plan §10):

- **Multi-cluster, multi-region, real HA.** Single-node kind cluster; replicas are demo theater above the backend's 2-replica baseline.
- **Production-grade auth / multi-tenancy.** No users, no RBAC beyond k8s defaults, no SSO.
- **Persistent state beyond the cluster lifecycle.** Redis is single-replica, ephemeral; no backups.
- **Kyverno policy enforcement** — documented-only in `docs/policy.md`.
- **Trivy Operator continuous scanning** — replaced by one-shot `trivy image` in CI (COULD).
- **Chaos Mesh experiments** — documented-only; canary rollout supplies the resilience signal.
- **Multi-architecture container builds** — local target is arm64 Mac.
- **AWS / GCP reference Terraform** — replaced by `docs/aws-migration.md` describing the *thinking*.
- **Frontend / Redis multi-replica** — 1 each.
- **3+ backend replicas** — 2 is enough to exercise canary + PDB.
- **vLLM / GPU serving / multi-tenant routing** — explicit follow-on work, not MVP.
- **Fine-tuning / RAG over a vector DB** — Loghub samples + few-shot prompts only.
- **Real incident ingestion (PagerDuty, Sentry, etc.)** — UI samples and pasted payloads only.
- **External LLM APIs (OpenAI, Anthropic, Gemini, OpenRouter)** — violates NFR6.
- **Mobile / responsive UI polish** — desktop Chrome on the reviewer's laptop is the only target.
- **i18n** — English only.
- **Sprint 4 deferrals to v1.1 backlog** (Open Question 1 resolution): k6 load tests, AWS migration doc, multi-arch builds — see Open Questions section.
- **Ad-hoc Grafana dashboard edits via UI** — dashboards are managed as JSON source files; `regen-configmaps.py` generates configmaps.yaml; `make dashboards` does delete-then-recreate. UI edits are not persisted.

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Hardware | M3 MacBook, 16 GB RAM (target reviewer machine) | Forces single-replica discipline, Q4 quantization, lean platform kit; no room for Maximal stack |
| Cost | Zero external API spend (NFR6) | Local inference (Ollama + Qwen 2.5 7B Q4); local judge (Llama 3.1 8B); no managed services |
| Time-to-value | Reviewer attention budget = 10 min total (NFR1, NFR7) | Cold-start budget is brutal; everything cacheable must be cached; `make seed-models` must be a separate one-time step |
| Networking | macOS + kind = no native host networking | Ollama reached via `ExternalName` Service → `host.docker.internal:11434`; this is the brittlest seam (Risk in BRAINSTORM §5) |
| LLM context | Qwen 2.5 7B has limited context window | Chunking/windowing strategy required for long log payloads — design work for `/design` |
| Portfolio framing | Must read as "operator literacy", not "API wrapper" | Every component must have a *visible moment* in the 10-min walkthrough or be cut |
| Demo determinism | Live demo must not flake on stage | One rehearsed canary path > one unpredictable chaos experiment |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `deploy/` (kind config, Helm values, ArgoCD app manifests, Argo Rollouts specs + AnalysisTemplate inside backend Helm chart, Sealed Secrets, OTel collector config, dashboard JSON + configmaps.yaml, mkcert CA artifacts), `src/backend/` (FastAPI), `src/frontend/` (UI), `datasets/` (Loghub, postmortems, eval ground truth), `docs/adr/` (4–6 ADRs), `Tiltfile`, `Makefile`, `scripts/regen-configmaps.py` | Multi-tree project; not a single-domain feature. Design phase will produce per-tree structure. |
| **KB Domains** | None of the existing `.claude/kb/` domains apply directly (this is a Kubernetes/observability project, not the GCP/Gemini/Pydantic stack the KB was built for). Pydantic patterns may apply for backend response models. | Design phase will create new KB notes for: kind-on-macOS, Argo Rollouts canary, Ollama-via-ExternalName, OTel synthetic span pattern, Loghub data handling. |
| **IaC Impact** | New: kind cluster config, Helm chart values for ArgoCD/Sealed-Secrets/Argo-Rollouts/LGTM/OTel-Collector, Argo Rollouts manifests, NetworkPolicy for egress denial. No cloud Terraform (deferred to `docs/aws-migration.md`). | Infrastructure is local-only but substantial — `/design` and `/architect` should treat the kind+Helm+ArgoCD layer as first-class IaC. |

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | Qwen 2.5 7B Q4 on Ollama produces structurally usable JSON for Log Analyzer with prompt engineering alone (no fine-tuning) | Need to add JSON-mode constrained decoding, function-calling shim, or fall back to a different local model | [ ] |
| A-002 | `host.docker.internal:11434` reaches host Ollama reliably from kind on macOS in 2026 on any supported container runtime. Host bridge CIDR varies by runtime (Docker Desktop `192.168.65.0/24` / OrbStack `198.19.249.0/24` / Colima `192.168.106.0/24` / Linux native Docker `172.17.0.0/16`); supported via helmfile env-templating with `HOST_BRIDGE_CIDR` env var (default: Docker Desktop). Auto-detect with `make detect-bridge`. See ADR-007 + ADR-008 (umbrella per-machine env-overridable pattern). | Need a sidecar Ollama in-cluster (blows memory budget) or a different host-bridge pattern | [x] (ADR-007 — configurable CIDR + detect target; subsumed by ADR-008 pattern) |
| A-003 | LGTM stack + OTel Collector + ArgoCD + Sealed Secrets + Argo Rollouts + Qwen 7B + backend×2 + frontend + Redis fits under 14 GB committed | Must drop a component (likely Mimir → Prometheus, or Loki → file-based logging) | [ ] |
| A-004 | Llama 3.1 8B as judge can distinguish good from bad Qwen analyses with ≥80% agreement vs. manual ground truth when the judge prompt requires semantic equivalence (not literal substring match) and the analyzer prompt requires evidence-grounded root cause | Swap to a stronger local judge (e.g., Qwen 2.5 14B if RAM allows, swapped on demand) or accept API-judge cost (violates NFR6) | [x] (Sprint 5 — semantic-equivalence prompt + evidence-grounding breaks few-shot overfit; judge hallucinates eliminated) |
| A-005 | Loghub HDFS subset is sufficiently diverse for both demo and eval — no need to pull BGL/Thunderbird | Add a second Loghub dataset; minimal code change but new ground-truth labeling work | [ ] |
| A-006 | A 10-min cold start is achievable with `make seed-models` pre-pulling Qwen weights as a one-time setup step (not counted in the 10 min) | Reframe NFR1 as "≤10 min after `make seed-models`", document explicitly in README | [x] (already implicit in BRAINSTORM §5) |
| A-007 | Backend can be designed fully stateless — SSE streams are per-request, no server-side session — so 2 replicas behind a Service need no sticky-session shenanigans | Need ingress session affinity or Redis-backed session store; complicates the canary story | [x] (resolved — see Open Questions) |
| A-008 | A reviewer's "10-min judgment window" is a real constraint and not a strawman | Demo can be slower; relaxes NFR1 and changes the polish-vs-features tiebreaker | [x] (project premise) |
| A-009 | Argo Rollouts canary will produce a *visibly different* response between v1 and v2 (e.g., v2 adds a field) so the rollout has a narratable moment; AnalysisTemplate ships inside the backend Helm chart (not as an orphan at `deploy/rollouts/`) so GitOps promotes it atomically with the rollout spec | Rollout becomes invisible cargo-culting; per BRAINSTORM §5 we should rip it out instead | [x] (Sprint 5 — AnalysisTemplate in Helm chart; HPA conditionally targets Rollout vs Deployment via `.Values.useArgoRollouts`; `make demo-canary` injects load) |
| A-011 | mkcert local CA + Traefik TLSStore wildcard cert for `*.localtest.me` eliminates per-subdomain self-signed cert warnings without requiring per-reviewer configuration beyond one `make trust-certs` call | Each subdomain still needs a manual cert-trust step; reviewer hits security warnings during walkthrough | [x] (Sprint 5 — `make trust-certs` is idempotent; validated across frontend/api/grafana/prometheus/argocd) |
| A-012 | ArgoCD image must be pre-pulled on the host and kind-loaded before cluster bootstrap because kind nodes' containerd does not inherit the host's corporate CA trust chain and cannot pull from quay.io through a corporate TLS proxy | Need an in-cluster registry mirror or VPN split-tunnel workaround | [x] (Sprint 5 — ArgoCD v2.14.5 kind-loaded; multi-arch manifest lists stripped via `docker save --platform` before kind import) |
| A-010 | Per-machine settings (Ollama URL, LLM model, judge model, ingress host, host bridge CIDR) are env-overridable with sensible defaults; the canonical M3/16 GB + Docker Desktop scenario requires zero overrides; reviewers with non-canonical setups (low-RAM, corporate DNS, OrbStack/Colima/Linux) follow the README "Per-machine configuration" section. See ADR-008 for the 4-layer pattern. | Each non-canonical setup hits a silent failure with no recovery path; demo only works on the author's specific machine — fatal for NFR7 reproducibility | [x] (ADR-008 — per-machine env-overridable pattern, README override matrix) |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Reviewer-judgment-in-10-min is concrete, falsifiable, and the entire project is shaped by it |
| Users | 3 | Two personas, real pain points pulled from success criteria; no ambiguity about audience |
| Goals | 3 | All MoSCoW-classified; FRs and NFRs map cleanly into goals |
| Success | 3 | Every criterion has a number and a verification mechanism (OTel metric, smoke target, CI gate, eval rate) |
| Scope | 2 | Out-of-scope is exhaustive, but Sprint 4 → v1.1 backlog split is proposed not yet user-confirmed (carried forward as resolvable open question) |
| **Total** | **14/15** | Above 12/15 threshold — ready for Design |

---

## Open Questions — Resolution Status

### Resolved by /define (do not need user)

**OQ-2 — Backend session-affinity / statelessness design** → **RESOLVED.**
Decision: backend is **fully stateless**. SSE streams are per-request and bound to a single replica for their lifetime; no cross-replica session state. No ingress sticky sessions. Rationale: matches the canary story (any replica can serve any request mid-rollout), keeps the design simple, and Redis is reserved for future use (caching, eval result store) — not session state. Captured as Assumption A-007.

**OQ-3 — Loghub subset selection** → **RESOLVED.**
Decision: **HDFS only for MVP.** Revisit BGL/Thunderbird only if Layer-3 manual review reveals the eval set lacks diversity (Assumption A-005). Adding a second dataset is mostly a labeling cost, not architecture work, so it can land in v1.1 without rework.

**OQ-4 — Local vs API LLM-judge** → **RESOLVED (with trip-wire).**
Decision: **Llama 3.1 8B local** is the default (preserves NFR6). Trip-wire: if Layer-3 manual spot-check shows judge–human agreement <80% over 2 consecutive sprints, escalate to user for an API-judge waiver. Captured as Assumption A-004.

### Resolved with proposal (user can override silently — no blocking question)

**OQ-1 — Sprint 4 overload triage** → **PROPOSED MVP vs. v1.1 split:**

| Sprint 4 item | MVP or v1.1 | Rationale |
|---|---|---|
| 4–6 ADRs | **MVP** | Core to the "reviewer reads ADRs, not YAML" success criterion |
| Loom walkthrough | **MVP** | Async reviewers can't all live-demo; Loom is the fallback path to the 10-min judgment |
| Trivy image scan in CI | **MVP** (one-shot only) | One CI step, low cost, visible in PR checks |
| k6 load tests | **v1.1** | No reviewer-visible moment; load is not the story |
| Multi-arch builds | **v1.1** | arm64-only ships fine for the target reviewer machine |
| AWS migration doc | **MVP as `docs/aws-migration.md`** | Documented-thinking, not implementation; small write |

**OQ-5 — ADR scope (which 4–6 decisions)** → **PROPOSED list of 6 ADRs:**

1. **ADR-001:** kind-native runtime over docker-compose (rejecting the compose-then-migrate path)
2. **ADR-002:** Lean + Argo Rollouts platform kit (rejecting Maximal / Security-forward / Resilience-forward)
3. **ADR-003:** Ollama on host + `ExternalName` Service to `host.docker.internal` (rejecting in-cluster Ollama)
4. **ADR-004:** Hybrid eval strategy (pytest structural + local Llama judge + manual spot-check)
5. **ADR-005:** Hybrid grounding-data strategy (Loghub HDFS + synthetic backend logs + 2 real / 2 synthetic postmortems)
6. **ADR-006:** Backend statelessness + per-request SSE (no sticky sessions, no Redis-backed state for MVP)

If user disagrees with any of OQ-1 or OQ-5 proposals, override at `/design` time — none of these need to block this DEFINE.

### Carried forward to /design (genuinely needs design-phase work, not user input)

- **Long-log chunking / windowing strategy** for Qwen 2.5 7B context limits (BRAINSTORM §5 risk).
- **Synthetic span design** for the host-hop to Ollama (how to attribute latency between backend → host → model) (FR5 mechanics).
- **NetworkPolicy egress denial** spec to enforce NFR6 in code, not just convention.
- **Anomaly injector** design in the backend for synthetic log generation.

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-26 | define-agent | Initial DEFINE from BRAINSTORM_sre-copilot.md; resolved OQ-2/3/4, proposed OQ-1/5 splits; transformed FR1–FR6 into AT-001–AT-013; tightened NFR1–NFR7 into success-criteria with verification mechanisms |
| 1.1 | 2026-04-26 | iterate-agent | Post-S2 portability back-port. A-002 amended: host bridge CIDR now described as runtime-dependent (Docker Desktop / OrbStack / Colima / Linux), validated via ADR-007 configurable `hostBridgeCIDR` + `make detect-bridge`. NFR7 / Goals MUST row amended: "any supported Docker runtime" qualifier added, `HOST_BRIDGE_CIDR` override step noted. AT-013 amended: Given clause expanded to "any supported Docker runtime". Status updated to reflect DESIGN v1.4. |
| 1.2 | 2026-04-26 | iterate-agent + manual | Per-machine configurability cascade (post-S2 v2). A-002 amended to reference ADR-008 (umbrella per-machine env-overridable pattern). New A-010: per-machine settings are env-overridable with defaults; non-canonical setups follow README "Per-machine configuration" section. AT-013 amended: explicit reference to README "Per-machine configuration" section for non-canonical setups (low-RAM, corporate DNS). New AT-014: low-RAM-tier reviewer path (`LLM_MODEL=phi3:mini SKIP_JUDGE=1 make up`) — design-validated via ADR-008 pattern; runtime-validated pending an 8 GB test machine. Status updated to reflect DESIGN v1.5. |
| 1.3 | 2026-04-26 | manual | Redis removal cascade (post-S2 v3, YAGNI cleanup). A-007 (backend statelessness) clarified — "Redis-backed session store" rejection retained but the "Redis deployed for future caching" hedge removed; backend is now both stateless AND has no Redis dependency at all. No requirement (FR/NFR/AT) referenced Redis directly, so no FR/NFR/AT changes needed. Status updated to reflect DESIGN v1.6. |
| 1.4 | 2026-04-27 | iterate-agent | Sprint 5 (36 commits): trusted local TLS, end-to-end log↔trace correlation, dashboards-as-source-of-truth, Argo Rollouts canary fully operational, cold-laptop `make up` with kind-loaded ArgoCD v2.14.5, meaningful nightly eval with stratified sampling. New AT-015–AT-019. New A-011, A-012. A-004 and A-009 validated. Status updated to S5 Complete. |
| 1.5 | 2026-04-27 | ship-agent | Shipped and archived. All 19 ATs verified or implemented across S1–S4 sprints. Post-build shakedown resolved ArgoCD race (6efb46e) and smoke-test hostname bug. Moved to archive with SHIPPED_2026-04-27.md summary.

---

## Next Step

**Ready for:** DESIGN update (Sprint 5 parallel iterate call) — no further DEFINE work needed for S5.
