import json
import os
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, AsyncOpenAI
from opentelemetry import trace

from backend.observability.metrics import LLM_OUTPUT_TOKENS
from backend.prompts import render_postmortem
from backend.schemas.postmortem import PostmortemRequest

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", "http://ollama.sre-copilot.svc.cluster.local:11434/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M")

router = APIRouter()
tracer = trace.get_tracer(__name__)
client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


async def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


@router.post("/postmortem")
async def generate_postmortem(req: PostmortemRequest, request: Request):
    prompt = render_postmortem(req.log_analysis, req.timeline, req.context)

    async def stream() -> AsyncIterator[bytes]:
        with tracer.start_as_current_span("postmortem.generate"):
            try:
                stream_resp = await client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                    response_format={"type": "json_object"},
                )
            except APIConnectionError as e:
                tracer.start_as_current_span("postmortem.generate").__exit__(None, None, None)
                raise HTTPException(503, "LLM backend is unavailable") from e

            output_tokens = 0
            async for chunk in stream_resp:
                if await request.is_disconnected():
                    await stream_resp.aclose()
                    return
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                output_tokens += 1
                yield await _sse({"type": "delta", "token": delta})
            LLM_OUTPUT_TOKENS.add(output_tokens)
            yield await _sse({"type": "done", "output_tokens": output_tokens})

    return StreamingResponse(stream(), media_type="text/event-stream")
