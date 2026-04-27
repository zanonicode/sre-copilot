# SRE Copilot

A kind-native, locally-runnable SRE assistant: streaming LLM log analysis, postmortem generation, full LGTM observability, GitOps via ArgoCD, and progressive delivery via Argo Rollouts — running entirely on your MacBook.

> **Sprint 1 (Foundations)** — end-to-end FastAPI + Next.js in a 3-node kind cluster with streaming SSE against a local Ollama model.

## Architecture

```text
Browser → Traefik (TLS) → frontend (Next.js) → backend (FastAPI ×2)
                                                      │
                                          ExternalName Service
                                                      │
                                      host:11434 (Ollama / Metal GPU)
                                     qwen2.5:7b-instruct-q4_K_M
```

**Platform components deployed in S1:** kind cluster, Traefik ingress, Redis (cache placeholder), Ollama ExternalName service, FastAPI backend (×2 replicas, PDB, HPA), Next.js frontend.

**Documented-only (S3+):** ArgoCD, Argo Rollouts, Sealed Secrets, LGTM observability stack, NetworkPolicy egress-denial. See [docs/policy.md](docs/policy.md) for rationale.

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

## Contributing

Sprint 2 adds: NetworkPolicy egress-denial, Sealed Secrets, hardened probes/securityContext, integration tests.
Sprint 3 adds: ArgoCD GitOps, full LGTM observability, OTel traces/metrics.
Sprint 4 adds: Argo Rollouts canary, the full demo script, ADRs, portfolio README.
