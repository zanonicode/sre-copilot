# Persistent Volumes

> **Purpose**: Durable storage lifecycle decoupled from Pod lifecycles using PV/PVC/StorageClass
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

Kubernetes separates storage provisioning (PersistentVolume / StorageClass) from consumption (PersistentVolumeClaim). A PVC is a request for storage; the cluster binds it to a matching PV (static) or dynamically provisions one via a StorageClass. On GKE, the default StorageClass uses Google Persistent Disks. PVs outlive Pods — data persists across restarts unless the PVC is deleted.

## The Pattern

```yaml
# StorageClass — defines the "class" of storage (once per cluster)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: pd.csi.storage.gke.io
parameters:
  type: pd-ssd
  replication-type: regional-pd   # High availability across zones
reclaimPolicy: Retain             # Don't delete disk when PVC is deleted
volumeBindingMode: WaitForFirstConsumer  # Provision in same zone as pod
---
# PersistentVolumeClaim — request for storage by a workload
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: invoice-archive-pvc
  namespace: pipeline
spec:
  accessModes:
    - ReadWriteOnce       # Single node at a time (block storage)
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 50Gi
---
# Pod consuming the PVC
apiVersion: apps/v1
kind: Deployment
metadata:
  name: archive-writer
  namespace: pipeline
spec:
  replicas: 1             # ReadWriteOnce: only one pod can mount
  selector:
    matchLabels:
      app: archive-writer
  template:
    metadata:
      labels:
        app: archive-writer
    spec:
      containers:
        - name: writer
          image: gcr.io/invoice-pipeline-prod/archive-writer:v1.0.0
          volumeMounts:
            - name: archive
              mountPath: /data/archive
      volumes:
        - name: archive
          persistentVolumeClaim:
            claimName: invoice-archive-pvc
```

## Access Modes

| Mode | Abbr | Description | GKE Support |
|------|------|-------------|-------------|
| `ReadWriteOnce` | RWO | One node read/write | PD (default) |
| `ReadOnlyMany` | ROX | Many nodes read-only | PD (read replicas) |
| `ReadWriteMany` | RWX | Many nodes read/write | Filestore (NFS) |
| `ReadWriteOncePod` | RWOP | One pod only (k8s 1.22+) | PD CSI driver |

## Reclaim Policies

| Policy | On PVC Delete | Use Case |
|--------|--------------|----------|
| `Retain` | PV stays, data intact | Production — manual cleanup |
| `Delete` | PV and disk deleted | Dev/test ephemeral data |
| `Recycle` | Deprecated | Avoid |

## Common Mistakes

### Wrong

```yaml
# No storageClassName → uses cluster default (may not match your needs)
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

### Correct

```yaml
# Always name the StorageClass explicitly
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 50Gi
```

## Related

- [Pods](pods.md)
- [Deployments](deployments.md)
- [Resource Limits](resource-limits.md)
