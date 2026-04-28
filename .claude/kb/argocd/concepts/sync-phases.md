# Sync Phases

> **Purpose**: Understand ArgoCD's sync lifecycle, hooks, waves, and health checks
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

ArgoCD's sync operation is not a simple `kubectl apply`. It proceeds through ordered phases controlled by sync waves and lifecycle hooks. This lets you run database migrations before deploying an app, verify infrastructure before routing traffic, or clean up resources after a failed rollout — all from within the GitOps paradigm without external CI orchestration.

## Sync Lifecycle

```text
1. REFRESH
   └── ArgoCD fetches latest Git commit and renders manifests

2. DIFF
   └── Compare rendered manifests against live cluster state

3. PRESYNC HOOKS
   └── Run Jobs/Pods annotated with hook: PreSync
       (e.g. database migrations, pre-flight checks)

4. SYNC (wave by wave, ascending wave number)
   ├── Wave -1: CRDs, Namespaces, PVCs
   ├── Wave  0: ConfigMaps, Secrets, ServiceAccounts (default)
   ├── Wave  1: Deployments, StatefulSets
   └── Wave  2: Ingress, smoke test Jobs

5. POSTSYNC HOOKS
   └── Run after all resources are Healthy
       (e.g. integration tests, cache warmup, Slack notifications)

6. SYNCFAIL HOOKS (only on failure)
   └── Run if any phase fails
       (e.g. rollback triggers, alert escalation)

7. POSTDELETE HOOKS
   └── Run after application deletion
       (e.g. cleanup external resources)
```

## Sync Waves

Waves control the order of resource deployment within a single sync. Lower wave numbers deploy first. ArgoCD waits for all resources in wave N to become Healthy before starting wave N+1.

```yaml
# Wave -1: Deploy CRDs before anything else
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: invoices.pipeline.example.com
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
---
# Wave 0: ConfigMaps and Secrets (default, annotation optional)
apiVersion: v1
kind: ConfigMap
metadata:
  name: pipeline-config
  annotations:
    argocd.argoproj.io/sync-wave: "0"
---
# Wave 1: Application deployments
apiVersion: apps/v1
kind: Deployment
metadata:
  name: data-extractor
  annotations:
    argocd.argoproj.io/sync-wave: "1"
---
# Wave 2: Smoke test Job runs after all services are up
apiVersion: batch/v1
kind: Job
metadata:
  name: smoke-test
  annotations:
    argocd.argoproj.io/sync-wave: "2"
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
```

## Lifecycle Hooks

Hooks are Kubernetes resources (Jobs, Pods) with the `argocd.argoproj.io/hook` annotation.

```yaml
# PreSync hook: run database migration before app deploys
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: my-app:1.2.3
          command: ["python", "manage.py", "migrate"]
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: db-credentials
                  key: url
---
# PostSync hook: send Slack notification after successful deploy
apiVersion: batch/v1
kind: Job
metadata:
  name: notify-deploy
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: notify
          image: curlimages/curl:8.x
          command:
            - sh
            - -c
            - |
              curl -X POST $SLACK_WEBHOOK \
                -H 'Content-type: application/json' \
                --data '{"text":"Invoice pipeline deployed to prod"}'
          env:
            - name: SLACK_WEBHOOK
              valueFrom:
                secretKeyRef:
                  name: slack-credentials
                  key: webhook-url
```

## Hook Delete Policies

| Policy | Behavior |
|--------|---------|
| `HookSucceeded` | Delete hook resource after it completes successfully |
| `HookFailed` | Delete hook resource after it fails |
| `BeforeHookCreation` | Delete previous hook resource before creating new one |

## Health Checks

ArgoCD evaluates resource health using built-in checks for standard Kubernetes types and custom Lua scripts for CRDs.

```yaml
# Built-in health check resources
Deployment     → Healthy when all replicas are ready
StatefulSet    → Healthy when all replicas are ready
DaemonSet      → Healthy when desired == ready
Job            → Healthy when completed; Degraded when failed
Ingress        → Healthy when loadBalancer IP is assigned
PVC            → Healthy when Bound
```

```yaml
# Custom health check for a CRD (in argocd-cm ConfigMap)
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resource.customizations.health.pipeline.example.com_InvoicePipeline: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.phase == "Running" then
        hs.status = "Healthy"
        hs.message = "Pipeline is running"
      elseif obj.status.phase == "Failed" then
        hs.status = "Degraded"
        hs.message = obj.status.message
      else
        hs.status = "Progressing"
        hs.message = "Pipeline is starting"
      end
    end
    return hs
```

## Sync Options

| Option | Effect |
|--------|--------|
| `CreateNamespace=true` | Create destination namespace if missing |
| `ServerSideApply=true` | Use server-side apply (avoids annotation size limits) |
| `PruneLast=true` | Prune orphaned resources after sync completes |
| `PrunePropagationPolicy=foreground` | Foreground deletion (wait for children) |
| `ApplyOutOfSyncOnly=true` | Only apply resources that are OutOfSync |
| `Replace=true` | Use `kubectl replace` instead of apply |
| `FailOnSharedResource=true` | Fail if resource owned by another app |

## Common Mistakes

### Wrong — no hook delete policy causes job accumulation

```yaml
metadata:
  annotations:
    argocd.argoproj.io/hook: PostSync
    # Missing hook-delete-policy — old Job pods accumulate
```

### Correct

```yaml
metadata:
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
```

## Related

- [application-model.md](application-model.md)
- [what-is-argocd.md](what-is-argocd.md)
- [patterns/helm-kustomize-integration.md](../patterns/helm-kustomize-integration.md)
