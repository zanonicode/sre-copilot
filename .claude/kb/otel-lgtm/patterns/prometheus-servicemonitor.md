# Prometheus + ServiceMonitor

> **Purpose**: Prometheus single-binary install + ServiceMonitor CRD pattern that the kube-prometheus-stack chart uses to discover scrape targets declaratively
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #30 (Prom replaces Mimir for kind)
- Sprint 3 entry #33 (backend ServiceMonitor)
- Whenever a new chart needs to be scraped

## Prometheus Helm Values

```yaml
# helm/observability/lgtm/prometheus-values.yaml
server:
  retention: 6h                                # short for kind
  resources:
    requests: { cpu: 200m, memory: 512Mi }
    limits:   { cpu: 1, memory: 1Gi }
  persistentVolume:
    enabled: false                             # ephemeral
  global:
    scrape_interval: 15s
    evaluation_interval: 15s
    external_labels:
      cluster: kind-sre-copilot

# Enable exemplar storage so Prom histograms can carry trace_id samples
extraArgs:
  enable-feature: "exemplar-storage,remote-write-receiver"

# Standard alerting rules + OUR rules loaded via ConfigMap
serverFiles:
  alerting_rules.yml:
    groups: []                                  # filled by separate Helm release
  recording_rules.yml:
    groups: []

alertmanager:
  enabled: true
  persistence: { enabled: false }
  resources:
    requests: { cpu: 50m, memory: 64Mi }
    limits:   { cpu: 200m, memory: 128Mi }

# Disable redundant exporters for kind
kube-state-metrics: { enabled: true }
prometheus-node-exporter: { enabled: true }
prometheus-pushgateway: { enabled: false }

# CRITICAL: enable ServiceMonitor CRD support (via prometheus-operator subchart)
# If using `prometheus-community/prometheus` chart, ServiceMonitor isn't native.
# For SRE Copilot we use `kube-prometheus-stack` instead — see note below.
```

> **Recommendation**: Switch to `kube-prometheus-stack` chart — it bundles Prom Operator (ServiceMonitor CRD), Prom, AM, Grafana. We disable the bundled Grafana to keep the standalone one. Memory footprint similar.

```yaml
# Alternative: kube-prometheus-stack-values.yaml (PREFERRED)
fullnameOverride: prometheus
crds:
  enabled: true
prometheus:
  prometheusSpec:
    retention: 6h
    resources:
      requests: { cpu: 200m, memory: 512Mi }
      limits:   { cpu: 1, memory: 1Gi }
    storageSpec: {}                            # ephemeral
    serviceMonitorSelectorNilUsesHelmValues: false      # match ANY ServiceMonitor
    enableFeatures: [exemplar-storage]
grafana: { enabled: false }                    # we run grafana separately
alertmanager:
  alertmanagerSpec:
    storage: {}
```

## ServiceMonitor for the Backend

```yaml
# helm/backend/templates/servicemonitor.yaml
{{- if .Values.servicemonitor.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "backend.fullname" . }}
  labels:
    {{- include "backend.labels" . | nindent 4 }}
    release: prometheus                              # MUST match Prom Operator selector
spec:
  selector:
    matchLabels: {{- include "backend.selectorLabels" . | nindent 6 }}
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
      honorLabels: true
{{- end }}
```

```yaml
# values.yaml
servicemonitor:
  enabled: true
```

## ServiceMonitor for the OTel Collector

The collector emits app metrics via its `prometheus` exporter on port 8889. Already configured in patterns/otel-collector-config.md (`serviceMonitor.enabled: true`).

This means there are TWO scrape sources for the same app:

1. Backend's own `/metrics` (FastAPI's middleware metrics, RED method)
2. OTel collector's `:8889/metrics` (the OTel SDK metrics — `llm_ttft_seconds`, etc.)

Both are useful. They produce different metric names — no conflict.

## Relabeling Cheats

```yaml
endpoints:
  - port: http
    relabelings:
      # Drop label
      - action: labeldrop
        regex: "container"
      # Rename namespace label
      - sourceLabels: [namespace]
        targetLabel: k8s_namespace
        action: replace
    metricRelabelings:
      # Drop a noisy metric entirely
      - sourceLabels: [__name__]
        regex: "go_gc_.*"
        action: drop
```

## Verification

```bash
# Are ServiceMonitors picked up?
kubectl get servicemonitor -A

# Active targets in Prom
kubectl port-forward -n observability svc/prometheus-operated 9090:9090
# → http://localhost:9090/targets

# Query a backend metric
curl 'http://prometheus-operated.observability:9090/api/v1/query?query=llm_ttft_seconds_count'
```

## Alerting Rules (PrometheusRule CRD)

For SRE Copilot, alert rules ship as separate `PrometheusRule` resources in `observability/alerts/` (DESIGN §3 entry #36):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: backend-slos
  namespace: observability
  labels:
    release: prometheus                              # picked up by Operator
spec:
  groups:
    - name: backend.availability
      rules:
        # ... see patterns/mwmbr-slo-alerts.md
```

## Common Issues

| Symptom | Fix |
|---------|-----|
| ServiceMonitor not scraped | Missing `release: prometheus` label OR `serviceMonitorSelectorNilUsesHelmValues` not set false |
| `up{job="backend"} == 0` | Pod has no `:8000/metrics` endpoint — install OTel Prom exporter or expose `/metrics` |
| Cardinality explosion | Check `prometheus_tsdb_head_series` — must stay < 100k for 1Gi limit |
| AlertManager not firing | Webhook misconfigured or `for:` too long for the test |

## See Also

- concepts/slo-burn-rate-math.md — what to alert on
- patterns/mwmbr-slo-alerts.md — full PrometheusRule
- patterns/grafana-sidecar-dashboards.md — datasource wiring
