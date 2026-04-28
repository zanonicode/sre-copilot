# Timeouts and Cancellation

> Per-phase `httpx` timeouts plus `asyncio` cancellation semantics that keep `/search` under the 2 s P95 budget.
> **MCP Validated**: 2026-04-23

## Four Phases, Four Budgets

`httpx.Timeout` exposes four independent timers:

| Phase | What it covers | Fires when |
|-------|----------------|------------|
| `connect` | DNS + TCP + TLS handshake | Server unreachable / slow handshake |
| `read` | Time between received bytes | Server accepted but stalled mid-response |
| `write` | Time between sent bytes | Uploading a large body and peer window shrinks |
| `pool` | Waiting for a free connection from the pool | All `max_connections` busy |

```python
import httpx

timeout = httpx.Timeout(connect=0.5, read=1.5, write=0.5, pool=0.5)
client = httpx.AsyncClient(timeout=timeout)
```

**Default** (`httpx.Timeout(5.0)`) applies 5 s to all four phases — too slow for a 2 s P95 target.

## Per-Request Override

Pass `timeout=` on individual calls to adjust tight budgets:

```python
# Tight budget for MediaWiki (typically fast)
r = await client.get(mw_url, params=p, timeout=httpx.Timeout(1.0))

# Looser for Discourse (occasionally slow full-text search)
r = await client.get(dc_url, params=p, timeout=httpx.Timeout(2.0))
```

## What Timeout Raises

| Phase | Exception |
|-------|-----------|
| `connect` | `httpx.ConnectTimeout` |
| `read` | `httpx.ReadTimeout` |
| `write` | `httpx.WriteTimeout` |
| `pool` | `httpx.PoolTimeout` |

All subclass `httpx.TimeoutException`. Catch the base when handling uniformly:

```python
try:
    r = await client.get(url)
except httpx.TimeoutException as e:
    logger.warning("upstream timeout", extra={"url": url, "phase": type(e).__name__})
    return []
```

## Overall Budget via `asyncio.wait_for`

Per-request timeouts guard each HTTP call. For the aggregated fan-out, wrap the whole `gather` in an outer deadline:

```python
import asyncio

try:
    results = await asyncio.wait_for(
        asyncio.gather(mw_task, dc_task, fts_task, return_exceptions=True),
        timeout=1.8,
    )
except asyncio.TimeoutError:
    results = []  # nothing finished in 1.8 s
```

If the outer `wait_for` fires, `asyncio` **cancels** the inner tasks. `httpx` respects cancellation and aborts in-flight sockets.

## Cancellation Semantics

When an asyncio Task is cancelled, `CancelledError` is raised **inside** the coroutine at the next `await`. In `httpx`, this means:

1. Any in-flight socket read / write is aborted
2. The connection is returned to the pool (or closed if mid-stream)
3. The coroutine must propagate `CancelledError` — do NOT swallow it

```python
# ❌ Broken — swallows cancellation
async def bad_search(q: str) -> list:
    try:
        r = await client.get(url, params={"q": q})
        return r.json()
    except Exception:  # catches CancelledError too!
        return []

# ✅ Correct — re-raise cancellation
async def good_search(q: str) -> list:
    try:
        r = await client.get(url, params={"q": q})
        return r.json()
    except asyncio.CancelledError:
        raise
    except httpx.HTTPError:
        return []
```

In Python 3.8+, `CancelledError` inherits from `BaseException`, so `except Exception:` skips it — but be explicit.

## Interaction with Retries

A retry loop must check cancellation between attempts, otherwise a cancelled request keeps retrying after its Task was killed:

```python
for attempt in range(3):
    if asyncio.current_task().cancelled():
        raise asyncio.CancelledError
    try:
        return await client.get(url)
    except httpx.ReadTimeout:
        await asyncio.sleep(backoff(attempt))
```

Easier: use `async def` with natural `await asyncio.sleep` — cancellation fires at the sleep.

## Shielding (rare, use carefully)

`asyncio.shield(coro)` protects a coroutine from the outer `wait_for` cancellation. Useful only for idempotent cleanup; almost never for upstream HTTP.

## Summary

| Do | Don't |
|-----|------|
| Set all four phases of `httpx.Timeout` explicitly | Rely on 5 s default |
| Wrap fan-out in `asyncio.wait_for(..., timeout=budget)` | Trust per-request timeouts alone |
| Re-raise `CancelledError` | Catch `Exception` without filtering |
| Keep total budget < SLA (e.g. 1.8 s for 2 s P95) | Set budget equal to SLA |

## Related

- [concepts/retry-and-circuit-breaker.md](retry-and-circuit-breaker.md)
- [patterns/parallel-fanout.md](../patterns/parallel-fanout.md)
