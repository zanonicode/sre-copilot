# Kubernetes Knowledge Base

> **Purpose**: Container orchestration for local dev (minikube), GKE, and multi-service workloads
> **MCP Validated**: 2026-04-22

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/pods.md](concepts/pods.md) | Smallest deployable unit; one or more containers |
| [concepts/deployments.md](concepts/deployments.md) | Declarative rollout and lifecycle management |
| [concepts/services.md](concepts/services.md) | Stable network endpoint for a set of pods |
| [concepts/namespaces.md](concepts/namespaces.md) | Virtual clusters for environment isolation |
| [concepts/configmaps-secrets.md](concepts/configmaps-secrets.md) | Externalise config and sensitive data |
| [concepts/ingress.md](concepts/ingress.md) | HTTP/S routing and TLS termination |
| [concepts/persistent-volumes.md](concepts/persistent-volumes.md) | Durable storage lifecycle decoupled from pods |
| [concepts/resource-limits.md](concepts/resource-limits.md) | CPU/memory requests and limits for scheduling |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/health-checks.md](patterns/health-checks.md) | Liveness, readiness, and startup probes |
| [patterns/rolling-deployments.md](patterns/rolling-deployments.md) | Zero-downtime rollout and rollback strategy |
| [patterns/horizontal-pod-autoscaling.md](patterns/horizontal-pod-autoscaling.md) | Scale replicas on CPU/memory or custom metrics |
| [patterns/multi-container-pods.md](patterns/multi-container-pods.md) | Sidecar, ambassador, and adapter patterns |
| [patterns/job-cronjob.md](patterns/job-cronjob.md) | Batch workloads and scheduled tasks |
| [patterns/gke-workload-identity.md](patterns/gke-workload-identity.md) | Keyless GCP auth for pods via GSA/KSA binding |

### Specs (Machine-Readable)

| File | Purpose |
|------|---------|
| [specs/kubernetes-spec.yaml](specs/kubernetes-spec.yaml) | Resource defaults, limits, and GKE settings |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) - Fast lookup tables

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Declarative Config** | Desired state in YAML; control plane reconciles reality |
| **Pod** | Atomic unit sharing network namespace and volumes |
| **Control Plane** | API Server, Scheduler, etcd, Controller Manager |
| **Node** | Worker machine running kubelet + container runtime |
| **Namespace** | Logical isolation boundary for resources and RBAC |
| **Label/Selector** | Key-value tags driving scheduling and service routing |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/pods.md, concepts/deployments.md, concepts/services.md |
| **Intermediate** | concepts/configmaps-secrets.md, patterns/health-checks.md, patterns/rolling-deployments.md |
| **Advanced** | patterns/horizontal-pod-autoscaling.md, patterns/gke-workload-identity.md, concepts/persistent-volumes.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| pipeline-architect | patterns/gke-workload-identity.md, concepts/services.md | Design GKE-hosted pipeline services |
| infra-deployer | specs/kubernetes-spec.yaml, concepts/resource-limits.md | Provision GKE workloads via Terraform |
| python-developer | patterns/health-checks.md, patterns/multi-container-pods.md | Add probes and sidecar logging |
| dataops-builder | patterns/job-cronjob.md, patterns/horizontal-pod-autoscaling.md | Schedule batch jobs and autoscale |

---

## Project Context

This pipeline runs on Cloud Run Functions (serverless). Kubernetes applies when:

| Scenario | Relevant KB Files |
|----------|------------------|
| Local dev with minikube | concepts/pods.md, concepts/deployments.md |
| Migrate a function to GKE | patterns/rolling-deployments.md, patterns/gke-workload-identity.md |
| Multi-service orchestration | concepts/services.md, concepts/ingress.md |
| Scheduled batch processing | patterns/job-cronjob.md |
| Scale under invoice burst | patterns/horizontal-pod-autoscaling.md |
