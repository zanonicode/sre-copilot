import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import trace


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": "backend",
            "trace_id": f"{ctx.trace_id:032x}" if ctx and ctx.trace_id else None,
            "span_id": f"{ctx.span_id:016x}" if ctx and ctx.span_id else None,
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for k in ("model", "input_tokens", "output_tokens", "duration_ms",
                  "endpoint", "user_session", "synthetic_anomaly"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure() -> None:
    # Append (don't replace) so we compose with the OTel LoggingHandler that
    # init_observability_providers() may have already attached to the root
    # logger. `root.handlers = [h]` would silently wipe the OTel exporter
    # and break the logs-to-Loki pipeline.
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_sre_json", False) for h in root.handlers):
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(JsonFormatter())
        h._sre_json = True  # marker so re-configure() is idempotent
        root.addHandler(h)
    root.setLevel(logging.INFO)
