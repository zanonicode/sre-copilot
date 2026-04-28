# App-of-Apps Pattern

> **Purpose**: Bootstrap an entire environment by managing ArgoCD Applications as Git-versioned resources
> **MCP Validated**: 2026-04-22

## When to Use

- You have many Applications across an environment and want a single sync to deploy all of them
- You need to bootstrap a fresh cluster from scratch declaratively
- You want ArgoCD Applications themselves to be version-controlled in Git
- You need ordered rollout of dependent services (use sync waves within the root app)

## How It Works

A single "root" Application points to a Git directory that contains only ArgoCD `Application` CRDs (not actual workload manifests). When ArgoCD syncs the root, it creates/updates all child Applications. Each child Application then manages its own workload independently.

```text
Root Application (argocd namespace)
└── Git: gitops-repo/bootstrap/prod/
    ├── app-tiff-to-png.yaml          → Application CRD
    ├── app-invoice-classifier.yaml   → Application CRD
    ├── app-data-extractor.yaml       → Application CRD
    ├── app-bigquery-writer.yaml      → Application CRD
    ├── app-dlq-processor.yaml        → Application CRD
    └── app-monitoring.yaml           → Application CRD
```

## Implementation

### 1. Root Application

```yaml
# deploy/root-app.yaml  — apply once with kubectl or Terraform
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: invoice-pipeline-root
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: invoice-pipeline

  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main
    path: bootstrap/prod             # contains child Application YAMLs

  destination:
    server: https://kubernetes.default.svc
    namespace: argocd                # child Apps must land in argocd ns

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### 2. Child Application (one per function)

```yaml
# bootstrap/prod/app-data-extractor.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: data-extractor-prod
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "1"   # deploy after infrastructure apps
spec:
  project: invoice-pipeline

  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main
    path: apps/data-extractor/overlays/prod

  destination:
    server: https://kubernetes.default.svc
    namespace: invoice-pipeline-prod

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

### 3. Infrastructure-first ordering with sync waves

```yaml
# bootstrap/prod/app-pubsub-config.yaml
# Wave 0: deploy Pub/Sub and IAM config before functions
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: pubsub-config-prod
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: invoice-pipeline
  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main
    path: apps/pubsub-config/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: invoice-pipeline-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
---
# bootstrap/prod/app-tiff-to-png.yaml
# Wave 1: function apps after infrastructure
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tiff-to-png-prod
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  project: invoice-pipeline
  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main
    path: apps/tiff-to-png/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: invoice-pipeline-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 4. Recommended Git Repository Layout

```text
invoice-pipeline-gitops/
├── bootstrap/
│   ├── dev/
│   │   ├── app-tiff-to-png.yaml
│   │   ├── app-invoice-classifier.yaml
│   │   ├── app-data-extractor.yaml
│   │   ├── app-bigquery-writer.yaml
│   │   └── app-dlq-processor.yaml
│   └── prod/
│       ├── app-tiff-to-png.yaml       # same structure, different values
│       ├── app-invoice-classifier.yaml
│       ├── app-data-extractor.yaml
│       ├── app-bigquery-writer.yaml
│       └── app-dlq-processor.yaml
└── apps/
    ├── tiff-to-png/
    │   ├── base/                       # shared K8s manifests
    │   └── overlays/
    │       ├── dev/                    # dev-specific patches
    │       └── prod/                   # prod-specific patches
    └── data-extractor/
        ├── base/
        └── overlays/
            ├── dev/
            └── prod/
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `spec.destination.namespace` | `argocd` | Root app always targets argocd ns |
| `syncPolicy.automated.prune` | `false` | Enable to remove deleted child apps |
| `syncPolicy.automated.selfHeal` | `false` | Revert manual Application changes |
| Sync wave annotation | `0` | Order child apps within root sync |

## Example Usage

```bash
# Bootstrap a new cluster (one-time)
kubectl apply -f deploy/root-app.yaml

# ArgoCD now manages everything; verify
argocd app list

# Check the root application
argocd app get invoice-pipeline-root

# Force sync the root (will cascade to children)
argocd app sync invoice-pipeline-root --async

# Check a specific child app
argocd app get data-extractor-prod
```

## See Also

- [application-model.md](../concepts/application-model.md)
- [patterns/multi-env-promotion.md](multi-env-promotion.md)
- [patterns/helm-kustomize-integration.md](helm-kustomize-integration.md)
