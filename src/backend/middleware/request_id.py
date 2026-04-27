import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

log = logging.getLogger("backend.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        log.info(
            "request started",
            extra={
                "event": "http.request",
                "endpoint": str(request.url.path),
                "method": request.method,
                "request_id": request_id,
            },
        )

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id

        log.info(
            "request completed",
            extra={
                "event": "http.response",
                "endpoint": str(request.url.path),
                "status_code": response.status_code,
                "request_id": request_id,
            },
        )

        return response
