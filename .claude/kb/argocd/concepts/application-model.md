# Application Model

> **Purpose**: Understand the Application, AppProject, and ApplicationSet CRDs
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

ArgoCD manages deployments through three custom resource definitions. The `Application` CRD is the core unit — it declares where manifests live in Git and where they should be deployed in Kubernetes. `AppProject` provides multi-tenancy boundaries. `ApplicationSet` generates many Applications from a single template, eliminating duplication across environments and clusters.

## Application CRD

The Application is the fundamental building block. It binds a Git source to a Kubernetes destination.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: invoice-pipeline-prod
  namespace: argocd                   # Always in argocd namespace
  finalizers:
    - resources-finalizer.argocd.argoproj.io  # Cascade-delete resources on app delete
spec:
  # Which AppProject governs this app
  project: invoice-pipeline

  # Source: where manifests live
  source:
    repoURL: https://github.com/myorg/invoice-pipeline-gitops
    targetRevision: main              # branch, tag, or commit SHA
    path: environments/prod           # directory within repo

    # If using Helm:
    helm:
      releaseName: invoice-pipeline
      valueFiles:
        - values-prod.yaml
      parameters:
        - name: image.tag
          value: "1.2.3"

  # Destination: where to deploy
  destination:
    server: https://kubernetes.default.svc   # in-cluster
    namespace: invoice-pipeline-prod

  # Sync policy
  syncPolicy:
    automated:
      prune: true        # remove resources deleted from Git
      selfHeal: true     # revert manual kubectl changes
    syncOptions:
      - CreateNamespace=true       # create namespace if missing
      - ServerSideApply=true       # use server-side apply (recommended)
      - PrunePropagationPolicy=foreground
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  # Ignore differences (e.g. operator-managed fields)
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas             # HPA manages replicas
```

## AppProject CRD

AppProject is the multi-tenancy boundary. It restricts which repos, clusters, namespaces, and resource kinds an Application (and its users) can touch.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: invoice-pipeline
  namespace: argocd
spec:
  description: UberEats Invoice Processing Pipeline

  # Allowed Git source repos
  sourceRepos:
    - https://github.com/myorg/invoice-pipeline-gitops
    - https://github.com/myorg/helm-charts

  # Allowed destination clusters and namespaces
  destinations:
    - server: https://kubernetes.default.svc
      namespace: invoice-pipeline-dev
    - server: https://kubernetes.default.svc
      namespace: invoice-pipeline-prod

  # Allowed Kubernetes resource types
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"

  # Deny specific resource types
  namespaceResourceBlacklist:
    - group: ""
      kind: ResourceQuota   # prevent quota manipulation

  # Roles within the project
  roles:
    - name: developer
      description: Read-only sync access
      policies:
        - p, proj:invoice-pipeline:developer, applications, get, invoice-pipeline/*, allow
        - p, proj:invoice-pipeline:developer, applications, sync, invoice-pipeline/*, allow
      groups:
        - myorg:developers
    - name: admin
      description: Full access within project
      policies:
        - p, proj:invoice-pipeline:admin, applications, *, invoice-pipeline/*, allow
      groups:
        - myorg:platform-team

  # Sync windows: restrict when syncs can happen
  syncWindows:
    - kind: deny
      schedule: "0 22 * * 1-5"   # deny weekday nights 22:00
      duration: 8h
      applications:
        - "*"
    - kind: allow
      schedule: "0 8 * * 1-5"    # allow weekday business hours
      duration: 14h
      applications:
        - "*"
```

## ApplicationSet CRD

ApplicationSet generates multiple Application resources from a single template using generators. Essential for managing many environments or clusters without duplication.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: invoice-pipeline-environments
  namespace: argocd
spec:
  # Prevent accidental deletion of child apps
  preservedFields:
    annotations:
      - argocd.argoproj.io/managed-by-application-set

  generators:
    # List generator: explicit environment list
    - list:
        elements:
          - env: dev
            cluster: https://kubernetes.default.svc
            namespace: invoice-pipeline-dev
            revision: develop
          - env: staging
            cluster: https://kubernetes.default.svc
            namespace: invoice-pipeline-staging
            revision: release/1.2
          - env: prod
            cluster: https://prod-cluster.example.com
            namespace: invoice-pipeline-prod
            revision: main

  template:
    metadata:
      name: "invoice-pipeline-{{env}}"
      namespace: argocd
    spec:
      project: invoice-pipeline
      source:
        repoURL: https://github.com/myorg/invoice-pipeline-gitops
        targetRevision: "{{revision}}"
        path: "environments/{{env}}"
      destination:
        server: "{{cluster}}"
        namespace: "{{namespace}}"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

## Generator Types

| Generator | Use Case |
|-----------|---------|
| `list` | Explicit list of environments/clusters |
| `clusters` | All clusters registered in ArgoCD |
| `git` | Directories or files in a Git repo |
| `matrix` | Combine two generators (e.g. clusters × apps) |
| `merge` | Merge values from multiple generators |
| `pullRequest` | One app per open PR (preview environments) |
| `scmProvider` | Scan GitHub/GitLab orgs for repos |

## Resource Tracking Methods

| Method | Annotation/Label | Recommended When |
|--------|-----------------|-----------------|
| `label` | `app.kubernetes.io/instance` | Default, widely compatible |
| `annotation` | `argocd.argoproj.io/tracking-id` | Multiple apps share resources |
| `annotation+label` | Both | Backward compatibility |

## Common Mistakes

### Wrong — Application in wrong namespace

```yaml
metadata:
  name: my-app
  namespace: default   # Applications must be in argocd namespace
```

### Correct

```yaml
metadata:
  name: my-app
  namespace: argocd
```

## Related

- [what-is-argocd.md](what-is-argocd.md)
- [sync-phases.md](sync-phases.md)
- [patterns/app-of-apps.md](../patterns/app-of-apps.md)
- [patterns/multi-env-promotion.md](../patterns/multi-env-promotion.md)
