# ArgoCD Quick Reference

> Fast lookup tables. For code examples, see linked files.
> **MCP Validated**: 2026-04-22

## Core CLI Commands

| Command | Description |
|---------|-------------|
| `argocd login <server>` | Authenticate to ArgoCD server |
| `argocd app list` | List all applications |
| `argocd app get <app>` | Show application status and details |
| `argocd app sync <app>` | Trigger manual sync |
| `argocd app sync <app> --prune` | Sync and remove orphaned resources |
| `argocd app sync <app> --dry-run` | Preview sync without applying |
| `argocd app diff <app>` | Show diff between Git and live state |
| `argocd app history <app>` | Show deployment history |
| `argocd app rollback <app> <id>` | Roll back to a previous revision |
| `argocd app delete <app>` | Delete application (not resources) |
| `argocd app wait <app>` | Wait until app is synced and healthy |
| `argocd proj list` | List all AppProjects |
| `argocd cluster list` | List registered clusters |
| `argocd repo list` | List registered repositories |

## Application Sync Status

| Status | Meaning |
|--------|---------|
| `Synced` | Cluster matches Git state |
| `OutOfSync` | Cluster differs from Git state |
| `Unknown` | ArgoCD cannot determine sync state |

## Application Health Status

| Status | Meaning |
|--------|---------|
| `Healthy` | All resources pass health checks |
| `Progressing` | Resources are being updated |
| `Degraded` | Resources failed health checks |
| `Suspended` | Application is paused |
| `Missing` | Resources not found in cluster |

## Sync Hooks

| Hook | Runs |
|------|------|
| `PreSync` | Before resources are applied |
| `Sync` | During resource application |
| `PostSync` | After all resources are healthy |
| `SyncFail` | If sync fails at any phase |
| `PostDelete` | After application is deleted |

## Sync Wave Ordering

| Annotation | Effect |
|------------|--------|
| `argocd.argoproj.io/sync-wave: "-1"` | Deploy before wave 0 (e.g. CRDs, namespaces) |
| `argocd.argoproj.io/sync-wave: "0"` | Default wave |
| `argocd.argoproj.io/sync-wave: "1"` | Deploy after wave 0 (e.g. apps after infra) |
| `argocd.argoproj.io/sync-wave: "2"` | Deploy last (e.g. smoke tests) |

## Key Application Fields

| Field | Description |
|-------|-------------|
| `spec.source.repoURL` | Git repo containing manifests |
| `spec.source.targetRevision` | Branch, tag, or commit SHA |
| `spec.source.path` | Directory within repo |
| `spec.destination.server` | Target cluster API URL |
| `spec.destination.namespace` | Target namespace |
| `spec.syncPolicy.automated` | Enable auto-sync |
| `spec.syncPolicy.automated.prune` | Remove resources deleted from Git |
| `spec.syncPolicy.automated.selfHeal` | Revert manual cluster changes |

## AppProject RBAC Verbs (v3.x)

| Verb | Scope |
|------|-------|
| `get` | Read application state |
| `create` | Create new applications |
| `update` | Update application spec |
| `delete` | Delete applications |
| `sync` | Trigger syncs |
| `override` | Override sync parameters |
| `action` | Run resource actions |
| `logs` | View pod logs (enforced by default in v3) |

## Decision Matrix

| Use Case | Choose |
|----------|--------|
| Single app, single env | Plain `Application` CRD |
| Many apps, one root | App-of-Apps pattern |
| Same app, many envs/clusters | `ApplicationSet` with generators |
| Helm values per environment | Helm multi-source or Kustomize overlay |
| Team isolation on shared cluster | `AppProject` with RBAC |
| Ordered deployment (CRDs before apps) | Sync waves |
| Database migrations before rollout | PreSync hooks |

## Common Pitfalls

| Avoid | Do Instead |
|-------|-----------|
| Using `--prune` without testing | Run `--dry-run` first |
| Storing secrets in Git | Use Sealed Secrets, ESO, or Vault |
| Skipping `selfHeal` in prod | Enable selfHeal to prevent drift |
| One giant Application | Use App-of-Apps or ApplicationSets |
| Hardcoding cluster URLs | Use `https://kubernetes.default.svc` for in-cluster |
| Ignoring sync waves for CRDs | Wave -1 for CRDs, 0+ for apps |

## Related Documentation

| Topic | Path |
|-------|------|
| What is ArgoCD | `concepts/what-is-argocd.md` |
| Application Model | `concepts/application-model.md` |
| Sync Phases | `concepts/sync-phases.md` |
| RBAC & Security | `concepts/rbac-and-security.md` |
| App-of-Apps | `patterns/app-of-apps.md` |
| Multi-Env Promotion | `patterns/multi-env-promotion.md` |
| Helm + Kustomize | `patterns/helm-kustomize-integration.md` |
| GKE Integration | `patterns/gke-integration.md` |
| Full Index | `index.md` |
