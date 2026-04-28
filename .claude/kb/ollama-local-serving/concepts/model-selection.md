# Model Selection (Qwen 2.5 7B vs Llama 3.1 8B)

> **Purpose**: Why SRE Copilot serves with Qwen 2.5 7B and judges with Llama 3.1 8B — quant choice, RAM, and the rotation pattern
> **MCP Validated**: 2026-04-26

## The Two Roles

| Role | Model | Why |
|------|-------|-----|
| **Serving** (analyzer + postmortem) | `qwen2.5:7b-instruct-q4_K_M` | Strong JSON-mode adherence; lower RAM; fast TTFT on Metal |
| **Judge** (eval) | `llama3.1:8b-instruct-q4_K_M` | Different family → independent biases; well-known instruction following |

The "serving + judge use different model families" rule comes from the LLM-as-judge literature: same-family models inflate self-grading scores.

## Spec Comparison

| Spec | Qwen 2.5 7B Q4_K_M | Llama 3.1 8B Q4_K_M |
|------|---------------------|----------------------|
| Disk size | ~4.7 GB | ~4.9 GB |
| RAM (loaded, Metal) | ~5.5 GB | ~6.2 GB |
| Context window | 32k native (128k via YaRN) | 128k native |
| TTFT (M1 Max, warm) | ~0.8s | ~1.1s |
| Tokens/s (M1 Max) | ~35 | ~28 |
| JSON-mode quality | Excellent | Good |
| License | Apache 2.0 | Llama 3.1 Community |

## Quantization Choice: Why Q4_K_M

| Quant | Size | Quality vs FP16 | When |
|-------|------|-----------------|------|
| Q2_K | smallest | noticeable degradation | RAM-starved |
| Q4_K_M (recommended) | small | ~95% retention | **DEFAULT for SRE Copilot** |
| Q5_K_M | medium | ~98% | If you have RAM |
| Q8_0 | large | ~99% | rarely worth it on consumer |
| FP16 | full | 100% | servers, not laptops |

Q4_K_M is the sweet spot — quality stays high while RAM stays manageable on a 16 GB Mac.

## RAM Math (16 GB Mac, both loaded simultaneously)

```text
macOS baseline + apps         5.0 GB
Docker Desktop VM             4.0 GB  (assumes 8 GB allocated, ~50% used)
Ollama runtime                0.5 GB
Qwen 7B Q4_K_M                5.5 GB
Llama 8B Q4_K_M               6.2 GB
─────────────────────────────────────
TOTAL                        21.2 GB  ← OVER 16 GB → SWAP THRASH
```

**Conclusion**: Never load both at once. Use rotation:

```text
Demo flow:
  load Qwen → run analyzer/postmortem demos → unload Qwen
  load Llama → run eval judge → unload Llama → reload Qwen
```

See `patterns/on-demand-model-load.md` for the API mechanics.

## Why Not Larger Models?

| Model | RAM | Verdict |
|-------|-----|---------|
| Qwen 2.5 14B Q4 | ~9 GB | Tight on 16 GB Mac; possible but no headroom |
| Qwen 2.5 32B Q4 | ~19 GB | OOM territory on 16 GB |
| Llama 3.1 70B Q4 | ~42 GB | Mac Studio territory only |

For prod swap → vLLM on EKS GPU node → Llama 3.1 70B becomes viable.

## Why Not Smaller Models?

`qwen2.5:3b-instruct-q4_K_M` (~2 GB RAM) is a usable fallback if you must run with Docker memory pressure. Quality on the 5-field log analyzer JSON is noticeably worse — more hallucinated runbook steps. Use only if Qwen 7B can't fit.

## Selection Per Endpoint

```python
# src/backend/config.py
import os

OLLAMA_BASE_URL = os.environ["OLLAMA_BASE_URL"]
SERVING_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
JUDGE_MODEL   = os.environ.get("OLLAMA_JUDGE_MODEL", "llama3.1:8b-instruct-q4_K_M")
```

Pass `model=SERVING_MODEL` from `/analyze/logs` and `/generate/postmortem`. Pass `model=JUDGE_MODEL` from `tests/eval/judge/run_judge.py` (DESIGN §4.12) — and make sure the judge runner explicitly unloads after.

## Verification: Does the Right Model Get Loaded?

```bash
# Trigger a serving call
curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","messages":[{"role":"user","content":"hi"}]}'

# Check what's in RAM
curl -s http://localhost:11434/api/ps | jq
# Expect: only qwen2.5:7b-instruct-q4_K_M
```

## See Also

- concepts/keep-alive-and-cold-load.md — load/unload mechanics
- patterns/on-demand-model-load.md — eval rotation recipe
- patterns/model-rotation-debugging.md — what swap-thrash looks like
