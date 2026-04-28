# MWMBR SLO Alerts (PrometheusRule)

> **Purpose**: Lift-able PrometheusRule for SRE Copilot's three SLOs — availability, TTFT, full-response — with multi-window multi-burn-rate alerts (Google SRE Workbook)
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #36 (`observability/alerts/`)
- Read concepts/slo-burn-rate-math.md first for the math

## SLO Targets (DESIGN §6)

| SLO | Target | Window | Budget |
|-----|--------|--------|--------|
| Availability | 99% (5xx ratio < 1%) | 30d | 0.01 |
| TTFT | p95 < 2.0s | 30d | (latency SLO) |
| Full response | p95 < 8.0s | 30d | (latency SLO) |

## The Recording Rules

```yaml
# observability/alerts/recording-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: backend-slo-recordings
  namespace: observability
  labels: { release: prometheus }
spec:
  groups:
    - name: backend.slo.recordings
      interval: 30s
      rules:
        # Availability: error ratio over multiple windows
        - record: backend:availability:error_ratio_5m
          expr: |
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend",
                  http_status_code=~"5.."}[5m]))
            /
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend"}[5m]))
        - record: backend:availability:error_ratio_30m
          expr: |
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend",
                  http_status_code=~"5.."}[30m]))
            /
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend"}[30m]))
        - record: backend:availability:error_ratio_1h
          expr: |
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend",
                  http_status_code=~"5.."}[1h]))
            /
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend"}[1h]))
        - record: backend:availability:error_ratio_6h
          expr: |
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend",
                  http_status_code=~"5.."}[6h]))
            /
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend"}[6h]))

        # TTFT bad-events ratio (>2s = bad)
        - record: backend:ttft:bad_ratio_5m
          expr: |
            (
              sum(rate(llm_ttft_seconds_count[5m]))
              -
              sum(rate(llm_ttft_seconds_bucket{le="2.0"}[5m]))
            ) / sum(rate(llm_ttft_seconds_count[5m]))
        - record: backend:ttft:bad_ratio_1h
          expr: |
            (
              sum(rate(llm_ttft_seconds_count[1h]))
              -
              sum(rate(llm_ttft_seconds_bucket{le="2.0"}[1h]))
            ) / sum(rate(llm_ttft_seconds_count[1h]))

        # Full-response bad-events ratio (>8s = bad)
        - record: backend:response:bad_ratio_5m
          expr: |
            (
              sum(rate(llm_response_seconds_count[5m]))
              -
              sum(rate(llm_response_seconds_bucket{le="8.0"}[5m]))
            ) / sum(rate(llm_response_seconds_count[5m]))
        - record: backend:response:bad_ratio_1h
          expr: |
            (
              sum(rate(llm_response_seconds_count[1h]))
              -
              sum(rate(llm_response_seconds_bucket{le="8.0"}[1h]))
            ) / sum(rate(llm_response_seconds_count[1h]))
```

## The Alert Rules

```yaml
# observability/alerts/alert-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: backend-slo-alerts
  namespace: observability
  labels: { release: prometheus }
spec:
  groups:
    # === AVAILABILITY (MWMBR pair: fast 5m+1h, slow 30m+6h) ===
    - name: backend.availability.alerts
      rules:
        - alert: BackendAvailabilityBurnFast
          expr: |
            backend:availability:error_ratio_1h > (14.4 * 0.01)
            and
            backend:availability:error_ratio_5m > (14.4 * 0.01)
          for: 2m
          labels: { severity: page, slo: availability, burn: fast }
          annotations:
            summary: "Backend burning availability budget fast (>14.4× over 1h)"
            description: "5xx ratio sustained > 14.4% across 1h and 5m. Will exhaust 30d budget in <2 days."
            runbook_url: "docs/runbooks/backend-pod-loss.md"

        - alert: BackendAvailabilityBurnSlow
          expr: |
            backend:availability:error_ratio_6h > (6 * 0.01)
            and
            backend:availability:error_ratio_30m > (6 * 0.01)
          for: 15m
          labels: { severity: page, slo: availability, burn: slow }
          annotations:
            summary: "Backend burning availability budget slowly (>6× over 6h)"
            description: "5xx ratio sustained > 6% across 6h and 30m. Will exhaust 30d budget in ~5 days."
            runbook_url: "docs/runbooks/backend-pod-loss.md"

    # === TTFT (single-window for latency) ===
    - name: backend.ttft.alerts
      rules:
        - alert: BackendTTFTBurn
          expr: |
            backend:ttft:bad_ratio_1h > (6 * 0.05)
            and
            backend:ttft:bad_ratio_5m > (6 * 0.05)
          for: 5m
          labels: { severity: page, slo: ttft }
          annotations:
            summary: "TTFT >2s for >30% of requests over 1h (6× burn vs 5% allowance)"
            description: "Likely Ollama model swap or host RAM pressure — check ollama process on host"
            runbook_url: "docs/runbooks/ollama-host-down.md"

    # === FULL RESPONSE (single-window for latency) ===
    - name: backend.response.alerts
      rules:
        - alert: BackendResponseBurn
          expr: |
            backend:response:bad_ratio_1h > (6 * 0.05)
            and
            backend:response:bad_ratio_5m > (6 * 0.05)
          for: 5m
          labels: { severity: page, slo: full_response }
          annotations:
            summary: "Full-response p95 >8s for >30% of requests over 1h"
            description: "Likely token-generation slowdown; check Tempo for ollama.inference span durations"
            runbook_url: "docs/runbooks/ollama-host-down.md"

    # === SUPPORT: Pod-level ===
    - name: backend.pods
      rules:
        - alert: BackendPodCrashLoop
          expr: |
            rate(kube_pod_container_status_restarts_total{pod=~"backend-.*"}[10m]) > 0
          for: 5m
          labels: { severity: warning }
          annotations:
            summary: "Backend pod {{ $labels.pod }} restarting"
        - alert: BackendNoReplicas
          expr: |
            kube_deployment_status_replicas_available{deployment="backend"} == 0
          for: 1m
          labels: { severity: page }
          annotations:
            summary: "Backend has zero available replicas"
```

## Burn-Rate Threshold Math

```text
Availability:
  budget = 1 - 0.99 = 0.01
  fast page  → 14.4 × 0.01 = 14.4% error rate over 1h confirmed by 5m
  slow page  →  6   × 0.01 =  6%   error rate over 6h confirmed by 30m

TTFT (5% allowance for >2s = "bad event budget"):
  fast burn → 6 × 0.05 = 30% bad over 1h confirmed by 5m
```

## Verification

```bash
# Synthetic burn (load test injecting 5xx)
hey -n 1000 -c 10 -m POST -T 'application/json' \
  -d '{"force_500": true}' http://backend.sre-copilot/analyze/logs

# Watch the recording
kubectl exec -n observability prometheus-prometheus-0 -- \
  promtool query instant http://localhost:9090 \
    'backend:availability:error_ratio_5m'

# Wait 2m for fast alert
kubectl get prometheusrule backend-slo-alerts -o yaml
```

## What We Cut for Scope

- 24h and 72h ticket-grade alerts (SRE Workbook full table) — adds noise on a demo cluster.
- Alertmanager routing config (PagerDuty, Slack) — out of scope for kind MVP.

## See Also

- concepts/slo-burn-rate-math.md — derivation of 14.4 / 6
- patterns/prometheus-servicemonitor.md — what produces the metrics
- argo-rollouts KB → patterns/prometheus-analysis-recipe.md — same metrics, different consumer
