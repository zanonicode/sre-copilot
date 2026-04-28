# BRAINSTORM: SRE Copilot

**Date:** 2026-04-25
**Phase:** 0 (Brainstorm)
**Source:** notes/sre-copilot-project-plan.md
**Next Phase:** `/define .claude/sdd/features/BRAINSTORM_sre-copilot.md`

---

## 1. Vision & Success Criteria

**Primary purpose:** Hiring signal. A reviewer clones the repo, runs `make up`, and within 10 minutes sees a streaming LLM-driven log analysis surfaced through real observability tooling. Their gut reaction should be: *"this person actually operates real platforms — not just a wrapper around an API key."*

**Secondary purpose:** A clean enough substrate that the same repo can later be extended into real LLM-serving / inference-platform work (vLLM, multi-tenant routing, GPU autoscaling) without throwing away the chassis.

**Tiebreaker rule:** When forced to choose between *more features* and *demo polish that holds up to a 10-minute live walkthrough*, polish wins. Every time.

**Success looks like:**
- Cold `make up` → working URL with streaming output, end-to-end traces in Grafana, and a visible canary rollout — all in under 10 minutes on an M3/16GB MacBook.
- Reviewer can answer "how does this work?" by reading 4–6 ADRs, not by spelunking YAML.
- Eval results (structural + judge) are committed and visible in the README.

---

## 2. Selected Approach

| Layer | Decision |
|---|---|
| **Runtime** | kind-native from day 1 + Tilt for inner-loop dev (no docker-compose detour) |
| **Platform kit** | **Lean + Argo Rollouts.** Deployed: ArgoCD, Sealed Secrets, Argo Rollouts. Documented-only: Kyverno, Trivy Operator, Chaos Mesh |
| **Replicas** | backend=2 (enables canary + PDB demo), frontend=1, redis=1 |
| **Inference** | Ollama + Qwen 2.5 7B Q4 running on the host, exposed into kind via an `ExternalName` Service pointing at `host.docker.internal` |
| **Observability** | Full LGTM stack — Loki, Grafana, Tempo, Mimir (or Prometheus), wired through an OpenTelemetry Collector |
| **Grounding data** | **a5** (hybrid Loghub HDFS + synthetic backend logs) + **b3** (2 real public postmortems + 2 hand-written) + **c1** (labeled ground truth JSON in `datasets/eval/`) |
| **Eval** | **Hybrid (option d):** pytest structural assertions in CI + Llama 3.1 8B as local LLM-judge on a held-out set + manual spot-check of ~5 cases per sprint |

---

## 3. Approaches Considered (with rejections)

### Runtime: Compose-first vs kind-native
- **Compose-first** rejected: would force a second migration to k8s mid-project, and the entire portfolio signal is *Kubernetes operator literacy*. Compose hides exactly what we want to show.
- **kind-native** chosen: matches the demo story, and Tilt closes the inner-loop gap that compose was supposed to solve.

### Platform kit: Lean / Security-forward / Resilience-forward / Maximal
- **Maximal** (everything deployed) rejected: blows the 16GB memory budget and pads the demo with components we can't narrate in 10 minutes.
- **Security-forward** (Kyverno + Trivy Operator deployed) rejected: continuous admission control and image scanning are real-platform concerns, but they have no visible *moment* in a portfolio walkthrough. Documented instead.
- **Resilience-forward** (Chaos Mesh deployed) rejected: one well-rehearsed canary rollout via Argo Rollouts is a stronger narrative beat than a chaos experiment that may or may not behave on stage.
- **Lean + Argo Rollouts** chosen: smallest deployed surface that still produces a real GitOps + progressive-delivery story, with the rest documented to show awareness.

### Eval: LLM-judge alone vs hybrid
- **Judge-only** rejected: no protection against output-shape regressions; a single judge run is too slow and too noisy for per-commit feedback.
- **Structural-only** rejected: tells you the JSON parses, not whether the analysis is any good.
- **Hybrid** chosen: pytest is the fast cheap floor; the judge is the slow expensive signal; manual is the ground truth that keeps the judge honest.

