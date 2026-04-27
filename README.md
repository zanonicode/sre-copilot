# SRE Copilot

[![CI](https://github.com/zanonicode/sre-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/zanonicode/sre-copilot/actions/workflows/ci.yml)
[![Nightly Eval](https://github.com/zanonicode/sre-copilot/actions/workflows/nightly-eval.yml/badge.svg)](https://github.com/zanonicode/sre-copilot/actions/workflows/nightly-eval.yml)
[![Release](https://github.com/zanonicode/sre-copilot/actions/workflows/release.yml/badge.svg)](https://github.com/zanonicode/sre-copilot/actions/workflows/release.yml)

A kind-native, locally-runnable SRE assistant: streaming LLM log analysis, postmortem generation, full LGTM observability, GitOps via ArgoCD, and progressive delivery via Argo Rollouts — running entirely on your MacBook.

## What It Looks Like

```text
                Reviewer Browser  (desktop Chrome)
              https://sre-copilot.localtest.me
                          │  HTTPS + SSE
                          ▼
       ┌──────────────────────────────────────────────┐
       │     kind cluster: sre-copilot (3 nodes)      │
       │                                              │
       │  worker-platform          worker-apps        │
       │  ┌─────────────────┐     ┌──────────────┐   │
       │  │ argocd          │     │ frontend ×1  │   │
       │  │ sealed-secrets  │     │ (Next.js)    │   │
       │  │ argo-rollouts   │◀───▶│              │   │
       │  │ traefik         │     │ backend ×2   │   │
       │  │ otel-collector  │ SSE │ (FastAPI)    │   │
       │  │ loki/tempo/prom │     │ Rollout+PDB  │   │
       │  │ grafana         │     └──────┬───────┘   │
       │  └─────────────────┘           │            │
       │       OTLP push                │ HTTP       │
       │                         ExternalName        │
       └─────────────────────────────── ┼ ───────────┘
                                        ▼
                              host:11434 (Ollama)
                         qwen2.5:7b-instruct-q4_K_M
                              Metal GPU / MPS
```

**Loom walkthrough:** [placeholder — see docs/loom-script.md] (3-minute recorded demo)

## Why This Stack

Most "demo repos" are scaffolding. This one runs a real incident-response workflow end-to-end:

1. **Log analysis streams tokens** from a local Qwen 2.5 7B via SSE — TTFT visible in Grafana
2. **Every request produces a distributed trace** in Tempo, including a synthetic span for the Ollama host hop
3. **ArgoCD owns everything** — push to main, 13 Applications sync in wave order
4. **Canary rollout is demoable in 2 minutes** — Argo Rollouts shifts traffic 25%→50%→100% with Prometheus AnalysisTemplate gating
5. **Eval pipeline runs nightly** — Llama 3.1 8B judges Qwen output against labeled ground truth; results committed to the repo

The decisions that made this possible are in [docs/adr/](docs/adr/) — eight ADRs covering every load-bearing choice.

## Platform: What Is Deployed vs Documented-Only

**Deployed (in cluster):** ArgoCD, Argo Rollouts, Sealed Secrets, Traefik, Loki, Grafana, Tempo, Prometheus, OTel Collector, NetworkPolicy egress-denial.

**Documented-only** (deferred per [ADR-002](docs/adr/0002-lean-platform-kit.md) — each has a doc explaining why and how to add it):
- Kyverno policy enforcement → [docs/policy.md](docs/policy.md)
- Trivy Operator continuous scanning → [docs/security.md](docs/security.md) (one-shot `trivy image` runs in CI)
- Chaos Mesh → [docs/chaos.md](docs/chaos.md) (canary + PDB cover the resilience story)

## Architecture

```text
Browser → Traefik (TLS) → frontend (Next.js) → backend (FastAPI ×2, Argo Rollouts)
                                                      │
                                          ExternalName Service
                                                      │
                                      host:11434 (Ollama / Metal GPU)
                                     qwen2.5:7b-instruct-q4_K_M
```

**Deployed:** kind cluster (3 nodes), Traefik ingress, Ollama ExternalName service, FastAPI backend (×2 replicas, PDB, HPA, Argo Rollouts Rollout), Next.js frontend, ArgoCD (13 Applications), Sealed Secrets, Argo Rollouts, LGTM stack (Loki + Grafana + Tempo + Prometheus), OTel Collector, NetworkPolicy egress-denial.

## Prerequisites

### Required

These are needed for [`make up`](Makefile) and [`make smoke`](Makefile).

| Tool | Version | Install | Verify |
|------|---------|---------|--------|
| Docker runtime | Desktop 4.30+ / OrbStack / Colima | https://orbstack.dev | `docker version` |
| kind | 0.23+ | `brew install kind` | `kind version` |
| kubectl | 1.31+ | `brew install kubectl` | `kubectl version --client` |
| Helm | 3.16+ | `brew install helm` | `helm version` |
| Helmfile | 0.167+ | `brew install helmfile` | `helmfile version` |
| Terraform | 1.6+ | `brew install terraform` | `terraform version` |
| Ollama | latest | `brew install ollama` (or https://ollama.com) | `ollama --version` |
| Python | 3.12+ | `brew install python@3.12` | `python3.12 --version` |

### Optional (lint + frontend dev)

These are only required for [`make lint`](Makefile) and frontend development.

| Tool | Version | Install | Used by |
|------|---------|---------|---------|
| Node.js | 20 LTS | `brew install node` | frontend dev |
| ruff | latest | `pip install ruff` | `make lint` |
| mypy | latest | `pip install mypy` | `make lint` |
| yamllint | latest | `brew install yamllint` | `make lint` |
| kubeconform | latest | `brew install kubeconform` | `make lint` |

**One-liner combined install:**

```bash
brew install kind kubectl helm helmfile terraform ollama python@3.12 node yamllint
```

**Hardware:** Apple Silicon Mac (M1/M2/M3), 16 GB RAM minimum. The stack uses ~13.5 GB at steady state.

## Configuring the Docker host bridge

The backend pod must reach Ollama on your host via `host.docker.internal:11434`. The Kubernetes NetworkPolicy allows that egress only for a specific CIDR — the **Docker host bridge CIDR**. If the configured CIDR doesn't match your runtime, the egress is silently dropped and the backend appears to "hang" on every Ollama call (connection timeouts, no useful logs).

The default in [helm/platform/ollama-externalname/values.yaml](helm/platform/ollama-externalname/values.yaml) is `192.168.65.0/24` (Docker Desktop on macOS). If that's what you use, you can skip the rest of this section.

### Runtime-to-CIDR table

| Runtime | Default bridge CIDR |
|---------|---------------------|
| Docker Desktop (macOS) | `192.168.65.0/24` |
| OrbStack | `198.19.249.0/24` |
| Colima / Lima | `192.168.106.0/24` |
| Linux native Docker | `172.17.0.0/16` |

### Detect and override

```bash
# 1. Detect the actual CIDR for your machine
make detect-bridge

# 2. Export the override before make up
export HOST_BRIDGE_CIDR=198.19.249.0/24
make up
```

Helmfile reads `HOST_BRIDGE_CIDR` via `{{ env "HOST_BRIDGE_CIDR" | default "192.168.65.0/24" }}` in [helmfile.yaml](helmfile.yaml) and passes it to the `ollama-externalname` chart's `hostBridgeCIDR` value, which the NetworkPolicy template consumes.

### Verify after `make up`

```bash
kubectl get networkpolicy -n sre-copilot allow-ollama-host-hop -o yaml | grep cidr
# Expected: cidr: 198.19.249.0/24   (or whatever you exported)
```

### Persistent override

For repeat-use machines, persist the export. A [direnv](https://direnv.net) `.envrc` at the repo root works well:

```bash
# .envrc (gitignored)
export HOST_BRIDGE_CIDR=198.19.249.0/24
```

Or add the export to your `~/.zshrc` / `~/.bashrc`.

If the helmfile env-templating approach doesn't work in your environment, you can fall back to a manual sync:

```bash
KUBECONFIG=$HOME/.kube/sre-copilot.config helmfile --environment local sync \
  --set hostBridgeCIDR=198.19.249.0/24
```

## Per-machine configuration

Beyond the host bridge CIDR, four other settings can vary per machine and are env-overridable. Defaults work for the canonical M3/16 GB MacBook + Docker Desktop scenario; override only if you have a reason.

| Env var | Default | When to override |
|---------|---------|------------------|
| `HOST_BRIDGE_CIDR` | `192.168.65.0/24` (Docker Desktop) | Non-Docker-Desktop runtime — see [Configuring the Docker host bridge](#configuring-the-docker-host-bridge) |
| `LLM_MODEL` | `qwen2.5:7b-instruct-q4_K_M` (~5 GB) | Lower-RAM machine: `phi3:mini` (~2 GB) for 8 GB RAM; higher-end: `qwen2.5:14b-instruct-q4_K_M` (~9 GB) for 32 GB+ |
| `LLM_JUDGE_MODEL` | `llama3.1:8b-instruct-q4_K_M` (~5 GB) | Same RAM-tier logic as `LLM_MODEL`. Or set `SKIP_JUDGE=1` to skip the judge model entirely (eval Layer 2 disabled) |
| `INGRESS_HOST` | `sre-copilot.localtest.me` | If your network/DNS blocks `localtest.me`, pick a domain that resolves to 127.0.0.1 (e.g., `sre-copilot.local` with an `/etc/hosts` entry) |
| `OLLAMA_BASE_URL` | in-cluster ExternalName | **Local backend dev only** — when running `uvicorn backend.main:app` outside the cluster, set to `http://localhost:11434/v1` |

**One-shot example** (low-RAM tier on Colima with custom hostname):

```bash
export HOST_BRIDGE_CIDR=192.168.106.0/24
export LLM_MODEL=phi3:mini
export SKIP_JUDGE=1
export INGRESS_HOST=sre-copilot.local
echo "127.0.0.1 sre-copilot.local" | sudo tee -a /etc/hosts

make seed-models
make up
```

**Persistent overrides** — the canonical pattern is a [direnv](https://direnv.net) `.envrc` at the repo root (gitignored):

```bash
# .envrc
export HOST_BRIDGE_CIDR=198.19.249.0/24    # OrbStack
export LLM_MODEL=qwen2.5:14b-instruct-q4_K_M
export LLM_JUDGE_MODEL=llama3.1:8b-instruct-q4_K_M
```

Or add the exports to your `~/.zshrc` / `~/.bashrc` if you don't use direnv.

**Verify after `make up`:**

```bash
# Check what model the backend is configured to call
kubectl get configmap backend-config -n sre-copilot -o jsonpath='{.data.LLM_MODEL}'

# Check what hostname the frontend builds against
kubectl get configmap frontend-config -n sre-copilot -o jsonpath='{.data.NEXT_PUBLIC_API_URL}'
```

## Quick Start

### 1. One-time setup (run once per machine)

```bash
# Clone and enter the repo
git clone https://github.com/you/sre-copilot.git
cd sre-copilot

# Pull models (~8.8 GB total) and pre-build images
make seed-models
```

[`make seed-models`](Makefile) pulls `qwen2.5:7b-instruct-q4_K_M` (primary model) and `llama3.1:8b-instruct-q4_K_M` (eval judge), pre-pulls all container images, and builds backend/frontend Docker images. This is the only step requiring internet access.

### 2. Start the cluster

```bash
# Ensure Ollama is running on your host
ollama serve &

# (Optional) override the Docker host bridge CIDR for non-Docker-Desktop runtimes
# export HOST_BRIDGE_CIDR=$(make -s detect-bridge | awk '/Suggested CIDR/{print $4}')

# Provision kind cluster + deploy all releases
make up
```

[`make up`](Makefile) runs Terraform to create a 3-node kind cluster, loads Docker images, and runs `helmfile sync`. Cold-start target: **< 5 minutes**.

Visit **https://sre-copilot.localtest.me** in your browser.

### 3. Validate

```bash
make smoke
```

Checks backend healthz, SSE streaming, and Ollama reachability through the ExternalName service. Exit code 0 = everything works.

### 4. Run tests

```bash
make test    # unit tests + structural eval (~30s)
make lint    # ruff, mypy, helm lint, terraform fmt, yamllint
```

### 5. Tear down

```bash
make down
```

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make seed-models` | Pull Ollama models, pre-pull images, build app images (once per machine) |
| `make detect-bridge` | Print the Docker host bridge CIDR for the current runtime |
| `make up` | Create kind cluster + deploy all S1 releases (honors `HOST_BRIDGE_CIDR`) |
| `make down` | Destroy kind cluster |
| `make smoke` | End-to-end healthcheck: backend, SSE, Ollama |
| `make demo` | Run the 7-minute narrated demo (requires `make up`) |
| `make lint` | ruff, mypy, helm lint, terraform fmt, yamllint |
| `make test` | pytest unit tests + structural eval |
| `make seal` | Seal a secret for the cluster's Sealed Secrets controller |

## Project Structure

```
sre-copilot/
├── Makefile                    # Top-level UX
├── Tiltfile                    # Inner-loop dev (Tilt)
├── helmfile.yaml               # Ordered Helm release orchestration
├── terraform/local/            # kind cluster Terraform module
├── src/
│   ├── backend/                # FastAPI service (Python 3.12)
│   │   ├── api/                # Routers: analyze, postmortem, health, admin
│   │   ├── schemas/            # Pydantic v2 models
│   │   ├── prompts/            # Jinja2 templates + few-shot exemplars
│   │   ├── observability/      # OTel SDK init, metrics, spans, logging
│   │   ├── chunking/           # Long-log strategy (summarize-then-analyze)
│   │   └── Dockerfile
│   └── frontend/               # Next.js 14 App Router
│       └── Dockerfile
├── helm/
│   ├── backend/                # Deployment×2, HPA, PDB, Service, SA, ConfigMap
│   ├── frontend/               # Deployment×1, Service, ConfigMap
│   ├── redis/                  # Redis single-replica wrapper
│   └── platform/
│       ├── traefik/            # Ingress + IngressRoute values
│       ├── networkpolicies/    # Namespace-wide default-deny + selective allows
│       └── ollama-externalname/ # ExternalName Service + host-bridge NetworkPolicy
├── datasets/
│   ├── loghub/hdfs/            # 50K-line Loghub HDFS subset + labels
│   └── eval/ground_truth/      # 10 labeled JSON ground-truth records
└── tests/
    └── backend/unit/           # pytest: prompt assembly, schema, injector
```

## How It Works

1. **Browser** submits logs to `POST /analyze/logs` with `Accept: text/event-stream`
2. **Backend** validates input (Pydantic), assembles a Jinja2 prompt with HDFS few-shot exemplar
3. **Backend** streams OpenAI-compatible tokens from Ollama via ExternalName Service → `host.docker.internal:11434`
4. **Browser** receives `data: {"type":"delta","token":"..."}` SSE frames, renders tokens in real time
5. Final SSE event is `{"type":"done"}` with the accumulated JSON validated against the `LogAnalysis` schema

## Troubleshooting

### Backend pod CrashLoopBackOff with "connection timed out to ollama:11434"

The most likely cause is a wrong `HOST_BRIDGE_CIDR`. The NetworkPolicy in [helm/platform/ollama-externalname/templates/networkpolicy.yaml](helm/platform/ollama-externalname/templates/networkpolicy.yaml) is dropping egress to your host bridge. Detect and override:

```bash
make detect-bridge
export HOST_BRIDGE_CIDR=<the suggested CIDR>
make down && make up
```

Then verify:

```bash
kubectl get networkpolicy -n sre-copilot allow-ollama-host-hop -o yaml | grep cidr
```

### `ollama: command not found` or model calls fail

Ollama must be installed and running on the host (not inside the cluster). Start it and seed the models:

```bash
ollama serve &
make seed-models
```

### kind cluster not visible to kubectl

The cluster's kubeconfig is written to `~/.kube/sre-copilot.config`, not the default kubeconfig. Either use `KUBECONFIG=~/.kube/sre-copilot.config kubectl ...` or merge the context:

```bash
kind export kubeconfig --name sre-copilot
kubectl config use-context kind-sre-copilot
```

### https://sre-copilot.localtest.me is unreachable

Check that Traefik is up and the IngressRoute exists:

```bash
kubectl get pods -n platform -l app.kubernetes.io/name=traefik
kubectl get ingressroute -n sre-copilot
```

If the IngressRoute is missing, re-run `helmfile sync` (or [`make up`](Makefile)). If Traefik is healthy but the host doesn't resolve, confirm `localtest.me` is not blocked by your DNS provider — it's a public wildcard pointing at `127.0.0.1`.

## Architecture Decisions

Eight ADRs document every load-bearing choice in this project:

| ADR | Decision | Why It Matters |
|-----|----------|----------------|
| [ADR-001](docs/adr/0001-kind-native-runtime.md) | kind from day 1, no docker-compose | Shows Kubernetes literacy from commit 1 |
| [ADR-002](docs/adr/0002-lean-platform-kit.md) | Lean kit — deploy what has a demo moment, document the rest | Every component narrates in 10 min |
| [ADR-003](docs/adr/0003-ollama-externalname.md) | Ollama on host via `ExternalName` Service | Metal GPU is unreachable inside Docker; ExternalName keeps backend code production-shaped |
| [ADR-004](docs/adr/0004-hybrid-eval-strategy.md) | 3-layer eval (pytest + Llama judge + manual spot-check) | Per-commit gate + nightly quality signal + human calibration |
| [ADR-005](docs/adr/0005-hybrid-grounding-data.md) | Loghub HDFS + synthetic logs; real + synthetic postmortems | Controllable demo + realistic eval |
| [ADR-006](docs/adr/0006-backend-statelessness.md) | Backend fully stateless — no sticky sessions, no Redis | Canary-compatible; simplifies reasoning |
| [ADR-007](docs/adr/0007-host-bridge-cidr.md) | Configurable `hostBridgeCIDR` via helmfile env-templating | Demo works on Docker Desktop, OrbStack, Colima, Linux |
| [ADR-008](docs/adr/0008-per-machine-env-overridable.md) | 4-layer per-machine env-override pattern | 5 overridable settings, zero required overrides on canonical M3/16GB |

## Production Path (AWS)

Curious how this migrates to EKS? See [docs/aws-migration.md](docs/aws-migration.md) — covers vLLM on Karpenter GPU nodes, IRSA + External Secrets Operator replacing Sealed Secrets, AWS Load Balancer Controller replacing Traefik, and the exact component substitution map.

The migration is a Service swap and a Terraform rewrite — the backend code, Helm charts, ArgoCD Applications, and Argo Rollouts manifests are unchanged.

## What I Learned

This project started as a way to demonstrate platform-engineering literacy in a 10-minute window. Building it surfaced a cluster of genuinely interesting problems that I did not anticipate from the design:

**The ExternalName-to-Metal hop.** The brittlest seam in the stack is not the LLM — it's the network path from inside a kind pod to a host process that holds Metal GPU context. Solving this with an `ExternalName` Service and a configurable `hostBridgeCIDR` taught me that "portability" in a local stack is a real engineering problem, not a documentation task. ADR-007 and ADR-008 emerged from actual broken demos on OrbStack.

**Distributed tracing across process boundaries.** You can't auto-instrument across the kind-cluster → host-Ollama boundary. The synthetic `ollama.inference` span — reconstructed retroactively from chunk arrival timestamps, with `synthetic: true` in its attributes — was the only way to attribute host-side latency without modifying Ollama. It's honest, discoverable, and taught me more about OTel span semantics than any tutorial.

**Eval is the hardest part.** Writing the Pydantic schema is trivial. Writing the Llama-judge rubric that correctly distinguishes "same root cause, different words" from "hallucinated root cause" is not. The 3-layer eval strategy (structural → judge → human spot-check) came from realizing that each layer answers a different question and fails gracefully in a different way.

**YAGNI at 16 GB.** Redis died early. Three components were documented-only instead of deployed. The 10-minute cold-start budget forced every component to earn its RAM. The constraint was the design.

**Progressive delivery makes the demo.** The canary moment — watching the traffic weight shift while Prometheus gating stays green — is more compelling than any chaos experiment could be, because it's deterministic, naratable, and doesn't flake. ADR-002's reasoning about "demo moments" was right.

## Runbooks

| Runbook | Scenario |
|---------|----------|
| [ollama-host-down](docs/runbooks/ollama-host-down.md) | Ollama process stopped; backend returns 503 |
| [backend-pod-loss](docs/runbooks/backend-pod-loss.md) | OOM kill, eviction, or Rollout step; PDB covers availability |
| [eval-judge-drift](docs/runbooks/eval-judge-drift.md) | Nightly eval pass rate falls below 80% |
| [sealed-secrets](docs/runbooks/sealed-secrets.md) | Sealed Secrets controller operations |

## Contributing

Sprint 2 adds: NetworkPolicy egress-denial, Sealed Secrets, hardened probes/securityContext, integration tests.
Sprint 3 adds: ArgoCD GitOps, full LGTM observability, OTel traces/metrics.
Sprint 4 adds: Argo Rollouts canary, the full demo script, 8 ADRs, eval pipeline, portfolio README.
