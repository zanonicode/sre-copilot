# Policy Enforcement: Kyverno (Documented-Only)

This document explains the Kyverno policy engine — what it is, why it was deferred from the MVP, and how it would slot into this stack when the time comes.

**Status:** Not deployed. Documented per [ADR-002](adr/0002-lean-platform-kit.md).

---

## What Kyverno Is

Kyverno is a Kubernetes-native policy engine. Unlike Open Policy Agent / Gatekeeper (which uses Rego), Kyverno policies are written in YAML and operate as validating or mutating admission webhooks. They intercept API server requests before resources are persisted and can:

- **Validate** — reject Pods without resource limits, reject images from untrusted registries, enforce label conventions.
- **Mutate** — inject sidecar containers, add default resource limits, rewrite image tags.
- **Generate** — auto-create companion resources (e.g., a NetworkPolicy whenever a new Namespace is created).
- **Verify image signatures** — enforce Sigstore/cosign image signatures as part of supply-chain security.

---

## Why It Was Deferred

From ADR-002:

> **Continuous admission control has no visible moment in 10 minutes.** A reviewer cannot observe Kyverno doing its job in real time during a walkthrough — they would have to deliberately violate a policy to see a rejection, which interrupts the demo narrative.

The RAM budget also played a role: Kyverno's controller + admission webhook server typically adds 150–300 MB, which tightens the 16 GB budget further.

The decision was: deploy components with a *visible demo moment*, document the rest. Kyverno's literacy signal comes from this document, not from memory consumed by the controller.

---

## How to Add Kyverno

When adding Kyverno to this stack (v1.1 or later), follow this sequence:

### 1. Add the Helm chart values

```yaml
# helm/platform/kyverno/values.yaml
kyverno:
  replicaCount: 1
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 384Mi
  admissionController:
    replicas: 1
```

### 2. Add an ArgoCD Application

```yaml
# argocd/applications/kyverno.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://kyverno.github.io/kyverno
    chart: kyverno
    targetRevision: "3.*"
    helm:
      valueFiles:
        - $values/helm/platform/kyverno/values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: kyverno
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### 3. Add starter policies

A minimal starter set for this cluster:

```yaml
# deploy/policies/require-resource-limits.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-resource-limits
      match:
        any:
          - resources:
              kinds: [Pod]
              namespaces: [sre-copilot]
      validate:
        message: "Resource limits are required for all containers."
        pattern:
          spec:
            containers:
              - resources:
                  limits:
                    memory: "?*"
                    cpu: "?*"
```

### 4. Namespace labeling policy (auto-generate NetworkPolicy)

```yaml
# deploy/policies/generate-netpol.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-default-deny
spec:
  rules:
    - name: generate-networkpolicy
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        name: default-deny-egress
        namespace: "{{request.object.metadata.name}}"
        data:
          spec:
            podSelector: {}
            policyTypes: [Egress]
            egress: []
```

---

## Memory Budget Impact

| Component | RSS |
|-----------|-----|
| Kyverno controller | ~200 MB |
| Kyverno admission webhook | ~100 MB |

On a 16 GB machine with the existing stack at ~13.5 GB steady-state, this leaves ~700 MB slack — tight but possible if Prometheus retention is reduced to 6h.

---

## References

- [Kyverno documentation](https://kyverno.io/docs/)
- [Kyverno Helm chart](https://github.com/kyverno/kyverno/tree/main/charts/kyverno)
- [ADR-002: Lean platform kit](adr/0002-lean-platform-kit.md)
