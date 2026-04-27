# SRE Copilot — Project Plan

> A portfolio-grade, locally-runnable platform that demonstrates production SRE/DevOps practices for serving LLM-powered applications. Combines **AI-assisted log analysis** and **automated postmortem generation** behind a complete cloud-native stack.

---

## 1. Vision & Goals

**What we're building:** A web application where SREs can paste raw logs or incident timelines and receive AI-generated diagnostics, root cause hypotheses, suggested runbooks, and structured postmortems — all served by a self-hosted LLM running on a local Kubernetes cluster managed via GitOps.

**Why this project:** Most "AI portfolio" projects are thin wrappers around the OpenAI API. This one demonstrates the full stack a senior SRE would design at a company that needs **private, cost-controlled, self-hosted inference**: cluster provisioning, GitOps, observability, progressive delivery, and infrastructure-as-code — all reproducible on a laptop.

**Hard constraints:**
- Must run end-to-end on an Apple Silicon MacBook (M3, 16GB RAM)
- Must be reproducible by a stranger in under 10 minutes (`make up`)
- Must cost zero dollars to run locally

---

## 2. The Two Use Cases

### 2.1 Log Analyzer ("SRE Copilot")

User pastes a log excerpt or stack trace into the UI. The backend streams an AI-generated analysis containing:

- **Severity classification** (info / warning / critical)
- **What happened** (plain-English summary)
- **Likely root cause** (with reasoning)
- **Suggested runbook** (numbered steps)
- **Related metrics to check** (Prometheus query suggestions)

The UI ships with curated examples loaded from the **Loghub** dataset (HDFS, BGL, Thunderbird, OpenSSH, Hadoop) so reviewers can click "Try an HDFS DataNode failure" and see the system work without typing anything.

### 2.2 Postmortem Generator

User pastes a raw incident timeline (Slack messages, on-call notes, terminal output). The backend produces a structured postmortem following the **Google SRE Workbook** template:

- Summary
- Impact (users affected, duration, severity)
- Timeline (cleaned and chronologically ordered)
- Root cause analysis (5 Whys format)
- What went well / what went wrong
- Action items (with suggested owners and priorities)
- Lessons learned

### 2.3 The Bridge

After running a log analysis, the user gets a **"Generate postmortem from this incident"** button that pipes the diagnostic context into the postmortem flow. This creates a coherent demo narrative: *detect → diagnose → document.*

---

## 3. Architecture

### 3.1 High-level diagram

```
                            ┌──────────────────────┐
                            │       Browser        │
                            │   localhost:8080     │
                            └──────────┬───────────┘
                                       │ HTTPS (self-signed)
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    kind cluster: sre-copilot                         │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Ingress: Traefik                                                │ │
│  └────────────────────────────────────────────────────────────────┘ │
│         │                          │                                 │
│         ▼                          ▼                                 │
│  ┌─────────────┐           ┌──────────────┐                         │
│  │  frontend   │           │   backend    │                         │
│  │  Next.js    │──────────▶│   FastAPI    │                         │
│  │  (3 pods)   │  REST/SSE │   (3 pods)   │                         │
│  └─────────────┘           └──────┬───────┘                         │
│                                   │                                  │
│                                   │ OpenAI-compatible HTTP           │
│                                   ▼                                  │
│                            ┌──────────────┐                          │
│                            │  ExternalName│                          │
│                            │   service    │                          │
│                            └──────┬───────┘                          │
│                                   │                                  │
│  ┌────────────────────────────────┼────────────────────────────┐    │
│  │  Platform namespace            │                            │    │
│  │                                │                            │    │
│  │  ┌──────────┐  ┌──────────┐   │   ┌──────────────────┐   │    │
│  │  │ ArgoCD   │  │Prometheus│   │   │   Grafana        │   │    │
│  │  │ (GitOps) │  │          │   │   │   (dashboards)   │   │    │
│  │  └──────────┘  └────┬─────┘   │   └──────────────────┘   │    │
│  │                     │          │                            │    │
│  │  ┌──────────┐  ┌────▼─────┐   │   ┌──────────────────┐   │    │
│  │  │  Loki    │  │  Tempo   │   │   │ OpenTelemetry    │   │    │
│  │  │ (logs)   │  │ (traces) │   │   │   Collector      │   │    │
│  │  └──────────┘  └──────────┘   │   └──────────────────┘   │    │
│  └────────────────────────────────┼────────────────────────────┘    │
└────────────────────────────────────┼─────────────────────────────────┘
                                     │
                              ┌──────▼──────────┐
                              │ Ollama (host)   │
                              │ port 11434      │
                              │                 │
                              │ Qwen 2.5 7B Q4  │
                              │ Apple Metal     │
                              └─────────────────┘
```

