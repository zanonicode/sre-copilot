# sre-copilot — project memory for Claude

> This file is loaded automatically. Keep it terse and operational — rules and gotchas, not narrative.
> Full project explanation: [`README.md`](../README.md). Deep docs: [`docs/`](../docs/).

## What this project is

Local-first SRE assistant: FastAPI backend + Next.js frontend running on a `kind` cluster, calling **Ollama on the host** for LLM inference. Full LGTM observability (Loki/Grafana/Tempo/Prometheus). GitOps via ArgoCD app-of-apps. Progressive delivery via Argo Rollouts.

Built end-to-end via **Spec-Driven Development (SDD) with Claude Code** — this is part of why the project exists. The SDD pipeline is real: Brainstorm → Define → Design → Build → Ship, captured in [`.claude/sdd/features/`](sdd/features/) and [`.claude/sdd/reports/`](sdd/reports/).

## Stack at a glance

| Layer | Tech | Notes |
|---|---|---|
| Cluster | kind, 3 nodes | Provisioned by Terraform ([`terraform/local/`](../terraform/local/)) |
| GitOps | ArgoCD app-of-apps | 14 child Applications, sync-wave ordered |
| Packaging | Helmfile + Helm | [`helmfile.yaml.gotmpl`](../helmfile.yaml.gotmpl) orchestrates 12 releases |
| Ingress | Traefik | IngressRoute CRDs, mkcert-signed wildcard `*.localtest.me` |
| Backend | FastAPI 3.12, async, OTel-instrumented | [`src/backend/`](../src/backend/) |
| Frontend | Next.js 14 App Router, browser OTel | [`src/frontend/`](../src/frontend/) |
| LLM | Ollama on host, reached via ExternalName Svc + NetworkPolicy egress | qwen2.5:7b (analyzer), llama3.1:8b (judge) |
| Observability | OTel SDK → Collector → Loki/Tempo/Prometheus → Grafana | [`observability/`](../observability/) |
| Progressive delivery | Argo Rollouts canary with Prometheus AnalysisTemplate | |
| Secrets | Bitnami Sealed Secrets | `make seal` wraps kubeseal |

## Commands you'll reach for

```
make up              # full bootstrap: terraform → kind → traefik → argocd → root-app
make down            # tear down kind + terraform state
make seed-models     # one-time: pull ~8.8 GB of Ollama models
make trust-certs     # mint mkcert wildcard cert for *.localtest.me
make smoke           # end-to-end smoke probes
make demo            # ENTER-paced narrated walkthrough (Loom-friendly)
make demo-canary     # ship backend:v2 as canary, watch Argo Rollouts gate it
make dashboards      # regenerate Grafana ConfigMaps from observability/dashboards/*.json
make lint            # ruff + mypy + eslint + helm lint + kubeconform + yamllint + terraform fmt
make test            # pytest + Layer-1 structural eval
make judge           # Layer-2 LLM-as-judge eval (needs cluster + Ollama)
make detect-bridge   # auto-detect Docker host bridge CIDR (for non-Docker-Desktop runtimes)
```

Help: `make help` lists every target with its description.

## Conventions and rules to respect

### Hostnames are split per service
- Frontend: `https://sre-copilot.localtest.me`
- **Backend: `https://api.sre-copilot.localtest.me`** (API health is here, not at root)
- ArgoCD: `https://argocd.sre-copilot.localtest.me`
- Grafana: `https://grafana.sre-copilot.localtest.me`
- Prometheus: `https://prometheus.sre-copilot.localtest.me`

Source of truth: `kubectl get ingressroute -A`. Never assume `/healthz` lives at the root host — it doesn't.

### Streaming protocol is SSE, not WebSocket
Both `/analyze/logs` and `/generate/postmortem` return `text/event-stream` with `data: {json}\n\n` framing. The browser uses native `EventSource`. Don't add WebSocket plumbing.

