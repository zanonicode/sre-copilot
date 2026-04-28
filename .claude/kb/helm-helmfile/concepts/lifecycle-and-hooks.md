# Lifecycle and Hooks

> **Purpose**: Know when each manifest is applied during install/upgrade/rollback and how Helm hooks let you inject one-shot Jobs at lifecycle phases
> **MCP Validated**: 2026-04-26

## Release Lifecycle Phases

```text
helm install  → load chart → render → install hooks (pre-install) → apply → post-install
helm upgrade  → render diff → pre-upgrade hooks → apply → post-upgrade hooks
helm rollback → load prev revision → pre-rollback → apply → post-rollback
helm uninstall→ pre-delete hooks → delete release → post-delete
helm test     → run hooks tagged "test"
```

Each `helm` action creates a new revision (visible via `helm history`).

## Hook Annotations

Mark a manifest as a hook by adding annotations. Hooks are NOT counted as part of the release; they live and die independently.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-weight": "-5"            # lower runs first
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: backend:{{ .Values.image.tag }}
          command: ["alembic", "upgrade", "head"]
```

### Hook Events

| Event | When |
|-------|------|
| `pre-install` | After templates rendered, before any resource applied (install only) |
| `post-install` | After all resources Ready (install only) |
| `pre-upgrade` | Before upgrade applies |
| `post-upgrade` | After upgrade applies |
| `pre-rollback` / `post-rollback` | Around rollback |
| `pre-delete` / `post-delete` | Around uninstall |
| `test` | Run via `helm test <release>` |

### Hook Weights

Integer string. Lower runs first. Use to order multiple hooks of the same event.

### Delete Policies

| Policy | Behavior |
|--------|----------|
| `before-hook-creation` (default) | Delete previous hook resource before creating new one |
| `hook-succeeded` | Delete after success — keeps cluster clean |
| `hook-failed` | Delete after failure (lose debug info!) |

For SRE Copilot recommendation: `before-hook-creation,hook-succeeded` so failed hooks stick around for `kubectl logs`.

## Immutable Fields and Upgrade Failures

Some K8s fields cannot be patched. Helm will fail on upgrade if you try:

| Resource | Immutable Fields |
|----------|------------------|
| Service | `.spec.clusterIP`, `.spec.type` (sometimes) |
| StatefulSet | `.spec.serviceName`, `.spec.volumeClaimTemplates` |
| Job | `.spec.template` |
| PVC | most of `.spec` |

Workaround: delete and recreate (data loss for stateful resources!) or use a recreate strategy via Argo Rollouts / manual.

## Rollback

```bash
helm history backend                      # see revisions
helm rollback backend 3                   # roll to revision 3
helm rollback backend 3 --wait            # wait for ready
```

Rollback creates a NEW revision (not "go back to 3", but "revision N+1 = contents of 3"). This is helpful: the history is append-only.

## `--atomic` and `--wait`

```bash
helm upgrade backend ./helm/backend --atomic --wait --timeout 5m
```

- `--wait`: block until all Pods/Deployments/etc. are Ready.
- `--atomic`: if any resource fails, automatically rollback.

For SRE Copilot's Tilt loop we deliberately skip `--atomic` (faster iteration); CI uses it.

## Helm Test

```yaml
# templates/tests/test-connection.yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "backend.fullname" . }}-test"
  annotations:
    "helm.sh/hook": test
spec:
  restartPolicy: Never
  containers:
    - name: curl
      image: curlimages/curl:8.10.1
      command: [curl, -fsS, "http://{{ include "backend.fullname" . }}:{{ .Values.service.port }}/healthz"]
```

```bash
helm test backend -n sre-copilot
```

Useful for `make smoke` integration but for SRE Copilot we prefer pytest-based smoke tests for richer assertions.

## Argo Rollouts Note

Argo Rollouts replaces the Deployment lifecycle with its own canary/blue-green flow. Helm hooks still work for one-shot init Jobs, but the workload "ready" semantics belong to the Rollout controller — see the `argo-rollouts` KB.

## See Also

- concepts/helmfile-model.md — helmfile-level pre/post hooks (different layer)
- patterns/common-pitfalls.md — immutable-field traps
