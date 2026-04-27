"""
AT-001 final assertion: trace visible in Tempo within 5s with >=4 spans,
including the synthetic ollama.inference span.

Runnable modes:
1. Full smoke test (live cluster): BACKEND_URL + TEMPO_URL set, Ollama healthy.
2. Offline / CI without cluster: skips the Tempo assertions, validates SSE shape only.

Usage:
    # Full (live cluster):
    BACKEND_URL=https://sre-copilot.localtest.me TEMPO_URL=http://localhost:3200 pytest tests/smoke/

    # Shape-only (no cluster):
    pytest tests/smoke/test_trace_visible.py

Environment variables:
    BACKEND_URL        Base URL of backend (default: http://localhost:8000)
    TEMPO_URL          Base URL of Tempo HTTP API (default: http://localhost:3200)
    SMOKE_TIMEOUT      Per-request timeout in seconds (default: 15)
    TRACE_WAIT_SECONDS How long to poll Tempo for the trace (default: 5)
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

import pytest

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TEMPO_URL = os.environ.get("TEMPO_URL", "http://localhost:3200")
SMOKE_TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "15"))
TRACE_WAIT_SECONDS = int(os.environ.get("TRACE_WAIT_SECONDS", "5"))

HDFS_LOG_SAMPLE = (
    "081109 203518 143 INFO dfs.DataNode$PacketResponder: "
    "PacketResponder 0 for block blk_-6670958622368987959_1148 terminating\n"
    "081109 203519 35 ERROR dfs.DataNode: DatanodeRegistration(10.250.19.102:50010): "
    "Exception in receiveBlock for block blk_-6670958622368987959_1148\n"
    "java.io.EOFException: EOF reading from stream\n"
    "081109 203519 35 INFO dfs.DataNode: DatanodeRegistration(10.250.19.102:50010): "
    "Receiving block blk_-6670958622368987959_1148 src: 10.251.73.220:52013 dest: 10.250.19.102:50010"
)


def _issue_analyze_request() -> tuple[Optional[str], list[dict]]:
    """
    POST a log analysis request and consume the SSE stream.
    Returns (trace_id, list_of_sse_events).
    trace_id is extracted from response headers if the backend propagates it.
    """
    payload = json.dumps({"log_payload": HDFS_LOG_SAMPLE}).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/analyze/logs",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    events: list[dict] = []
    trace_id: Optional[str] = None

    with urllib.request.urlopen(req, timeout=SMOKE_TIMEOUT) as resp:
        trace_id = resp.headers.get("X-Trace-Id") or resp.headers.get("traceparent")
        if trace_id and trace_id.startswith("00-"):
            trace_id = trace_id.split("-")[1]

        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line.removeprefix("data: "))
            except json.JSONDecodeError:
                continue
            events.append(event)
            if event.get("type") == "done":
                break

    return trace_id, events


def _query_tempo_trace(trace_id: str) -> Optional[dict]:
    """
    Query the Tempo HTTP API for a specific trace by ID.
    Returns the trace JSON dict or None if not found / Tempo unreachable.
    """
    url = f"{TEMPO_URL}/api/traces/{trace_id}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError):
        return None


def _search_tempo_recent(service_name: str = "sre-copilot-backend") -> Optional[str]:
    """
    Search Tempo for the most recent trace from sre-copilot-backend.
    Returns the first trace ID found, or None.
    """
    url = (
        f"{TEMPO_URL}/api/search"
        f"?tags=service.name%3D{service_name}"
        f"&limit=1"
        f"&start={int(time.time()) - 60}"
        f"&end={int(time.time()) + 5}"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
            traces = data.get("traces", [])
            if traces:
                return traces[0]["traceID"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError):
        pass
    return None


def _tempo_reachable() -> bool:
    try:
        req = urllib.request.Request(f"{TEMPO_URL}/ready")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def _backend_reachable() -> bool:
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/healthz")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


class TestSseShape:
    """Shape assertions that work without a live cluster (offline safe)."""

    @pytest.mark.skipif(
        not _backend_reachable(),
        reason=f"Backend not reachable at {BACKEND_URL} — skipping SSE shape test.",
    )
    def test_sse_stream_opens_and_emits_tokens(self):
        """
        AT-001 (part 1): Backend streams SSE tokens within the timeout.
        Validates that the stream opens, emits at least one delta event,
        and terminates with a done event.
        """
        _, events = _issue_analyze_request()

        assert events, "No SSE events received from backend"
        delta_events = [e for e in events if e.get("type") == "delta"]
        assert delta_events, "No 'delta' (token) events in SSE stream"

        last = events[-1]
        assert last.get("type") == "done", (
            f"Last SSE event was not 'done'; got type={last.get('type')!r}"
        )

    @pytest.mark.skipif(
        not _backend_reachable(),
        reason=f"Backend not reachable at {BACKEND_URL} — skipping final payload test.",
    )
    def test_sse_final_payload_contains_required_fields(self):
        """
        AT-001 (part 2): The accumulated JSON from delta events parses to a
        valid LogAnalysis with all 5 required fields (FR1).
        """
        _, events = _issue_analyze_request()

        accumulated = "".join(
            e["token"] for e in events if e.get("type") == "delta"
        )
        try:
            parsed = json.loads(accumulated)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Accumulated SSE tokens do not form valid JSON: {exc!r}")

        required = {"severity", "summary", "root_cause", "runbook", "related_metrics"}
        missing = required - set(parsed.keys())
        assert not missing, f"Final JSON missing required fields: {missing}"


class TestTempoTrace:
    """
    AT-001 (part 3): Trace visible in Tempo within 5s with >=4 spans,
    including ollama.inference synthetic span.
    """

    @pytest.mark.skipif(
        not _tempo_reachable() or not _backend_reachable(),
        reason=(
            f"Tempo not reachable at {TEMPO_URL} or "
            f"backend not reachable at {BACKEND_URL} — "
            "skipping live Tempo trace assertion. "
            "Set TEMPO_URL to the port-forwarded Tempo address to enable."
        ),
    )
    def test_trace_visible_in_tempo_within_5s(self):
        """
        AT-001 final: Issue one request, then poll Tempo until the trace appears
        (within TRACE_WAIT_SECONDS) and verify >=4 spans exist including
        the synthetic ollama.inference span.
        """
        trace_id, _ = _issue_analyze_request()

        found_trace = None
        deadline = time.time() + TRACE_WAIT_SECONDS

        while time.time() < deadline:
            candidate_id = trace_id or _search_tempo_recent()
            if candidate_id:
                found_trace = _query_tempo_trace(candidate_id)
            if found_trace:
                break
            time.sleep(0.5)

        assert found_trace is not None, (
            f"No trace found in Tempo within {TRACE_WAIT_SECONDS}s. "
            f"trace_id={trace_id!r}. "
            "Check that OTEL_EXPORTER_OTLP_ENDPOINT is set on backend pods "
            "and OTel collector is running in observability namespace."
        )

        all_spans = [
            span
            for rs in found_trace.get("resourceSpans", [])
            for scope_spans in rs.get("scopeSpans", [])
            for span in scope_spans.get("spans", [])
        ]

        assert len(all_spans) >= 4, (
            f"Expected >=4 spans in trace, found {len(all_spans)}. "
            f"Span names: {[s.get('name') for s in all_spans]}"
        )

        span_names = {s.get("name", "") for s in all_spans}
        assert "ollama.inference" in span_names, (
            f"Synthetic span 'ollama.inference' not found in trace. "
            f"Found spans: {sorted(span_names)}. "
            "This span is created by backend/observability/spans.py after stream completion. "
            "Check that synthetic_ollama_span() is being called in analyze.py."
        )

        assert "ollama.host_call" in span_names, (
            f"Expected 'ollama.host_call' span in trace. "
            f"Found spans: {sorted(span_names)}"
        )

        ollama_inference = next(
            s for s in all_spans if s.get("name") == "ollama.inference"
        )
        attrs = {
            a["key"]: a.get("value", {})
            for a in ollama_inference.get("attributes", [])
        }
        assert "synthetic" in attrs, (
            "ollama.inference span must have 'synthetic=True' attribute "
            "for honesty in Tempo trace viewer."
        )
        assert "llm.output_tokens" in attrs, (
            "ollama.inference span must carry llm.output_tokens attribute."
        )
