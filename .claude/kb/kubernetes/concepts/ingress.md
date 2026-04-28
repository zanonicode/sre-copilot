# Ingress

> **Purpose**: HTTP/S routing rules and TLS termination for external traffic entering the cluster
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

An Ingress resource defines routing rules (host/path → Service) and is implemented by an Ingress Controller (e.g., nginx, GKE's built-in GCLB). It consolidates external access through a single load balancer instead of one `LoadBalancer` Service per workload. On GKE, the default controller provisions a Google Cloud HTTP(S) Load Balancer automatically.

## The Pattern

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: pipeline-ingress
  namespace: pipeline
  annotations:
    kubernetes.io/ingress.class: "gce"               # GKE built-in GCLB
    networking.gke.io/managed-certificates: "pipeline-cert"
    kubernetes.io/ingress.allow-http: "false"         # Force HTTPS
spec:
  rules:
    - host: api.invoice-pipeline.internal
      http:
        paths:
          - path: /extract
            pathType: Prefix
            backend:
              service:
                name: data-extractor-svc
                port:
                  number: 80
          - path: /classify
            pathType: Prefix
            backend:
              service:
                name: invoice-classifier-svc
                port:
                  number: 80
  defaultBackend:
    service:
      name: fallback-svc
      port:
        number: 80
---
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: pipeline-cert
  namespace: pipeline
spec:
  domains:
    - api.invoice-pipeline.internal
```

## Quick Reference

| Field | Purpose | Notes |
|-------|---------|-------|
| `host` | Hostname-based routing | Omit for path-only routing |
| `pathType: Prefix` | Match prefix `/api` → `/api/v1`, `/api/v2` | `Exact` for strict matching |
| `pathType: Exact` | Match only `/health`, not `/health/ready` | Use for status endpoints |
| `defaultBackend` | Catch-all when no rule matches | 404 fallback service |

## Common Mistakes

### Wrong

```yaml
# No host — all traffic on this IP hits the same backend
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: everything-svc
                port:
                  number: 80
```

### Correct

```yaml
# Separate host rules per service
spec:
  rules:
    - host: api.invoice-pipeline.internal
      http:
        paths:
          - path: /extract
            pathType: Prefix
            backend:
              service:
                name: data-extractor-svc
                port:
                  number: 80
    - host: admin.invoice-pipeline.internal
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: admin-svc
                port:
                  number: 80
```

## GKE-Specific Annotations

| Annotation | Purpose |
|------------|---------|
| `kubernetes.io/ingress.class: "gce"` | Use GKE's native GCLB controller |
| `kubernetes.io/ingress.allow-http: "false"` | Redirect HTTP → HTTPS |
| `networking.gke.io/managed-certificates` | Google-managed TLS cert |
| `cloud.google.com/backend-config` | Custom health check, CDN, IAP |

## Related

- [Services](services.md)
- [Namespaces](namespaces.md)
- [GKE Workload Identity](../patterns/gke-workload-identity.md)
