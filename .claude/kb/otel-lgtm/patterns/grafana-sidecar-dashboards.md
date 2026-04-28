# Grafana Sidecar Auto-loaded Dashboards

> **Purpose**: Ship the 4 SRE Copilot dashboards as ConfigMaps that the Grafana sidecar discovers + provisions automatically — no manual import, no `gitops` for the dashboard JSON
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #35 (Overview, LLM Performance, Cluster Health, Cost & Capacity)
- Any time you want to ship a dashboard as code

## How the Sidecar Works

The Grafana Helm chart can run a `kiwigrid/k8s-sidecar` container that watches the cluster for ConfigMaps with a configured label, mounts their data into Grafana's provisioning directory, and triggers a hot-reload.

```text
ConfigMap (label: grafana_dashboard=1)
    ↓
sidecar mounts data/<key>.json into /tmp/dashboards/
    ↓
Grafana picks up via dashboards provider config
    ↓
Dashboard appears in UI under the configured folder
```

## Helm Values (Grafana)

```yaml
# helm/observability/lgtm/grafana-values.yaml
adminUser: admin
adminPassword: admin                                  # kind-only

resources:
  requests: { cpu: 50m, memory: 128Mi }
  limits:   { cpu: 200m, memory: 256Mi }

persistence: { enabled: false }
service:
  type: ClusterIP

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        uid: prometheus
        url: http://prometheus-operated.observability.svc:9090
        isDefault: true
      - name: Loki
        type: loki
        uid: loki
        url: http://loki.observability.svc:3100
      - name: Tempo
        type: tempo
        uid: tempo
        url: http://tempo.observability.svc:3100
        jsonData:
          tracesToLogsV2:
            datasourceUid: loki
            tags: [{ key: 'service.name', value: 'service' }]

# THE KEY PART: sidecar config
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard                         # ConfigMap label key
    labelValue: "1"
    folder: /tmp/dashboards
    folderAnnotation: grafana_folder                 # ConfigMap annotation drives folder
    provider:
      foldersFromFilesStructure: true
    searchNamespace: ALL                             # discover ConfigMaps in any ns
  datasources:
    enabled: true                                    # also auto-load datasource CMs

# IngressRoute (Traefik)
ingress:
  enabled: true
  ingressClassName: traefik
  hosts: [grafana.kind.local]
```

## Dashboard ConfigMap Pattern

```yaml
# observability/dashboards/overview-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dashboard-overview
  namespace: observability
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "SRE Copilot"
data:
  overview.json: |
    {
      "title": "SRE Copilot Overview",
      "uid": "sre-overview",
      "panels": [
        { "title": "Active LLM Requests", "type": "stat",
          "targets": [{ "expr": "sum(llm_active_requests)" }] },
        { "title": "TTFT p95 (s)", "type": "timeseries",
          "targets": [{ "expr": "histogram_quantile(0.95, sum by (le) (rate(llm_ttft_seconds_bucket[5m])))" }] },
        { "title": "Error Rate", "type": "timeseries",
          "targets": [{ "expr": "sum(rate(http_server_duration_count{http_status_code=~\"5..\"}[5m])) / sum(rate(http_server_duration_count[5m]))" }] }
      ]
    }
```

## The Four Dashboards (suggested panels)

### 1. Overview

- Active requests, error rate, TTFT p95, full-response p95 (RED + LLM-specific)
- Pod status by deployment
- Recent errors (Loki: `{service="backend", level="error"}`)

### 2. LLM Performance

- TTFT histogram heatmap
- Tokens per request (input vs output)
- Tokens/second throughput
- Model version label breakdown
- Trace exemplars on TTFT histogram → click to Tempo

### 3. Cluster Health

- Node CPU/RAM (kube-state-metrics)
- Pod restarts by namespace
- PVC usage (n/a — ephemeral)
- Network in/out per namespace

### 4. Cost & Capacity

- Request CPU/RAM vs limit per namespace
- Tokens/min × ~$0/$0 (model is local; $0 cost — placeholder for AWS migration)
- HPA replica count over time
- Headroom: `(node_capacity - sum(requests)) / node_capacity`

## Helm Templating Trick (load JSON from file)

If JSON gets large, do:

```yaml
data:
  overview.json: |
{{ .Files.Get "dashboards/overview.json" | indent 4 }}
```

Place `overview.json` next to `Chart.yaml`.

## Verification

```bash
kubectl port-forward -n observability svc/grafana 3001:80
# → http://admin:admin@localhost:3001
# → Folder "SRE Copilot" should contain 4 dashboards

# If missing: check sidecar logs
kubectl logs -n observability deploy/grafana -c grafana-sc-dashboard
```

## Common Issues

| Symptom | Fix |
|---------|-----|
| Dashboard doesn't appear | Wrong `grafana_dashboard: "1"` label, or `searchNamespace` doesn't include the CM's ns |
| Datasource broken in panel | Use `uid` reference (`prometheus`, `loki`, `tempo`), not name |
| JSON parse error | Validate with `jq < dashboard.json` before committing |
| Folder is "General" | Missing `grafana_folder` annotation |

## See Also

- patterns/prometheus-servicemonitor.md — what produces the metrics queried
- patterns/loki-single-binary-recipe.md — Loki datasource
- patterns/tempo-monolithic-recipe.md — Tempo datasource + tracesToLogs
