# Loki Single-Binary Recipe (kind / 16 GB Mac)

> **Purpose**: Loki monolithic (`singleBinary`) Helm install for ephemeral local logs — no S3, no MinIO, filesystem-only
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #30 (LGTM stack)
- Local kind cluster on developer Mac (≤16 GB)
- For prod-like with persistence, swap to `simpleScalable` mode

## Helm Values

```yaml
# helm/observability/lgtm/loki-values.yaml
deploymentMode: SingleBinary

loki:
  auth_enabled: false                       # single-tenant kind
  commonConfig:
    replication_factor: 1
  storage:
    type: filesystem
  schemaConfig:
    configs:
      - from: 2024-01-01
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: index_
          period: 24h
  limits_config:
    retention_period: 24h                   # ephemeral; we don't keep history
    ingestion_rate_mb: 10
    ingestion_burst_size_mb: 20
    max_label_name_length: 1024
    max_label_value_length: 4096
    max_label_names_per_series: 30
  compactor:
    retention_enabled: true
    delete_request_store: filesystem
  pattern_ingester:
    enabled: false                          # save RAM

singleBinary:
  replicas: 1
  resources:
    requests: { cpu: 100m, memory: 256Mi }
    limits:   { cpu: 500m, memory: 512Mi }
  persistence:
    enabled: false                          # ephemeral; data lost on Pod restart

# Disable everything we don't need in monolithic mode
backend:  { replicas: 0 }
read:     { replicas: 0 }
write:    { replicas: 0 }
chunksCache:
  enabled: false
resultsCache:
  enabled: false
gateway:
  enabled: false                            # collector pushes directly to :3100

monitoring:
  selfMonitoring: { enabled: false, grafanaAgent: { installOperator: false } }
  serviceMonitor: { enabled: true, labels: { release: prometheus } }
  lokiCanary:     { enabled: false }

test:
  enabled: false
```

## Helmfile Release

```yaml
- name: loki
  namespace: observability
  chart: grafana/loki
  version: ~6.0.0
  values:
    - ./helm/observability/lgtm/loki-values.yaml
  needs: [platform/traefik]
```

## What This Gets You

- Single Pod listening on `:3100` for both push (HTTP `/loki/api/v1/push`) and query (HTTP `/loki/api/v1/query_range`).
- Filesystem storage in the Pod's emptyDir — wiped on Pod restart (acceptable for kind).
- Service DNS: `loki.observability.svc.cluster.local:3100`
- ServiceMonitor for Prometheus self-observability.

## Wiring from OTel Collector

```yaml
# (in otel-collector values)
exporters:
  loki:
    endpoint: http://loki.observability.svc.cluster.local:3100/loki/api/v1/push
```

The collector's `loki` exporter converts OTLP log records to Loki push format. Resource attributes become labels (be careful — see cardinality below).

## Cardinality Discipline (CRITICAL)

The OTel→Loki exporter promotes Resource attributes to Loki labels by default. Limit which ones:

```yaml
exporters:
  loki:
    endpoint: http://loki...
    default_labels_enabled:
      exporter: false
      job: true
      instance: false
      level: true
```

Or explicitly via attribute hints in the SDK. NEVER label by trace_id, request_id, user_id — those go in the body and are queried via `| json`.

## Loki Datasource (Grafana)

```yaml
datasources:
  - name: Loki
    type: loki
    url: http://loki.observability.svc.cluster.local:3100
    jsonData:
      derivedFields:
        - name: trace_id
          matcherRegex: "trace_id=(\\w+)"
          url: '$${__value.raw}'
          datasourceUid: tempo
```

Now Loki query results render `trace_id=abc123` as a clickable link to Tempo.

## Smoke Test

```bash
# Push a test log
curl -H "Content-Type: application/json" -X POST \
  http://loki.observability:3100/loki/api/v1/push \
  -d '{"streams":[{"stream":{"service":"test"},"values":[["1700000000000000000","hello"]]}]}'

# Query
curl -G http://loki.observability:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service="test"}' \
  --data-urlencode 'start=1700000000000000000' \
  --data-urlencode 'end=1700000010000000000'
```

## Memory Behavior

| Concern | Notes |
|---------|-------|
| Boot memory | ~150 Mi |
| Steady (low traffic) | ~250 Mi |
| Burst (10 Mi/s ingest) | up to 500 Mi |
| OOM trigger | high-cardinality labels (most common) |

If you blow the limit, check: `loki_distributor_streams_total{tenant="fake"}` — should be < 1000 on kind.

## See Also

- concepts/lgtm-stack-roles.md — Loki storage + cardinality theory
- patterns/otel-collector-config.md — exporter wiring
- patterns/grafana-sidecar-dashboards.md — datasource provisioning
