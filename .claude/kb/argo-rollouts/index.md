# Argo Rollouts Knowledge Base

> **Purpose**: Replace the backend's Deployment with an Argo Rollouts `Rollout` controller that performs canary releases (25% → 50% → 100%) gated by Prometheus AnalysisTemplates — the centerpiece of the SRE Copilot demo
> **MCP Validated**: 2026-04-26

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/rollout-vs-deployment.md](concepts/rollout-vs-deployment.md) | What Rollout adds over Deployment; CRD shape; controller behavior |
| [concepts/analysis-templates.md](concepts/analysis-templates.md) | AnalysisTemplate / AnalysisRun lifecycle, success/failure conditions |
| [concepts/traffic-routing-modes.md](concepts/traffic-routing-modes.md) | Replica-based (default) vs Traefik weighted routing vs SMI |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/rollout-from-deployment.md](patterns/rollout-from-deployment.md) | Migrate `helm/backend/templates/deployment.yaml` → `rollout.yaml` (workloadRef pattern) |
| [patterns/prometheus-analysis-recipe.md](patterns/prometheus-analysis-recipe.md) | The error-rate + p95-latency AnalysisTemplate (DESIGN §4.5 verbatim) |
| [patterns/traefik-basic-canary.md](patterns/traefik-basic-canary.md) | Replica-based canary with Traefik (no fancy SMI needed) |
| [patterns/hpa-rollout-integration.md](patterns/hpa-rollout-integration.md) | Point HPA at the Rollout (not Deployment); how scaling interacts with steps |
| [patterns/cli-demo-runbook.md](patterns/cli-demo-runbook.md) | `kubectl argo rollouts` commands for the live demo |
| [patterns/abort-and-promote-flow.md](patterns/abort-and-promote-flow.md) | What to do when AnalysisTemplate fails (or you want to promote early) |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — CLI cheatsheet, CRD field map, AnalysisRun status enum

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Rollout** | CRD that REPLACES Deployment with progressive delivery semantics |
| **Step** | One entry in `strategy.canary.steps` (setWeight / pause / analysis) |
| **AnalysisTemplate** | Reusable template defining "is the canary healthy?" via metric providers (Prometheus, Datadog, Web) |
| **AnalysisRun** | Instance of an AnalysisTemplate; "Successful" / "Failed" / "Inconclusive" |
| **workloadRef** | Migration helper — Rollout points to an existing Deployment as its template source |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/rollout-vs-deployment.md, patterns/cli-demo-runbook.md |
| **Intermediate** | patterns/rollout-from-deployment.md, concepts/analysis-templates.md, patterns/prometheus-analysis-recipe.md |
| **Advanced** | concepts/traffic-routing-modes.md, patterns/traefik-basic-canary.md, patterns/hpa-rollout-integration.md, patterns/abort-and-promote-flow.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| k8s-platform-engineer | patterns/rollout-from-deployment.md, patterns/prometheus-analysis-recipe.md | Sprint 4 entries #39–41 |
| ci-cd-specialist | patterns/cli-demo-runbook.md | `make demo-canary` Makefile target (#42) |
| observability-engineer | patterns/prometheus-analysis-recipe.md | Wire AnalysisTemplate metrics from Prom |

---

## Project Context

This KB drives Sprint 4 of SRE Copilot — the canary moment is the climax of the demo (DESIGN §8). DESIGN §4.5 specifies the exact Rollout + AnalysisTemplate manifests; this KB grounds them and adds operator playbook.

| Component | Pattern |
|-----------|---------|
| `helm/platform/argo-rollouts/` (controller) | concepts/rollout-vs-deployment.md install notes |
| `helm/backend/templates/rollout.yaml` (replaces deployment.yaml) | patterns/rollout-from-deployment.md |
| `deploy/rollouts/analysis-templates/` | patterns/prometheus-analysis-recipe.md |
| `make demo-canary` | patterns/cli-demo-runbook.md |
| `backend:v2` with `confidence` field | patterns/abort-and-promote-flow.md (visual diff) |

---

## External Resources

- [Argo Rollouts Docs](https://argoproj.github.io/argo-rollouts/)
- [AnalysisTemplate Reference](https://argoproj.github.io/argo-rollouts/features/analysis/)
- [kubectl-argo-rollouts plugin](https://argoproj.github.io/argo-rollouts/installation/#kubectl-plugin-installation)
- [Traffic Management overview](https://argoproj.github.io/argo-rollouts/features/traffic-management/)
