# What is ArgoCD

> **Purpose**: Understand ArgoCD's role, architecture, and GitOps principles
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

ArgoCD is a declarative, GitOps continuous delivery tool for Kubernetes. It continuously monitors Git repositories containing Kubernetes manifests (plain YAML, Helm charts, Kustomize, Jsonnet) and reconciles the live cluster state to match the desired state declared in Git. When drift is detected, ArgoCD either auto-syncs or alerts operators, depending on policy.

ArgoCD runs inside the cluster as a set of Kubernetes controllers, exposing a web UI, CLI, and REST/gRPC API. It reached v3.x in 2025, with v3.0 introducing fine-grained RBAC enforcement for application resources and mandatory logs RBAC.

## GitOps Principles

| Principle | How ArgoCD Implements It |
|-----------|--------------------------|
| **Git as source of truth** | Every Application points to a Git repo path |
| **Declarative desired state** | Kubernetes manifests define what should exist |
| **Automated reconciliation** | Controllers watch for drift and sync on change |
| **Auditable history** | Every sync is tied to a Git commit SHA |

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                     ArgoCD Control Plane                    │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  API Server │  │ Repo Server  │  │  Application      │  │
│  │  (UI/CLI)   │  │ (git clone,  │  │  Controller       │  │
│  │             │  │  template)   │  │  (reconcile loop) │  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
│         │                │                    │             │
│  ┌─────────────┐  ┌──────────────┐            │             │
│  │  Dex (SSO)  │  │  Redis       │            │             │
│  │  optional   │  │  (cache)     │            │             │
│  └─────────────┘  └──────────────┘            │             │
└───────────────────────────────────────────────┼─────────────┘
                                                │ kubectl apply
                                    ┌───────────▼──────────┐
                                    │   Target Cluster(s)  │
                                    │   (GKE, in-cluster,  │
                                    │    external)         │
                                    └──────────────────────┘
```

**Key components:**

| Component | Role |
|-----------|------|
| API Server | Serves UI, CLI, and REST API; enforces RBAC |
| Repo Server | Clones Git repos, renders templates (Helm, Kustomize) |
| Application Controller | Reconciliation loop — compares desired vs live state |
| Dex | Optional OIDC provider for SSO (Google, GitHub, Okta) |
| Redis | Caches repo and cluster state for performance |

## Core Resource Types

| CRD | Scope | Purpose |
|-----|-------|---------|
| `Application` | Namespaced | Single app deployment spec |
| `AppProject` | Namespaced | RBAC and routing boundary |
| `ApplicationSet` | Namespaced | Templated generator for multiple Applications |

## Installation (Helm — recommended for production)

```yaml
# values.yaml for ArgoCD Helm chart
global:
  domain: argocd.example.com

server:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod

configs:
  params:
    # Disable TLS termination at ArgoCD (handled by ingress)
    server.insecure: true
  cm:
    # Enable ApplicationSet controller
    application.resourceTrackingMethod: annotation

redis-ha:
  enabled: true  # HA mode for production

controller:
  replicas: 1    # Increase for large clusters

repoServer:
  replicas: 2    # Multiple repo servers for parallelism
```

```bash
# Install ArgoCD via Helm
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version 7.x \
  -f values.yaml
```

## Version Notes (v2 vs v3)

| Behavior | v2.x | v3.x |
|----------|------|------|
| Application resource RBAC | Inherited from app | Fine-grained, explicit |
| Logs RBAC | Optional enforcement | Enforced by default |
| `update/*` on managed resources | Allowed by app `update` | Requires explicit `update/*` policy |
| Migration flag | N/A | `server.rbac.disableApplicationFineGrainedRBACInheritance: false` |

## Common Mistakes

### Wrong — pointing to a mutable branch without selfHeal

```yaml
spec:
  source:
    targetRevision: main  # mutable
  syncPolicy:
    automated:
      prune: true
      # selfHeal omitted — manual kubectl changes persist
```

### Correct — automated sync with selfHeal for production

```yaml
spec:
  source:
    targetRevision: main
  syncPolicy:
    automated:
      prune: true
      selfHeal: true    # reverts any manual cluster changes
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

## Related

- [application-model.md](application-model.md)
- [sync-phases.md](sync-phases.md)
- [patterns/gke-integration.md](../patterns/gke-integration.md)