---

## 4. YAGNI Cuts

| Cut | Reasoning |
|---|---|
| **Kyverno** → documented-only | Memory budget tight; no critical demo moment that policy enforcement creates |
| **Trivy Operator** → documented-only | Continuous CVE scanning is over-spec for a portfolio repo; one-shot `trivy image` in CI is enough |
| **Chaos Mesh** → documented-only | The Argo Rollouts canary already supplies the resilience signal; chaos adds risk to the live demo |
| **Multi-arch builds** → deferred | Local target is arm64 Mac; cross-builds add CI time for zero demo value |
| **AWS reference Terraform module** → documented-only (`docs/aws-migration.md`) | Showing the *thinking* about cloud migration beats half-implementing it |
| **Frontend / Redis multi-replica** → 1 each | Single-node kind cluster — HA replicas are theater, not signal |
| **Backend 3 → 2 replicas** | 2 replicas already exercise canary, PDB, and rolling update; the 3rd is pure cost |
| **8–12 ADRs** → 4–6 | Only the load-bearing decisions get an ADR; the rest live in inline comments or `docs/` |

---

## 5. Hidden Risks Surfaced

- **Memory budget.** 16GB physical, ~14–15GB committed at peak (Ollama + LGTM + kind + Chrome). Mitigation: single-replica discipline, `kind load docker-image` to skip registry pulls, and a `make seed-models` target that pre-pulls Qwen weights before `make up`.
- **Cold-start time.** Plan budget is 10 minutes; we should target <5 min cold to leave slack for reviewer Wi-Fi. Needs cached Helm chart deps, pre-pulled base images, and seeded model weights.
- **kind networking on macOS.** The brittlest seam in the stack is Traefik ingress + the `ExternalName` hop to `host.docker.internal:11434` for Ollama. Worth a smoke test target (`make smoke`) and an explicit ADR.
- **Argo Rollouts cargo-cult risk.** Rollouts is only justified if the demo script *visibly uses it*. Commit to a real canary moment (e.g., deploy a v2 backend that returns extra fields, watch traffic shift) — otherwise rip it out.
- **Qwen 7B context window.** Limits how much log volume we can stuff into a single prompt. Chunking / windowing strategy is real design work — defer specifics to `/define`.

---

## 6. Sample / Grounding Data Plan

**Inputs (a5 — hybrid logs):**
- **Loghub HDFS subset.** Well-labeled, manageable size, classic SRE failure modes (DataNode crashes, block replication failures). Stored under `datasets/loghub/hdfs/`.
- **Synthetic backend logs.** Generated from the FastAPI service itself by deliberately injecting anomalies (timeouts, 5xx bursts, cascading retries) — drives the *live* demo path where the reviewer sees real-time analysis of logs the cluster is producing right now.

**Postmortems (b3 — hybrid):**
- **2 real public PMs** (e.g., Cloudflare, GitHub published incident reviews) for stylistic grounding.
- **2 hand-written PMs** that match the demo incidents one-for-one, so the LLM has clear in-distribution exemplars.

**Ground truth (c1):**
- Per demo incident: a labeled JSON record in `datasets/eval/` containing the expected root cause, severity, candidate remediations, and "must-not-hallucinate" assertions. This file is what both the pytest layer and the LLM judge score against.

| Type | Location | Initial Count | Notes |
|---|---|---|---|
| Loghub HDFS logs | `datasets/loghub/hdfs/` | 1 subset | Start small, expand if eval signal warrants |
| Synthetic logs | generated at runtime | n/a | Anomaly injector lives in backend |
| Real postmortems | `datasets/postmortems/real/` | 2 | Public sources, attribution preserved |
| Synthetic postmortems | `datasets/postmortems/synth/` | 2 | One per demo incident |
| Ground truth | `datasets/eval/*.json` | 10–20 | Grows over time |

---

## 7. Eval Strategy

Three layers, each with a distinct cost/signal profile:

