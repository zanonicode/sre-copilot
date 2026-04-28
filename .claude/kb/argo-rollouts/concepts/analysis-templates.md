# AnalysisTemplate and AnalysisRun

> **Purpose**: How Argo Rollouts asks "is the canary healthy?" — the AnalysisTemplate CRD definition, the AnalysisRun lifecycle, success/failure conditions, and provider types
> **MCP Validated**: 2026-04-26

## Two Resources

| Resource | Role |
|----------|------|
| `AnalysisTemplate` | Reusable definition: which metrics, what thresholds, which provider |
| `AnalysisRun` | An instantiation of a template, scoped to one Rollout step or background analysis |

A Rollout REFERENCES templates (`templates: [{ templateName: ... }]`); the controller CREATES AnalysisRuns at the right time.

## Template Anatomy

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: { name: backend-canary-health }
spec:
  args:
    - name: service-name
    - name: prometheus-port
      value: "9090"
  metrics:
    - name: error-rate
      interval: 15s
      count: 4
      failureLimit: 2
      successCondition: result[0] < 0.05
      provider:
        prometheus:
          address: http://prometheus.observability.svc:{{args.prometheus-port}}
          query: |
            sum(rate(http_server_duration_count{
                  service_name="{{args.service-name}}",
                  http_status_code=~"5.."}[1m]))
            /
            sum(rate(http_server_duration_count{
                  service_name="{{args.service-name}}"}[1m]))
```

## Conditions (Success / Failure / Inconclusive)

For each measurement Argo evaluates against `result`:

| Condition | Result |
|-----------|--------|
| `successCondition` true | This measurement is "Successful" |
| `failureCondition` true | This measurement is "Failed" |
| Neither true | "Inconclusive" |

Per-metric tally:

- More than `failureLimit` failed measurements -> Metric Failed -> AnalysisRun Failed -> Rollout Degraded
- More than `inconclusiveLimit` inconclusive -> Metric Inconclusive
- All measurements done with no failure threshold breach -> Metric Successful

## Result Shape (Prometheus)

PromQL returns a vector. Argo passes its values as `result`:

| Query | result shape |
|-------|--------------|
| `histogram_quantile(0.95, ...)` (scalar) | `[0.83]` -> `result[0]` |
| `sum by(pod) (...)` (vector) | `[0.01, 0.02, 0.99]` -> need list comprehension |

For SRE Copilot we always reduce to a scalar in PromQL so `result[0] < 0.05` works.

## Where Analyses Run

### 1. Step-inline (gated checkpoint)

```yaml
strategy:
  canary:
    steps:
      - setWeight: 25
      - analysis:
          templates: [{ templateName: backend-canary-health }]
      - setWeight: 50
```

Step blocks until AnalysisRun finishes. Failure -> Rollout Degraded.

### 2. Background (continuous during all steps)

```yaml
strategy:
  canary:
    analysis:
      templates: [{ templateName: backend-canary-health }]
      startingStep: 1
    steps: [...]
```

Created at startingStep, runs continuously until rollout finishes or fails.

### 3. Pre-/Post-promotion (blueGreen only)

Outside SRE Copilot's canary scope.

## Providers (most useful)

| Provider | Purpose |
|----------|---------|
| `prometheus` | PromQL — SRE Copilot default |
| `datadog` | DD metrics queries |
| `web` | HTTP GET; result extracted via JSONPath |
| `job` | Run a K8s Job; success = exit 0 |
| `kubernetes` | Read object status (e.g., `.status.readyReplicas`) |

## ClusterAnalysisTemplate

For org-wide reusable templates across namespaces, use `ClusterAnalysisTemplate`. SRE Copilot is single-namespace so we stick with namespaced.

## Args + Templating

```yaml
analysis:
  templates: [{ templateName: backend-canary-health }]
  args:
    - name: service-name
      value: backend
```

Reference in template via `{{args.service-name}}` (Argo's own renderer, not Go templates).

## Status Inspection

```bash
kubectl get analysisrun -n sre-copilot
kubectl describe analysisrun backend-66cd8455-3 -n sre-copilot
```

## Common Issues

| Issue | Fix |
|-------|-----|
| `Inconclusive` (no data) | PromQL returns empty vector — usually wrong selector or freshly-deployed canary has no traffic yet |
| `Error: Post "...": no such host` | Wrong Prom address; verify `prometheus.observability.svc:9090` |
| Always Failed even when canary is fine | Check `failureLimit: 0` accidentally — even 1 fail kills it |
| Step ANALYSIS hangs | No `count` set -> runs forever; the step never completes |

## See Also

- patterns/prometheus-analysis-recipe.md — DESIGN section 4.5 verbatim
- patterns/abort-and-promote-flow.md — what happens when AnalysisRun fails
