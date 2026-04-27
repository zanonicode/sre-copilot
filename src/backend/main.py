from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.admin.injector import router as admin_router
from backend.api.analyze import router as analyze_router
from backend.api.health import router as health_router
from backend.api.postmortem import router as postmortem_router
from backend.middleware import RequestIdMiddleware, register_error_handlers
from backend.observability.init import init_otel
from backend.observability.logging import configure as configure_logging


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
register_error_handlers(app)

init_otel(app)

app.include_router(analyze_router, prefix="/analyze")
app.include_router(postmortem_router, prefix="/generate")
app.include_router(health_router)
app.include_router(admin_router)
