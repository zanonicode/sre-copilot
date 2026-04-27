# Container Security Scanning: Trivy Operator (Documented-Only)

This document explains the Trivy Operator — what it is, why continuous scanning was deferred from the MVP, and the one-shot `trivy image` CI step that was deployed instead.

**Status:** Continuous Trivy Operator not deployed. One-shot `trivy image` scan runs in [`.github/workflows/release.yml`](../.github/workflows/release.yml) per [ADR-002](adr/0002-lean-platform-kit.md).

---

## What Trivy Operator Is

The Trivy Operator runs as a Kubernetes controller that continuously scans running workloads for vulnerabilities. It produces `VulnerabilityReport`, `ConfigAuditReport`, and `ExposedSecretReport` custom resources that surface in `kubectl get vulnerabilityreport -A`.

Key capabilities:
- **Workload scanning** — scans container images for CVEs on schedule and on new Pod creation.
- **Config auditing** — checks manifests against CIS Kubernetes benchmarks.
- **Secret detection** — scans for accidentally committed secrets in container filesystems.
- **SBOM generation** — produces Software Bill of Materials per image.

---

## Why Continuous Scanning Was Deferred

From ADR-002:

> **Trivy as a CI step (vs Operator) shows supply-chain literacy in PR checks — reviewers see it without it consuming cluster RAM.**

The Operator's memory footprint (~200–300 MB for the controller + per-node cache) competes with the RAM budget on a 16 GB MacBook. More importantly, continuous vulnerability reports are not visible in a 10-minute walkthrough — a reviewer would have to specifically ask "`kubectl get vulnerabilityreport`" to see them.

The one-shot CI scan is visible in GitHub PR checks: every release runs `trivy image` and the results appear in the Actions tab — high signal, zero cluster cost.

---

## Current Security Posture

The following are in place without the Operator:

| Control | Where |
|---------|-------|
| Non-root containers | `securityContext.runAsNonRoot: true` in all Helm charts |
| Read-only root filesystem | `securityContext.readOnlyRootFilesystem: true` |
| Dropped capabilities | `capabilities.drop: ["ALL"]` |
| SeccompProfile | `RuntimeDefault` on all pods |
| Egress-deny NetworkPolicy | Default-deny with explicit allow-list in `helm/platform/networkpolicies/` |
| Sealed Secrets | Encrypted secrets committed to Git, decrypted only in-cluster |
| One-shot Trivy scan | `trivy image` in [release workflow](../.github/workflows/release.yml) |

---

## How to Add the Trivy Operator

When adding continuous scanning (v1.1 or later):

### 1. Helm values

```yaml
# helm/platform/trivy-operator/values.yaml
trivy-operator:
  replicaCount: 1
  trivyOperator:
    scanJobConcurrency: 2
    scanJobTimeout: 5m
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 384Mi
```

### 2. ArgoCD Application

```yaml
# argocd/applications/trivy-operator.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: trivy-operator
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://aquasecurity.github.io/helm-charts
    chart: trivy-operator
    targetRevision: "0.*"
    helm:
      valueFiles:
        - $values/helm/platform/trivy-operator/values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: trivy-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### 3. View results

```bash
# List vulnerability reports for all workloads
kubectl get vulnerabilityreport -A

# Detailed report for the backend
kubectl describe vulnerabilityreport -n sre-copilot replicaset-backend-<hash>-backend
```

---

## References

- [Trivy Operator documentation](https://aquasecurity.github.io/trivy-operator/)
- [ADR-002: Lean platform kit](adr/0002-lean-platform-kit.md)
- [Release workflow with one-shot scan](../.github/workflows/release.yml)
