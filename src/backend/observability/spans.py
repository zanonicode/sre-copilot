import os

from opentelemetry import trace
from opentelemetry.trace import SpanKind

_LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M")

_tracer = trace.get_tracer(__name__)


def synthetic_ollama_span(
    parent,
    t0: float,
    duration: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Create a child INTERNAL span representing host-side Ollama work.

    Reconstructed from chunk arrival timestamps because OTel cannot auto-instrument
    across the kind-cluster → host-process boundary (no Metal GPU passthrough in Docker).
    The `synthetic=True` attribute signals this to Tempo viewers.
    """
    end_time_ns = int((t0 + duration) * 1e9)
    start_time_ns = int(t0 * 1e9)
    with _tracer.start_as_current_span(
        "ollama.inference",
        kind=SpanKind.INTERNAL,
        start_time=start_time_ns,
        attributes={
            "llm.model": _LLM_MODEL,
            "llm.input_tokens": input_tokens,
            "llm.output_tokens": output_tokens,
            "llm.duration_seconds": duration,
            "llm.tokens_per_second": output_tokens / duration if duration else 0.0,
            "synthetic": True,
        },
    ) as span:
        span.end(end_time=end_time_ns)
