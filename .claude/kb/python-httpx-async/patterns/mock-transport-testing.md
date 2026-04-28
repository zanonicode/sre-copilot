# Pattern: MockTransport for Testing

> Simulate MediaWiki + Discourse upstreams offline with `httpx.MockTransport`. No network, deterministic responses, per-source failure injection.
> **MCP Validated**: 2026-04-23

## Why MockTransport

`httpx.MockTransport(handler)` intercepts requests at the transport layer. Tests exercise the real `AsyncClient` code path — URL encoding, headers, timeouts, retries — without touching the network.

Alternatives (and why `MockTransport` wins):

| Tool | Drawback |
|------|----------|
| `unittest.mock.patch("httpx.AsyncClient.get")` | Bypasses the client entirely — misses bugs in URL/header handling |
| `respx` (3rd-party) | Another dependency; `MockTransport` is built-in |
| Live network calls | Flaky, slow, depend on upstream uptime |

## Basic Handler

A handler is `Callable[[httpx.Request], httpx.Response]`:

```python
import httpx


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "platformwiki.example":
        return httpx.Response(
            200,
            json={"query": {"search": [{"title": "Kubernetes", "snippet": "..."}]}},
        )
    if request.url.host == "community.example":
        return httpx.Response(
            200,
            json={"topics": [{"id": 1, "title": "Helm tips"}]},
        )
    return httpx.Response(404)


transport = httpx.MockTransport(handler)
client = httpx.AsyncClient(transport=transport)
```

## pytest Fixtures

Provide one fixture per source plus a combined fixture:

```python
# conftest.py
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest


def _mw_ok(hits: list[dict]) -> Callable[[httpx.Request], httpx.Response]:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": {"search": hits}})
    return h


def _dc_ok(topics: list[dict]) -> Callable[[httpx.Request], httpx.Response]:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"topics": topics})
    return h


@pytest.fixture
def mock_client_all_ok() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == "platformwiki.example":
            return _mw_ok([{"title": "Deploy", "snippet": "rolling"}])(req)
        if host == "community.example":
            return _dc_ok([{"id": 1, "title": "Helm"}])(req)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def mock_client_mw_500() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "platformwiki.example":
            return httpx.Response(500, text="Internal Server Error")
        if req.url.host == "community.example":
            return _dc_ok([{"id": 1, "title": "Helm"}])(req)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
```

## Injecting the Client

Module-level clients are awkward to replace. Use `monkeypatch`:

```python
# test_search.py
import pytest
from myapp import handler as search_module


@pytest.mark.asyncio
async def test_all_sources_ok(mock_client_all_ok, monkeypatch):
    monkeypatch.setattr(search_module, "_client", mock_client_all_ok)
    results = await search_module.search_all("kubernetes")
    assert [r.source for r in results] == ["mediawiki", "discourse", "local"]
    assert all(not r.error for r in results if r.source != "local")


@pytest.mark.asyncio
async def test_mediawiki_500_returns_partial(mock_client_mw_500, monkeypatch):
    monkeypatch.setattr(search_module, "_client", mock_client_mw_500)
    results = await search_module.search_all("kubernetes")
    mw = next(r for r in results if r.source == "mediawiki")
    dc = next(r for r in results if r.source == "discourse")
    assert mw.error is not None
    assert mw.hits == []
    assert dc.error is None
    assert len(dc.hits) == 1
```

## Simulating Slow Sources

`MockTransport` accepts async handlers — use `asyncio.sleep` to inject delay:

```python
async def slow_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "community.example":
        await asyncio.sleep(3.0)  # will blow the read timeout
    return httpx.Response(200, json={})

client = httpx.AsyncClient(
    transport=httpx.MockTransport(slow_handler),
    timeout=httpx.Timeout(read=0.5),
)
```

Then assert that a slow Discourse does NOT block the fan-out: measure wall time inside the test and verify it stays under the overall budget.

## Asserting Retry Behavior

Count handler invocations to verify retry attempts:

```python
@pytest.mark.asyncio
async def test_mediawiki_retries_on_503(monkeypatch):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "platformwiki.example":
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"query": {"search": []}})
        return httpx.Response(404)

    monkeypatch.setattr(
        search_module,
        "_client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await search_module.search_mediawiki("k8s")
    assert calls["n"] == 3  # initial + 2 retries
```

## Pitfalls

| Pitfall | Fix |
|---------|-----|
| Test asserts against the global `_client` | `monkeypatch.setattr` to inject mock |
| Handler not awaited when async | Use plain def for sync, async def for await-needing handlers |
| Forgetting `pytest-asyncio` | Add `@pytest.mark.asyncio` and install `pytest-asyncio` |
| Leaking transports across tests | Scope fixtures to `function` (default) |

## Related

- [patterns/parallel-fanout.md](parallel-fanout.md)
- [patterns/retry-with-backoff.md](retry-with-backoff.md)
- [concepts/async-client-lifecycle.md](../concepts/async-client-lifecycle.md)
