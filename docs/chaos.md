# Chaos Engineering: Chaos Mesh (Documented-Only)

This document explains the Chaos Mesh chaos engineering platform — what it is, why it was deferred from the MVP, and the resilience signal that was delivered instead.

**Status:** Not deployed. Documented per [ADR-002](adr/0002-lean-platform-kit.md). The demo's resilience beat uses Argo Rollouts (canary) + PDB (`kubectl delete pod`) instead.

---

## What Chaos Mesh Is

Chaos Mesh is a cloud-native chaos engineering platform for Kubernetes. It injects failure scenarios at the infrastructure level using Kubernetes custom resources. Key experiment types:

- **PodChaos** — kill, pause, or container-kill target pods on a schedule or one-shot.
- **NetworkChaos** — inject latency, packet loss, bandwidth throttling, or full network partitions between services.
- **StressChaos** — inject CPU or memory stress into containers.
- **IOChaos** — inject filesystem latency or errors into container I/O.
- **TimeChaos** — skew the system clock inside a container.

Chaos Mesh provides a web UI (Chaos Dashboard) and a declarative `Workflow` resource for composing multi-step experiments.

---

## Why It Was Deferred

From ADR-002:

> **Chaos experiments are flaky on stage; canary tells a stronger, deterministic resilience story.**

Three specific concerns applied:

1. **Flakiness on stage.** A live chaos experiment during a demo walkthrough has a non-trivial chance of an unexpected outcome (cascade failure, side effects on the Loki/Tempo stack, timeout races). For a portfolio demo, a failed chaos experiment is a net negative — it raises questions rather than answering them.
2. **No visible moment without setup.** Chaos Mesh's value is in the *automated detection and response* loop (dashboards alerting, SLOs burning, automated rollback). Demonstrating that in 10 minutes requires the viewer to have context on alert routing and burn-rate windows — context that has to be built up first.
3. **RAM budget.** Chaos Mesh controller + admission webhook adds ~200 MB, tightening the 16 GB budget.

**The substitute that was delivered:** The demo's resilience beat (`make demo`, 6:30–7:00 mark) runs `kubectl delete pod -l app=backend` on one of the two replicas. The PDB (minAvailable=1) keeps the service available. An in-flight curl loop never sees a 5xx. Replacement pod is Ready in <30s. This is deterministic, naratable, and provable in real time — a stronger signal than an experiment that might behave unexpectedly on stage.

---

## How to Add Chaos Mesh

When adding chaos engineering (v1.1 or later):

### 1. Install Chaos Mesh

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-testing --create-namespace \
  --version 2.*
```

### 2. Network latency experiment (starter)

```yaml
# deploy/chaos/backend-network-delay.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: backend-network-delay
  namespace: sre-copilot
spec:
  action: delay
  mode: one
  selector:
    namespaces: [sre-copilot]
    labelSelectors:
      app.kubernetes.io/name: backend
  delay:
    latency: "200ms"
    correlation: "25"
    jitter: "50ms"
  duration: "60s"
```

### 3. Pod kill experiment

```yaml
# deploy/chaos/backend-pod-kill.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: backend-pod-kill
  namespace: sre-copilot
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces: [sre-copilot]
    labelSelectors:
      app.kubernetes.io/name: backend
  duration: "30s"
```

### 4. Integrate with the demo

The chaos experiments complement (not replace) the canary moment. Suggested order:
1. Canary rollout (Argo Rollouts) — shows progressive delivery.
2. Pod kill (PDB demo) — shows availability during disruption.
3. Network delay (Chaos Mesh) — shows resilience under degraded conditions.

For the 10-minute portfolio demo, stick with steps 1 and 2. Add step 3 only in a longer technical walkthrough where the reviewer has context on SLO burn-rate dashboards.

---

## References

- [Chaos Mesh documentation](https://chaos-mesh.org/docs/)
- [Chaos Mesh Helm chart](https://github.com/chaos-mesh/chaos-mesh/tree/master/helm/chaos-mesh)
- [ADR-002: Lean platform kit](adr/0002-lean-platform-kit.md)
