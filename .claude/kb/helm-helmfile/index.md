# Helm + Helmfile Knowledge Base

> **Purpose**: Package, render, and orchestrate Kubernetes releases for the SRE Copilot kind cluster (FastAPI backend, Next.js frontend, Redis, Traefik, ExternalName Ollama bridge, LGTM stack)
> **MCP Validated**: 2026-04-26

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/chart-anatomy.md](concepts/chart-anatomy.md) | Chart.yaml, values.yaml, templates/, _helpers.tpl, NOTES |
| [concepts/values-inheritance.md](concepts/values-inheritance.md) | values.yaml + values-dev/prod overrides + `--set` precedence |
| [concepts/helmfile-model.md](concepts/helmfile-model.md) | `releases:`, `needs:`, environments, templating, sync vs apply |
| [concepts/lifecycle-and-hooks.md](concepts/lifecycle-and-hooks.md) | install/upgrade/rollback/uninstall, pre-/post- hooks, weights |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/app-chart-skeleton.md](patterns/app-chart-skeleton.md) | Minimal app chart: Deployment + Service + ConfigMap + HPA + PDB |
| [patterns/probes-and-security.md](patterns/probes-and-security.md) | Liveness/readiness/startup probes + securityContext + resource limits |
| [patterns/helmfile-ordered-releases.md](patterns/helmfile-ordered-releases.md) | The SRE Copilot release graph (verbatim DESIGN §4.8) |
| [patterns/lint-template-diff.md](patterns/lint-template-diff.md) | `helm lint`, `helm template`, `helm diff upgrade`, kubeconform |
| [patterns/common-pitfalls.md](patterns/common-pitfalls.md) | YAML indent, range scopes, immutable fields, secret rotation |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — CLI, file layout, values precedence, helmfile commands

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Chart** | A directory of templates + values rendered into K8s manifests |
| **Release** | A named, versioned install of a chart into a cluster/namespace |
| **Values** | Hierarchical config: chart defaults → env overrides → `--set` |
| **Helmfile** | Declarative wrapper that orchestrates many releases with `needs:` ordering |
| **Hook** | A manifest annotated to run at a specific lifecycle phase |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/chart-anatomy.md, patterns/app-chart-skeleton.md |
| **Intermediate** | concepts/values-inheritance.md, patterns/probes-and-security.md, patterns/lint-template-diff.md |
| **Advanced** | concepts/helmfile-model.md, patterns/helmfile-ordered-releases.md, concepts/lifecycle-and-hooks.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| k8s-platform-engineer | patterns/app-chart-skeleton.md, patterns/helmfile-ordered-releases.md | Author backend/frontend/redis/traefik charts; wire helmfile.yaml |
| ci-cd-specialist | patterns/lint-template-diff.md | Wire helm lint + kubeconform into CI |
| observability-engineer | patterns/probes-and-security.md | Add ServiceMonitor + probes to LGTM charts |

---

## Project Context

This KB supports Sprint 1–4 of SRE Copilot:

| Component | Pattern |
|-----------|---------|
| `helm/backend/` Deployment×2 + HPA + PDB | patterns/app-chart-skeleton.md |
| `helm/frontend/`, `helm/redis/` (bitnami wrap) | patterns/app-chart-skeleton.md |
| `helm/platform/{traefik,sealed-secrets,argo-rollouts}/` | concepts/helmfile-model.md |
| `helm/platform/ollama-externalname/` | See `ollama-local-serving` KB → externalname-host-bridge |
| `helmfile.yaml` (S1 → S4 release order) | patterns/helmfile-ordered-releases.md |
| Probes + securityContext (S2) | patterns/probes-and-security.md |

---

## External Resources

- [Helm Docs (v3)](https://helm.sh/docs/)
- [Helmfile (helmfile.yaml.gotmpl reference)](https://helmfile.readthedocs.io/)
- [helm-diff plugin](https://github.com/databus23/helm-diff)
- [kubeconform](https://github.com/yannh/kubeconform)
