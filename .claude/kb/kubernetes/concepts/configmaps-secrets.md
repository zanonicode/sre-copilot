# ConfigMaps and Secrets

> **Purpose**: Externalise configuration and sensitive data from container images
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

ConfigMaps store non-sensitive key-value data (environment variables, config files). Secrets store sensitive data (API keys, passwords) as base64-encoded values. Both are injected into pods as environment variables or mounted as files. On GKE, use External Secrets Operator or Workload Identity + Secret Manager for production secrets instead of native Secrets (which are only base64, not encrypted at rest by default without KMS).

## The Pattern

```yaml
# ConfigMap — non-sensitive config
apiVersion: v1
kind: ConfigMap
metadata:
  name: pipeline-config
  namespace: pipeline
data:
  GCP_REGION: "us-central1"
  LOG_LEVEL: "INFO"
  MAX_RETRIES: "3"
  # Multi-line config file
  app.properties: |
    batch.size=100
    timeout.seconds=30
---
# Secret — sensitive values (base64 in YAML, plaintext via kubectl)
apiVersion: v1
kind: Secret
metadata:
  name: pipeline-secrets
  namespace: pipeline
type: Opaque
stringData:                          # stringData auto-encodes to base64
  LANGFUSE_PUBLIC_KEY: "pk-lf-..."
  LANGFUSE_SECRET_KEY: "sk-lf-..."
---
# Inject into Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: invoice-extractor
  namespace: pipeline
spec:
  template:
    spec:
      containers:
        - name: extractor
          image: gcr.io/project/extractor:v1.0.0
          envFrom:
            - configMapRef:
                name: pipeline-config       # All keys as env vars
          env:
            - name: LANGFUSE_PUBLIC_KEY
              valueFrom:
                secretKeyRef:
                  name: pipeline-secrets
                  key: LANGFUSE_PUBLIC_KEY
          volumeMounts:
            - name: config-volume
              mountPath: /etc/config
      volumes:
        - name: config-volume
          configMap:
            name: pipeline-config
            items:
              - key: app.properties
                path: app.properties
```

## Quick Reference

| Input | Output | Notes |
|-------|--------|-------|
| `kubectl create configmap` | ConfigMap object | Or from file: `--from-file=app.conf` |
| `kubectl create secret generic` | Secret object | Use `--from-literal` or `--from-file` |
| `envFrom: configMapRef` | All keys as env vars | Flat namespace; watch for key collisions |
| Volume mount | File at mountPath | Updates propagate within ~1 min |

## GKE Production Pattern (Secret Manager)

```yaml
# Use External Secrets Operator with GCP Secret Manager
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: pipeline-secrets
  namespace: pipeline
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: gcp-secret-manager
  target:
    name: pipeline-secrets
  data:
    - secretKey: LANGFUSE_SECRET_KEY
      remoteRef:
        key: langfuse-secret-key        # GCP Secret Manager name
```

## Common Mistakes

### Wrong

```yaml
env:
  - name: API_KEY
    value: "sk-abc123"   # Hardcoded in manifest — committed to git
```

### Correct

```yaml
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: api-secrets
        key: API_KEY
```

## Related

- [GKE Workload Identity](../patterns/gke-workload-identity.md)
- [Namespaces](namespaces.md)
- [Pods](pods.md)