### 3.2 Why Ollama runs outside the cluster

Apple Silicon GPUs are accessed via Metal Performance Shaders (MPS), which is not exposed to containers. Running Ollama on the host gives us native GPU acceleration; the cluster reaches it through a Kubernetes `Service` of type `ExternalName` pointing to `host.docker.internal:11434`. This mirrors a realistic production pattern where inference runs on dedicated GPU nodes managed separately from the application plane.

### 3.3 Cluster topology

Three-node kind cluster simulating a production layout:

| Node | Role | Labels | Purpose |
|------|------|--------|---------|
| `control-plane` | control-plane | `node-role.kubernetes.io/control-plane` | API server, etcd, scheduler |
| `worker-platform` | worker | `workload=platform` | ArgoCD, Prometheus, Grafana, Loki, Tempo |
| `worker-apps` | worker | `workload=apps` | frontend, backend |

Workloads use `nodeSelector` to land on the correct pool. This proves the candidate understands node segregation — a real-world concern when GPU nodes cost 10x more than CPU nodes.

---

## 4. Tooling & Stack (the full inventory)

### 4.1 Local development & cluster

| Tool | Version target | Role |
|------|----------------|------|
| Docker Desktop | 4.30+ | Container runtime for kind |
| **kind** | 0.23+ | Local Kubernetes cluster (3 nodes) |
| **kubectl** | 1.30+ | Cluster CLI |
| **Helm** | 3.15+ | Package manager for Kubernetes |
| **Helmfile** | 0.166+ | Declarative Helm release management |
| **Terraform** | 1.9+ | Provisions kind cluster + bootstrap resources |
| **Tilt** *(optional)* | 0.33+ | Hot-reload dev loop for app code |
| **k9s** | 0.32+ | Terminal UI for cluster inspection (developer QoL) |

### 4.2 Inference layer

| Component | Choice | Notes |
|-----------|--------|-------|
| Inference engine (local) | **Ollama** | Native Apple Metal support; OpenAI-compatible API |
| Model (default) | **Qwen 2.5 7B Instruct (Q4_K_M)** | Best quality/size ratio for 16GB RAM |
| Alternative model | **Llama 3.1 8B Instruct (Q4_K_M)** | Configurable via Helm values |
| Inference engine (production target) | **vLLM** | Documented in `docs/aws-migration.md`; not deployed locally |

### 4.3 Application stack

| Layer | Tech | Why |
|-------|------|-----|
| Frontend | **Next.js 14** (App Router, React Server Components) | Streaming SSE for token-by-token output, modern DX |
| UI library | **shadcn/ui + Tailwind** | Looks polished without design effort |
| Backend | **FastAPI** (Python 3.12) | Native async, easy to instrument, ecosystem fit for LLM work |
| LLM client | **OpenAI Python SDK** pointed at Ollama | Same code path that would talk to vLLM in prod |
| Validation | **Pydantic v2** | Schema for postmortem output |
| Streaming | **Server-Sent Events** | Simpler than WebSockets for one-way streaming |

### 4.4 Platform layer

