"""Layer-1 structural eval: SSE event shape and token bounds (AT-010).

These tests exercise the SSE framing contract using the real FastAPI app
with a mocked Ollama client. No live LLM calls are made.
"""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# Tests run with no OTel collector available — keep the SDK on the no-op path.
# init_observability_providers() returns early when this env is unset.
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def _make_mock_chunk(content: str):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return chunk


class _MockStream:
    """Real async-iterable mock stream — AsyncMock can't satisfy `async for`."""
    def __init__(self, raw_chunks):
        self._chunks = [_make_mock_chunk(c) for c in raw_chunks]
    def __aiter__(self):
        return self._gen()
    async def _gen(self):
        for c in self._chunks:
            yield c
    async def aclose(self):
        pass


def _make_mock_stream(chunks):
    return _MockStream(chunks)


def _valid_analysis_json() -> str:
    return json.dumps({
        "severity": "critical",
        "summary": "DataNode replication failure detected in HDFS cluster.",
        "root_cause": "Network partition disrupted DataNode heartbeats to NameNode.",
        "runbook": ["Check DataNode logs", "Verify network", "Restart service"],
        "related_metrics": ["hdfs_datanode_block_reports_total"],
    })


@pytest.mark.asyncio
async def test_sse_emits_delta_events(hdfs_sample: str):
    chunks = list(_valid_analysis_json())
    mock_stream = _make_mock_stream(chunks)

    mock_client = AsyncMock()
    mock_client.chat = AsyncMock()
    mock_client.chat.completions = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

    with patch("backend.api.analyze.client", mock_client):
        from backend.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/analyze/logs",
                json={"log_payload": hdfs_sample},
            ) as r:
                assert r.status_code == 200
                assert "text/event-stream" in r.headers.get("content-type", "")

                events = []
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line.removeprefix("data: "))
                    events.append(evt)
                    if evt.get("type") == "done":
                        break

    assert any(e.get("type") == "delta" for e in events), "must emit delta events"
    assert events[-1].get("type") == "done", "final event must be 'done'"


@pytest.mark.asyncio
async def test_sse_done_event_has_output_tokens(hdfs_sample: str):
    chunks = list(_valid_analysis_json())
    mock_stream = _make_mock_stream(chunks)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

    with patch("backend.api.analyze.client", mock_client):
        from backend.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/analyze/logs",
                json={"log_payload": hdfs_sample},
            ) as r:
                done_event = None
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line.removeprefix("data: "))
                    if evt.get("type") == "done":
                        done_event = evt
                        break

    assert done_event is not None
    assert "output_tokens" in done_event
    assert done_event["output_tokens"] > 0


@pytest.mark.asyncio
async def test_sse_accumulated_tokens_parse_as_valid_json(hdfs_sample: str):
    json_str = _valid_analysis_json()
    chunks = list(json_str)
    mock_stream = _make_mock_stream(chunks)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

    with patch("backend.api.analyze.client", mock_client):
        from backend.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/analyze/logs",
                json={"log_payload": hdfs_sample},
            ) as r:
                accumulated = ""
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line.removeprefix("data: "))
                    if evt.get("type") == "delta":
                        accumulated += evt.get("token", "")
                    elif evt.get("type") == "done":
                        break

    parsed = json.loads(accumulated)
    from backend.schemas import LogAnalysis
    LogAnalysis.model_validate(parsed)


@pytest.mark.asyncio
async def test_malformed_input_returns_422(hdfs_sample: str):
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/analyze/logs", json={"log_payload": "short"})
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_empty_input_returns_400():
    """Per AT-008 + S2 error_handler middleware: validation errors → 400 (structured)."""
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/analyze/logs", json={})
    assert r.status_code == 400


def test_token_bounds_within_limits(hdfs_sample: str):
    from backend.schemas import LogAnalysisRequest
    req = LogAnalysisRequest(log_payload=hdfs_sample)
    tokens = req.estimated_tokens()
    assert 0 < tokens < 100_000, f"token estimate out of bounds: {tokens}"
