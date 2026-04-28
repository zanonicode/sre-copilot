# OpenAI-Compatible API (Ollama)

> **Purpose**: Ollama exposes a subset of OpenAI's HTTP API on `/v1/...` so the official `openai` Python SDK works unchanged — know exactly what's supported and what isn't
> **MCP Validated**: 2026-04-26

## Endpoints Implemented

| Endpoint | Status |
|----------|--------|
| `POST /v1/chat/completions` | ✅ Full support, including `stream=true` |
| `POST /v1/completions` | ✅ Legacy completion |
| `POST /v1/embeddings` | ✅ Returns vectors |
| `GET  /v1/models` | ✅ Lists local models in OpenAI shape |
| `POST /v1/audio/...` | ❌ Not supported |
| `POST /v1/images/...` | ❌ Not supported |
| `POST /v1/moderations` | ❌ Not supported |
| `POST /v1/responses` | ❌ Not supported (OpenAI's newer API) |

## SDK Wiring

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="http://ollama.sre-copilot.svc.cluster.local:11434/v1",
    api_key="ollama",                # SDK requires non-empty; Ollama ignores
)

resp = await client.chat.completions.create(
    model="qwen2.5:7b-instruct-q4_K_M",
    messages=[
        {"role": "system", "content": "You are an SRE assistant."},
        {"role": "user",   "content": "Analyze this log: ..."},
    ],
    stream=True,
    response_format={"type": "json_object"},
    temperature=0.2,
    max_tokens=1024,
)
```

## Supported Request Fields

| Field | Notes |
|-------|-------|
| `model` | Must match exactly (e.g., `qwen2.5:7b-instruct-q4_K_M`) — case-sensitive |
| `messages` | Standard chat shape; `system`, `user`, `assistant`, `tool` roles |
| `stream` | Server-Sent Events with OpenAI-compatible `delta` chunks |
| `temperature`, `top_p`, `max_tokens`, `seed`, `stop` | Standard |
| `response_format={"type":"json_object"}` | Enables strict JSON mode (newer Ollama versions) |
| `tools` / `tool_choice` | ⚠️ Partial — works for some models (Qwen 2.5, Llama 3.1); test |
| `n` (multiple completions) | ❌ Ignored — only `n=1` |
| `logprobs` | ❌ Ignored |
| `frequency_penalty`, `presence_penalty` | ❌ Ignored |
| `user` | Ignored (no per-user accounting) |

## Ollama-Specific Extensions (`extra_body`)

```python
extra_body = {
    "keep_alive": "10m",          # how long to keep model in RAM after this call
    "options": {
        "num_ctx": 8192,          # context window
        "num_gpu": 99,            # use Metal for all layers
        "num_thread": 8,          # CPU threads if not Metal
        "repeat_penalty": 1.1,
    },
}
```

## Streaming Response Shape (matches OpenAI exactly)

```text
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,
       "model":"qwen2.5:7b-instruct-q4_K_M",
       "choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,
       "model":"qwen2.5:7b-instruct-q4_K_M",
       "choices":[{"index":0,"delta":{"content":"{\""},"finish_reason":null}]}

... more delta chunks ...

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,
       "choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

The SDK iterates these as `async for chunk in stream_resp` and exposes `chunk.choices[0].delta.content`.

## Token Counts

Ollama returns `prompt_eval_count` and `eval_count` only at the END of streaming, in a NON-OpenAI-shaped final chunk in the native API but NOT in `/v1/chat/completions`. To track tokens precisely, count yourself or call `/api/generate` with `stream=false` and inspect.

For SRE Copilot we count emitted tokens in the SSE handler (DESIGN §4.1: `output_tokens += 1`) and export to Prom.

## JSON Mode Reliability

`response_format={"type":"json_object"}` instructs the model to emit valid JSON, but it does NOT enforce a schema. You MUST validate post-receipt with Pydantic (DESIGN §4.2). Models occasionally:

- Wrap in markdown fences (```json ... ```)
- Emit comments (// not valid JSON)
- Truncate mid-object on max_tokens

See `patterns/structured-json-prompts.md` for hardening.

## Error Shapes

```json
// Connection refused (Ollama not running)
APIConnectionError: Connection error.

// Model not pulled
{"error":{"message":"model 'foo' not found, try pulling it first","type":"api_error"}}

// Bad request
HTTP 400 + JSON error body
```

Catch `openai.APIConnectionError` for the host-down case and translate to your 503.

## See Also

- patterns/openai-sdk-streaming.md — full FastAPI SSE wrapper
- patterns/structured-json-prompts.md — schema enforcement
- concepts/keep-alive-and-cold-load.md — `keep_alive` semantics
