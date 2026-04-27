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
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(logging.INFO)