**Layer 1 — pytest structural (every commit, seconds).**
Asserts JSON output shape, required fields present (`severity`, `summary`, `root_cause`, `runbook`, `related_metrics`), token bounds respected, no obvious malformed-output failure modes. Runs in CI on every push. This is the floor.

**Layer 2 — Local LLM-judge (nightly or pre-release, minutes).**
Llama 3.1 8B (loaded on demand via `ollama run`, unloaded after) scores a held-out set of ~10–20 incidents against a fixed rubric: (a) root-cause match vs. ground truth, (b) remediation soundness, (c) hallucination check (does the output reference logs/services that don't exist in the input?). Llama is the judge specifically *because* it's a different model family from Qwen — reduces self-preference bias. Runs occasionally, not per-request, so it doesn't compete with primary inference for steady-state RAM.

**Layer 3 — Manual spot-check (per sprint, ~30 minutes).**
5 cases reviewed against a markdown checklist. This is the calibration signal that tells us whether to trust the judge.

**Why local judge:** preserves the zero-dollar hard constraint from Section 1 of the project plan. Trade-off acknowledged: a local 8B judge is weaker than Claude/Gemini-as-judge. If Layer-3 manual review reveals Layer-2 judge scores drifting from human judgment, swap to an API judge (open question for `/define`).

---

## 8. Open Questions for /define

1. **Sprint 4 overload.** k6 load tests + Trivy scan + multi-arch builds + AWS migration doc + Loom walkthrough + 4–6 ADRs is still too much for one sprint. `/design` needs to slot these or defer some to a "v1.1" backlog.
2. **Backend statelessness.** With 2 backend replicas behind a Service, any session/streaming state must be designed to either live in Redis or be sticky via the ingress. Affects SSE design directly.
3. **Loghub subset selection.** Start with HDFS; revisit whether to add BGL or Thunderbird if the eval set needs more diversity.
4. **Local vs API judge.** Default is local Llama 3.1 8B. Revisit if Layer-3 calibration shows the local judge can't distinguish good from bad outputs.
5. **ADR scope.** Which 4–6 decisions are load-bearing enough to document? Candidates: kind-vs-compose, Ollama-via-ExternalName, Lean-kit selection, hybrid-eval design, grounding-data strategy, canary-via-Argo-Rollouts.

---

## 9. Draft Requirements

### Functional

- **FR1 — Log Analyzer.** Endpoint accepts a log payload and streams structured LLM analysis (`severity`, `summary`, `root_cause`, `runbook`, `related_metrics`) over Server-Sent Events.
- **FR2 — Postmortem Generator.** Endpoint accepts a raw incident timeline and produces a structured postmortem in Google SRE Workbook format.
- **FR3 — Bridge UX.** A "Generate postmortem from this incident" button pipes Log Analyzer output directly into the Postmortem flow.
- **FR4 — Curated examples.** UI ships with one-click Loghub samples (e.g., "Try HDFS DataNode failure") so a reviewer never faces an empty textarea.
- **FR5 — End-to-end traces.** Every request is traced from browser → ingress → backend → Ollama (via a synthetic span for the host hop), visible in Tempo/Grafana.
- **FR6 — Demoable rollout.** Backend version bumps are demoable via `kubectl argo rollouts get rollout` showing canary progression.

### Non-Functional

- **NFR1 — Cold-start.** `make up` from clean clone completes in <10 min on M3/16GB MacBook (stretch target: <5 min).
- **NFR2 — Warm restart.** <30 seconds.
- **NFR3 — Memory.** Total committed memory <14 GB at steady state with Ollama loaded.
- **NFR4 — TTFT.** Time-to-first-token <2s at p95.
- **NFR5 — Full response.** Complete LLM response <30s at p90.
- **NFR6 — Zero cost.** No external API spend — local inference and local judge model.
- **NFR7 — Reproducibility.** A stranger can go from clean clone to working demo in <10 minutes total.

---

## 10. Next Steps

**Status:** ✅ Shipped and archived 2026-04-27

**Status:** ✅ Shipped
