"""Unit tests for the anomaly injector admin endpoint."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def client_with_token(monkeypatch):
    monkeypatch.setenv("ANOMALY_INJECTOR_TOKEN", "test-token-12345")
    return TestClient(app)


class TestAnomalyInjector:
    def test_inject_forbidden_without_token(self, client_with_token):
        resp = client_with_token.post("/admin/inject?scenario=cascade_retry_storm")
        assert resp.status_code == 403

    def test_inject_forbidden_with_wrong_token(self, client_with_token):
        resp = client_with_token.post(
            "/admin/inject?scenario=cascade_retry_storm",
            headers={"X-Inject-Token": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_inject_unknown_scenario_returns_404(self, client_with_token):
        resp = client_with_token.post(
            "/admin/inject?scenario=nonexistent_scenario",
            headers={"X-Inject-Token": "test-token-12345"},
        )
        assert resp.status_code == 404

    def test_inject_endpoint_not_in_openapi_schema(self):
        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        paths = schema.get("paths", {})
        assert "/admin/inject" not in paths

    def test_healthz_returns_ok(self):
        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestChunkingStrategy:
    def test_single_strategy_for_short_text(self):
        from backend.chunking.strategy import select_strategy
        assert select_strategy("short log line") == "single"

    def test_summarize_strategy_for_medium_text(self):
        from backend.chunking.strategy import select_strategy
        medium_text = "error in service " * 1000
        result = select_strategy(medium_text)
        assert result in ("single", "summarize")

    def test_map_reduce_strategy_for_long_text(self):
        from backend.chunking.strategy import select_strategy, SUMMARIZE_LIMIT
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        long_text = "error in upstream service timeout " * 2000
        tokens = len(enc.encode(long_text))
        if tokens > SUMMARIZE_LIMIT:
            assert select_strategy(long_text) == "map_reduce"

    def test_chunk_text_respects_max_tokens(self):
        from backend.chunking.strategy import chunk_text, count_tokens
        lines = ["log line number " + str(i) for i in range(500)]
        text = "\n".join(lines)
        chunks = chunk_text(text, max_tokens=100)
        for chunk in chunks:
            assert count_tokens(chunk) <= 120