| Component | Tool | Purpose |
|-----------|------|---------|
| Ingress | **Traefik** | Single entry point, TLS termination |
| GitOps | **ArgoCD** | Declarative cluster state from Git |
| Progressive delivery | **Argo Rollouts** | Canary deploys for backend changes |
| Secrets *(simulated)* | **Sealed Secrets** | Encrypted secrets safe to commit to Git |
| Policy | **Kyverno** | Enforce resource limits, security context, image provenance |
| Image security | **Trivy Operator** | Continuous CVE scanning of running images |

### 4.5 Observability stack (LGTM + OTel)

| Signal | Tool | Notes |
|--------|------|-------|
| Metrics | **Prometheus** | Scrapes app + platform metrics |
| Logs | **Loki** + **Promtail** | Structured JSON logs from all pods |
| Traces | **Tempo** | Distributed traces across frontend → backend → Ollama |
| Dashboards | **Grafana** | Pre-built dashboards committed to repo |
| Instrumentation | **OpenTelemetry Collector** | Single agent pattern; receives OTLP, exports to Prom/Loki/Tempo |
| Alerting | **Alertmanager** | Rules for SLO burn, error rate, latency |

### 4.6 CI/CD & quality gates

| Stage | Tool |
|-------|------|
| Lint Terraform | `terraform fmt`, `tflint` |
| Lint Helm/K8s | `helm lint`, `kubeconform`, `kube-linter` |
| Lint Python | `ruff`, `mypy` |
| Lint TypeScript | `eslint`, `tsc --noEmit` |
| Security scan (code) | `gitleaks` (secrets), `bandit` (Python) |
| Security scan (images) | `trivy image` |
| Container build | `docker buildx` (multi-arch: amd64 + arm64) |
| CI runner | **GitHub Actions** |

### 4.7 Documentation

| Asset | Tool |
|-------|------|
| Diagrams | **Mermaid** (in markdown) + **Excalidraw** (for the hero diagram) |
| Architecture decisions | **ADRs** in `docs/adr/` |
| Runbooks | Markdown in `docs/runbooks/` |
| Demo video | Loom (linked from README) |

---

## 5. Observability Deep Dive

This is the section that separates the project from generic portfolio work. We instrument the system as if it were a real production service.

### 5.1 The "RED + USE + LLM-specific" framework

We track three layers of metrics:

**RED metrics (per service):**
- **R**ate — requests per second
- **E**rrors — error rate (4xx, 5xx, exceptions)
- **D**uration — p50, p95, p99 latency

**USE metrics (per resource):**
- **U**tilization — CPU, memory, GPU (via Ollama API)
- **S**aturation — request queue depth, connection pool
- **E**rrors — OOMKills, evictions, restarts

**LLM-specific metrics (the differentiator):**
- `llm_tokens_input_total` — input tokens processed
- `llm_tokens_output_total` — output tokens generated
- `llm_time_to_first_token_seconds` — TTFT histogram
- `llm_inter_token_latency_seconds` — streaming smoothness
- `llm_request_duration_seconds{model, endpoint}` — full inference time
- `llm_active_requests` — concurrent in-flight inferences
- `llm_context_length_tokens` — input size distribution
- `llm_completion_length_tokens` — output size distribution
- `llm_cost_estimated_usd_total` — synthetic cost based on token rates (proves cost-awareness)

### 5.2 Distributed tracing

Every request gets a trace that spans:

```
[browser fetch]
    └─[ingress: traefik]
        └─[frontend: SSR render]
            └─[backend: /analyze/logs]
                ├─[backend: prompt construction]
                ├─[backend: ollama call]
                │   └─[ollama: model inference]  (synthetic span)
                └─[backend: response streaming]
```

Tempo stores the traces, Grafana renders them. The demo video shows clicking a slow request in Grafana and drilling into the exact bottleneck — a moment that lands in interviews.

### 5.3 Structured logging

All services emit JSON logs with a standard schema:

```json
{
  "timestamp": "2026-04-25T18:00:00Z",
  "level": "info",
  "service": "backend",
  "trace_id": "abc123...",
  "span_id": "def456...",
  "user_session": "anon-7f3a",
  "event": "llm.request.completed",
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "input_tokens": 412,
  "output_tokens": 287,
  "duration_ms": 3420,
  "endpoint": "/analyze/logs"
}
```

