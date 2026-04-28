# OTel Collector Architecture

> **Purpose**: The collector is the routing hub — receives OTLP from apps, processes, fans out to Loki/Tempo/Prometheus
> **MCP Validated**: 2026-04-26

## Three-Stage Pipeline

```text
Receivers → Processors → Exporters
   ↑           ↑             ↑
   what       transform     where
   comes in   / filter      it goes
```

A "pipeline" is a named (`traces`, `metrics`, `logs`) wiring of these three. You can have multiple pipelines per signal.

## Components

### Receivers

| Receiver | What |
|----------|------|
| `otlp` | Native OTLP (gRPC :4317, HTTP :4318) — primary input |
| `prometheus` | Scrape Prom-format `/metrics` endpoints |
| `filelog` | Tail container log files |
| `kubeletstats` | Pull node/pod metrics from kubelet API |

For SRE Copilot we use `otlp` only (Loki ingests logs via its own Promtail, Prometheus scrapes via ServiceMonitor — see ADR notes).

### Processors

Run in declared order per pipeline.

| Processor | Purpose |
|-----------|---------|
| `memory_limiter` | Drop data when collector RAM exceeds threshold (FIRST in chain) |
| `batch` | Buffer items into batches before exporting (LAST in chain) |
| `resource` | Add/modify Resource attributes (`deployment.environment=kind-local`) |
| `attributes` | Add/modify span/log attributes |
| `filter` | Drop items by expression (e.g., exclude `/healthz` traces) |
| `tail_sampling` | Sample after the trace is complete (e.g., keep all errors) |

### Exporters

| Exporter | Target |
|----------|--------|
| `otlp` | Forward OTLP to another collector (or Tempo OTLP receiver) |
| `prometheus` | Expose `/metrics` for Prom to scrape (collector becomes a target) |
| `prometheusremotewrite` | Push metrics to a remote_write endpoint (Mimir, Cortex) |
| `loki` | Push logs to Loki HTTP push API |
| `debug` | Stdout — for triage |

## SRE Copilot Pipeline Wiring

```text
TRACES pipeline
  receivers:  [otlp]
  processors: [memory_limiter, resource, batch]
  exporters:  [otlp/tempo]                    # → Tempo OTLP receiver

METRICS pipeline
  receivers:  [otlp]
  processors: [memory_limiter, resource, batch]
  exporters:  [prometheus]                    # collector exposes :8889/metrics

LOGS pipeline (optional — we mostly use stdout → Promtail)
  receivers:  [otlp]
  processors: [memory_limiter, resource, batch]
  exporters:  [loki]
```

## Deployment Modes

| Mode | When |
|------|------|
| **Deployment** (1 replica) | SRE Copilot — single hub, all apps point at one Service |
| **DaemonSet** | Per-node node-local agent + central gateway pattern |
| **Sidecar** | One-collector-per-pod (rare; high overhead) |

For kind on a Mac: Deployment of 1 replica is enough. CPU/RAM budget: 100m / 256Mi req, 500m / 512Mi limit.

## Failure Modes

| Failure | Symptom | Mitigation |
|---------|---------|------------|
| Tempo down | Traces back up in collector buffer; eventual drop | `memory_limiter` + `batch` retry |
| Loki down | Same for logs | Same |
| Collector OOM | Whole observability stack stops | `memory_limiter` MUST be first processor |
| App can't reach collector | Backend logs `OTLP export failed` | Verify Service DNS + NetworkPolicy egress allow |

## Health + Observability (collector observing itself)

```yaml
service:
  telemetry:
    logs: { level: info }
    metrics:
      address: 0.0.0.0:8888              # collector's own internal metrics
  extensions: [health_check, pprof, zpages]

extensions:
  health_check:
    endpoint: 0.0.0.0:13133              # use as readiness probe
```

## Versioning

The collector ships in two distros: `core` (limited components) and `contrib` (everything). Use `contrib` for SRE Copilot — Loki exporter and tail_sampling processor are contrib-only.

The Helm chart `open-telemetry/opentelemetry-collector` defaults to contrib when `mode: deployment` and `image.repository: otel/opentelemetry-collector-contrib`.

## See Also

- patterns/otel-collector-config.md — full lift-able config
- concepts/lgtm-stack-roles.md — what each backend stores
- patterns/loki-single-binary-recipe.md, tempo-monolithic-recipe.md, prometheus-servicemonitor.md
