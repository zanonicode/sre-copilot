import asyncio
import json
import os
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, AsyncOpenAI
from opentelemetry import trace

from backend.observability.metrics import LLM_OUTPUT_TOKENS, LLM_TTFT
from backend.observability.spans import synthetic_ollama_span
from backend.prompts import render_log_analyzer
from backend.schemas import LogAnalysisRequest

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", "http://ollama.sre-copilot.svc.cluster.local:11434/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M")

router = APIRouter()
tracer = trace.get_tracer(__name__)
client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


async def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


@router.post("/logs")
async def analyze_logs(req: LogAnalysisRequest, request: Request):
    prompt = render_log_analyzer(req.log_payload, req.context)

    async def stream() -> AsyncIterator[bytes]:
        with tracer.start_as_current_span(
            "ollama.host_call",
            attributes={
                "llm.model": LLM_MODEL,
                "llm.input_tokens": req.estimated_tokens(),
                "peer.service": "ollama-host",
                "net.peer.name": "host.docker.internal",
                "net.peer.port": 11434,
            },
        ) as span:
            try:
                stream_resp = await client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                    response_format={"type": "json_object"},
                )
            except APIConnectionError as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, "ollama unreachable")
                yield await _sse({"type": "error", "code": "ollama_unreachable",
                                  "message": "LLM backend is unavailable"})
                return

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
                        LLM_TTFT.record(ttft)
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
                yield await _sse({"type": "done", "output_tokens": output_tokens})

    return StreamingResponse(stream(), media_type="text/event-stream")
