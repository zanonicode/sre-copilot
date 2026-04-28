# Multi-Environment Promotion Pattern

> **Purpose**: Promote releases from dev → staging → prod using GitOps image tag updates
> **MCP Validated**: 2026-04-22

## When to Use

- You want a traceable, Git-history-backed promotion audit trail
- You need to gate production deploys behind manual approval or CI checks
- You have environment-specific config (resource limits, replica counts, secrets refs)
- You use Kustomize overlays to separate environment values from base manifests

## How It Works

Image tags are the promotion artifact. CI builds a new image → updates the dev overlay's `kustomization.yaml` → ArgoCD syncs dev automatically → promotion to prod is a PR that bumps the tag in the prod overlay.

```text
CI Pipeline
  └── docker build → push :sha-abc123

GitOps PR (auto, dev)
  └── apps/data-extractor/overlays/dev/kustomization.yaml
        newTag: sha-abc123   ← ArgoCD auto-syncs dev

Manual PR (human, prod)
  └── apps/data-extractor/overlays/prod/kustomization.yaml
        newTag: sha-abc123   ← ArgoCD auto-syncs prod after merge
```

## Implementation

### 1. Kustomize Base (shared manifests)

```yaml
# apps/data-extractor/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: data-extractor
spec:
  replicas: 1
  selector:
    matchLabels:
      app: data-extractor
  template:
    metadata:
      labels:
        app: data-extractor
    spec:
      containers:
        - name: data-extractor
          image: gcr.io/invoice-pipeline-prod/data-extractor:latest  # overridden by overlay
          envFrom:
            - secretRef:
                name: gemini-credentials
          resources:
            requests:
              cpu: "100m"
              memory: "256Mi"
```

```yaml
# apps/data-extractor/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
```

### 2. Dev Overlay (auto-synced by CI)

```yaml
# apps/data-extractor/overlays/dev/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: invoice-pipeline-dev
resources:
  - ../../base
images:
  - name: gcr.io/invoice-pipeline-prod/data-extractor
    newTag: sha-abc123          # ← CI updates this field
patches:
  - path: replica-patch.yaml
```

```yaml
# apps/data-extractor/overlays/dev/replica-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: data-extractor
spec:
  replicas: 1                   # dev: single replica
```

### 3. Prod Overlay (manual PR promotion)

```yaml
# apps/data-extractor/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: invoice-pipeline-prod
resources:
  - ../../base
images:
  - name: gcr.io/invoice-pipeline-prod/data-extractor
    newTag: sha-abc123          # ← human PR updates this to promote
patches:
  - path: replica-patch.yaml
  - path: resource-patch.yaml
```

```yaml
# apps/data-extractor/overlays/prod/replica-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: data-extractor
spec:
  replicas: 3                   # prod: HA replicas
```

### 4. CI Automation (GitHub Actions)

```yaml
# .github/workflows/promote-dev.yaml
name: Promote to Dev
on:
  push:
    branches: [main]

jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: myorg/invoice-pipeline-gitops
          token: ${{ secrets.GITOPS_PAT }}

      - name: Update dev image tag
        run: |
          IMAGE_TAG="sha-${{ github.sha }}"
          # Use kustomize edit to update the tag safely
          cd apps/data-extractor/overlays/dev
          kustomize edit set image \
            gcr.io/invoice-pipeline-prod/data-extractor=gcr.io/invoice-pipeline-prod/data-extractor:${IMAGE_TAG}

      - name: Commit and push
        run: |
          git config user.email "ci@myorg.com"
          git config user.name "CI Bot"
          git add .
          git commit -m "chore(dev): promote data-extractor to sha-${{ github.sha }}"
          git push
```

### 5. ArgoCD Applications per environment

```yaml
# bootstrap/dev/app-data-extractor.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: data-extractor-dev
  namespace: argocd
spec:
  project: invoice-pipeline
  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main
    path: apps/data-extractor/overlays/dev
  destination:
    server: https://kubernetes.default.svc
    namespace: invoice-pipeline-dev
  syncPolicy:
    automated:
      prune: true
      selfHeal: true            # auto-sync on git push
---
# bootstrap/prod/app-data-extractor.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: data-extractor-prod
  namespace: argocd
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
      selfHeal: false           # require manual sync approval for prod
    syncOptions:
      - CreateNamespace=true
```

## Promotion Workflow

```bash
# 1. Dev is auto-promoted by CI. Verify it's healthy:
argocd app get data-extractor-dev
argocd app wait data-extractor-dev --health

# 2. Create a promotion PR (human or automation):
#    - Bump newTag in overlays/prod/kustomization.yaml
#    - Get code review + approval

# 3. After merge, ArgoCD detects the change. Sync prod:
argocd app sync data-extractor-prod

# 4. Watch rollout:
argocd app wait data-extractor-prod --health --timeout 120

# 5. If something goes wrong, roll back by reverting the PR
#    ArgoCD will auto-sync back to the previous tag
```

## Configuration Reference

| Setting | Dev | Prod | Notes |
|---------|-----|------|-------|
| `automated.selfHeal` | `true` | `false` | Prod requires deliberate sync |
| `automated.prune` | `true` | `true` | Remove resources deleted from Git |
| Replicas | 1 | 3 | Patched per overlay |
| Image tag source | CI auto-commit | Manual PR | Promotion gate |

## See Also

- [app-of-apps.md](app-of-apps.md)
- [helm-kustomize-integration.md](helm-kustomize-integration.md)
- [concepts/sync-phases.md](../concepts/sync-phases.md)
