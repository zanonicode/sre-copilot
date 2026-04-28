# OpenAI SDK Streaming Wrapper (FastAPI SSE)

> **Purpose**: The lift-able async wrapper that takes a user request, streams from Ollama via the OpenAI SDK, and re-emits as SSE to the browser — with TTFT timing, cancellation, error mapping, and synthetic-span hooks
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 1 entry #4 (`src/backend/`)
- Mirrors DESIGN §4.1 verbatim — this pattern is the implementation contract

## Implementation

```python
# src/backend/api/analyze.py
import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI, APIConnectionError
from opentelemetry import trace

from backend.schemas import LogAnalysisRequest
from backend.prompts import render_log_analyzer
from backend.observability.metrics import LLM_TTFT, LLM_OUTPUT_TOKENS
from backend.observability.spans import synthetic_ollama_span

router = APIRouter()
tracer = trace.get_tracer(__name__)
client = AsyncOpenAI(
    base_url="http://ollama.sre-copilot.svc.cluster.local:11434/v1",
    api_key="ollama",
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
                    extra_body={"keep_alive": "30m"},
                )
            except APIConnectionError as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, "ollama unreachable")
                yield await _sse({
                    "type": "error",
                    "code": "ollama_unreachable",
                    "message": "LLM backend is unavailable",
                })
                raise HTTPException(503) from None

            t0 = asyncio.get_event_loop().time()
            first_token_seen = False
            output_tokens = 0
            try:
                async for chunk in stream_resp:
                    # AT-009: cancel on client disconnect
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
                LLM_OUTPUT_TOKENS.add(output_tokens)
                synthetic_ollama_span(
                    parent=span, t0=t0, duration=duration,
                    output_tokens=output_tokens,
                    input_tokens=req.estimated_tokens(),
                )
                yield await _sse({
                    "type": "done",
                    "output_tokens": output_tokens,
                })

    return StreamingResponse(stream(), media_type="text/event-stream")
```

## Configuration

| Concern | Setting |
|---------|---------|
| Ollama URL | `OLLAMA_BASE_URL` env (defaults to ExternalName Service URL) |
| Model | `OLLAMA_MODEL` env (defaults to qwen2.5:7b-instruct-q4_K_M) |
| Keep model warm during demo | `extra_body={"keep_alive": "30m"}` |
| JSON mode | `response_format={"type": "json_object"}` |
| Timeout | Set on AsyncOpenAI: `AsyncOpenAI(..., timeout=60.0)` |

## Error Mapping (DESIGN AT-007/008/009)

| Failure | Catch | SSE response | HTTP |
|---------|-------|--------------|------|
| Ollama down | `APIConnectionError` | `{"type":"error","code":"ollama_unreachable"}` | 503 |
| Model not pulled | Returned 404 by Ollama → `openai.NotFoundError` | `{"type":"error","code":"model_missing"}` | 503 |
| Bad request schema | Pydantic ValidationError before stream() | n/a | 400 |
| Client disconnect | `request.is_disconnected()` | (silent, just stop) | n/a |

## Example Usage

```bash
curl -N -X POST http://localhost:8000/analyze/logs \
  -H 'Content-Type: application/json' \
  -d '{"log_payload": "081109 203518 143 INFO ..."}'
```

Expected SSE stream:

```text
data: {"type":"delta","token":"{"}
data: {"type":"delta","token":"\""}
data: {"type":"delta","token":"severity"}
...
data: {"type":"done","output_tokens":127}
```

## Frontend Consumption

```typescript
const resp = await fetch("/api/analyze/logs", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ log_payload }),
});
const reader = resp.body!.getReader();
const decoder = new TextDecoder();
let buffer = "", accumulated = "";
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value);
  const lines = buffer.split("\n\n");
  buffer = lines.pop()!;
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const evt = JSON.parse(line.slice(6));
    if (evt.type === "delta") accumulated += evt.token;
    if (evt.type === "done") return JSON.parse(accumulated);
  }
}
```

## See Also

- concepts/openai-compat-api.md — what fields are honored
- patterns/structured-json-prompts.md — Pydantic post-validation
- otel-lgtm KB → patterns/python-fastapi-instrumentation.md — span/metric definitions
