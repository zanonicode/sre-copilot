# Services

> **Purpose**: Stable virtual IP and DNS name for a dynamic set of pods
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

Pods are ephemeral — their IPs change on restart. A Service provides a stable ClusterIP and DNS name that load-balances traffic to matching pods via label selectors. kube-proxy programs iptables/IPVS rules to route traffic. Services also expose pods externally via NodePort or LoadBalancer types.

## The Pattern

```yaml
# ClusterIP — internal service discovery
apiVersion: v1
kind: Service
metadata:
  name: invoice-extractor
  namespace: pipeline
spec:
  selector:
    app: invoice-extractor     # Must match Deployment pod labels
  ports:
    - name: http
      protocol: TCP
      port: 80           # Service port (cluster-internal)
      targetPort: 8080   # Container port
  type: ClusterIP
---
# LoadBalancer — external GKE access
apiVersion: v1
kind: Service
metadata:
  name: invoice-api
  namespace: pipeline
  annotations:
    cloud.google.com/load-balancer-type: "External"
spec:
  selector:
    app: invoice-api
  ports:
    - port: 443
      targetPort: 8443
  type: LoadBalancer
```

## Quick Reference

| Input | Output | Notes |
|-------|--------|-------|
| Service created | DNS: `<name>.<ns>.svc.cluster.local` | Resolved inside any pod |
| Selector matches pods | kube-proxy routes traffic | Endpoints auto-updated as pods come/go |
| `type: LoadBalancer` on GKE | External IP provisioned | Charges for GCP Network LB |

## Service Types

| Type | Cluster IP | External Access | Use Case |
|------|-----------|----------------|----------|
| ClusterIP | Yes | No | Internal microservice calls |
| NodePort | Yes | NodeIP:port | Dev/test; not for production |
| LoadBalancer | Yes | Cloud LB IP | Production external traffic on GKE |
| ExternalName | No | DNS alias | Map to external hostname |
| Headless (`clusterIP: None`) | No | No | StatefulSets; direct pod DNS |

## DNS Resolution Pattern

```
# From any pod in namespace "pipeline":
http://invoice-extractor/endpoint

# From any pod in any namespace:
http://invoice-extractor.pipeline.svc.cluster.local/endpoint

# Short form works within same namespace
curl invoice-extractor:80/health
```

## Common Mistakes

### Wrong

```yaml
spec:
  selector:
    app: invoice-processor    # Label value doesn't match Deployment
```

### Correct

```bash
# Verify selector matches pods before applying
kubectl get pods -n pipeline --show-labels
# Ensure 'app: invoice-extractor' appears in LABELS column
```

## Related

- [Ingress](ingress.md)
- [Namespaces](namespaces.md)
- [Deployments](deployments.md)
