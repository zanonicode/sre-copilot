# Resource Limits

> **Purpose**: CPU/memory requests and limits that drive scheduling decisions and runtime enforcement
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

Kubernetes uses two values per resource: `requests` (what the scheduler reserves on a node) and `limits` (the runtime ceiling). CPU over-limit is throttled; memory over-limit triggers OOMKill. Setting requests too low causes CPU starvation; setting limits too low causes unnecessary OOMKills. Always set both for production workloads.

## The Pattern

```yaml
resources:
  requests:
    cpu: "500m"       # 0.5 vCPU reserved for scheduling
    memory: "256Mi"   # 256 MiB reserved on node
  limits:
    cpu: "2000m"      # 2 vCPU hard cap (throttled, not killed)
    memory: "512Mi"   # 512 MiB hard cap (OOMKilled if exceeded)
```

### LimitRange — Set Namespace Defaults

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: pipeline-limits
  namespace: pipeline
spec:
  limits:
    - type: Container
      default:            # Applied when limits not specified
        cpu: "1000m"
        memory: "512Mi"
      defaultRequest:     # Applied when requests not specified
        cpu: "250m"
        memory: "128Mi"
      max:                # Hard ceiling for the namespace
        cpu: "4000m"
        memory: "4Gi"
      min:
        cpu: "50m"
        memory: "32Mi"
```

### ResourceQuota — Cap Total Namespace Consumption

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: pipeline-quota
  namespace: pipeline
spec:
  hard:
    requests.cpu: "10"        # Total requested CPU across all pods
    requests.memory: "8Gi"
    limits.cpu: "20"
    limits.memory: "16Gi"
    pods: "50"                # Max pod count
    persistentvolumeclaims: "10"
```

## Quick Reference

| Scenario | requests | limits | Reason |
|----------|----------|--------|--------|
| Stable API server | = limits | 2x requests | Guaranteed QoS, predictable |
| Batch job (burst) | low | high | Burstable QoS, uses slack |
| Memory-safe service | measured | 1.5x requests | Avoid OOMKill on spikes |
| Dev/test pod | 50m/64Mi | 500m/256Mi | Save cluster resources |

## QoS Classes (affects eviction priority)

| Class | Condition | Eviction Risk |
|-------|-----------|---------------|
| `Guaranteed` | requests == limits for all containers | Last evicted |
| `Burstable` | requests < limits (at least one container) | Middle |
| `BestEffort` | No requests or limits set | First evicted |

## Common Mistakes

### Wrong

```yaml
# No limits — pod can consume all node memory, evicting neighbours
resources:
  requests:
    memory: "256Mi"
# limits: {}  ← missing
```

### Correct

```yaml
# Always set both; memory limit ≥ 1.5x request to absorb spikes
resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "1000m"
    memory: "384Mi"
```

## Related

- [Pods](pods.md)
- [Deployments](deployments.md)
- [Horizontal Pod Autoscaling](../patterns/horizontal-pod-autoscaling.md)
- [Health Checks](../patterns/health-checks.md)
