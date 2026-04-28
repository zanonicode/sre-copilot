# Helm + Kustomize Integration Pattern

> **Purpose**: Use Helm charts for upstream dependencies and Kustomize overlays for your own services
> **MCP Validated**: 2026-04-22

## When to Use

- You install third-party charts (cert-manager, nginx-ingress, ArgoCD itself) via Helm
- You manage your own workloads with Kustomize for GitOps-friendly diffs
- You need to patch Helm chart output without forking the chart (post-render patching)
- You want readable `git diff` output — Helm renders to opaque blobs; Kustomize patches are readable

## Decision Table

| Scenario | Use |
|----------|-----|
| Third-party chart (stable, version-pinned) | Helm |
| Your own services | Kustomize |
| Need to patch a Helm chart output | Helm + Kustomize post-render |
| Multi-env config differences | Kustomize overlays |
| Shared upstream values across envs | Helm values files |

## Pattern A: Pure Kustomize (own services)

Best for Cloud Run function manifests and invoice pipeline services.

```yaml
# apps/invoice-classifier/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - hpa.yaml
commonLabels:
  app.kubernetes.io/part-of: invoice-pipeline
  app.kubernetes.io/managed-by: argocd
```

```yaml
# apps/invoice-classifier/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: invoice-pipeline-prod
resources:
  - ../../base
images:
  - name: gcr.io/invoice-pipeline-prod/invoice-classifier
    newTag: "1.4.2"
configMapGenerator:
  - name: invoice-classifier-config
    literals:
      - GEMINI_MODEL=gemini-2.0-flash
      - LOG_LEVEL=INFO
      - MAX_RETRIES=3
patches:
  - patch: |-
      - op: replace
        path: /spec/replicas
        value: 3
    target:
      kind: Deployment
      name: invoice-classifier
```

## Pattern B: Helm for Third-Party (ArgoCD Application)

```yaml
# bootstrap/prod/app-cert-manager.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cert-manager
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-1"    # install before pipeline apps
spec:
  project: invoice-pipeline
  source:
    repoURL: https://charts.jetstack.io
    chart: cert-manager
    targetRevision: v1.14.5               # always pin chart version
    helm:
      releaseName: cert-manager
      valuesObject:
        installCRDs: true
        global:
          leaderElection:
            namespace: cert-manager
  destination:
    server: https://kubernetes.default.svc
    namespace: cert-manager
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true              # required for CRDs
```

## Pattern C: Helm with Multiple Value Files per Environment

```yaml
# bootstrap/dev/app-pubsub-emulator.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: pubsub-emulator-dev
  namespace: argocd
spec:
  project: invoice-pipeline
  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main
    path: charts/pubsub-emulator
    helm:
      releaseName: pubsub-emulator
      valueFiles:
        - values.yaml                     # base values
        - values-dev.yaml                 # dev overrides
  destination:
    server: https://kubernetes.default.svc
    namespace: invoice-pipeline-dev
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

```yaml
# charts/pubsub-emulator/values.yaml      (base)
replicaCount: 1
image:
  repository: gcr.io/google.com/cloudsdktool/cloud-sdk
  tag: "latest"
  pullPolicy: IfNotPresent
service:
  port: 8085
resources:
  requests:
    cpu: 100m
    memory: 128Mi
```

```yaml
# charts/pubsub-emulator/values-dev.yaml  (dev overrides)
replicaCount: 1
resources:
  limits:
    cpu: 500m
    memory: 256Mi
```

## Pattern D: Kustomize Post-Render Patching of Helm Output

When you need to patch a Helm chart's rendered output without forking it:

```yaml
# apps/argocd-self/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
# Pull the Helm-rendered output and patch it
helmCharts:
  - name: argo-cd
    repo: https://argoproj.github.io/argo-helm
    version: "7.7.0"
    releaseName: argocd
    namespace: argocd
    valuesFile: values.yaml
patches:
  - patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: argocd-server
      spec:
        template:
          spec:
            containers:
              - name: argocd-server
                args:
                  - /usr/local/bin/argocd-server
                  - --insecure           # TLS terminated at GKE ingress
    target:
      kind: Deployment
      name: argocd-server
```

## ArgoCD Source Configuration Reference

```yaml
# Kustomize source
source:
  path: apps/my-service/overlays/prod
  # ArgoCD auto-detects kustomization.yaml; no extra config needed

# Helm chart from registry
source:
  repoURL: https://charts.example.com
  chart: my-chart
  targetRevision: 1.2.3
  helm:
    releaseName: my-release
    valueFiles: [values.yaml, values-prod.yaml]
    valuesObject:          # inline values (highest precedence)
      key: value

# Helm chart from Git
source:
  repoURL: https://github.com/myorg/gitops
  path: charts/my-chart
  targetRevision: main
  helm:
    releaseName: my-release
    valueFiles: [values.yaml]
```

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Helm chart version unpinned (`latest`) | Always pin `targetRevision` to a semver |
| `valuesObject` not overriding `valueFiles` | `valuesObject` takes precedence — use it for env-specific secrets |
| Kustomize `configMapGenerator` creates new CM name on change | Add `generatorOptions.disableNameSuffixHash: true` if referencing by static name |
| Helm CRDs not installing | Add `ServerSideApply=true` to `syncOptions` |

## See Also

- [multi-env-promotion.md](multi-env-promotion.md)
- [gke-integration.md](gke-integration.md)
- [concepts/application-model.md](../concepts/application-model.md)
