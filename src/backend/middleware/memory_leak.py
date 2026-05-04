import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("backend.middleware.memory_leak")

LEAK_MB_PER_REQ = int(os.getenv("MEMORY_LEAK_MB_PER_REQ", "0"))

_LEAKED: list[bytearray] = []


class MemoryLeakMiddleware(BaseHTTPMiddleware):
    """Failure-injection middleware: allocate N MB per request and never free.

    Default 0 = no-op. Used by `make demo-canary-memory-leak` to push pods
    into OOMKilled territory within the demo window. The 5xx-rate gate in
    backend-canary-health then fires at the 25% canary step.

    Skips /healthz so liveness probes don't accelerate the leak themselves.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if LEAK_MB_PER_REQ > 0 and request.url.path != "/healthz":
            _LEAKED.append(bytearray(LEAK_MB_PER_REQ * 1024 * 1024))
            log.warning(
                "memory leak: %d MB allocated (total leaked: %d MB)",
                LEAK_MB_PER_REQ,
                LEAK_MB_PER_REQ * len(_LEAKED),
            )
        return await call_next(request)
