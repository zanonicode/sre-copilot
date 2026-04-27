"""
OTel SDK init split into two phases:

1. init_observability_providers() — installs TracerProvider + MeterProvider on
   the global OTel APIs. Must run BEFORE any module imports that create
   meters/instruments at module load (e.g., backend.observability.metrics),
   otherwise instruments bind permanently to the no-op ProxyMeterProvider.

2. instrument_app(app) — wires FastAPIInstrumentor onto the app instance and
   activates HTTPXClientInstrumentor. Runs AFTER the FastAPI app exists.
"""
import logging
import os
import sys

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_INITIALIZED = False


def init_observability_providers() -> None:
    """Install OTel TracerProvider + MeterProvider on the global APIs.

    Idempotent. No-op if OTEL_EXPORTER_OTLP_ENDPOINT is unset (local dev).
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        return

    resource = Resource.create({
        "service.name": "sre-copilot-backend",
        "service.version": os.environ.get("APP_VERSION", "dev"),
        "deployment.environment": "kind-local",
        # Hint to the Loki exporter in the collector: promote these resource
        # attributes to Loki stream labels so dashboards can filter by them.
        "loki.resource.labels": "service.name,deployment.environment",
    })

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tp)

    mp = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, insecure=True),
                export_interval_millis=10_000,
            )
        ],
    )
    metrics.set_meter_provider(mp)

    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    _logs.set_logger_provider(lp)

    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=lp)
    logging.getLogger().addHandler(otel_handler)

    # Surface OTel SDK errors to stderr so we see export failures
    # (BatchSpanProcessor swallows them by default).
    logging.getLogger("opentelemetry").addHandler(logging.StreamHandler(sys.stderr))

    # Filter benign async-generator warnings: contextvar tokens attached
    # in one asyncio task can fail to detach when the SSE generator's
    # finally runs in a different task (client disconnect, aclose, GC).
    # These don't affect span correctness — they just spam logs.
    class _AsyncCtxNoise(logging.Filter):
        _patterns = ("Failed to detach context", "Calling end() on an ended span")
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(p in msg for p in self._patterns)

    logging.getLogger("opentelemetry.context").addFilter(_AsyncCtxNoise())
    logging.getLogger("opentelemetry.sdk.trace").addFilter(_AsyncCtxNoise())

    _INITIALIZED = True


def instrument_app(app) -> None:
    """Wire auto-instrumentation onto the FastAPI app instance.

    Safe to call even when providers weren't initialized (instruments will
    no-op against the ProxyTracerProvider).
    """
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/healthz,/metrics",
        http_capture_headers_server_request=["traceparent", "x-request-id"],
    )
    HTTPXClientInstrumentor().instrument()


# Backwards-compatible alias for any external caller.
def init_otel(app) -> None:
    init_observability_providers()
    instrument_app(app)