Loki indexes by `service`, `level`, `event`. The `trace_id` allows jumping from any log line to the full distributed trace in Tempo with one click.

### 5.4 Pre-built Grafana dashboards

Four dashboards committed to the repo:

1. **SRE Copilot Overview** — golden signals across the whole app
2. **LLM Performance** — token throughput, TTFT, model utilization
3. **Cluster Health** — node CPU/mem, pod restarts, etcd latency
4. **Cost & Capacity** — estimated cost per request, projected monthly burn at current rate

### 5.5 SLOs and alerts

We define and enforce three SLOs:

| SLO | Target | Window | Burn-rate alert |
|-----|--------|--------|-----------------|
| Availability | 99% successful responses | 7 days | Page on 14.4× burn over 1h |
| Latency (TTFT) | 95% under 2s | 7 days | Page on 6× burn over 6h |
| Latency (full response) | 90% under 30s | 7 days | Ticket on 3× burn over 24h |

Alertmanager routes to a webhook that posts to a local file (simulating PagerDuty). The README explains the multi-window, multi-burn-rate alerting strategy from the Google SRE Workbook — this is exactly the literacy hiring managers look for.

### 5.6 Synthetic load & chaos

A `loadtest/` directory ships with:

- **k6** scripts that generate realistic traffic patterns
- **Chaos experiments** using `chaos-mesh` (kill backend pod, network latency injection, Ollama timeout)
- A `make chaos` target that runs a 5-minute scenario and shows the system recovering — captured in the demo video

---

## 6. Repository Layout

```
sre-copilot/
├── README.md                    # The hero document
├── Makefile                     # `make up`, `make down`, `make demo`, `make chaos`
├── .github/
│   └── workflows/
│       ├── ci.yml               # lint + test + security scan
│       └── release.yml          # tag + changelog
├── terraform/
│   ├── local/                   # kind cluster + namespaces + bootstrap
│   └── aws/                     # reference EKS module (documented, not deployed)
├── helm/
│   ├── backend/                 # custom chart
│   ├── frontend/                # custom chart
│   └── values/                  # environment overrides
├── helmfile.yaml                # orchestrates all releases
├── argocd/
│   ├── bootstrap/               # app-of-apps pattern
│   └── applications/            # one Application per component
├── apps/
│   ├── backend/                 # FastAPI service
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── frontend/                # Next.js app
│       ├── src/
│       ├── Dockerfile
│       └── package.json
├── observability/
│   ├── dashboards/              # Grafana JSON
│   ├── alerts/                  # Prometheus rules
│   └── slo/                     # SLO definitions
├── policies/
│   └── kyverno/                 # cluster policies
├── loadtest/
│   ├── k6/                      # load scripts
│   └── chaos/                   # chaos-mesh experiments
├── datasets/
│   └── loghub-samples/          # curated examples for the UI
└── docs/
    ├── adr/                     # architecture decision records
    ├── runbooks/                # operational procedures
    ├── aws-migration.md         # how this would run on EKS
    └── images/                  # diagrams, screenshots
```

---

## 7. Execution Plan — 8 Weeks, 4 Sprints

### Sprint 1 (Weeks 1–2) — Foundations

**Goal:** end-to-end working app, no Kubernetes yet.

- [ ] Install Ollama, pull Qwen 2.5 7B, validate Metal acceleration
- [ ] FastAPI backend with `/analyze/logs` and `/generate/postmortem` endpoints
- [ ] Pydantic schemas for postmortem output
- [ ] Streaming SSE responses
- [ ] Next.js frontend with two routes, shared chat component
- [ ] Sample log examples from Loghub loaded into UI
- [ ] Docker Compose setup so anyone can run `docker compose up`
- [ ] Basic structured logging (no tracing yet)
- [ ] First README draft

**Exit criteria:** a friend can clone the repo and run the app via Docker Compose in one command.

### Sprint 2 (Weeks 3–4) — Kubernetes Native

