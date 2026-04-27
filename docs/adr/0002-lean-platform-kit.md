# ADR-002: Lean platform kit (Sealed Secrets + Argo Rollouts deployed; Kyverno / Trivy Operator / Chaos Mesh documented-only)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |

---

## Context

The 16 GB RAM budget cannot accommodate the full "Maximal" platform kit (ArgoCD + Sealed Secrets + Argo Rollouts + Kyverno + Trivy Operator + Chaos Mesh + LGTM + OTel + 2 backend replicas + Ollama). Reviewers also cannot absorb a tour of every CNCF project in a 10-minute walkthrough — components without a *visible moment* in the demo dilute the signal.

## Choice

**Deploy:** ArgoCD, Sealed Secrets, Argo Rollouts, Traefik, full LGTM (Loki + Grafana + Tempo + Prometheus), OTel Collector.

**Document only** (in `docs/policy.md`, `docs/security.md`, `docs/chaos.md`): Kyverno, Trivy Operator, Chaos Mesh.

Keep one-shot `trivy image` in the release CI workflow as a low-cost visible signal.

## Rationale

- Each *deployed* component has a narrated demo moment: ArgoCD sync (GitOps), Sealed Secrets (kubeseal flow), Argo Rollouts (canary panel), LGTM (every dashboard), OTel (traces tab).
- Documented-only components prove awareness without paying memory or demo-time tax.
- Trivy as a CI step (vs Operator) shows supply-chain literacy in PR checks — reviewers see it without it consuming cluster RAM.

## Alternatives Rejected

1. **Maximal kit.** Rejected: blows RAM budget; no narrative room.
2. **Security-forward (Kyverno + Trivy Operator).** Rejected: continuous admission control has no visible moment in 10 minutes.
3. **Resilience-forward (Chaos Mesh).** Rejected: chaos experiments are flaky on stage; canary tells a stronger, deterministic resilience story.

## Consequences

- README must explicitly state which platform components are deployed vs documented, to pre-empt "you skipped Kyverno" critique.
- `docs/policy.md`, `docs/security.md`, `docs/chaos.md` become first-class deliverables, not afterthoughts.
- The repo gets a clean v1.1 expansion path: each documented component already has a stub doc explaining where it would slot in.
