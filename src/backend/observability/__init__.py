"""
Observability package.

DELIBERATELY EMPTY of eager re-exports. Callers must import submodules
directly (e.g., `from backend.observability.metrics import LLM_TTFT`).

Why: `metrics.py` creates instruments at module load. If `__init__.py`
re-exports them, any `from backend.observability import ...` triggers
metric creation BEFORE `init_observability_providers()` has installed
the real MeterProvider — instruments bind to the no-op ProxyMeterProvider
permanently. Keeping this file empty preserves the strict load ordering
documented in `init.py`.
"""
