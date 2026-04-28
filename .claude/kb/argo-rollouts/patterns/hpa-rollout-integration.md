# HPA + Rollout Integration

> **Purpose**: Make HorizontalPodAutoscaler scale a `Rollout` (not a `Deployment`) and understand how scaling interacts with canary steps
> **MCP Validated**: 2026-04-26

## When to Use

- Anytime you migrate Deployment -> Rollout AND have an existing HPA
- SRE Copilot S4 entry #40

## The One-Line Change

```yaml
# helm/backend/templates/hpa.yaml
spec:
  scaleTargetRef:
    apiVersion: argoproj.io/v1alpha1   # was: apps/v1
    kind: Rollout                      # was: Deployment
    name: {{ include "backend.fullname" . }}
```

That's it. Everything else (metrics, min/max, behavior) works identically.

## Why It Works

Argo Rollouts implements the `scale` subresource on its CRD, just like Deployment does. HPA queries `/scale` and PATCHes a new replica count. Argo accepts and adjusts.

## How HPA + Canary Steps Interact (replica-based)

For replica-based canary (no traffic router), the actual canary pod count is computed:

```text
canary_count = max(1, ceil(replicas * setWeight / 100))
stable_count = replicas - canary_count
```

If HPA scales `replicas` mid-rollout from 2 -> 4, Argo recomputes:

```text
At setWeight: 25, replicas: 2 -> 1 canary + 1 stable
HPA scales replicas to 4
At setWeight: 25, replicas: 4 -> 1 canary + 3 stable
```

So HPA can scale up smoothly during a canary. Going back DOWN can briefly leave the canary over-weighted; Argo auto-corrects within seconds.

## How HPA + Canary Steps Interact (traffic-routed, e.g., Traefik)

Traffic is split by the router; pod counts don't drive weights. HPA can size canary and stable independently if you want — but by default Argo keeps them in proportion to `setWeight`.

For SRE Copilot keep it simple: HPA targets the Rollout, Argo handles internal ratio.

## Min/Max Settings

```yaml
spec:
  minReplicas: 2
  maxReplicas: 4
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: 70 }
```

`minReplicas: 2` is required so the PDB (`minAvailable: 1`) can satisfy itself during canary. With `minReplicas: 1`, a canary step that adds a new pod and removes an old one could violate PDB momentarily.

## Behavior During Step Pauses

HPA continues to react. If load spikes during a `pause:` step, HPA scales up — both canary and stable proportionally (replica-based) or as configured (traffic-routed). The Rollout step stays paused.

## Behavior During AnalysisRun

Same — HPA is independent of analyses. An AnalysisRun looking at p95 latency may actually NOTICE the new pods coming online because TTFT briefly spikes during cold-load. Solution: set the AnalysisTemplate `interval: 30s` (longer than typical scale-up settle time).

## Verification

```bash
# Check HPA target
kubectl get hpa -n sre-copilot
# NAME      REFERENCE                       TARGETS   MINPODS   MAXPODS   REPLICAS
# backend   Rollout/backend                 12%/70%   2         4         2

# Trigger load
hey -n 5000 -c 50 -m POST -T 'application/json' \
  -d '{"log_payload":"..."}' http://backend.sre-copilot:8000/analyze/logs

# Watch HPA scale (during canary)
watch 'kubectl get hpa,rollout -n sre-copilot'
```

## Pitfalls

| Pitfall | Fix |
|---------|-----|
| HPA still references `apps/v1 Deployment` after Rollout migration | Update `scaleTargetRef.apiVersion` AND `kind`; `kubectl describe hpa` will show `<unknown>` if wrong |
| HPA flapping during canary cold-loads | Increase `behavior.scaleDown.stabilizationWindowSeconds` to 60s |
| HPA scales to 0 because new metric API not registered | metrics-server must run; for kind: `helm install metrics-server bitnami/metrics-server --set apiService.create=true --set extraArgs={--kubelet-insecure-tls}` |
| `minReplicas: 1` + canary step requests new pod | PDB violation; raise minReplicas to 2 |

## Optional: Disable HPA During Canary

If you want predictable replica counts during the demo:

```bash
kubectl scale hpa backend --replicas=0 -n sre-copilot     # not allowed; HPA can't be scaled
# Workaround: set minReplicas == maxReplicas == 2 in values-dev.yaml
```

For the SRE Copilot demo, scaling stays on — the rollout step counts and HPA together produce more "real" behavior.

## See Also

- patterns/rollout-from-deployment.md — the Rollout this targets
- helm-helmfile KB -> patterns/probes-and-security.md — PDB minAvailable interaction
- concepts/traffic-routing-modes.md — replica vs router mode
