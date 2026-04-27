# ADR-003: Ollama on host via `ExternalName` Service (no in-cluster GPU containers)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

---

## Context

Apple Silicon GPUs are accessed through Metal Performance Shaders (MPS). MPS is **not** exposed inside Docker containers on macOS — there is no equivalent of `nvidia-container-runtime` for Metal. Running Ollama in the cluster would force CPU-only inference on Qwen 2.5 7B, which exceeds the 30-second p90 latency SLO by an order of magnitude.

## Choice

Run Ollama as a host process (started by `make seed-models` and `ollama serve`). Expose it into the cluster via a Kubernetes `Service` of `type: ExternalName` whose `externalName` field is `host.docker.internal`. Backend pods address it as `http://ollama.sre-copilot.svc.cluster.local:11434` — standard service-discovery code path, identical to what would target a vLLM Service in EKS.

## Rationale

- Native Metal acceleration is the only way to hit TTFT ≤2s p95 and full-response ≤30s p90 on this hardware.
- `ExternalName` keeps the application code production-shaped: the backend doesn't know "Ollama is on the host" — it just resolves a Service name. Migrating to in-cluster vLLM later is a Service swap, not a code change.
- This pattern mirrors a real-world topology where inference runs on GPU nodes managed separately from the application plane (different node pool, different lifecycle, different scaling).

## Alternatives Rejected

1. **In-cluster Ollama (CPU).** Rejected: violates latency SLOs; fans-out memory across container layers.
2. **In-cluster Ollama with hostNetwork + GPU passthrough.** Rejected: no GPU passthrough exists for Metal on macOS.
3. **Direct host URL hard-coded in backend (no Service).** Rejected: breaks the "production-shaped" invariant; every test would need env-var overrides; ADR loses its teaching moment.

## Consequences

- The `host.docker.internal` hop is the brittlest seam in the stack. Mitigated by: (a) `make smoke` healthcheck targeting Ollama through the Service, (b) explicit failure mode in AT-007, (c) NetworkPolicy explicitly *allows* this egress.
- OpenTelemetry cannot auto-instrument across the host hop. Mitigated by a **synthetic span** pattern — the backend emits a reconstructed `ollama.inference` span with start/end timestamps from chunk arrival times. See `src/backend/observability/spans.py`.
- A Linux fork of the project would need a different ADR — noted in the portability section of `docs/aws-migration.md`.
