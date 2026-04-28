# Python httpx Async Quick Reference

> Async `httpx` for the `/search` fan-out. Python 3.12 on AWS Lambda.

## Client Setup (module-level, reused across Lambda invocations)

```python
import httpx

client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=0.5, read=1.5, write=0.5, pool=0.5),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    http2=True,
    headers={"User-Agent": "devops-wiki-search/1.0"},
)
```

## Parallel Fan-Out

```python
import asyncio

async def search_all(q: str) -> list[dict]:
    results = await asyncio.gather(
        search_mediawiki(q),
        search_discourse(q),
        search_local_fts(q),
        return_exceptions=True,
    )
    return [r for r in results if not isinstance(r, Exception)]
```

## Timeout Budget (overall)

```python
try:
    return await asyncio.wait_for(search_all(q), timeout=1.8)
except asyncio.TimeoutError:
    return []  # caller handles partial/empty
```

## Timeouts Cheat Sheet

| Phase | Typical | Meaning |
|-------|---------|---------|
| `connect` | 0.5 s | TCP + TLS handshake |
| `read` | 1.5 s | Waiting for server response bytes |
| `write` | 0.5 s | Sending request body |
| `pool` | 0.5 s | Waiting for a free connection |

## Retry Decision Table

| Condition | Retry? |
|-----------|--------|
| `httpx.ConnectError` | Yes |
| `httpx.ReadTimeout` on GET | Yes |
| `httpx.ReadTimeout` on POST | **No** (not idempotent) |
| HTTP 5xx | Yes (max 2) |
| HTTP 429 | Yes, honor `Retry-After` |
| HTTP 4xx (other) | No |

## Backoff Formula

```python
import random
delay = min(base * (2 ** attempt), cap) + random.uniform(0, 0.25)
# base=0.1, cap=1.0 → 0.1, 0.2, 0.4, 0.8, 1.0
```

## Circuit Breaker States

| State | Behavior |
|-------|----------|
| `CLOSED` | Normal — count failures |
| `OPEN` | Short-circuit — return cached empty for `cooldown` seconds |
| `HALF_OPEN` | One probe — success → CLOSED, failure → OPEN |

Trip rule: 5 consecutive failures within 30 s → OPEN for 30 s.

## Testing with MockTransport

```python
def handler(req: httpx.Request) -> httpx.Response:
    if "mediawiki" in req.url.host:
        return httpx.Response(200, json={"query": {"search": []}})
    return httpx.Response(404)

client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
```

## Common Pitfalls

| Don't | Do |
|-------|-----|
| `async with httpx.AsyncClient()` per request | Create once at module import |
| `requests.get()` in async handler | Use `httpx.AsyncClient` (non-blocking) |
| Default 5 s `read` timeout | Set an explicit budget (≤ 2 s total) |
| Retry POSTs blindly | Only retry idempotent GETs |
| `asyncio.gather(...)` without `return_exceptions` | One slow source kills all |
