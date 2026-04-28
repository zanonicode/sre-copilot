# Python FastAPI Instrumentation

> **Purpose**: Lift-able OTel init for the SRE Copilot backend — auto-instrument FastAPI + httpx, manual span around Ollama, synthetic ollama.inference span, JSON logs with trace_id injection
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #32 (`src/backend/observability/`)
- Mirrors DESIGN §4.3 (init), §4.4 (logs), §9.2 (synthetic span)

## Implementation

### Module layout

```text
src/backend/observability/
├── __init__.py
├── init.py            # init_otel(app)
├── metrics.py         # LLM_TTFT, LLM_OUTPUT_TOKENS, ...
├── spans.py           # synthetic_ollama_span(...)
└── logging.py         # JsonFormatter + configure()
```

### `init.py` (verbatim DESIGN §4.3, with imports)

```python
import os
from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

def init_otel(app):
    resource = Resource.create({
        "service.name": "sre-copilot-backend",
        "service.version": os.environ.get("APP_VERSION", "dev"),
        "deployment.environment": "kind-local",
    })
    endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(tp)

    mp = MeterProvider(resource=resource, metric_readers=[
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=True),
            export_interval_millis=10_000),
    ])
    metrics.set_meter_provider(mp)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz,/metrics")
    HTTPXClientInstrumentor().instrument()
```

### `metrics.py`

```python
from opentelemetry.metrics import get_meter
m = get_meter("sre_copilot.backend")

LLM_TTFT          = m.create_histogram("llm.ttft_seconds", unit="s",
                       description="Time to first token from Ollama")
LLM_RESPONSE      = m.create_histogram("llm.response_seconds", unit="s",
                       description="Full LLM response time")
LLM_OUTPUT_TOKENS = m.create_counter("llm.tokens_output_total")
LLM_INPUT_TOKENS  = m.create_counter("llm.tokens_input_total")
LLM_ACTIVE        = m.create_up_down_counter("llm.active_requests")
```

### `spans.py` (synthetic span — DESIGN §9.2)

```python
from opentelemetry import trace

def synthetic_ollama_span(parent, t0, duration, output_tokens, input_tokens):
    tracer = trace.get_tracer(__name__)
    ctx = trace.set_span_in_context(parent)
    s = tracer.start_span(
        "ollama.inference",
        context=ctx,
        start_time=int(t0 * 1e9),
        attributes={
            "llm.input_tokens": input_tokens,
            "llm.output_tokens": output_tokens,
            "peer.service": "ollama-host",
        },
    )
    s.end(end_time=int((t0 + duration) * 1e9))
```

### `logging.py` (DESIGN §4.4)

```python
import json, logging, sys
from datetime import datetime, timezone
from opentelemetry import trace

class JsonFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "backend",
            "trace_id": f"{ctx.trace_id:032x}" if ctx and ctx.trace_id else None,
            "span_id":  f"{ctx.span_id:016x}"  if ctx and ctx.span_id  else None,
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for k in ("model", "input_tokens", "output_tokens", "duration_ms",
                 "endpoint", "user_session"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))

def configure():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(logging.INFO)
```

### Wire into `main.py`

```python
from fastapi import FastAPI
from backend.observability.init import init_otel
from backend.observability.logging import configure as configure_logs
from backend.api import analyze, postmortem, health

configure_logs()
app = FastAPI()
init_otel(app)                   # MUST come after FastAPI() and BEFORE include_router
app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(postmortem.router)
```

## Configuration

| Env Var | Value (kind) |
|---------|--------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.observability:4317` |
| `OTEL_PYTHON_EXCLUDED_URLS` | `/healthz,/metrics` |
| `APP_VERSION` | injected by Helm from `.Chart.AppVersion` |

## Example Usage

```bash
curl -N -X POST http://localhost:8000/analyze/logs \
  -H 'Content-Type: application/json' \
  -d '{"log_payload": "..."}'

# Verify trace landed in Tempo
curl -s http://tempo.observability:3100/api/search?service.name=sre-copilot-backend | jq
```

## Verification (smoke)

```python
# tests/smoke/test_trace_visible.py — AT-001
async def test_trace_in_tempo():
    trace_id = await call_analyze_and_extract_trace_id()
    await asyncio.sleep(5)
    r = httpx.get(f"http://tempo.observability:3100/api/traces/{trace_id}")
    assert r.status_code == 200
    spans = r.json()["batches"][0]["scopeSpans"][0]["spans"]
    names = [s["name"] for s in spans]
    assert "ollama.host_call" in names
    assert "ollama.inference" in names
    assert len(spans) >= 4
```

## See Also

- concepts/otel-sdk-init.md — provider/resource/exporter theory
- patterns/otel-collector-config.md — receiving endpoint
- patterns/browser-otel-traceparent.md — frontend side
