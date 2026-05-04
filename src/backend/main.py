"""
Backend entrypoint.

CRITICAL: OTel SDK providers MUST be installed before importing any module that
creates meters/instruments at import time (e.g., backend.observability.metrics).
Otherwise instruments bind to the no-op ProxyMeterProvider permanently. This is
why init_observability() runs first, before all other backend.* imports.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# OTel init MUST come before any backend.api / backend.observability.metrics imports.
from backend.observability.init import init_observability_providers, instrument_app
from backend.observability.logging import configure as configure_logging

# Install TracerProvider + MeterProvider FIRST (before metrics/spans modules import).
init_observability_providers()

# Now safe to import modules that create instruments/tracers at module load.
from backend.admin.injector import router as admin_router  # noqa: E402
from backend.admin.judge_canary import router as judge_canary_router  # noqa: E402
from backend.api.analyze import router as analyze_router  # noqa: E402
from backend.api.health import router as health_router  # noqa: E402
from backend.api.postmortem import router as postmortem_router  # noqa: E402
from backend.middleware import (  # noqa: E402
    MemoryLeakMiddleware,
    RequestIdMiddleware,
    register_error_handlers,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield


app = FastAPI(
    title="SRE Copilot Backend",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(MemoryLeakMiddleware)
register_error_handlers(app)

# Wire FastAPI auto-instrumentation onto the app instance.
instrument_app(app)

app.include_router(analyze_router, prefix="/analyze")
app.include_router(postmortem_router, prefix="/generate")
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(judge_canary_router)
