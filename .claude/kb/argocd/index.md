# ArgoCD Knowledge Base

> **Purpose**: GitOps continuous delivery for Kubernetes on GKE
> **MCP Validated**: 2026-04-22

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/what-is-argocd.md](concepts/what-is-argocd.md) | ArgoCD fundamentals, architecture, and GitOps principles |
| [concepts/application-model.md](concepts/application-model.md) | Application, AppProject, ApplicationSet CRDs |
| [concepts/sync-phases.md](concepts/sync-phases.md) | Sync lifecycle, hooks, waves, and health checks |
| [concepts/rbac-and-security.md](concepts/rbac-and-security.md) | RBAC policies, AppProjects, SSO, and secret management |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/app-of-apps.md](patterns/app-of-apps.md) | Bootstrap entire environments with a root Application |
| [patterns/multi-env-promotion.md](patterns/multi-env-promotion.md) | Promote releases dev → staging → prod with GitOps |
| [patterns/helm-kustomize-integration.md](patterns/helm-kustomize-integration.md) | Combine Helm charts and Kustomize overlays |
| [patterns/gke-integration.md](patterns/gke-integration.md) | Deploy ArgoCD on GKE with Terraform, Workload Identity |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — CLI commands, field references, and decision tables

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **GitOps** | Git is the single source of truth; ArgoCD reconciles cluster to desired state |
| **Application CRD** | Declares source repo, target cluster, and sync policy |
| **AppProject** | Namespace and RBAC boundary for multi-tenant clusters |
| **ApplicationSet** | Templated generator for many Applications from one spec |
| **Sync Waves** | Ordered deployment phases within a single sync operation |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/what-is-argocd.md, concepts/application-model.md |
| **Intermediate** | concepts/sync-phases.md, patterns/app-of-apps.md |
| **Advanced** | concepts/rbac-and-security.md, patterns/multi-env-promotion.md, patterns/gke-integration.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| infra-deployer | patterns/gke-integration.md | Provision ArgoCD on GKE via Terraform |
| pipeline-architect | patterns/multi-env-promotion.md | Design promotion workflows |
| function-developer | patterns/helm-kustomize-integration.md | Package Cloud Run manifests |

---

## Project Context

This KB supports GitOps deployment of the UberEats Invoice Processing Pipeline on GCP/GKE:

| Component | ArgoCD Pattern |
|-----------|----------------|
| Cloud Run Functions (5) | Helm chart per function, Kustomize per env |
| Multi-env (dev → prod) | patterns/multi-env-promotion.md |
| Terraform-provisioned GKE | patterns/gke-integration.md |
| All services bootstrapped | patterns/app-of-apps.md |

---

## External Resources

- [ArgoCD Official Docs](https://argo-cd.readthedocs.io/en/stable/)
- [ArgoCD v2→v3 Upgrade Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/upgrading/2.14-3.0/)
- [ArgoCD on GKE — Google Cloud Blog](https://cloud.google.com/blog/products/containers-kubernetes/building-a-fleet-with-argocd-and-gke)
- [RBAC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
