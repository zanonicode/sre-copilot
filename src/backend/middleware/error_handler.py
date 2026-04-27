import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("backend.middleware")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _request_id(request)
        log.warning(
            "validation error",
            extra={
                "event": "http.validation_error",
                "endpoint": str(request.url.path),
                "request_id": request_id,
                "errors": exc.errors(),
            },
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": "validation_error",
                "detail": exc.errors(),
                "request_id": request_id,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id = _request_id(request)
        log.error(
            "http error",
            extra={
                "event": "http.error",
                "endpoint": str(request.url.path),
                "status_code": exc.status_code,
                "request_id": request_id,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail or "internal_error",
                "request_id": request_id,
            },
        )
