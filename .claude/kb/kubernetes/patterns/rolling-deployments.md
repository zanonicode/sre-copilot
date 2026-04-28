# Rolling Deployments

> **Purpose**: Ship new container images with zero downtime and instant rollback capability
> **MCP Validated**: 2026-04-22

## When to Use

- Every production image update to stateless workloads
- When you need instant rollback without re-deploying the old image
- Canary testing by running two Deployments at different replica counts temporarily

## Implementation

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: invoice-extractor
  namespace: pipeline
  annotations:
    deployment.kubernetes.io/revision: "1"
spec:
  replicas: 4
  revisionHistoryLimit: 5         # Keep last 5 ReplicaSets for rollback
  selector:
    matchLabels:
      app: invoice-extractor
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0           # Never reduce capacity below 4
      maxSurge: 1                 # Allow 5 pods total during rollout
  template:
    metadata:
      labels:
        app: invoice-extractor
      annotations:
        # Force rollout even with same image tag (e.g. latest)
        rollme: "{{ randAlphaNum 5 | quote }}"
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: extractor
          image: gcr.io/invoice-pipeline-prod/extractor:v2.1.0
          lifecycle:
            preStop:
              exec:
                # Drain in-flight requests before SIGTERM
                command: ["/bin/sh", "-c", "sleep 5"]
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8080
            periodSeconds: 5
            failureThreshold: 3
```

## Rollout Commands

```bash
# Trigger rollout with new image
kubectl set image deployment/invoice-extractor \
  extractor=gcr.io/invoice-pipeline-prod/extractor:v2.2.0 \
  -n pipeline

# Watch rollout progress (blocks until complete or timeout)
kubectl rollout status deployment/invoice-extractor -n pipeline --timeout=5m

# View revision history
kubectl rollout history deployment/invoice-extractor -n pipeline

# Inspect what changed in revision 3
kubectl rollout history deployment/invoice-extractor --revision=3 -n pipeline

# Instant rollback to previous revision
kubectl rollout undo deployment/invoice-extractor -n pipeline

# Rollback to specific revision
kubectl rollout undo deployment/invoice-extractor --to-revision=2 -n pipeline

# Pause mid-rollout (manual canary)
kubectl rollout pause deployment/invoice-extractor -n pipeline

# Resume after verification
kubectl rollout resume deployment/invoice-extractor -n pipeline
```

## Configuration

| Setting | Recommended | Description |
|---------|-------------|-------------|
| `maxUnavailable` | `0` | Prevent capacity drop during rollout |
| `maxSurge` | `1` (or 25%) | Extra pods added during rollout |
| `revisionHistoryLimit` | `5` | ReplicaSets retained for rollback |
| `terminationGracePeriodSeconds` | `30` | Time for in-flight requests to drain |

## Example Usage

```bash
# CI/CD: update image and wait for healthy rollout
IMAGE="gcr.io/invoice-pipeline-prod/extractor:${GIT_SHA}"
kubectl set image deployment/invoice-extractor extractor="${IMAGE}" -n pipeline
kubectl rollout status deployment/invoice-extractor -n pipeline --timeout=10m || \
  kubectl rollout undo deployment/invoice-extractor -n pipeline
```

## See Also

- [patterns/health-checks.md](health-checks.md)
- [patterns/horizontal-pod-autoscaling.md](horizontal-pod-autoscaling.md)
- [concepts/deployments.md](../concepts/deployments.md)
