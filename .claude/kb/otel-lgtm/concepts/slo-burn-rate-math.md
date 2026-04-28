# SLO Burn-Rate Math

> **Purpose**: Why "alert when error rate > 1%" is wrong, and how multi-window multi-burn-rate (MWMBR) gives you fast-and-precise alerting
> **MCP Validated**: 2026-04-26

## The Setup

| Term | Definition |
|------|------------|
| **SLO** | Target — e.g., 99% availability over 30 days |
| **Error budget** | `1 - SLO` over the window — e.g., 1% = 0.01 |
| **Burn rate** | Rate of consuming the budget. `1.0` = budget will be exhausted exactly at end of window. `2.0` = exhausted at midpoint. |

## Burn Rate Formula

```text
burn_rate(window) = error_rate(window) / (1 - SLO)
```

- 99% SLO → 1% budget. Error rate of 2% → burn rate = 2.
- 99.9% SLO → 0.1% budget. Error rate of 1% → burn rate = 10.

## Why Single-Threshold Alerting Fails

| Strategy | Failure |
|----------|---------|
| "Alert if 1m error rate > 5%" | Tons of false positives from tiny outages; pages on noise |
| "Alert if 1h error rate > 1%" | Slow burns invisible; team paged after budget already gone |
| "Alert if total errors > 1000" | Doesn't scale with traffic; threshold drifts |

## MWMBR (Google SRE Workbook)

Use **two pairs of windows**: a fast pair (5m + 1h) for quick burns, a slow pair (30m + 6h) for slow burns. Within each pair, the SHORTER window confirms the LONGER one is real (debounce). The longer window sets the burn-rate threshold.

| Severity | Long window | Short window | Burn rate threshold | Budget consumed if sustained |
|----------|-------------|--------------|---------------------|------------------------------|
| Page (fast) | 1h | 5m | 14.4 | 2% in 1h |
| Page (slow) | 6h | 30m | 6 | 5% in 6h |
| Ticket (slow) | 24h | 2h | 3 | 10% in 24h |
| Ticket (slow) | 72h | 6h | 1 | 10% in 72h |

The numbers come from the time-to-detect / fraction-of-budget tradeoff in the SRE Workbook chapter.

## The Prometheus Recording Rules

```yaml
groups:
  - name: backend-availability-burn
    interval: 30s
    rules:
      # Atom: error rate over each window
      - record: backend:request_errors:ratio_rate5m
        expr: |
          sum(rate(http_server_duration_count{
                service_name="sre-copilot-backend",
                http_status_code=~"5.."}[5m]))
          /
          sum(rate(http_server_duration_count{
                service_name="sre-copilot-backend"}[5m]))
      - record: backend:request_errors:ratio_rate1h
        expr: |
          sum(rate(http_server_duration_count{
                service_name="sre-copilot-backend",
                http_status_code=~"5.."}[1h]))
          /
          sum(rate(http_server_duration_count{
                service_name="sre-copilot-backend"}[1h]))
      - record: backend:request_errors:ratio_rate30m
        expr: ...
      - record: backend:request_errors:ratio_rate6h
        expr: ...
```

## The Alert

```yaml
- alert: BackendAvailabilityBurnRateFast
  expr: |
    backend:request_errors:ratio_rate1h  > (14.4 * 0.01)
    and
    backend:request_errors:ratio_rate5m  > (14.4 * 0.01)
  for: 2m
  labels: { severity: page, slo: backend-availability }
  annotations:
    summary: "Backend burning availability budget fast (>14.4x)"
    runbook: "docs/runbooks/backend-pod-loss.md"

- alert: BackendAvailabilityBurnRateSlow
  expr: |
    backend:request_errors:ratio_rate6h  > (6 * 0.01)
    and
    backend:request_errors:ratio_rate30m > (6 * 0.01)
  for: 15m
  labels: { severity: page, slo: backend-availability }
```

The `and` between long and short windows enforces the debounce. The `for:` adds another small delay against transients.

## SRE Copilot's Three SLOs (DESIGN §6)

| SLO | Definition | Budget |
|-----|------------|--------|
| Availability | <1% 5xx on `/analyze/logs` + `/generate/postmortem` over 30d | 0.01 |
| TTFT | p95 < 2.0s over 30d | n/a (latency SLO — see below) |
| Full response | p95 < 8.0s over 30d | n/a |

For latency SLOs, "burn" is measured as the fraction of requests that VIOLATE the threshold:

```promql
# Bad-events ratio
sum(rate(llm_ttft_seconds_bucket{le="2.0"}[1h])) is "good";
"bad" = total - good
```

Then apply the same MWMBR table.

## What NOT To Do

- Don't alert on a single 1m window — too noisy.
- Don't alert on burn rate without the short-window debounce — flaps.
- Don't use a window shorter than 4× scrape interval — sampling noise dominates.
- Don't make burn-rate alerts have varying thresholds per service ad-hoc — pick a budget per service and stick to it.

## See Also

- patterns/mwmbr-slo-alerts.md — full SRE Copilot alert rules YAML
- patterns/prometheus-servicemonitor.md — what produces `http_server_duration_count`
- [SRE Workbook ch. Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/)
