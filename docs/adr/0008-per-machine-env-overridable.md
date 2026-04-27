# ADR-008: Per-machine env-overridable settings via Makefile + Helmfile + Helm values

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 (post-Sprint-2 portability iteration v2) |

---

## Context

ADR-007 introduced `HOST_BRIDGE_CIDR` as the first env-overridable setting. A subsequent audit identified four more genuinely-machine-or-user-dependent settings that were hardcoded across multiple files:

- **Ollama URL** — duplicated in `analyze.py` + `postmortem.py`; blocked local backend dev (running uvicorn outside kind).
- **LLM model name** — duplicated in 5 places; RAM-tier dependent (8 GB users want `phi3:mini`).
- **LLM judge model name** — same shape as LLM_MODEL; some users want to skip the judge entirely.
- **Ingress hostname** (`sre-copilot.localtest.me`) — hardcoded in 4 places; corporate DNS sometimes blocks `localtest.me`.

Things deliberately *not* externalized (reproducibility anchors): cluster name `sre-copilot`, K8s version pin, image names, Pod CIDR.

## Choice

Standardize a 4-layer pattern for any per-machine setting:

1. **Makefile** — declare with `?=` default and `export VAR_NAME` so child processes inherit.
2. **Helmfile** — `set:` block with `{{ env "VAR_NAME" | default "<value>" }}`.
3. **Helm chart values.yaml** — declare a structured value with a sensible default.
4. **Helm template** — render into ConfigMap (or directly into pod env).

The 5 settings externalized: `HOST_BRIDGE_CIDR`, `LLM_MODEL`, `LLM_JUDGE_MODEL`, `INGRESS_HOST`, `OLLAMA_BASE_URL` (backend-only — no helmfile path needed since the in-cluster default is correct for production runtime; override via env only for local Tilt-style dev).

## Rationale

1. **Single override mechanism across the stack.** Users learn one pattern, not five.
2. **Defaults are the happy path.** Overrides are opt-in and never required for the canonical Docker-Desktop / 16-GB scenario.
3. **`direnv` / `.envrc` provides persistence** without polluting global shell state.
4. **Bounded externalization.** Five settings only, with explicit "do not externalize" guidance for reproducibility anchors.

## Alternatives Rejected

1. **Per-environment values files** (`values-low-ram.yaml`, `values-corp.yaml`). Rejected: proliferates files; doesn't compose when 2+ overrides combine.
2. **Single mega-config file at repo root.** Rejected: loses Helm's value validation and templating.
3. **Externalize everything.** Rejected: every override is a future bug.

## Consequences

- (+) Demo works on 4 Docker runtimes × 3 RAM tiers × custom DNS scenarios with a single env-export step per non-canonical setting.
- (+) Local backend dev now possible via `OLLAMA_BASE_URL=http://localhost:11434/v1`.
- (+) Pattern documented in README "Per-machine configuration" section with a verify-after-`make-up` snippet.
- (–) 5 env vars to know — mitigated by README override matrix table, all with defaults.
- (–) Pattern requires changes in 4 layers per new setting — mitigated by small-N (5 settings, not growing).
