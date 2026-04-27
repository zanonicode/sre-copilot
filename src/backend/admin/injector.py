import asyncio
import logging
import os
import random

from fastapi import APIRouter, Header, HTTPException

router = APIRouter(prefix="/admin", include_in_schema=False)
log = logging.getLogger("backend.injector")

SCENARIOS: dict[str, list[tuple[str, str, str]]] = {
    "cascade_retry_storm": [
        ("error", "downstream.timeout", "GET /upstream/api timed out after 5000ms"),
        ("error", "retry.attempt", "retrying GET /upstream/api (attempt 2/3)"),
        ("error", "retry.attempt", "retrying GET /upstream/api (attempt 3/3)"),
        ("critical", "circuit.open", "circuit breaker OPEN for upstream-api"),
    ],
    "memory_leak": [
        ("warning", "gc.long_pause", "GC pause 1.4s, heap=82%"),
        ("warning", "gc.long_pause", "GC pause 1.8s, heap=89%"),
        ("critical", "oom.imminent", "heap=96%, eviction failed"),
    ],
}


@router.post("/inject")
async def inject(
    scenario: str,
    x_inject_token: str | None = Header(default=None),
) -> dict:
    if x_inject_token != os.environ.get("ANOMALY_INJECTOR_TOKEN"):
        raise HTTPException(403)
    if scenario not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario: {scenario}")
    pattern = SCENARIOS[scenario]
    for _ in range(15):
        for level, event, msg in pattern:
            getattr(log, "error" if level == "critical" else level)(
                msg,
                extra={"event": event, "synthetic_anomaly": True},
            )
            await asyncio.sleep(random.uniform(0.05, 0.35))
    return {"status": "injected", "scenario": scenario, "events": 15 * len(pattern)}
