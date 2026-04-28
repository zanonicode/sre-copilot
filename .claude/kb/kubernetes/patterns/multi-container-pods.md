# Multi-Container Pods

> **Purpose**: Sidecar, ambassador, and adapter patterns for co-located containers sharing network and storage
> **MCP Validated**: 2026-04-22

## When to Use

- **Sidecar**: Augment the main container without modifying it (logging agent, metrics exporter, secret refresher)
- **Ambassador**: Proxy outbound traffic (service mesh, connection pooling, mTLS)
- **Adapter**: Normalise the main container's output for a standard consumer (log format converter)
- **Init containers**: One-off setup before the main container starts (DB migration, config fetch)

## Implementation

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: invoice-extractor-with-sidecar
  namespace: pipeline
spec:
  replicas: 2
  selector:
    matchLabels:
      app: invoice-extractor
  template:
    metadata:
      labels:
        app: invoice-extractor
    spec:
      # Init container: fetch secrets from Secret Manager before main starts
      initContainers:
        - name: secret-init
          image: google/cloud-sdk:slim
          command:
            - /bin/sh
            - -c
            - |
              gcloud secrets versions access latest \
                --secret=gemini-api-key \
                --project=invoice-pipeline-prod \
                > /secrets/gemini-api-key
          volumeMounts:
            - name: secrets-vol
              mountPath: /secrets

      containers:
        # Main container
        - name: extractor
          image: gcr.io/invoice-pipeline-prod/extractor:v2.1.0
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: secrets-vol
              mountPath: /secrets
              readOnly: true
            - name: shared-logs
              mountPath: /var/log/app

        # Sidecar: ship structured logs to Cloud Logging
        - name: log-shipper
          image: fluent/fluent-bit:3.0
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
          volumeMounts:
            - name: shared-logs
              mountPath: /var/log/app
              readOnly: true
            - name: fluentbit-config
              mountPath: /fluent-bit/etc

      volumes:
        - name: secrets-vol
          emptyDir: {}
        - name: shared-logs
          emptyDir: {}
        - name: fluentbit-config
          configMap:
            name: fluentbit-config
```

## Sidecar Pattern Summary

| Pattern | What it does | Example |
|---------|-------------|---------|
| **Sidecar** | Adds capability alongside main container | Log shipper, metrics agent |
| **Ambassador** | Proxies outbound calls | Envoy for mTLS, retry logic |
| **Adapter** | Translates main container output | Prometheus exporter |
| **Init container** | Runs once before main starts | Secret fetch, DB migration |

## Configuration

| Setting | Guidance |
|---------|----------|
| Sidecar CPU/memory | Set tight limits — don't starve the main container |
| `emptyDir` volume | Shared ephemeral storage between containers in same pod |
| Init container failure | Pod stays in `Init:CrashLoopBackOff` — check `kubectl logs <pod> -c <init-name>` |

## Example Usage

```bash
# View logs from a specific container in a multi-container pod
kubectl logs invoice-extractor-abc123 -c log-shipper -n pipeline -f

# Exec into sidecar for debugging
kubectl exec -it invoice-extractor-abc123 -c log-shipper -n pipeline -- /bin/sh

# Check init container status
kubectl describe pod invoice-extractor-abc123 -n pipeline | grep -A5 "Init Containers:"
```

## See Also

- [patterns/health-checks.md](health-checks.md)
- [concepts/pods.md](../concepts/pods.md)
- [concepts/configmaps-secrets.md](../concepts/configmaps-secrets.md)
