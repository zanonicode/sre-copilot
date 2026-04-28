# Tempo Monolithic Recipe (kind / 16 GB Mac)

> **Purpose**: Tempo single-binary monolithic Helm install — OTLP receiver, filesystem storage, ephemeral
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #30 (LGTM stack)
- Local kind only; for prod use `tempo-distributed` chart

## Helm Values

```yaml
# helm/observability/lgtm/tempo-values.yaml
tempo:
  resources:
    requests: { cpu: 100m, memory: 256Mi }
    limits:   { cpu: 500m, memory: 512Mi }

  storage:
    trace:
      backend: local
      local:
        path: /var/tempo/traces
      wal:
        path: /var/tempo/wal

  retention: 24h                              # ephemeral kind
  reportingEnabled: false

  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

  metricsGenerator:
    enabled: false                            # saves RAM; no service-graph in MVP

  global_overrides:
    max_search_duration: 1h
    metrics_generator_processors: []

persistence:
  enabled: false                              # emptyDir; trace data lost on Pod restart

service:
  type: ClusterIP

serviceMonitor:
  enabled: true
  labels: { release: prometheus }
```

## Helmfile Release

```yaml
- name: tempo
  namespace: observability
  chart: grafana/tempo
  version: ~1.10.0
  values:
    - ./helm/observability/lgtm/tempo-values.yaml
  needs: [platform/traefik]
```

## What This Gets You

- Single Pod listening on `:4317` (OTLP gRPC), `:4318` (OTLP HTTP), `:3100` (HTTP query API).
- Local filesystem storage in emptyDir.
- Service DNS: `tempo.observability.svc.cluster.local`
- 24h retention (sufficient for demo; rotates automatically).

## Wiring from OTel Collector

```yaml
# (in otel-collector values)
exporters:
  otlp/tempo:
    endpoint: tempo.observability.svc.cluster.local:4317
    tls: { insecure: true }
```

## Tempo Datasource (Grafana)

```yaml
datasources:
  - name: Tempo
    type: tempo
    url: http://tempo.observability.svc.cluster.local:3100
    uid: tempo
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        spanStartTimeShift: -5m
        spanEndTimeShift: 5m
        tags: [{ key: 'service.name', value: 'service' }]
        filterByTraceID: true
      tracesToMetrics:
        datasourceUid: prometheus
        tags: [{ key: 'service.name', value: 'service_name' }]
      serviceMap:
        datasourceUid: prometheus
      nodeGraph:
        enabled: true
      search:
        hide: false
      lokiSearch:
        datasourceUid: loki
```

## Query API

| Endpoint | Use |
|----------|-----|
| `GET /api/traces/{traceID}` | Fetch by ID (cheap) |
| `GET /api/search?tags=service.name=backend` | Tag search (limited) |
| `POST /api/v2/search` | TraceQL (`{ name="ollama.host_call" }`) |
| `GET /ready` | Readiness probe |

## Smoke Test

```bash
# Send via OTel collector (preferred)
curl -X POST http://otel-collector.observability:4318/v1/traces -d @sample-trace.json

# Direct to Tempo
curl -X POST http://tempo.observability:4318/v1/traces -d @sample-trace.json

# Fetch
curl http://tempo.observability:3100/api/traces/<trace_id> | jq '.batches[0].scopeSpans[0].spans[].name'
```

## Memory Notes

| Operation | Cost |
|-----------|------|
| Idle | ~150 Mi |
| Steady ingestion (10 traces/s) | ~250 Mi |
| TraceQL search across 1h block | spike to 400+ Mi |

If you OOM, drop retention to 12h and disable `metricsGenerator` (already done above).

## What We Cut for Scope

- **Service graph generation** (`metricsGenerator`) — would emit service-to-service edges as Prom metrics. Re-enable in v1.1.
- **Multi-tenant** — single tenant only; `auth_enabled: false`.
- **S3 backend** — would replace `local` for durability.

## See Also

- concepts/lgtm-stack-roles.md — Tempo theory
- patterns/otel-collector-config.md — exporter wiring
- patterns/python-fastapi-instrumentation.md — what produces the spans
