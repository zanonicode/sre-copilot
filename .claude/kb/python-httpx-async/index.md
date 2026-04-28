# Python httpx Async Knowledge Base

> **Purpose**: Async `httpx` patterns for the DevOps Wiki `/search` aggregator — parallel fan-out to 3 sources (MediaWiki `api.php`, Discourse `/search.json`, local SQLite FTS5) with per-request timeouts, retries, and circuit breakers. Target runtime: AWS Lambda (Python 3.12, FastAPI + Mangum).
> **MCP Validated**: 2026-04-23

## Why Async httpx

- **Native async** — works with FastAPI + asyncio without thread pools
- **HTTP/2 + connection pooling** — amortizes TLS cost across Lambda warm invocations
- **Granular timeouts** — separate connect / read / write / pool budgets
- **Testable** — `httpx.MockTransport` simulates each upstream source without network
- **No wrappers** — raw client against MediaWiki / Discourse for full control

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/async-client-lifecycle.md](concepts/async-client-lifecycle.md) | `AsyncClient` reuse, connection pools, Lambda warm-container reuse |
| [concepts/timeouts-and-cancellation.md](concepts/timeouts-and-cancellation.md) | Per-phase timeouts, `asyncio.wait_for`, Task cancellation |
| [concepts/retry-and-circuit-breaker.md](concepts/retry-and-circuit-breaker.md) | Exponential backoff + jitter, idempotency, breaker states |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/parallel-fanout.md](patterns/parallel-fanout.md) | `asyncio.gather(return_exceptions=True)` across 3 sources, partial success |
| [patterns/retry-with-backoff.md](patterns/retry-with-backoff.md) | Retry decorator with jitter, Powertools logger integration |
| [patterns/mock-transport-testing.md](patterns/mock-transport-testing.md) | pytest fixtures using `httpx.MockTransport` per source |

### Quick Reference

- [quick-reference.md](quick-reference.md) — one-page cheat sheet

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **AsyncClient** | `httpx.AsyncClient` — persistent connection pool, created once per Lambda container |
| **Timeout** | `httpx.Timeout(connect=, read=, write=, pool=)` — per-phase budgets |
| **Fan-out** | `asyncio.gather(*coros, return_exceptions=True)` — parallel calls, partial failure tolerated |
| **Budget** | Overall deadline (e.g. 1.8 s) enforced via `asyncio.wait_for` — keeps P95 < 2 s |
| **Breaker** | In-memory state (`CLOSED` / `OPEN` / `HALF_OPEN`) to skip dead sources |
| **MockTransport** | `httpx.MockTransport(handler)` — injects canned responses in tests |

---

## Usage in the Aggregator

```text
   /search?q=…
        │
        ▼
  ┌─────────────────────────────┐
  │  asyncio.gather (budget=1.8s)│
  └──┬──────────┬──────────┬────┘
     │          │          │
  MediaWiki  Discourse   SQLite FTS5
  (httpx)    (httpx)     (thread)
     │          │          │
     ▼          ▼          ▼
   retry+breaker    (local, fast)
```

Each upstream call: `timeout → retry → breaker → gather`. Partial results are returned to the caller; failed sources surface as warnings in the response payload.

---

## Agent Usage

| Agent | Files | Use Case |
|-------|-------|----------|
| `python-lambda-developer` | all patterns | `/search` endpoint fan-out |
| `mediawiki-api-specialist` | patterns/parallel-fanout.md, patterns/retry-with-backoff.md | Platform Wiki client |
| `discourse-api-specialist` | patterns/parallel-fanout.md, patterns/retry-with-backoff.md | o9 Community client |
| `test-generator` | patterns/mock-transport-testing.md | Unit tests for clients |

---

## Related KBs

| Topic | Path |
|-------|------|
| FastAPI on Lambda | `../fastapi-lambda/` |
| MediaWiki client | `../mediawiki-api/` |
| Discourse client | `../discourse-api/` |
| SQLite FTS5 (local source) | `../sqlite-fts5/` |
