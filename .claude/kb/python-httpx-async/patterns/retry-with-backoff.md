# Pattern: Retry with Backoff

> Reusable async retry decorator with full-jitter exponential backoff and AWS Lambda Powertools logging. Wraps per-source `httpx` calls.
> **MCP Validated**: 2026-04-23

## Goal

Retry transient upstream failures (timeouts, 5xx, 429) without blocking the event loop, with observable state transitions, and within a bounded time budget.

## The Decorator

```python
from __future__ import annotations

import asyncio
import functools
import random
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

import httpx
from aws_lambda_powertools import Logger

logger = Logger()

P = ParamSpec("P")
R = TypeVar("R")

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


def _full_jitter(attempt: int, base: float, cap: float) -> float:
    exp = min(base * (2 ** attempt), cap)
    return random.uniform(0, exp)


def retry_http(
    *,
    max_attempts: int = 2,
    base_delay: float = 0.1,
    cap_delay: float = 0.5,
    source: str = "unknown",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Retry decorator for idempotent async httpx calls."""

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: BaseException | None = None
            for attempt in range(max_attempts + 1):
                try:
                    result = await fn(*args, **kwargs)
                    if isinstance(result, httpx.Response) and result.status_code in _RETRYABLE_STATUS:
                        retry_after = _parse_retry_after(result)
                        if attempt < max_attempts:
                            delay = retry_after or _full_jitter(attempt, base_delay, cap_delay)
                            logger.warning(
                                "http_retry",
                                extra={
                                    "source": source,
                                    "attempt": attempt,
                                    "status": result.status_code,
                                    "delay": round(delay, 3),
                                },
                            )
                            await asyncio.sleep(delay)
                            continue
                    return result
                except asyncio.CancelledError:
                    raise
                except _RETRYABLE_EXC as exc:
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    delay = _full_jitter(attempt, base_delay, cap_delay)
                    logger.warning(
                        "http_retry",
                        extra={
                            "source": source,
                            "attempt": attempt,
                            "error": type(exc).__name__,
                            "delay": round(delay, 3),
                        },
                    )
                    await asyncio.sleep(delay)
            logger.error(
                "http_retry_exhausted",
                extra={"source": source, "attempts": max_attempts + 1},
            )
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None  # HTTP-date form ignored; full jitter used instead
```

## Usage on a Source Adapter

Wrap the raw HTTP call — NOT the `SourceResult`-returning outer function (the outer catches to return partial failure; retry must see raw exceptions):

```python
@retry_http(max_attempts=2, cap_delay=0.5, source="mediawiki")
async def _mw_get(q: str) -> httpx.Response:
    return await _client.get(
        "https://platformwiki.example/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": q,
            "format": "json",
        },
        timeout=httpx.Timeout(1.0),
    )


async def search_mediawiki(q: str) -> SourceResult:
    try:
        r = await _mw_get(q)
        r.raise_for_status()
        return SourceResult(source="mediawiki", hits=r.json()["query"]["search"])
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return SourceResult(source="mediawiki", hits=[], error=str(e))
```

## Honoring `Retry-After`

Discourse emits `Retry-After` (seconds) on 429 throttling. The decorator parses it and sleeps exactly that long, bypassing jitter — the server has told us when it'll be ready.

MediaWiki's `api.php` uses the `Retry-After` header too on rate limits. Same behavior.

## Budget Math

With `max_attempts=2, base=0.1, cap=0.5`:

| Attempt | Max backoff | Cumulative worst-case |
|---------|-------------|-----------------------|
| 0 → 1 | 0.1 s | 0.1 s |
| 1 → 2 | 0.2 s | 0.3 s |

Plus 3 HTTP calls × 1.0 s timeout = 3.0 s upper bound. This EXCEEDS the 1.8 s fan-out budget, which is fine — the outer `asyncio.wait_for` cancels retries still in flight. Design: retries are opportunistic, not guaranteed.

## Integration with Circuit Breaker

Wrap the retry-decorated function with a breaker check. Simple sketch:

```python
import time
from dataclasses import dataclass

@dataclass
class Breaker:
    threshold: int = 5
    cooldown: float = 30.0
    failures: int = 0
    opened_at: float = 0.0

    def allow(self) -> bool:
        if self.failures < self.threshold:
            return True
        if time.monotonic() - self.opened_at > self.cooldown:
            self.failures = self.threshold - 1  # half-open probe
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures == self.threshold:
            self.opened_at = time.monotonic()
```

Call `breaker.allow()` before `_mw_get(q)`; record success/failure around it.

## Pitfalls

| Pitfall | Fix |
|---------|-----|
| Retrying POSTs | Restrict decorator to GET-only helpers |
| `except Exception:` swallows `CancelledError` | Re-raise it explicitly (the decorator does) |
| Synchronous `time.sleep` | Use `asyncio.sleep` — never block the loop |
| Uncapped exponential | Always set `cap_delay` |
