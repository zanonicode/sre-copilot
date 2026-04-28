# OTel + LGTM Quick Reference

> **MCP Validated**: 2026-04-26

## OTLP Endpoints

| Protocol | Port | Path | When |
|----------|------|------|------|
| gRPC | 4317 | — | Default; lower overhead |
| HTTP/protobuf | 4318 | `/v1/{traces,metrics,logs}` | Browser, restrictive networks |

In-cluster collector URL: `http://otel-collector.observability.svc.cluster.local:4317`

## Standard Env Vars

```bash
OTEL_SERVICE_NAME=sre-copilot-backend
OTEL_RESOURCE_ATTRIBUTES=service.version=0.1.0,deployment.environment=kind-local
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.observability:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0          # 100% sample for kind/dev
OTEL_PYTHON_EXCLUDED_URLS=/healthz,/readyz,/metrics
```

## Python SDK Install

```bash
uv pip install \
  opentelemetry-api \
  opentelemetry-sdk \
  opentelemetry-exporter-otlp \
  opentelemetry-instrumentation-fastapi \
  opentelemetry-instrumentation-httpx \
  opentelemetry-instrumentation-logging
```

## LogQL (Loki) Cheats

```logql
# All backend errors with their trace_id
{service="backend", level="error"} | json

# Errors that have a trace, joined to Tempo
{service="backend"} |= "error" | json | trace_id != ""

# Rate of errors over 5m
sum by (service) (rate({service="backend", level="error"}[5m]))
```

## TraceQL (Tempo) Cheats

```traceql
{ service.name = "sre-copilot-backend" && status = error }
{ name = "ollama.host_call" && duration > 5s }
{ resource.deployment.environment = "kind-local" } | rate()
```

## PromQL (Prometheus) Cheats

```promql
# Backend p95 TTFT
histogram_quantile(0.95, sum by (le) (rate(llm_ttft_seconds_bucket[5m])))

# Backend error rate (5xx)
sum(rate(http_server_duration_count{service_name="sre-copilot-backend", http_status_code=~"5.."}[5m]))
  /
sum(rate(http_server_duration_count{service_name="sre-copilot-backend"}[5m]))

# Burn rate over 1h (vs SLO of 99% availability → error budget = 0.01)
(1 - (sum(rate(http_server_duration_count{...}[1h])) / sum(rate(...[1h])))) / 0.01
```

## Collector Pipelines (logical)

```text
RECEIVERS         PROCESSORS               EXPORTERS
otlp/grpc:4317  → batch                  → loki        (logs)
                  resource (env)         → otlp/tempo  (traces)
                  memory_limiter         → prometheus  (metrics, /metrics scrape)
```

## Helm Charts (versions tested)

| Chart | Repo | Version (2026-04) |
|-------|------|-------------------|
| `opentelemetry-collector` | open-telemetry | 0.108.x (mode: deployment) |
| `loki` | grafana | 6.x (singleBinary) |
| `tempo` | grafana | 1.x (single-binary monolithic) |
| `prometheus` | prometheus-community | 27.x |
| `grafana` | grafana | 8.x |

## Decision Tables

| Need | Choice |
|------|--------|
| Local kind, 16 GB Mac, ephemeral | Loki single-binary + Tempo monolithic + Prometheus (NOT Mimir) |
| Browser → backend trace continuity | W3C `traceparent` header + CORS expose-headers |
| Logs correlated to traces | JSON formatter injects `trace_id` + `span_id` from current span |
| Auto-load dashboards | grafana sidecar with label `grafana_dashboard=1` |
| Alert on SLO burn | MWMBR (14.4, 6, 1, 1) — see patterns/mwmbr-slo-alerts.md |

## SRE Copilot SLOs (from DESIGN §6)

| SLO | Target | Window | Burn alert |
|-----|--------|--------|------------|
| Availability | 99% (5xx < 1%) | 30d | MWMBR fast (5m/1h) + slow (30m/6h) |
| TTFT p95 | < 2.0s | 30d | Single-window 1h |
| Full response p95 | < 8.0s | 30d | Single-window 1h |
