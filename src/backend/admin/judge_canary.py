"""Canary quality gate endpoint.

Called by the Argo Rollouts AnalysisTemplate `backend-canary-quality` during the
50%->100% rollout step. Runs the LLM judge against a stratified sample of
ground-truth records, scoring THIS pod's own /analyze/logs output, then returns
a numeric verdict the AnalysisTemplate compares against `>= 0.80`.

Self-evaluation: POSTs to localhost:8000/analyze/logs so the candidate
analysis comes from this exact canary pod, not the load-balanced Service.

Auth: Bearer token via Authorization header. Token sealed via Bitnami Sealed
Secrets and mounted as JUDGE_CANARY_TOKEN env var, mirroring the existing
ANOMALY_INJECTOR_TOKEN sibling.

Judge composition: env-driven via `factory.make_judges()` — zero env =
Ollama-only single judge (preserves demo property); JUDGE_PROVIDERS=anthropic,
openai,ollama = panel-of-judges with hybrid aggregation. Per-record verdict
comes from `panel.panel_score()`; inconclusive (quorum<2) records are skipped
under fail-open semantics inherited from ADR-0009.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from opentelemetry import trace

from backend.eval.judge_core import (
    JUDGE_PROMPT,
    aggregate,
    fetch_candidate,
    stratified_sample,
)
from backend.eval.panel import panel_score
from backend.eval.providers.factory import make_judges
from backend.observability.metrics import JUDGE_CANARY_DURATION, JUDGE_CANARY_RUNS

router = APIRouter(prefix="/admin", include_in_schema=False)
log = logging.getLogger("backend.judge_canary")
tracer = trace.get_tracer(__name__)

# CWD-relative defaults work for local `make judge` flow; override via env
# in container deploys where dataset is COPYed under a different path.
GROUND_TRUTH_DIR = pathlib.Path(
    os.environ.get("JUDGE_GROUND_TRUTH_DIR", "datasets/eval/ground_truth")
)
RUBRIC_PATH = pathlib.Path(
    os.environ.get("JUDGE_RUBRIC_PATH", "tests/eval/judge/rubric.yaml")
)
SELF_BACKEND_URL = os.environ.get("JUDGE_SELF_BACKEND_URL", "http://localhost:8000")
PASS_THRESHOLD = float(os.environ.get("JUDGE_PASS_THRESHOLD", "0.80"))

async def verify_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("JUDGE_CANARY_TOKEN", "")
    if not expected:
        raise HTTPException(503, "JUDGE_CANARY_TOKEN not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "Invalid bearer token")


@router.get("/judge-canary", dependencies=[Depends(verify_token)])
async def judge_canary(sample_size: int = 6) -> dict[str, Any]:
    started = time.perf_counter()
    with tracer.start_as_current_span("judge_canary") as span:
        span.set_attribute("judge.sample_size", sample_size)

        gt_paths = stratified_sample(
            sorted(GROUND_TRUTH_DIR.glob("*.json")), sample_size
        )
        if not gt_paths:
            JUDGE_CANARY_RUNS.add(1, {"result": "error"})
            JUDGE_CANARY_DURATION.record(time.perf_counter() - started)
            raise HTTPException(
                503, f"No ground-truth records under {GROUND_TRUTH_DIR}"
            )

        rubric = RUBRIC_PATH.read_text()
        providers = make_judges()
        provider_names = [p.name for p in providers]
        span.set_attribute("judge.providers", ",".join(provider_names))

        results: list[dict[str, Any]] = []
        for gt_path in gt_paths:
            gt = json.loads(gt_path.read_text())
            log_payload = gt.get("log_payload") or gt.get("log_snippet", "")
            if not log_payload:
                continue
            candidate = await asyncio.to_thread(
                fetch_candidate, SELF_BACKEND_URL, log_payload
            )
            if candidate is None:
                continue
            prompt = JUDGE_PROMPT.format(
                rubric=rubric,
                ground_truth=json.dumps(gt, indent=2),
                candidate=json.dumps(candidate, indent=2),
            )
            verdict = await panel_score(providers, prompt)
            if verdict is None:
                # Quorum not met for this record — skip; per-record fail-open.
                continue
            results.append({
                "root_cause_match": verdict.root_cause_match,
                "remediation_soundness": verdict.remediation_soundness,
                "hallucination": verdict.hallucination,
                "rationale": verdict.rationale,
            })

        if not results:
            JUDGE_CANARY_RUNS.add(1, {"result": "error"})
            JUDGE_CANARY_DURATION.record(time.perf_counter() - started)
            log.warning("judge_canary: all samples skipped")
            raise HTTPException(503, "All samples skipped (backend or panel unreachable)")

        summary = aggregate(results, PASS_THRESHOLD)
        result_label = "pass" if summary["passed"] else "fail"
        JUDGE_CANARY_RUNS.add(1, {"result": result_label})
        JUDGE_CANARY_DURATION.record(time.perf_counter() - started)

        span.set_attribute("judge.match_rate", summary["root_cause_match_rate"])
        span.set_attribute("judge.passed", summary["passed"])

        return {
            "root_cause_match_rate": summary["root_cause_match_rate"],
            "evaluated": summary["evaluated"],
            "providers": provider_names,
            "sample_size": sample_size,
        }
