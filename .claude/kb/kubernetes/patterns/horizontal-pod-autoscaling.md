# Horizontal Pod Autoscaling

> **Purpose**: Automatically scale replica count based on CPU, memory, or custom metrics
> **MCP Validated**: 2026-04-22

## When to Use

- Workloads with variable load (e.g. invoice ingestion spikes during business hours)
- When manual scaling is too slow to react to traffic changes
- Combined with rolling deployments to maintain uptime during scale-out

## Implementation

```yaml
# HPA v2 — supports CPU, memory, and custom/external metrics
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: invoice-extractor-hpa
  namespace: pipeline
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: invoice-extractor
  minReplicas: 2      # Always at least 2 for HA
  maxReplicas: 20     # Cap to protect downstream services

  metrics:
    # Scale on CPU utilisation relative to requests
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60   # Target 60% CPU; scale out above, in below

    # Scale on memory utilisation relative to requests
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 70

  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30   # React quickly to spikes
      policies:
        - type: Pods
          value: 4           # Add up to 4 pods per scale event
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300  # Wait 5m before scaling down (avoid flapping)
      policies:
        - type: Percent
          value: 25          # Remove at most 25% of replicas per event
          periodSeconds: 60
```

### Pub/Sub Queue-Depth Autoscaling (KEDA)

```yaml
# KEDA ScaledObject — scale on undelivered Pub/Sub messages
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: extractor-pubsub-scaler
  namespace: pipeline
spec:
  scaleTargetRef:
    name: invoice-extractor
  minReplicaCount: 0       # Scale to zero when queue empty
  maxReplicaCount: 50
  triggers:
    - type: gcp-pubsub
      metadata:
        subscriptionSize: "100"    # One replica per 100 messages
        subscriptionName: "invoice-extract-sub"
        credentialsFromEnv: GOOGLE_APPLICATION_CREDENTIALS
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `minReplicas` | 1 | Floor — never go below (use ≥2 for HA) |
| `maxReplicas` | — | Required; cap to protect downstream |
| `averageUtilization` | — | % of resource request to target |
| `stabilizationWindowSeconds` (down) | 300 | Prevents flapping on scale-in |
| `stabilizationWindowSeconds` (up) | 0 | Default: react immediately |

## Example Usage

```bash
# View current HPA state
kubectl get hpa invoice-extractor-hpa -n pipeline

# Describe with current metrics
kubectl describe hpa invoice-extractor-hpa -n pipeline

# Watch live scaling events
kubectl get events -n pipeline --field-selector reason=SuccessfulRescale -w
```

## See Also

- [patterns/rolling-deployments.md](rolling-deployments.md)
- [concepts/resource-limits.md](../concepts/resource-limits.md)
- [concepts/deployments.md](../concepts/deployments.md)
