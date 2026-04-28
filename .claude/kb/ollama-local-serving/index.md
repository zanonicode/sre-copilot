# Ollama Local Serving Knowledge Base

> **Purpose**: Run LLM inference on the developer's Mac via Ollama (Metal-accelerated), expose it to the kind cluster through `host.docker.internal`, and consume it from FastAPI via the OpenAI-compatible API
> **MCP Validated**: 2026-04-26

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/macos-metal-serving.md](concepts/macos-metal-serving.md) | Why Ollama runs on the host (not a Pod), Metal GPU, RAM math |
| [concepts/openai-compat-api.md](concepts/openai-compat-api.md) | `/v1/chat/completions` shape, what's supported, what isn't |
| [concepts/model-selection.md](concepts/model-selection.md) | Qwen 2.5 7B vs Llama 3.1 8B — quant choice, eval-judge separation |
| [concepts/keep-alive-and-cold-load.md](concepts/keep-alive-and-cold-load.md) | `keep_alive`, model swap cost, cold-load timing |
| [concepts/kind-host-networking.md](concepts/kind-host-networking.md) | `host.docker.internal` on kind, ExternalName Service, NetworkPolicy |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/openai-sdk-streaming.md](patterns/openai-sdk-streaming.md) | AsyncOpenAI streaming wrapper for FastAPI SSE |
| [patterns/externalname-host-bridge.md](patterns/externalname-host-bridge.md) | The `helm/platform/ollama-externalname/` chart that bridges Pods → host Ollama |
| [patterns/structured-json-prompts.md](patterns/structured-json-prompts.md) | `response_format={"type":"json_object"}` + Pydantic validation |
| [patterns/on-demand-model-load.md](patterns/on-demand-model-load.md) | Load llama3.1 only for eval, unload after to free 8 GB |
| [patterns/model-rotation-debugging.md](patterns/model-rotation-debugging.md) | What goes wrong when two big models thrash; how to detect |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — env vars, model names, ollama CLI cheats, RAM table

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Host-side serving** | Ollama runs as a launchd / brew service on the Mac, NOT in a Pod |
| **Metal acceleration** | Ollama uses Apple Metal GPU automatically on M-series chips |
| **OpenAI-compatible API** | Ollama exposes `/v1/chat/completions` mimicking OpenAI; the Python SDK works unchanged |
| **`host.docker.internal`** | The DNS name kind Pods use to reach the host (works on Docker Desktop Mac) |
| **ExternalName Service** | K8s Service of type `ExternalName` that points at `host.docker.internal` so Pods can use cluster DNS |
| **`keep_alive`** | Per-request flag controlling how long Ollama keeps a model loaded after request finishes |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/macos-metal-serving.md, concepts/openai-compat-api.md, patterns/openai-sdk-streaming.md |
| **Intermediate** | concepts/kind-host-networking.md, patterns/externalname-host-bridge.md, patterns/structured-json-prompts.md |
| **Advanced** | concepts/model-selection.md, concepts/keep-alive-and-cold-load.md, patterns/on-demand-model-load.md, patterns/model-rotation-debugging.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| python-developer | patterns/openai-sdk-streaming.md, patterns/structured-json-prompts.md | Wire FastAPI → Ollama |
| k8s-platform-engineer | patterns/externalname-host-bridge.md, concepts/kind-host-networking.md | The `ollama-externalname` Helm chart + NetworkPolicy |
| llm-specialist | concepts/model-selection.md, patterns/on-demand-model-load.md | Choose serving vs judge models, avoid thrash |

---

## Project Context

This KB supports DESIGN §4.1 (FastAPI SSE handler), §4.12 (judge runner), §3 entry #13 (`helm/platform/ollama-externalname/`), and the cold-start budget (AT-004: ≤10 min from clean clone).

| Decision | Outcome |
|----------|---------|
| Serving model (analyzer + postmortem) | `qwen2.5:7b-instruct-q4_K_M` (~5 GB RAM) |
| Judge model (eval) | `llama3.1:8b-instruct-q4_K_M` (~6 GB RAM) — load on-demand only |
| Both loaded simultaneously? | NO — would exceed 16 GB Mac. Rotate via `keep_alive: 0` after eval. |
| Cluster bridge | ExternalName Service `ollama.sre-copilot.svc` → `host.docker.internal` |
| Egress restriction | NetworkPolicy allows only 11434 to host.docker.internal from `backend` Pods |

---

## External Resources

- [Ollama docs](https://github.com/ollama/ollama/tree/main/docs)
- [Ollama OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/openai.md)
- [Ollama Modelfile reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.md)
- [Qwen 2.5 model card](https://qwenlm.github.io/blog/qwen2.5/)
- [Llama 3.1 model card](https://ai.meta.com/blog/meta-llama-3-1/)
