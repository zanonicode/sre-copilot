# LGTM Stack Roles

> **Purpose**: Which signal lives where, what query language each speaks, and the cardinality rules that prevent OOM
> **MCP Validated**: 2026-04-26

## At a Glance

| Letter | Component | Stores | Query | Index Strategy |
|--------|-----------|--------|-------|----------------|
| L | Loki | Logs | LogQL | Index = LABELS only; payload is unindexed bytes |
| G | Grafana | Nothing — UI only | n/a | n/a |
| T | Tempo | Traces | TraceQL | Index = trace_id only (block-storage scan for content) |
| M | Mimir / Prometheus | Metrics | PromQL | Inverted index by label set |

> SRE Copilot substitutes Prometheus single-binary for Mimir to fit a 16 GB Mac. Same query language; smaller scale.

## Loki — Log Aggregation

**Mental model**: like Prometheus but for log lines. Labels (low cardinality) form the index; the log body is opaque. Search the body with `|=` substring or `| json` parser.

```logql
{service="backend", level="error"} |= "ollama"
{service="backend"} | json | trace_id != "" | line_format "{{.message}}"
```

**Cardinality rule (critical)**: NEVER make a label out of a high-cardinality value (request_id, user_id, span_id). Put those in the JSON body and parse at query time.

| Good labels | Bad labels |
|-------------|------------|
| service, level, namespace, env | trace_id, request_id, user_id, path |

**Storage modes**:
- `singleBinary` (SRE Copilot) — one process, filesystem storage, no S3
- `simpleScalable` — read/write/backend trio, S3-required
- `distributed` — full microservices

For kind: singleBinary with `persistence.enabled=false`.

## Tempo — Distributed Tracing

**Mental model**: trace storage indexed only by `trace_id`. Queries either fetch by ID (cheap) or scan blocks via TraceQL (expensive — limit by time window + service).

```traceql
{ service.name = "sre-copilot-backend" && status = error }
{ name = "ollama.host_call" && duration > 5s }
{ resource.deployment.environment = "kind-local" } | rate()
```

**Storage modes**:
- `monolithic` (SRE Copilot) — single binary, local filesystem
- `microservices` — distributor + ingester + querier + compactor

**Search-by-trace-id** is the dominant pattern; **TraceQL search** is for forensics. For SRE Copilot, the dashboards link `trace_id` from logs straight to Tempo's by-id endpoint.

## Prometheus — Metrics

**Mental model**: time series database, label-set indexed. PromQL operates on these series.

```promql
histogram_quantile(0.95, sum by (le) (rate(llm_ttft_seconds_bucket[5m])))
sum by (service) (rate(http_server_duration_count{http_status_code=~"5.."}[5m]))
```

**Cardinality rule**: every unique label combination = a new time series = RAM. Do NOT label by trace_id, request_id, user, full URL path. Use `path` only if templated (`/users/:id` not `/users/12345`).

For SRE Copilot:
- Backend exposes `/metrics` via OTel Prometheus exporter (or via OTel Collector :8889)
- Prometheus discovers via `ServiceMonitor` (kube-prometheus-stack CRD)
- Scrape interval: 15s
- Retention: 6h (kind-local; we don't need history)

## Grafana — UI Layer

Datasources (provisioned at install via Helm values):

```yaml
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.observability.svc:80
        isDefault: true
      - name: Loki
        type: loki
        url: http://loki.observability.svc:3100
      - name: Tempo
        type: tempo
        url: http://tempo.observability.svc:3100
        jsonData:
          tracesToLogsV2:
            datasourceUid: loki
            tags: [{ key: 'service.name', value: 'service' }]
          tracesToMetrics:
            datasourceUid: prometheus
```

The `tracesToLogsV2` link makes a trace span clickable → jump to the matching Loki query.

## The Correlation Triangle

```text
LOG ───── trace_id ─────► TRACE ──── service.name ────► METRIC
 ↑                          │                              │
 └─── line_format ──────────┘                              │
 ↑                                                         │
 └────────── exemplar (Prom histogram) ───────────────────┘
```

- Logs carry `trace_id` → click in Grafana → opens Tempo
- Traces carry `service.name` → "Trace to metrics" jumps to Prom
- Histograms can attach exemplars (a sample trace_id per bucket) — enable `--enable-feature=exemplar-storage` in Prometheus

## Memory Budget (kind on 16 GB Mac)

| Component | Req | Limit |
|-----------|-----|-------|
| Loki (singleBinary) | 256 Mi | 512 Mi |
| Tempo (monolithic) | 256 Mi | 512 Mi |
| Prometheus | 512 Mi | 1 Gi |
| Grafana | 128 Mi | 256 Mi |
| OTel Collector | 256 Mi | 512 Mi |
| **Subtotal** | **~1.4 Gi** | **~2.8 Gi** |

Plus apps + Traefik + control-plane: budget ~6 GB used / 14 GB available.

## See Also

- patterns/loki-single-binary-recipe.md
- patterns/tempo-monolithic-recipe.md
- patterns/prometheus-servicemonitor.md
- patterns/grafana-sidecar-dashboards.md
