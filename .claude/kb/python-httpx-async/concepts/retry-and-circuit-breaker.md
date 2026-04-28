# Retry and Circuit Breaker

> When to retry, how to back off, and how to stop hammering a dead source.
> **MCP Validated**: 2026-04-23

## When to Retry

**Retry only idempotent operations.** All DevOps Wiki upstream calls are `GET`s — safe by definition. For any future `POST` / `PATCH`, default to no retry unless the server guarantees idempotency keys.

| Failure | Retry? | Why |
|---------|--------|-----|
| `httpx.ConnectError` | Yes | Transient DNS / TCP |
| `httpx.ConnectTimeout` | Yes | Server briefly overloaded |
| `httpx.ReadTimeout` (GET) | Yes | Slow response, safe to resend |
| `httpx.ReadTimeout` (POST) | **No** | May have been processed |
| `httpx.WriteTimeout` | No | Body half-sent, server state unknown |
| HTTP 500, 502, 503, 504 | Yes (max 2) | Upstream hiccup |
| HTTP 429 | Yes | Honor `Retry-After` header |
| HTTP 4xx (other) | No | Client error — fix the request |

## Exponential Backoff with Jitter

**Never** retry immediately — synchronized retries create thundering herds. Use exponential backoff **with jitter**:

```python
import random

def backoff_delay(attempt: int, base: float = 0.1, cap: float = 1.0) -> float:
    """Full-jitter exponential backoff."""
    exp = min(base * (2 ** attempt), cap)
    return random.uniform(0, exp)
```

| Attempt | Max delay | Typical delay (full jitter) |
|---------|-----------|------------------------------|
| 0 | 0.10 s | 0.00 – 0.10 s |
| 1 | 0.20 s | 0.00 – 0.20 s |
| 2 | 0.40 s | 0.00 – 0.40 s |
| 3 | 0.80 s | 0.00 – 0.80 s |

**Full jitter** (AWS Architecture Blog recommendation) spreads retries uniformly across the window — better than "equal jitter" for collision avoidance.

## Retry Budget vs Timeout Budget

Total time spent retrying must fit inside the overall fan-out budget (1.8 s). For 3 attempts with cap 1.0 s, worst-case backoff is ~1.4 s — too much. Cap lower or allow fewer attempts.

Recommended for this project: **max 2 attempts, cap 0.5 s**.

## Circuit Breaker — Why

A repeatedly-failing source wastes time, connection-pool slots, and retry budget. A breaker short-circuits calls to dead sources until they recover.

## Breaker States

```text
         ┌────────────┐
  ──────▶│  CLOSED    │  normal; count failures
         └─┬──────┬───┘
   failure │      │ success
   ≥ N     │      │
           ▼      │
         ┌────────┴───┐
         │   OPEN     │  reject all calls for `cooldown` s
         └─────┬──────┘
               │ cooldown elapsed
               ▼
         ┌────────────┐
         │ HALF_OPEN  │  allow one probe
         └─┬──────┬───┘
     success│      │failure
            ▼      ▼
         CLOSED   OPEN
```

| State | Behavior | Transition |
|-------|----------|-----------|
| `CLOSED` | All calls pass | ≥ N consecutive failures → `OPEN` |
| `OPEN` | Calls return synthetic empty immediately | `cooldown` elapses → `HALF_OPEN` |
| `HALF_OPEN` | Exactly one probe allowed | success → `CLOSED`, failure → `OPEN` |

## Recommended Thresholds

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Failure threshold `N` | 5 | Tolerate transient blips |
| Measurement window | 30 s | Short enough for fast recovery |
| Cooldown | 30 s | Give peer time to heal |
| Probe attempts in HALF_OPEN | 1 | Avoid flooding a half-healthy peer |

## In-Memory Only (Lambda-Appropriate)

A Lambda container holds breaker state in process memory. Across containers, each has its own state. That's fine for < 100 concurrent users:

- If one container decides a source is OPEN, others probe independently
- No shared state → no Redis dependency → no cold-start penalty

Cross-container coordination (e.g. via DynamoDB TTL) is **overkill** at this scale — skip it.

## Combining Retry + Breaker

Order matters: **breaker first, retry inside**:

```text
request → breaker.allow()? → retry_loop → httpx call
            │                     │
            └─ reject if OPEN     └─ records success/failure back to breaker
```

The breaker counts retry-exhausted failures, not individual attempts.

## Observability

Log state transitions (Powertools logger):

```python
logger.warning("breaker_opened", extra={"source": "mediawiki", "failures": 5})
logger.info("breaker_half_open", extra={"source": "mediawiki"})
logger.info("breaker_closed", extra={"source": "mediawiki"})
```

Emit a CloudWatch metric per transition to alert on persistent upstream failures.

## Summary

| Do | Don't |
|-----|------|
| Retry only idempotent GETs | Retry POSTs blindly |
| Full-jitter exponential backoff | Fixed delay |
| Cap total retry time < fan-out budget | Retry 5 times with 1 s cap |
| In-memory breaker per Lambda container | Build distributed breaker at this scale |

## Related

- [patterns/retry-with-backoff.md](../patterns/retry-with-backoff.md)
- [concepts/timeouts-and-cancellation.md](timeouts-and-cancellation.md)
