# Deployments

> **Purpose**: Declarative controller for managing stateless pod replicas with rolling updates
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

A Deployment describes the desired state (image, replicas, update strategy) and the control plane continuously reconciles reality to match it. It owns a ReplicaSet which owns the Pods. Deployments support rolling updates and instant rollbacks via revision history.

## The Pattern

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: invoice-extractor
  namespace: pipeline
  labels:
    app: invoice-extractor
spec:
  replicas: 3
  selector:
    matchLabels:
      app: invoice-extractor
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # Extra pods during rollout
      maxUnavailable: 0    # No downtime: always full capacity
  template:
    metadata:
      labels:
        app: invoice-extractor
    spec:
      serviceAccountName: invoice-extractor-sa
      terminationGracePeriodSeconds: 30
      containers:
        - name: extractor
          image: gcr.io/invoice-pipeline-prod/extractor:v2.1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2000m"
              memory: "1Gi"
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 15
```

## Quick Reference

| Input | Output | Notes |
|-------|--------|-------|
| `kubectl apply -f deploy.yaml` | RollingUpdate starts | Old RS scales down, new RS up |
| `kubectl rollout undo deploy/name` | Previous revision restored | Up to `revisionHistoryLimit` (default 10) |
| `kubectl scale deploy/name --replicas=5` | Immediate replica change | Overridden by HPA if active |

## Update Strategy Options

| Strategy | Behaviour | When to Use |
|----------|-----------|-------------|
| `RollingUpdate` | Gradual pod replacement | Default; zero-downtime |
| `Recreate` | Kill all pods, then create new | Singletons; acceptable downtime |

## Common Mistakes

### Wrong

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 50%   # Half the fleet gone during rollout
    maxSurge: 0
```

### Correct

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0     # Always keep full capacity
    maxSurge: 1           # One extra pod during update
```

## Rollout Commands

```bash
# Watch rollout progress
kubectl rollout status deployment/invoice-extractor -n pipeline

# View revision history
kubectl rollout history deployment/invoice-extractor -n pipeline

# Roll back one revision
kubectl rollout undo deployment/invoice-extractor -n pipeline

# Roll back to specific revision
kubectl rollout undo deployment/invoice-extractor --to-revision=3 -n pipeline
```

## Related

- [Pods](pods.md)
- [Rolling Deployments](../patterns/rolling-deployments.md)
- [Horizontal Pod Autoscaling](../patterns/horizontal-pod-autoscaling.md)
- [Health Checks](../patterns/health-checks.md)
