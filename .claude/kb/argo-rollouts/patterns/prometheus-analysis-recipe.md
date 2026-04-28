# Prometheus AnalysisTemplate Recipe (DESIGN section 4.5)

> **Purpose**: The error-rate + p95-latency AnalysisTemplate that gates SRE Copilot's canary — verbatim from DESIGN section 4.5 with operational notes
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 4 entry #41 (`deploy/rollouts/analysis-templates/`)
- Referenced by the Rollout in patterns/rollout-from-deployment.md

## The Template (DESIGN section 4.5 verbatim)

```yaml
# deploy/rollouts/analysis-templates/backend-canary-health.yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: backend-canary-health
  namespace: sre-copilot
spec:
  args:
    - name: service-name
  metrics:
    - name: error-rate
      interval: 15s
      successCondition: result[0] < 0.05
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.observability.svc:9090
          query: |
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend",
                  http_status_code=~"5.."}[1m]))
            /
            sum(rate(http_server_duration_count{
                  service_name="sre-copilot-backend"}[1m]))
    - name: p95-latency
      interval: 15s
      successCondition: result[0] < 2.0
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.observability.svc:9090
          query: |
            histogram_quantile(0.95,
              sum by (le) (rate(llm_ttft_seconds_bucket[1m])))
```

## How It Behaves

- Every 15s, Argo runs both PromQL queries against Prometheus.
- `error-rate` must stay below 5%; `p95-latency` (TTFT) must stay below 2.0s.
- TWO consecutive failed measurements (~30s) on EITHER metric -> AnalysisRun Failed -> Rollout Degraded.
- Background analysis means this runs continuously through ALL canary steps (25 -> 50 -> 100).

## Why These Thresholds

| Metric | Threshold | Source |
|--------|-----------|--------|
| 5xx ratio < 5% | DESIGN section 6 SLO is 1%, but for a 1-minute window 5% is a reasonable canary cutoff (single-window decision vs MWMBR 30-day decision) |
| TTFT p95 < 2.0s | DESIGN section 6 SLO directly |

The canary threshold is intentionally LOOSER than the SLO target so transient spikes don't kill rollouts. The SLO alert (otel-lgtm KB -> patterns/mwmbr-slo-alerts.md) will catch sustained breaches separately.

## Refining: Add a Job-Level Smoke Check

```yaml
- name: smoke-test
  count: 1
  successCondition: result == "ok"
  provider:
    job:
      spec:
        template:
          spec:
            restartPolicy: Never
            containers:
              - name: smoke
                image: curlimages/curl:8.10.1
                command: [sh, -c]
                args:
                  - |
                    curl -fsS -X POST http://{{args.service-name}}.sre-copilot:8000/analyze/logs \
                      -H 'Content-Type: application/json' \
                      -d '{"log_payload":"test"}' && echo ok
```

This runs once at the gated step. Useful as a "the new version still serves SSE" check. Optional for SRE Copilot MVP — Prom queries already cover error rate.

## Wiring from the Rollout

```yaml
spec:
  strategy:
    canary:
      analysis:                                # background
        templates: [{ templateName: backend-canary-health }]
        startingStep: 1
        args:
          - name: service-name
            value: backend
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - analysis:                            # explicit gate
            templates: [{ templateName: backend-canary-health }]
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
```

## Helm-Templating the Template

If you want the AnalysisTemplate to live in the Helm chart (so namespace + service-name are derived):

```yaml
# helm/backend/templates/analysistemplate.yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: {{ include "backend.fullname" . }}-canary-health
spec:
  args:
    - name: service-name
      value: {{ include "backend.fullname" . }}
  metrics:
    - name: error-rate
      interval: 15s
      successCondition: result[0] < {{ .Values.canary.errorBudget }}
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.observability.svc:9090
          query: |
            sum(rate(http_server_duration_count{
                  service_name="{{ "{{args.service-name}}" }}",
                  http_status_code=~"5.."}[1m]))
            /
            sum(rate(http_server_duration_count{
                  service_name="{{ "{{args.service-name}}" }}"}[1m]))
```

Note the `{{ "{{args.service-name}}" }}` escaping: Helm needs to emit literal `{{args.service-name}}` for Argo's renderer.

## Verification

```bash
# Apply the template
kubectl apply -f deploy/rollouts/analysis-templates/backend-canary-health.yaml

# Trigger a Rollout (needs a previous revision)
kubectl argo rollouts set image backend backend=sre-copilot/backend:v2 -n sre-copilot

# Watch
kubectl argo rollouts get rollout backend -n sre-copilot --watch

# Inspect the AnalysisRun created at step 2 (the gated `analysis:` step)
kubectl get analysisrun -n sre-copilot
kubectl describe analysisrun <name>
```

## Failure Demonstration (for the demo)

To DELIBERATELY trigger an AnalysisRun failure during the screencast:

```bash
# Inject 5xx via the anomaly injector
curl -X POST http://backend.sre-copilot:8000/admin/inject \
  -H 'X-Token: devsecret' \
  -d '{"type":"force_500","percentage":50,"duration_seconds":120}'

# Then promote a new image
make demo-canary
# Within ~30s, AnalysisRun should fail and Rollout enters Degraded
kubectl argo rollouts undo backend -n sre-copilot
```

## See Also

- concepts/analysis-templates.md — template/run lifecycle
- patterns/abort-and-promote-flow.md — Degraded state recovery
- otel-lgtm KB -> patterns/mwmbr-slo-alerts.md — same metrics, longer windows
