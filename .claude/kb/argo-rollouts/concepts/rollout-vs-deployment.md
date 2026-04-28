# Rollout vs Deployment

> **Purpose**: What you gain (and lose) by replacing a Deployment with an Argo Rollouts `Rollout` CRD
> **MCP Validated**: 2026-04-26

## Side-by-Side

| Capability | Deployment | Rollout |
|------------|-----------|---------|
| Rolling update | ✅ Built-in | ✅ Equivalent |
| Pause/resume mid-update | ⚠️ via `kubectl rollout pause` (binary) | ✅ Step-driven, conditional |
| Canary (% traffic split) | ❌ | ✅ `setWeight` steps |
| Blue-green | ❌ | ✅ `blueGreen` strategy |
| Automated metric analysis | ❌ | ✅ AnalysisTemplate |
| Auto-rollback on metric failure | ❌ | ✅ |
| HPA support | ✅ | ✅ (HPA targets Rollout) |
| PDB support | ✅ | ✅ |
| `kubectl rollout` plugin | ✅ | ✅ via `kubectl argo rollouts` |
| Argo CD compatibility | ✅ | ✅ (with Rollout CRD installed in cluster) |
| Pod template shape | apps/v1 PodTemplateSpec | Same — drop-in |

## What You Lose

- A few `kubectl get deployments` workflows — must learn `kubectl argo rollouts get rollout`.
- Some operators (e.g., kube-state-metrics) need the rollout-specific exporter to surface counts.
- HPA must reference `apiVersion: argoproj.io/v1alpha1, kind: Rollout`, not `apps/v1, kind: Deployment`.

## CRD Shape (canary)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: backend
spec:
  replicas: 2
  selector:
    matchLabels: { app: backend }
  template:
    # IDENTICAL to Deployment.spec.template
    metadata: { labels: { app: backend } }
    spec:
      containers:
        - name: backend
          image: sre-copilot/backend:v1
          ports: [{ containerPort: 8000 }]
  strategy:
    canary:
      maxSurge: 1
      maxUnavailable: 0
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - analysis: { templates: [{ templateName: backend-canary-health }] }
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
```

## How It Works (replica-based canary)

In the absence of a traffic router (Traefik/SMI), Rollouts simulates "weight" via REPLICA RATIO.

```text
replicas: 2, setWeight: 25 → 1 stable (75%) + 1 canary (~25% effective)
replicas: 4, setWeight: 25 → 3 stable + 1 canary
replicas: 4, setWeight: 50 → 2 stable + 2 canary
```

So with 2 replicas you can't do better than 50/50 weight precision. For SRE Copilot with `replicas: 2` the 25% step is approximated. Add a Traefik `TrafficRouting` block for true weight precision (see `concepts/traffic-routing-modes.md`).

## Controller Behavior

- One controller (`argo-rollouts` Deployment in `platform` namespace) reconciles every Rollout.
- For each spec change (image, env, configmap-checksum), controller creates a new ReplicaSet, executes steps in order, blocks at pauses, runs AnalysisRuns.
- On step failure (analysis Failed) → marks Rollout Degraded → STOPS, does NOT auto-undo. You must `kubectl argo rollouts undo` (or it'll re-execute on next reconcile).

## Migration Idiom: `workloadRef`

Don't want to copy your full PodTemplateSpec into the Rollout? Reference an existing Deployment:

```yaml
spec:
  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  replicas: 2
  strategy: { canary: { steps: [...] } }
```

The Rollout takes ownership of the Deployment's pods, scales the Deployment to 0, and runs from the Deployment's template. Useful for first migration.

For SRE Copilot we go straight to inline `template:` (no `workloadRef`) for clarity. See `patterns/rollout-from-deployment.md`.

## When NOT to Use a Rollout

- Stateless one-shot Jobs / CronJobs — no benefit.
- A workload that needs zero-traffic-shift (just a binary swap) — Deployment is simpler.
- DaemonSets or StatefulSets — Rollout doesn't replace these (use their own progressive-update settings).

## See Also

- patterns/rollout-from-deployment.md — full migration recipe
- concepts/analysis-templates.md — AnalysisRun lifecycle
- concepts/traffic-routing-modes.md — replica-based vs Traefik
