# Pods

> **Purpose**: Smallest deployable unit in Kubernetes — one or more tightly-coupled containers
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

A Pod wraps one or more containers that share a network namespace (same IP, port space) and optionally storage volumes. Pods are ephemeral; controllers (Deployment, Job) manage their lifecycle. You rarely create bare Pods in production — use a Deployment instead.

## The Pattern

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: invoice-processor
  namespace: pipeline
  labels:
    app: invoice-processor
    version: "1.0"
spec:
  serviceAccountName: invoice-sa        # Workload Identity SA
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
  containers:
    - name: processor
      image: gcr.io/invoice-pipeline-prod/processor:v1.2.3
      ports:
        - containerPort: 8080
      resources:
        requests:
          cpu: "250m"
          memory: "256Mi"
        limits:
          cpu: "1000m"
          memory: "512Mi"
      env:
        - name: GOOGLE_CLOUD_PROJECT
          value: "invoice-pipeline-prod"
      readinessProbe:
        httpGet:
          path: /health
          port: 8080
        initialDelaySeconds: 5
        periodSeconds: 10
```

## Quick Reference

| Input | Output | Notes |
|-------|--------|-------|
| YAML manifest | Running container(s) | Pods are mortal; use Deployments |
| `kubectl apply -f pod.yaml` | Pod scheduled to node | Scheduler picks node by resources |
| Pod deletion | Containers terminated | No restart unless controller recreates |

## Common Mistakes

### Wrong

```yaml
# Bare Pod — no controller, no restart on failure
apiVersion: v1
kind: Pod
metadata:
  name: processor
spec:
  containers:
    - name: processor
      image: processor:latest   # mutable tag, unpredictable
```

### Correct

```yaml
# Use Deployment for lifecycle management + pinned image tag
apiVersion: apps/v1
kind: Deployment
metadata:
  name: processor
spec:
  replicas: 2
  selector:
    matchLabels:
      app: processor
  template:
    metadata:
      labels:
        app: processor
    spec:
      containers:
        - name: processor
          image: gcr.io/project/processor:v1.2.3  # pinned
```

## Pod Lifecycle States

| Phase | Meaning |
|-------|---------|
| Pending | Scheduled, image pulling or waiting for resources |
| Running | At least one container running |
| Succeeded | All containers exited 0 (Job pods) |
| Failed | At least one container exited non-zero |
| Unknown | Node communication lost |

## Related

- [Deployments](deployments.md)
- [Resource Limits](resource-limits.md)
- [Health Checks](../patterns/health-checks.md)
- [Multi-Container Pods](../patterns/multi-container-pods.md)
