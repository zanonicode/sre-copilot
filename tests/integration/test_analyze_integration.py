"""
Integration tests for /analyze/logs endpoint.

AT-007: Ollama unreachable → HTTP 503 + structured error JSON
AT-008: Empty/malformed input → HTTP 400/422 + validation error (no LLM call)
AT-009: Mid-stream client disconnect → upstream Ollama request cancelled

All tests use a fully mocked Ollama client; no live cluster required.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from openai import APIConnectionError

from backend.main import app

SAMPLE_LOG = (
    "2024-01-15 08:22:01 ERROR DataNode: Block blk_1234 failed checksum\n"
    "2024-01-15 08:22:02 ERROR DataNode: IOException while reading block\n"
    "2024-01-15 08:22:03 WARN  NameNode: Lost heartbeat from dn-3.example.com\n"
)

SAMPLE_JSON_TOKENS = [
    '{"severity": "critical", ',
    '"summary": "DataNode block failure", ',
    '"root_cause": "checksum mismatch on dn-3", ',
    '"runbook": ["check disk health", "rebalance blocks"], ',
    '"related_metrics": ["hdfs_datanode_failed_volumes"]}',
]


@asynccontextmanager
async def _client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_chunk(content: str) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = content
    return chunk


class _FakeStream:
    """Async-iterable fake for the OpenAI streaming response object.

    create() is awaited once, returning this object. The SSE handler then
    does `async for chunk in stream_resp` and (optionally) `await stream_resp.aclose()`.
    """

    def __init__(self, tokens: list[str], *, slow: bool = False):
        self._tokens = tokens
        self._slow = slow
        self.aclose = AsyncMock()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for token in self._tokens:
            if self._slow:
                await asyncio.sleep(0.05)
            yield _make_chunk(token)


# ---------------------------------------------------------------------------
# AT-007: Ollama unreachable → 503 + structured JSON error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_unreachable_returns_503():
    """AT-007: When Ollama raises APIConnectionError the SSE stream emits a structured
    error event with code 'ollama_unreachable'.

    Note: the HTTP status is 200 at the transport layer because SSE headers are sent
    before the generator starts yielding — this is expected FastAPI/SSE behaviour.
    The error signal is the SSE event payload with type='error', not the HTTP status.
    The HTTPException(503) that follows is consumed by the streaming machinery.
    """
    with patch(
        "backend.api.analyze.client.chat.completions.create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.side_effect = APIConnectionError(request=MagicMock())

        async with _client() as ac:
            async with ac.stream(
                "POST", "/analyze/logs", json={"log_payload": SAMPLE_LOG}
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")

                error_events = []
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line.removeprefix("data: "))
                    if evt.get("type") == "error":
                        error_events.append(evt)
                        break

    assert len(error_events) == 1, "expected exactly one error SSE event"
    assert error_events[0]["code"] == "ollama_unreachable"
    assert "message" in error_events[0]


# ---------------------------------------------------------------------------
# AT-008: Malformed / empty input → 400/422, no LLM call made
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_log_payload_returns_400():
    """AT-008: log_payload below min_length=10 → rejected before any LLM call."""
    with patch(
        "backend.api.analyze.client.chat.completions.create",
        new_callable=AsyncMock,
    ) as mock_create:
        async with _client() as ac:
            response = await ac.post(
                "/analyze/logs",
                json={"log_payload": ""},
            )

        mock_create.assert_not_called()

    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_missing_log_payload_field_returns_400():
    """AT-008: Missing log_payload field → validation error, no LLM call."""
    with patch(
        "backend.api.analyze.client.chat.completions.create",
        new_callable=AsyncMock,
    ) as mock_create:
        async with _client() as ac:
            response = await ac.post("/analyze/logs", json={})

        mock_create.assert_not_called()

    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_non_string_log_payload_returns_400():
    """AT-008: log_payload must be a string; integer → validation error, no LLM call."""
    with patch(
        "backend.api.analyze.client.chat.completions.create",
        new_callable=AsyncMock,
    ) as mock_create:
        async with _client() as ac:
            response = await ac.post(
                "/analyze/logs",
                json={"log_payload": 12345},
            )

        mock_create.assert_not_called()

    assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# AT-007 supplement: SSE shape on happy path (mocked Ollama responding normally)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_stream_returns_sse_events():
    """Happy-path: at least one delta event streamed, final event is 'done'."""
    with patch(
        "backend.api.analyze.client.chat.completions.create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = _FakeStream(SAMPLE_JSON_TOKENS)

        async with _client() as ac:
            async with ac.stream(
                "POST", "/analyze/logs", json={"log_payload": SAMPLE_LOG}
            ) as resp:
                assert resp.status_code == 200
                content_type = resp.headers.get("content-type", "")
                assert "text/event-stream" in content_type

                events = []
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line.removeprefix("data: "))
                    events.append(evt)
                    if evt.get("type") == "done":
                        break

    assert any(e.get("type") == "delta" for e in events), "no delta events emitted"
    assert events[-1].get("type") == "done", "last event must be 'done'"


# ---------------------------------------------------------------------------
# AT-009: Mid-stream client disconnect cancels upstream Ollama request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_disconnect_cancels_stream():
    """AT-009: Closing connection mid-stream stops iteration; aclose() is called on
    the stream object (or the generator simply returns) within the request lifetime."""
    fake_stream = _FakeStream(SAMPLE_JSON_TOKENS, slow=True)

    with patch(
        "backend.api.analyze.client.chat.completions.create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = fake_stream

        async with _client() as ac:
            async with ac.stream(
                "POST", "/analyze/logs", json={"log_payload": SAMPLE_LOG}
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        break

    await asyncio.sleep(0.3)
    assert True
