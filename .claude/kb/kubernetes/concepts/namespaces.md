# Namespaces

> **Purpose**: Virtual cluster partitions for environment isolation, RBAC scoping, and quota enforcement
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

Namespaces divide a single Kubernetes cluster into isolated virtual clusters. Resources within a namespace share a DNS subdomain, can be governed by RBAC policies, and have ResourceQuotas applied. Cross-namespace traffic is allowed by default but can be blocked with NetworkPolicies.

## The Pattern

```yaml
# Create namespace with labels
apiVersion: v1
kind: Namespace
metadata:
  name: pipeline
  labels:
    env: production
    team: data-engineering
---
# ResourceQuota — prevent runaway resource consumption
apiVersion: v1
kind: ResourceQuota
metadata:
  name: pipeline-quota
  namespace: pipeline
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    limits.cpu: "16"
    limits.memory: 32Gi
    pods: "50"
    services: "10"
---
# LimitRange — defaults for pods that don't specify requests/limits
apiVersion: v1
kind: LimitRange
metadata:
  name: pipeline-defaults
  namespace: pipeline
spec:
  limits:
    - type: Container
      default:
        cpu: "500m"
        memory: "256Mi"
      defaultRequest:
        cpu: "100m"
        memory: "128Mi"
```

## Quick Reference

| Input | Output | Notes |
|-------|--------|-------|
| `kubectl create namespace pipeline` | Namespace created | Or use declarative YAML |
| `kubectl get all -n pipeline` | All resources in namespace | Safer than cluster-wide get |
| `kubectl config set-context --current --namespace=pipeline` | Default namespace set | Avoid typing `-n` each time |

## Common Namespace Strategy

| Namespace | Purpose |
|-----------|---------|
| `default` | Avoid — use named namespaces |
| `kube-system` | Kubernetes system components |
| `pipeline` | Invoice pipeline workloads |
| `monitoring` | Prometheus, Grafana |
| `ingress-nginx` | Ingress controller |

## Common Mistakes

### Wrong

```bash
# Deploying everything to default namespace
kubectl apply -f deploy.yaml   # Goes to 'default'
```

### Correct

```bash
# Always specify namespace or set context default
kubectl apply -f deploy.yaml -n pipeline
# Or embed namespace in manifest metadata
```

## System Namespaces (Never Modify)

| Namespace | Contents |
|-----------|----------|
| `kube-system` | API server, scheduler, etcd, coredns |
| `kube-public` | Publicly readable bootstrap configmap |
| `kube-node-lease` | Node heartbeat lease objects |

## Related

- [Services](services.md)
- [Resource Limits](resource-limits.md)
- [GKE Workload Identity](../patterns/gke-workload-identity.md)
