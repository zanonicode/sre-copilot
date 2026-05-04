import asyncio
import json
import os
import random
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, AsyncOpenAI
from opentelemetry import trace

from backend.observability.metrics import (
    LLM_ACTIVE,
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    LLM_RESPONSE,
    LLM_TTFT,
)
from backend.observability.spans import synthetic_ollama_span
from backend.prompts import render_log_analyzer
from backend.schemas import LogAnalysisRequest

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", "http://ollama.sre-copilot.svc.cluster.local:11434/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# Failure-injection hook: artificial delay before the LLM call. Default 0
# (no-op). Used by `make demo-canary-slow` overlay to inflate TTFT past the
# operational gate's p95 threshold.
LLM_PRE_CALL_DELAY_S = float(os.getenv("LLM_PRE_CALL_DELAY_S", "0"))

# Failure-injection hook: hard-truncate the log payload to this many chars
# before rendering the prompt. Default 0 = no truncation. Used by
# `make demo-canary-broken-chunking` so the LLM analyzes a fragment and the
# semantic gate (LLM-judge match-rate) catches the regression while
# operational metrics stay green.
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "0"))

# Failure-injection hook: rewrite the LLM's expected output schema (e.g., to
# emit `summary_v1` instead of `root_cause`). Default empty = no rewrite.
# Used by `make demo-canary-bad-schema` to demo the judge gate catching a
# schema regression that slipped past Layer-1 pytest.
ANALYZE_SCHEMA_OVERRIDE = os.getenv("ANALYZE_SCHEMA_OVERRIDE", "")

# v2 feature flag: when ENABLE_CONFIDENCE=true, the analyzer appends a
# confidence score to the JSON output. This makes the canary visibly different
# from v1 — callers see 'confidence' in the response from v2 replicas only.
ENABLE_CONFIDENCE = os.getenv("ENABLE_CONFIDENCE", "false").lower() == "true"

router = APIRouter()
tracer = trace.get_tracer(__name__)
client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


async def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


@router.post("/logs")
async def analyze_logs(req: LogAnalysisRequest, request: Request):
    log_payload = req.log_payload
    if CHUNK_MAX_CHARS > 0 and len(log_payload) > CHUNK_MAX_CHARS:
        log_payload = log_payload[:CHUNK_MAX_CHARS]
    prompt = render_log_analyzer(log_payload, req.context, schema_override=ANALYZE_SCHEMA_OVERRIDE)
    input_tokens = req.estimated_tokens()

    async def stream() -> AsyncIterator[bytes]:
        LLM_INPUT_TOKENS.add(input_tokens)
        LLM_ACTIVE.add(1)
        try:
            with tracer.start_as_current_span(
                "ollama.host_call",
                attributes={
                    "llm.model": LLM_MODEL,
                    "llm.input_tokens": input_tokens,
                    "peer.service": "ollama-host",
                    "net.peer.name": "host.docker.internal",
                    "net.peer.port": 11434,
                },
            ) as span:
                if LLM_PRE_CALL_DELAY_S > 0:
                    span.add_event("pre_call_delay", {"seconds": LLM_PRE_CALL_DELAY_S})
                    await asyncio.sleep(LLM_PRE_CALL_DELAY_S)
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
                    LLM_RESPONSE.record(duration)
                    synthetic_ollama_span(
                        parent=span, duration=duration,
                        output_tokens=output_tokens,
                        input_tokens=input_tokens,
                    )
                    extra_fields: dict = {}
                    if ENABLE_CONFIDENCE:
                        extra_fields["confidence"] = round(random.uniform(0.72, 0.97), 3)
                    yield await _sse({"type": "done", "output_tokens": output_tokens, **extra_fields})
        finally:
            LLM_ACTIVE.add(-1)

    return StreamingResponse(stream(), media_type="text/event-stream")
