# OTel Collector Config (SRE Copilot)

> **Purpose**: Lift-able Helm values for `opentelemetry-collector` chart in deployment mode — OTLP in, Loki/Tempo/Prometheus out
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #31 (`helm/observability/otel-collector/`)
- Companion to patterns/loki/tempo/prometheus recipes

## Helm Values

```yaml
# helm/observability/otel-collector/values.yaml
mode: deployment
replicaCount: 1
image:
  repository: otel/opentelemetry-collector-contrib   # contrib for loki exporter
  tag: 0.108.0

resources:
  requests: { cpu: 100m, memory: 256Mi }
  limits:   { cpu: 500m, memory: 512Mi }

ports:
  otlp:       { enabled: true, containerPort: 4317, servicePort: 4317, protocol: TCP }
  otlp-http:  { enabled: true, containerPort: 4318, servicePort: 4318, protocol: TCP }
  metrics:    { enabled: true, containerPort: 8889, servicePort: 8889, protocol: TCP }

config:
  receivers:
    otlp:
      protocols:
        grpc: { endpoint: 0.0.0.0:4317 }
        http: { endpoint: 0.0.0.0:4318, cors: { allowed_origins: ["*"] } }

  processors:
    memory_limiter:
      check_interval: 5s
      limit_percentage: 75
      spike_limit_percentage: 25
    batch:
      timeout: 5s
      send_batch_size: 1024
    resource:
      attributes:
        - key: deployment.environment
          value: kind-local
          action: upsert
    filter/healthz:
      traces:
        span:
          - 'attributes["http.target"] == "/healthz"'
          - 'attributes["http.target"] == "/metrics"'

  exporters:
    otlp/tempo:
      endpoint: tempo.observability.svc.cluster.local:4317
      tls: { insecure: true }
    loki:
      endpoint: http://loki.observability.svc.cluster.local:3100/loki/api/v1/push
    prometheus:
      endpoint: 0.0.0.0:8889
      const_labels:
        cluster: kind-sre-copilot
      resource_to_telemetry_conversion:
        enabled: true
    debug:
      verbosity: basic

  extensions:
    health_check: { endpoint: 0.0.0.0:13133 }

  service:
    extensions: [health_check]
    telemetry:
      logs: { level: info }
      metrics: { address: 0.0.0.0:8888 }
    pipelines:
      traces:
        receivers:  [otlp]
        processors: [memory_limiter, filter/healthz, resource, batch]
        exporters:  [otlp/tempo]
      metrics:
        receivers:  [otlp]
        processors: [memory_limiter, resource, batch]
        exporters:  [prometheus]
      logs:
        receivers:  [otlp]
        processors: [memory_limiter, resource, batch]
        exporters:  [loki]

# Make collector itself scrapeable by Prom (for self-observability)
serviceMonitor:
  enabled: true
  metricsEndpoints:
    - port: metrics
      interval: 15s
```

## Helmfile Release

```yaml
# helmfile.yaml (excerpt)
- name: otel-collector
  namespace: observability
  chart: open-telemetry/opentelemetry-collector
  values:
    - ./helm/observability/otel-collector/values.yaml
  needs:
    - observability/loki
    - observability/tempo
    - observability/prometheus
```

## Configuration Notes

| Setting | Why |
|---------|-----|
| `mode: deployment` | Single hub replica; not a per-node agent |
| `memory_limiter` first | Drop incoming if RAM > 75%; protects collector from OOM |
| `batch` last | Coalesce items into bigger batches (efficiency) |
| `filter/healthz` | Drop traces from health probes — they'd swamp Tempo |
| `prometheus` exporter on 8889 | Prometheus scrapes the collector for app metrics |
| `loki` endpoint | Push API path is `/loki/api/v1/push` — easy to typo |
| `tls: { insecure: true }` | Cluster-internal; we don't run mTLS in MVP |

## Verification

```bash
# Send a test trace via OTLP/HTTP
curl -X POST http://localhost:4318/v1/traces \
  -H 'Content-Type: application/json' \
  -d @- <<'EOF'
{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"test"}}]},
"scopeSpans":[{"spans":[{"traceId":"5b8aa5a2d2c872e8321cf37308d69df2","spanId":"051581bf3cb55c13",
"name":"test-span","kind":1,"startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000001000000000"}]}]}]}
EOF

# Confirm in Tempo
curl http://localhost:3100/api/traces/5b8aa5a2d2c872e8321cf37308d69df2

# Collector self-metrics
curl http://otel-collector.observability:8888/metrics | grep otelcol_processor
```

## NetworkPolicy (DESIGN §9.3)

The `default-deny` NetworkPolicy in observability namespace must allow:
- Ingress on 4317/4318 from `sre-copilot` namespace pods
- Ingress on 8889 from prometheus
- Egress to `loki:3100`, `tempo:4317`, no internet

## See Also

- concepts/collector-architecture.md — receiver/processor/exporter theory
- patterns/loki-single-binary-recipe.md, tempo-monolithic-recipe.md
- patterns/prometheus-servicemonitor.md — how Prom scrapes :8889
