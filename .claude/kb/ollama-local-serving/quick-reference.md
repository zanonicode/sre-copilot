# Ollama Local Serving Quick Reference

> **MCP Validated**: 2026-04-26

## Install + Service (macOS)

```bash
brew install ollama
brew services start ollama                         # launchd-managed, auto-start
# or one-shot foreground:
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

`brew services` listens on `127.0.0.1:11434` by default. To reach from kind Pods via `host.docker.internal`, you may need:

```bash
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
brew services restart ollama
```

## Model Pulls

```bash
ollama pull qwen2.5:7b-instruct-q4_K_M             # ~5 GB on disk; primary serving
ollama pull llama3.1:8b-instruct-q4_K_M            # ~6 GB on disk; judge only
ollama list                                         # what's local
ollama rm <model>                                   # free disk
```

`make seed-models` should wrap these.

## Useful Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/tags` | List local models |
| `POST /api/generate` | Native completion (non-OpenAI) |
| `POST /api/chat` | Native chat (non-OpenAI) |
| `POST /api/show` | Model metadata + parameters |
| `POST /v1/chat/completions` | OpenAI-compatible (USE THIS) |
| `POST /v1/embeddings` | OpenAI-compatible embeddings |
| `POST /api/pull` | Download a model (programmatic) |
| `POST /api/ps` | Currently loaded models in RAM |

## Env Vars

| Var | Effect |
|-----|--------|
| `OLLAMA_HOST` | Bind address (default 127.0.0.1:11434) |
| `OLLAMA_MODELS` | Model storage path (default ~/.ollama/models) |
| `OLLAMA_KEEP_ALIVE` | Default keep-alive ("5m", "0", "-1" = forever) |
| `OLLAMA_NUM_PARALLEL` | Concurrent requests per model (default 4) |
| `OLLAMA_MAX_LOADED_MODELS` | Hard cap on RAM-loaded models (default 1 on Mac) |

## Model Choice Cheat (16 GB Mac)

| Model | RAM (loaded) | Use |
|-------|--------------|-----|
| qwen2.5:7b-instruct-q4_K_M | ~5 GB | Serving (analyzer + postmortem) — KEEP loaded |
| llama3.1:8b-instruct-q4_K_M | ~6 GB | Judge only — load → eval → unload |
| qwen2.5:3b-instruct-q4_K_M | ~3 GB | Fallback if RAM constrained |
| nomic-embed-text | ~300 MB | Embeddings (if added later) |

## OpenAI SDK Wiring

```python
from openai import AsyncOpenAI
client = AsyncOpenAI(
    base_url="http://ollama.sre-copilot.svc.cluster.local:11434/v1",
    api_key="ollama",                       # required by SDK; Ollama ignores
)

resp = await client.chat.completions.create(
    model="qwen2.5:7b-instruct-q4_K_M",
    messages=[{"role": "user", "content": "Hi"}],
    stream=True,
    response_format={"type": "json_object"},
    extra_body={"keep_alive": "10m"},
)
```

## Cluster Bridge URL

| From | URL |
|------|-----|
| Pod in `sre-copilot` ns | `http://ollama.sre-copilot.svc.cluster.local:11434` |
| Local dev (uvicorn) | `http://localhost:11434` |
| Kind node → host | `http://host.docker.internal:11434` (only via ExternalName) |

## Common Commands

```bash
# What's loaded RIGHT NOW?
curl -s http://localhost:11434/api/ps | jq

# Force unload everything
curl -s http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","keep_alive":0}'

# Inspect model parameters
curl -s http://localhost:11434/api/show -d '{"name":"qwen2.5:7b-instruct-q4_K_M"}' | jq .parameters

# Cold-load timing (first inference after fresh boot)
time curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","messages":[{"role":"user","content":"hi"}]}'
# Expect 8–25s on M1/M2; 4–10s on M3 Pro
```

## Decision Tables

| Want | Setting |
|------|---------|
| Strict JSON output | `response_format={"type":"json_object"}` |
| Streaming SSE to frontend | `stream=True` + manual `data:` SSE wrapping |
| Keep model warm during demo | `extra_body={"keep_alive": "30m"}` |
| Free RAM after a single eval call | `extra_body={"keep_alive": 0}` |
| Detect "is Ollama up?" | `GET /api/tags` returns 200 + JSON |
