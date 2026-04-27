# ADR-006: Backend statelessness + per-request SSE (no sticky sessions, no Redis-backed session state)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — partially superseded in v1.6 (Redis removed entirely; statelessness retained) |
| **Date** | 2026-04-26 |

---

## Context

With 2 backend replicas behind a Service, any cross-request session state requires either (a) ingress sticky sessions, or (b) a shared store like Redis. Both add complexity and option (a) is incompatible with the canary-rollout story — sticky sessions strand users on a draining replica.

## Choice

Backend is **fully stateless**. Each SSE stream is bound to a single replica for its lifetime (a single TCP connection). No session ID. No cross-request server-side state.

Redis was originally intended as a future caching layer (not session state), but was removed entirely in v1.6 per YAGNI after the first reviewer asked "why is Redis here?" within hours of the build.

## Rationale

- Matches the canary story: any replica can serve any request mid-rollout; no drain coordination.
- Eliminates an entire category of bugs (session leaks, store consistency, TTL).
- SSE-per-TCP-connection is the right granularity: if a client reconnects, they start a new analysis — that's correct UX (analysis is cheap, idempotent, and re-running with the same input gives consistent-shaped output).

## Alternatives Rejected

1. **Ingress sticky sessions (Traefik affinity cookie).** Rejected: breaks canary; cookie pinning conflicts with traffic-weight shifts.
2. **Redis-backed session store.** Rejected: speculative; no MVP requirement needs cross-request server state.
3. **Keep Redis for future caching.** Rejected in v1.6: the "future caching" door was never opened, the apology docs were never written, and the 80 MB cost is real on a 16 GB Mac. YAGNI wins.

## Consequences

- Frontend must handle SSE reconnect gracefully (start a fresh analysis; do not attempt mid-stream resume).
- Backend Pods can be killed at any time without user-visible damage beyond the in-flight stream → makes AT-006 (PDB) easy to demonstrate.
- If/when prompt-result caching becomes a real demo requirement (e.g., "second click on the same Loghub sample returns sub-100ms"), re-introduce Redis or an in-memory LRU — it's a well-understood extension, not a rearchitecture.
