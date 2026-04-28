# Argo Rollouts Quick Reference

> **MCP Validated**: 2026-04-26

## Install Controller (Helm)

```bash
helm upgrade --install argo-rollouts argo/argo-rollouts \
  -n platform --create-namespace \
  --set dashboard.enabled=true
```

## Install kubectl Plugin

```bash
brew install argoproj/tap/kubectl-argo-rollouts
# verify
kubectl argo rollouts version
```

## CLI Cheatsheet

| Command | Purpose |
|---------|---------|
| `kubectl argo rollouts get rollout backend -n sre-copilot` | Live status (default refreshes every 2s) |
| `kubectl argo rollouts get rollout backend -n sre-copilot --watch` | Stream status |
| `kubectl argo rollouts list rollouts -A` | All rollouts in cluster |
| `kubectl argo rollouts set image backend backend=sre-copilot/backend:v2 -n sre-copilot` | Trigger new revision |
| `kubectl argo rollouts promote backend -n sre-copilot` | Skip current pause / step (manual approval) |
| `kubectl argo rollouts promote backend --full -n sre-copilot` | Skip ALL remaining steps → 100% |
| `kubectl argo rollouts abort backend -n sre-copilot` | Halt rollout, do NOT roll back |
| `kubectl argo rollouts undo backend -n sre-copilot` | Roll back to previous revision |
| `kubectl argo rollouts retry rollout backend -n sre-copilot` | Re-attempt after `Degraded` state |
| `kubectl argo rollouts status backend -n sre-copilot` | One-shot status, exits 0 when Healthy |

## Rollout Phases

```text
Healthy → (image change) → Progressing → (step pauses + analyses) → Healthy
                                       ↘ AnalysisRun fails → Degraded
                                       ↘ user abort        → Paused
```

## CRD Field Map (canary strategy)

```yaml
spec:
  replicas: 2
  selector: { matchLabels: { app: backend } }
  template: { ... pod spec, just like Deployment ... }
  strategy:
    canary:
      maxSurge: 1
      maxUnavailable: 0
      analysis:                          # background analysis (every step)
        templates: [{ templateName: backend-canary-health }]
        startingStep: 1
      steps:
        - setWeight: 25                  # send 25% traffic to new version
        - pause: { duration: 30s }
        - analysis: { templates: [{ templateName: backend-canary-health }] }
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
```

## AnalysisTemplate Skeleton

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: { name: backend-canary-health }
spec:
  args: [{ name: service-name }]
  metrics:
    - name: error-rate
      interval: 15s
      successCondition: result[0] < 0.05
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.observability.svc:9090
          query: 'sum(rate(...{http_status_code=~"5.."}[1m])) / sum(rate(...[1m]))'
```

| Field | Notes |
|-------|-------|
| `successCondition` | CEL/template expression; `result[0]` is the first PromQL value |
| `failureLimit` | How many consecutive failed measurements to declare AnalysisRun failed |
| `inconclusiveLimit` | Same but for "no data" |
| `interval` | Measurement frequency |
| `count` | Total measurements (omit → forever until step ends) |

## AnalysisRun Status

| Phase | Meaning |
|-------|---------|
| `Pending` | Created, no measurements yet |
| `Running` | Measurements in flight |
| `Successful` | All metrics met successCondition |
| `Failed` | A metric exceeded failureLimit |
| `Inconclusive` | Hit inconclusiveLimit (e.g., no data) |
| `Error` | Provider error (Prom unreachable) |

## Decision Tables

| Need | Use |
|------|-----|
| Migrate Deployment → Rollout with zero-downtime | `workloadRef` pattern (patterns/rollout-from-deployment.md) |
| Visualize during demo | `kubectl argo rollouts get rollout ... --watch` |
| Manual gate between 25% and 50% | `pause: {}` (indefinite) + `kubectl argo rollouts promote` |
| Force-promote during demo | `kubectl argo rollouts promote backend --full` |
| Roll back on failure (auto) | AnalysisTemplate failure → controller marks Degraded; `kubectl argo rollouts undo` |

## Demo URL Snippets

```bash
# Watch
watch 'kubectl argo rollouts get rollout backend -n sre-copilot'

# Trigger v2 with the visible diff
make demo-canary
# (builds backend:v2 with `confidence: float` field, kind load, set image)
```