### Ollama lives on the host, reached via ExternalName
`ollama.sre-copilot.svc.cluster.local` → `host.docker.internal:11434`. The `allow-ollama-host-hop` NetworkPolicy allows egress to `hostBridgeCIDR` (default `192.168.65.0/24` for Docker Desktop). For OrbStack/Colima/podman, the user must `export HOST_BRIDGE_CIDR=$(make detect-bridge ...)` before `make up`. See [`docs/DEPLOYMENT.md §4`](../docs/DEPLOYMENT.md#4-pre-flight-per-machine-config).

### GitOps means git is the source of truth
ArgoCD has automated sync + self-heal turned on. **Never `kubectl edit` workloads** — the change will get reverted. To make a change: edit chart values, commit, push, ArgoCD reconciles. Exception: `make demo-canary` does an in-place `kubectl set image` on purpose (ephemeral demo).

### Bootstrap order matters
The `make up` recipe is sensitive to a known race: `argocd-repo-server` gRPC listener binds a beat after its Deployment goes Ready. We wait twice (server + repo-server) at [`Makefile:82-87`](../Makefile#L82-L87). If you change the bootstrap order, preserve that wait.

### File-reference style in docs
Use markdown links `[text](path)` or `[file.py:42](path/file.py#L42)`. **Don't** use `` `Makefile:53` `` backticks — they're not clickable in the user's IDE (VS Code Claude Code extension renders relative-path links).

### `/workflow:ship` — preserve working files (project-specific override)
The canonical `/workflow:ship` recipe deletes DEFINE/DESIGN/BUILD_REPORT working files from `.claude/sdd/features/` and `.claude/sdd/reports/` after archiving. **For this repo, do NOT delete them.** This project is a reference implementation of SDD-with-Claude-Code; visitors browsing `.claude/sdd/features/` should see live artifacts, not empty folders. The archive at `.claude/sdd/archive/{FEATURE}/` is the canonical historical record with `Status: ✅ Shipped`; the working files are the educational mirror.

## File layout

```
src/backend/         FastAPI app — api/, admin/, schemas/, prompts/, observability/, middleware/, chunking/
src/frontend/        Next.js 14 SPA — app/, components/, lib/sse.ts, observability/
helm/                Local Helm charts (backend, frontend, ollama-externalname, networkpolicies, …)
helmfile.yaml.gotmpl Helmfile orchestrating 12 releases (env-templated via Go templates)
argocd/
  bootstrap/         root-app.yaml — the app-of-apps entry point
  applications/      14 child Application manifests
terraform/local/     kind cluster definition (kubeconfig → ~/.kube/sre-copilot.config)
observability/
  dashboards/        4 Grafana dashboard JSONs + regen-configmaps.py
  alerts/            PrometheusRules — SLO recording + MWMBR burn-rate alerts
tests/
  backend/           pytest unit tests (35 in S1)
  integration/       in-cluster integration tests
  smoke/             end-to-end probes (probe_sse.py + smoke harness)
  eval/              Layer-1 structural + Layer-2 judge fixtures + golden labels
docs/                README's deep companions: DEPLOYMENT, APP_GUIDE, INFRASTRUCTURE, OBSERVABILITY
.claude/
  sdd/               BRAINSTORM/DEFINE/DESIGN per feature + BUILD reports per sprint
  kb/                Knowledge bases (only the ones relevant to this stack)
  agents/            Specialized agents used during the build
  commands/          Slash commands (workflow:brainstorm, build, etc.)
```

## SDD workflow

When the user invokes `/workflow:brainstorm`, `/workflow:define`, `/workflow:design`, `/workflow:build`, or `/workflow:iterate`, follow the corresponding agent in [`.claude/agents/workflow/`](agents/workflow/). The pipeline expects artifacts in [`.claude/sdd/features/`](sdd/features/) (per-feature) and [`.claude/sdd/reports/`](sdd/reports/) (per-sprint).

Post-sprint code changes need to flow back to DESIGN — use `/workflow:iterate` rather than editing build reports directly. The build-agent reads DESIGN, not reports.

## Knowledge bases relevant here

When working on these areas, the KB has validated patterns:
- Helm/Helmfile: [`.claude/kb/helm-helmfile/`](kb/helm-helmfile/)
- OTel + LGTM: [`.claude/kb/otel-lgtm/`](kb/otel-lgtm/)
- Ollama local serving: [`.claude/kb/ollama-local-serving/`](kb/ollama-local-serving/)
- Argo Rollouts: [`.claude/kb/argo-rollouts/`](kb/argo-rollouts/)
- ArgoCD: [`.claude/kb/argocd/`](kb/argocd/)
- Kubernetes: [`.claude/kb/kubernetes/`](kb/kubernetes/)
- Terraform: [`.claude/kb/terraform/`](kb/terraform/)

## Past gotchas worth not re-rediscovering

- **ArgoCD root-app stuck `Unknown`** after `make up` — repo-server gRPC race. Fix: `kubectl annotate application sre-copilot-root -n argocd argocd.argoproj.io/refresh=hard --overwrite`. Permanent fix is the second rollout-status wait already in the Makefile.
- **Smoke test ingress probe failing with 404** — wrong hostname. Backend `/healthz` is on `api.sre-copilot.localtest.me`, NOT the bare frontend host.
- **Docker host bridge CIDR is runtime-dependent** — Docker Desktop uses `192.168.65.0/24`, OrbStack uses `198.19.249.0/24`, Colima/Podman vary. The `hostBridgeCIDR` Helm value is overridable via the `HOST_BRIDGE_CIDR` env var in [`helmfile.yaml.gotmpl`](../helmfile.yaml.gotmpl).
- **`pip install uvicorn[standard]` fails in zsh** — bracket globbing. Quote it: `pip install 'uvicorn[standard]'`.
- **Multi-arch ArgoCD image breaks `kind load`** — Docker 27+ pushes attestation manifests. The Makefile uses `docker save --platform=<host>` first to strip them.
- **Severity enum** uses `StrEnum` (not `str + Enum`). Python 3.12 idiom; don't regress to the older mixin pattern.

## Don't

- Don't add WebSocket support — the protocol is SSE.
- Don't add a separate auth layer to public APIs without asking — this is a localhost demo; the cluster boundary + NetworkPolicies are the security model.
- Don't `kubectl edit` workloads — ArgoCD self-heal will revert.
- Don't rename ports/hostnames without updating both the IngressRoute *and* the smoke test.
- Don't commit `.env`, `.certs/`, `.claude/settings.local.json`, or anything under `.claude/telemetry/sessions/`.
- Don't add new top-level `docs/*.md` files without linking from the README's documentation map.
- Don't write multi-paragraph code comments — the codebase convention is sparse comments, only when WHY is non-obvious.
