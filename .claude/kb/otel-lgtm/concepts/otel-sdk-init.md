# OTel SDK Initialization

> **Purpose**: How an app process turns into a producer of traces + metrics + logs that ship over OTLP to a collector
> **MCP Validated**: 2026-04-26

## Three Providers, One Resource

| Signal | Provider | Default Exporter |
|--------|----------|------------------|
| Traces | `TracerProvider` | `OTLPSpanExporter` (gRPC :4317) |
| Metrics | `MeterProvider` | `OTLPMetricExporter` (gRPC :4317) |
| Logs | `LoggerProvider` | `OTLPLogExporter` (gRPC :4317) — or stdout JSON for SRE Copilot |

All three share a `Resource` — the identity attached to every emitted item.

## The Resource

The Resource is the "who am I" of telemetry. Set once at process start.

```python
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "service.name": "sre-copilot-backend",
    "service.version": os.environ.get("APP_VERSION", "dev"),
    "deployment.environment": "kind-local",        # or "prod"
    "service.instance.id": socket.gethostname(),    # pod name on K8s
})
```

Standard semantic conventions: prefer `service.name`, `service.version`, `service.namespace`, `deployment.environment`. These power Grafana variable-driven dashboards.

## Initialization Order (must run before any instrumentation)

```python
def init_otel(app):
    # 1. Resource
    resource = Resource.create({...})

    # 2. TracerProvider + exporter + BatchSpanProcessor
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=ENDPOINT, insecure=True)
    ))
    trace.set_tracer_provider(tp)

    # 3. MeterProvider with periodic reader
    mp = MeterProvider(resource=resource, metric_readers=[
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=ENDPOINT, insecure=True),
            export_interval_millis=10_000,
        ),
    ])
    metrics.set_meter_provider(mp)

    # 4. Auto-instrumentation (must come AFTER providers are set)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz,/metrics")
    HTTPXClientInstrumentor().instrument()
```

If you instrument before setting the provider, spans go to the no-op default tracer and are silently dropped.

## Span Processors: Batch vs Simple

| Processor | When | Latency |
|-----------|------|---------|
| `BatchSpanProcessor` | Production / general | Buffered, default 5s flush |
| `SimpleSpanProcessor` | Tests / local debug | Synchronous |

Use Batch in SRE Copilot. For pytest, force flush in fixtures: `tp.force_flush(timeout_millis=2000)`.

## Sampling

```python
# 100% in dev, ratio in prod
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
tp = TracerProvider(resource=resource, sampler=ParentBasedTraceIdRatio(1.0))
```

`ParentBased` honors a sampled-or-not decision propagated via `traceparent` from upstream (browser → backend). For SRE Copilot kind cluster: sample 100%.

## Manual Spans

```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("ollama.host_call",
    attributes={"llm.model": "qwen2.5:7b", "peer.service": "ollama-host"}
) as span:
    try:
        result = await ollama.chat(...)
        span.set_attribute("llm.output_tokens", count)
    except Exception as e:
        span.record_exception(e)
        span.set_status(trace.StatusCode.ERROR, str(e))
        raise
```

## Synthetic Spans (DESIGN §9.2)

When the upstream system is opaque (Ollama on host, no OTel), emit a span FROM your process that REPRESENTS the upstream work — backdated start, real duration:

```python
def synthetic_ollama_span(parent, t0, duration, output_tokens, input_tokens):
    tracer = trace.get_tracer(__name__)
    ctx = trace.set_span_in_context(parent)
    s = tracer.start_span("ollama.inference", context=ctx,
                          start_time=int(t0 * 1e9))
    s.set_attribute("llm.input_tokens", input_tokens)
    s.set_attribute("llm.output_tokens", output_tokens)
    s.end(end_time=int((t0 + duration) * 1e9))
```

This makes the trace tree show "ollama.inference" as a real-looking span even though Ollama itself emitted nothing.

## Metrics Idioms

```python
from opentelemetry.metrics import get_meter
m = get_meter("sre_copilot.backend")
LLM_TTFT = m.create_histogram("llm.ttft_seconds", unit="s")
LLM_OUTPUT_TOKENS = m.create_counter("llm.tokens_output_total")
LLM_ACTIVE = m.create_up_down_counter("llm.active_requests")
```

| Instrument | Use |
|------------|-----|
| `Counter` | Monotonic count (errors, tokens emitted) |
| `UpDownCounter` | Bidirectional (active requests, queue depth) |
| `Histogram` | Distribution (latency, token-count distribution) |
| `Gauge` (observable) | Snapshot (CPU, RSS) — use callbacks |

## Logs (SRE Copilot choice: JSON to stdout, NOT OTLP)

We write structured JSON logs (DESIGN §4.4 / §5.3) to stdout, with `trace_id` + `span_id` injected from the current span. Loki Promtail/sidecar tails container stdout. This avoids the OTel logs SDK churn and Loki ingests cleanly.

## See Also

- patterns/python-fastapi-instrumentation.md — full lift-able init module
- concepts/collector-architecture.md — what receives the OTLP payloads
- patterns/browser-otel-traceparent.md — frontend equivalent
