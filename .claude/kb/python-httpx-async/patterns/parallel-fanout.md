# Pattern: Parallel Fan-Out

> Concurrent calls to MediaWiki + Discourse + local SQLite FTS5 with partial-success tolerance. Core `/search` implementation.
> **MCP Validated**: 2026-04-23

## Goal

Given a query `q`, fetch results from all 3 sources in parallel, aggregate successes, and tolerate individual failures without aborting the whole request.

## Shape

```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceResult:
    source: str
    hits: list[dict[str, Any]]
    error: str | None = None


_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=0.5, read=1.5, write=0.5, pool=0.5),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    http2=True,
    headers={"User-Agent": "devops-wiki-search/1.0"},
)
```

## Source Adapters

Each upstream gets a thin async function returning `SourceResult`:

```python
async def search_mediawiki(q: str) -> SourceResult:
    try:
        r = await _client.get(
            "https://platformwiki.example/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": q,
                "format": "json",
                "srlimit": 20,
            },
            timeout=httpx.Timeout(1.0),
        )
        r.raise_for_status()
        hits = r.json().get("query", {}).get("search", [])
        return SourceResult(source="mediawiki", hits=hits)
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("mediawiki failure", extra={"error": str(e)})
        return SourceResult(source="mediawiki", hits=[], error=str(e))


async def search_discourse(q: str) -> SourceResult:
    try:
        r = await _client.get(
            "https://community.example/search.json",
            params={"q": q},
            timeout=httpx.Timeout(2.0),
        )
        r.raise_for_status()
        hits = r.json().get("topics", [])
        return SourceResult(source="discourse", hits=hits)
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("discourse failure", extra={"error": str(e)})
        return SourceResult(source="discourse", hits=[], error=str(e))


async def search_local_fts(q: str) -> SourceResult:
    # SQLite is sync — offload to thread so we don't block the event loop
    try:
        hits = await asyncio.to_thread(_sqlite_fts5_query, q)
        return SourceResult(source="local", hits=hits)
    except Exception as e:
        logger.warning("local fts failure", extra={"error": str(e)})
        return SourceResult(source="local", hits=[], error=str(e))
```

## Fan-Out with `gather`

The key is `return_exceptions=True` — one source failing must NOT cancel the others:

```python
async def search_all(q: str, budget: float = 1.8) -> list[SourceResult]:
    tasks = [
        search_mediawiki(q),
        search_discourse(q),
        search_local_fts(q),
    ]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=budget,
        )
    except asyncio.TimeoutError:
        logger.warning("overall budget exceeded", extra={"budget": budget})
        return []

    normalized: list[SourceResult] = []
    for name, res in zip(("mediawiki", "discourse", "local"), results):
        if isinstance(res, BaseException):
            normalized.append(SourceResult(source=name, hits=[], error=repr(res)))
        else:
            normalized.append(res)
    return normalized
```

**Why `return_exceptions=True`**: without it, the first exception cancels the whole `gather`, losing partial progress from other sources.

**Why each adapter already catches**: belt-and-suspenders. Adapters return `SourceResult(error=...)` for known failures; `gather` catches unknown failures (e.g. `CancelledError`, `asyncio.TimeoutError` from per-call override).

## Aggregation & Merge

Merge results for the API response, preserving which source failed:

```python
def build_response(results: list[SourceResult]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    warnings: list[str] = []
    for r in results:
        if r.error:
            warnings.append(f"{r.source}: {r.error}")
        else:
            hits.extend({**h, "_source": r.source} for h in r.hits)
    return {"hits": hits, "warnings": warnings, "count": len(hits)}
```

Relevance ranking across heterogeneous sources is a separate concern — v1 keeps per-source order and appends (see risk R4 in CLAUDE.md). Future: BM25-normalized merged score.

## FastAPI Endpoint

```python
from fastapi import FastAPI, Query

app = FastAPI()

@app.get("/search")
async def search(q: str = Query(..., min_length=2, max_length=200)) -> dict[str, Any]:
    results = await search_all(q)
    return build_response(results)
```

## Why Not `asyncio.as_completed`

`as_completed` streams results as they finish — useful for progressive UI. But FastAPI/Lambda returns a single JSON response, so buffering with `gather` is simpler and gives deterministic ordering.

If streaming JSON is ever needed (via SSE), switch to `as_completed` inside a generator.

## Testing the Fan-Out

See [patterns/mock-transport-testing.md](mock-transport-testing.md) — inject `MockTransport` to simulate each source failing independently and verify partial-success semantics.

## Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| `gather(...)` without `return_exceptions=True` | One slow 500 kills all results | Add the flag |
| Running sync SQLite in the event loop | Whole event loop stalls | `asyncio.to_thread(sync_fn, ...)` |
| Per-source timeout > overall budget | Outer `wait_for` trips first | Keep per-call ≤ 2 s, overall 1.8 s |
| Raising `HTTPException` inside adapters | `gather` cancels siblings | Return `SourceResult(error=...)` instead |

## Related

- [concepts/async-client-lifecycle.md](../concepts/async-client-lifecycle.md)
- [patterns/retry-with-backoff.md](retry-with-backoff.md)
- [patterns/mock-transport-testing.md](mock-transport-testing.md)
