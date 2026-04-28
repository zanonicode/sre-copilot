# AsyncClient Lifecycle

> Why one long-lived `httpx.AsyncClient` per Lambda container beats per-request clients.
> **MCP Validated**: 2026-04-23

## The Problem with Per-Request Clients

```python
# ❌ Anti-pattern — creates a new connection pool on every request
async def search(q: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params={"q": q})
        return r.json()
```

Each `async with` block:

1. Allocates a fresh connection pool
2. Performs a full TCP + TLS handshake
3. Closes sockets on exit — no reuse

On MediaWiki + Discourse (both HTTPS), TLS handshake adds ~100–200 ms per source. Across 3 sources per request, that's ~400 ms of avoidable latency.

## The Lambda Warm-Container Model

AWS Lambda reuses Python process state across invocations ("warm containers"). Module-level globals persist. An `AsyncClient` created at import time survives across many `/search` requests:

```python
# handler.py
import httpx

_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=0.5, read=1.5, write=0.5, pool=0.5),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    http2=True,
)

async def lambda_handler(event: dict, context: object) -> dict:
    r = await _client.get("https://platformwiki.example/api.php", params={"q": event["q"]})
    return {"statusCode": 200, "body": r.text}
```

The first invocation pays TLS cost; subsequent invocations reuse keep-alive connections.

## Connection Pool Sizing

| Parameter | Meaning | Recommended |
|-----------|---------|-------------|
| `max_connections` | Total open sockets | 20 (per upstream × concurrency headroom) |
| `max_keepalive_connections` | Idle sockets kept warm | 10 |
| `keepalive_expiry` | Seconds before idle close | 5 (default) |

Under low scale (< 100 concurrent users, Lambda concurrency typically ≤ 10), defaults are generous. Don't over-tune.

## HTTP/2 — Optional but Cheap

`http2=True` multiplexes multiple requests over one TCP connection. MediaWiki servers typically support HTTP/2; Discourse does too. Falls back to HTTP/1.1 silently if the peer doesn't offer it.

Requires the `h2` extra: `pip install 'httpx[http2]'`.

## Shutdown Hook (optional)

Lambda doesn't guarantee a clean shutdown, but if a SIGTERM arrives, draining the pool avoids half-closed socket noise:

```python
import atexit, asyncio

def _close_client() -> None:
    try:
        asyncio.run(_client.aclose())
    except RuntimeError:
        pass  # event loop already closed

atexit.register(_close_client)
```

## Mixing FastAPI + Lambda

With FastAPI + Mangum, use the lifespan hook:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await _client.aclose()

app = FastAPI(lifespan=lifespan)
```

## Testing Consideration

Module-level clients make testing awkward — you can't easily inject a mock. Solution: expose a factory and let tests monkeypatch it.

```python
def get_client() -> httpx.AsyncClient:
    return _client

# In tests:
monkeypatch.setattr(module, "_client", mock_client)
```

See [patterns/mock-transport-testing.md](../patterns/mock-transport-testing.md) for the full pattern.

## Summary

| Do | Don't |
|-----|------|
| Create `AsyncClient` once at module import | `async with httpx.AsyncClient()` per call |
| Set explicit `timeout=` + `limits=` | Use library defaults (5 s read is too slow) |
| Enable `http2=True` for HTTPS upstreams | Force HTTP/1.1 unless debugging |
| Expose a factory for tests | Hardcode the global in every function |

## Related

- [concepts/timeouts-and-cancellation.md](timeouts-and-cancellation.md)
- [patterns/parallel-fanout.md](../patterns/parallel-fanout.md)