**Goal:** everything runs in kind, deployed manually.

- [ ] Terraform module for kind cluster (3 nodes, labeled)
- [ ] Helm charts for backend and frontend (proper probes, resource limits, HPA)
- [ ] Traefik ingress + self-signed TLS
- [ ] `ExternalName` service pointing to host Ollama
- [ ] Kyverno policies enforcing best practices
- [ ] Helmfile orchestrating all releases
- [ ] `make up` brings the whole stack up cleanly

**Exit criteria:** `terraform apply` followed by `helmfile sync` produces a working cluster with the app reachable at `https://sre-copilot.localhost`.

### Sprint 3 (Weeks 5–6) — GitOps & Observability

**Goal:** the system manages itself.

- [ ] ArgoCD bootstrap with app-of-apps pattern
- [ ] All workloads moved from Helmfile to ArgoCD Applications
- [ ] OpenTelemetry Collector deployed
- [ ] Prometheus + Grafana + Loki + Tempo (LGTM stack via single Helm release)
- [ ] Backend instrumented with OTel SDK (metrics, traces, logs)
- [ ] Frontend instrumented (web vitals + traces propagating to backend)
- [ ] Four Grafana dashboards committed and auto-loaded
- [ ] Alertmanager rules with multi-window burn-rate alerts
- [ ] Sealed Secrets configured

**Exit criteria:** changing any value in Git triggers an ArgoCD sync within 60 seconds. All four dashboards display live data.

### Sprint 4 (Weeks 7–8) — Polish, Resilience, Demo

**Goal:** turn it into a portfolio piece.

- [ ] Argo Rollouts canary deploy for backend
- [ ] k6 load tests + Chaos Mesh experiments
- [ ] `make chaos` scenario captured in demo video
- [ ] Trivy Operator scanning images continuously
- [ ] GitHub Actions: full CI matrix, multi-arch image builds, release pipeline
- [ ] All ADRs written (target: 8–12 decisions documented)
- [ ] AWS migration guide written
- [ ] 3-minute Loom demo recorded
- [ ] Hero architecture diagram in Excalidraw
- [ ] README final pass — screenshots, badges, quick-start, "what I learned"
- [ ] Tag `v1.0.0`, write release notes

**Exit criteria:** a stranger lands on the repo, watches the video, runs `make up`, and sees the system work — within 10 minutes total.

---

## 8. The README Strategy

The README is the only thing 90% of visitors will read. It must answer, in order:

1. **What is this?** (1 sentence + screenshot)
2. **Why does it exist?** (the SRE problem it solves)
3. **What does it look like?** (animated GIF or video)
4. **How is it built?** (the architecture diagram)
5. **How do I run it?** (`make up`)
6. **What did you decide and why?** (link to ADRs)
7. **What would change in production?** (link to AWS migration doc)
8. **What did you learn?** (honest reflection — this is what hiring managers read)

---

## 9. What This Project Demonstrates (the resume bullets it earns)

After completion, you can credibly claim:

- Designed and operated a multi-node Kubernetes platform with GitOps-driven delivery
- Implemented LLM inference serving with OpenAI-compatible APIs and SLO-backed observability
- Instrumented services with OpenTelemetry across metrics, logs, and traces
- Defined and monitored SLOs using multi-window, multi-burn-rate alerting
- Practiced progressive delivery with canary rollouts and automated rollback
- Enforced cluster policy and supply-chain security with Kyverno and Trivy
- Validated resilience through chaos engineering and synthetic load testing
- Authored architecture decision records and operational runbooks

---

## 10. What This Project Deliberately Does Not Do

Honesty section, also goes in the README:

- **No fine-tuning or training.** Inference only. Training is a different discipline.
- **No real GPU at scale.** The local stack uses Apple Metal; production-scale GPU concerns (NCCL, topology-aware scheduling) are documented but not implemented.
- **No multi-tenancy.** Single-user assumption throughout.
- **No production-grade auth.** Local-only; auth is a stub.

Calling these out shows technical maturity. Pretending you covered everything reads as junior.