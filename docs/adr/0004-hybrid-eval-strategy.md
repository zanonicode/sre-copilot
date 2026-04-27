# ADR-004: Hybrid eval strategy (pytest structural + local Llama judge + manual spot-check)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

---

## Context

Eval needs to run at three different cadences (per-commit, nightly, per-sprint) with three different cost/signal profiles. A single layer — judge-only or structural-only — fails one of those cadences.

## Choice

Three-layer eval:

- **Layer 1 — pytest structural** (every commit, seconds): JSON shape, required fields, token bounds, no obvious malformations. CI gate (AT-010). Lives in `tests/eval/structural/`.
- **Layer 2 — Local Llama 3.1 8B judge** (nightly, ~minutes): scores Qwen output against ground truth on a fixed rubric (root-cause match, remediation soundness, hallucination check). Llama is loaded on-demand via Ollama and unloaded after, so it doesn't compete with primary inference for steady-state RAM. AT-011. Lives in `tests/eval/judge/`.
- **Layer 3 — Manual spot-check** (per sprint, ~30 min): 5 cases against the checklist in `docs/eval/manual_checklist.md`. Calibrates the judge.

## Rationale

- Llama is a different model family from Qwen → reduces self-preference bias in judging.
- Local judge preserves NFR6 (zero external API spend).
- Layer 3 is the calibration loop: if Llama-judge agreement with humans drifts below 80%, escalate to user for a possible API-judge waiver.

## Alternatives Rejected

1. **Judge-only.** Rejected: no protection against output-shape regressions; too slow for per-commit feedback.
2. **Structural-only.** Rejected: tells you JSON parses, not whether analysis is good.
3. **API judge (GPT-4 / Claude as judge).** Rejected: violates NFR6 (zero external API spend at runtime).

## Consequences

- Llama judge cold-load adds ~30s to nightly eval; acceptable.
- Manual layer is process discipline, not code — must appear in the per-sprint checklist (`docs/eval/manual_checklist.md`).
- The judge rubric (`tests/eval/judge/rubric.yaml`) is a versioned artefact — changes need PR review.
- The nightly eval workflow (`.github/workflows/nightly-eval.yml`) commits judge results to `datasets/eval/judge_runs/` so historical pass-rate trends are visible in the repo.
