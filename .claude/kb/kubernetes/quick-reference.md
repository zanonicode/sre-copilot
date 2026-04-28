# Kubernetes Quick Reference

> Fast lookup tables. For code examples, see linked files.
> **MCP Validated**: 2026-04-22

## Core Object Types

| Object | Scope | Purpose |
|--------|-------|---------|
| Pod | Namespaced | Smallest deployable unit |
| Deployment | Namespaced | Stateless workload lifecycle |
| StatefulSet | Namespaced | Ordered, persistent-identity workloads |
| DaemonSet | Namespaced | One pod per node (logging, metrics) |
| Job / CronJob | Namespaced | One-shot / scheduled batch |
| Service | Namespaced | Stable network endpoint |
| Ingress | Namespaced | HTTP/S routing + TLS |
| ConfigMap | Namespaced | Non-sensitive config |
| Secret | Namespaced | Sensitive data (base64-encoded) |
| PVC / PV | Namespaced / Cluster | Durable storage |
| HPA | Namespaced | Horizontal pod autoscaler |
| Namespace | Cluster | Isolation boundary |

## kubectl Cheat Sheet

| Task | Command |
|------|---------|
| Apply manifest | `kubectl apply -f manifest.yaml` |
| Delete resource | `kubectl delete -f manifest.yaml` |
| Get pods | `kubectl get pods -n <ns>` |
| Describe pod | `kubectl describe pod <name> -n <ns>` |
| Logs | `kubectl logs <pod> -c <container> -f` |
| Exec into pod | `kubectl exec -it <pod> -- /bin/sh` |
| Port-forward | `kubectl port-forward svc/<svc> 8080:80` |
| Scale deployment | `kubectl scale deploy/<name> --replicas=3` |
| Rollout status | `kubectl rollout status deploy/<name>` |
| Rollout undo | `kubectl rollout undo deploy/<name>` |
| Apply secret | `kubectl create secret generic <n> --from-literal=k=v` |
| Get events | `kubectl get events --sort-by='.lastTimestamp'` |

## Resource Requests vs Limits

| Field | Scheduler Uses | Runtime Enforces | Set To |
|-------|---------------|-----------------|--------|
| `requests.cpu` | Yes | No | Typical steady-state |
| `limits.cpu` | No | Yes (throttle) | 2-4x request |
| `requests.memory` | Yes | No | Typical steady-state |
| `limits.memory` | No | Yes (OOMKill) | 1.5x request |

## Service Types

| Type | Accessibility | Use Case |
|------|--------------|----------|
| ClusterIP | In-cluster only | Default; internal microservices |
| NodePort | Node IP + port | Dev/test external access |
| LoadBalancer | Cloud LB (external IP) | Production GKE ingress |
| ExternalName | DNS alias | Point to external service |

## Probe Types

| Probe | Failure Action | Use For |
|-------|---------------|---------|
| `livenessProbe` | Restart container | Detect deadlock / hung process |
| `readinessProbe` | Remove from Service endpoints | Wait until app is ready |
| `startupProbe` | Restart if not ready in time | Slow-starting apps |

## GKE-Specific Defaults

| Setting | Default | Recommendation |
|---------|---------|---------------|
| Node pool machine type | e2-medium | e2-standard-4 for ML workloads |
| Autoscaling | Off | Enable cluster autoscaler |
| Workload Identity | Off | Enable; required for GCP API access |
| Release channel | None | `regular` for stability |
| Max pods per node | 110 | 64 for large clusters |

## Decision Matrix

| Use Case | Choose |
|----------|--------|
| Stateless API / processor | Deployment |
| Ordered stateful DB | StatefulSet |
| One pod per node | DaemonSet |
| One-off batch job | Job |
| Recurring pipeline batch | CronJob |
| Internal service discovery | ClusterIP Service |
| GCP API calls from pod | Workload Identity |
| Burst traffic scaling | HPA + cluster autoscaler |

## Common Pitfalls

| Avoid | Do Instead |
|-------|------------|
| No resource limits | Always set requests AND limits |
| `latest` image tag | Pin to digest or semver tag |
| Secrets in env vars from ConfigMap | Use Secret objects |
| Single replica in production | min 2 replicas for HA |
| No readiness probe | Add readinessProbe before going live |
| Default namespace for everything | Use namespaces per environment |
| Running as root | Set `runAsNonRoot: true` |

## Related Documentation

| Topic | Path |
|-------|------|
| Getting Started | `concepts/pods.md` |
| GKE Auth | `patterns/gke-workload-identity.md` |
| Full Index | `index.md` |
