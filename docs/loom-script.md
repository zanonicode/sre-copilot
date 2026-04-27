# Loom Walkthrough Script (3 minutes)

**Recording link:** [placeholder — record with Loom after `make demo` is validated]

Replace the placeholder above with your Loom URL after recording. Add it to the README "What It Looks Like" section.

---

## Pre-recording Setup (5 minutes)

```bash
# 1. Cluster must be running
make smoke  # verify 0 failures

# 2. Port-forwards open
kubectl port-forward -n observability svc/grafana 3001:80 &

# 3. Argo Rollouts dashboard
kubectl argo rollouts dashboard &  # opens on port 3100

# 4. Open browser tabs (do this before hitting Record)
open https://sre-copilot.localtest.me       # Tab 1: SRE Copilot UI
open http://localhost:3001                   # Tab 2: Grafana
open http://localhost:3100                   # Tab 3: Argo Rollouts Dashboard

# 5. Position terminal in repo root, visible on screen
```

**Screen layout:** Browser (80%) | Terminal (20%). Use a dark terminal theme for contrast.

---

## Script (3 minutes, beat-by-beat)

### 0:00–0:30 — What We're Looking At

> "This is SRE Copilot — a kind-native platform demo. Everything you're going to see runs locally on an M3 MacBook, in a 3-node Kubernetes cluster, with no external API calls."

- Point at the browser: SRE Copilot UI
- Point at the terminal: `kubectl get pods -n sre-copilot` — show 2 backend pods Running

> "The backend is FastAPI, the LLM is Qwen 2.5 7B running on the host via Ollama, reached through a Kubernetes ExternalName service — same code pattern as a vLLM deployment on EKS."

---

### 0:30–1:15 — Live Log Analysis + Streaming

> "Let me trigger a synthetic anomaly — this fires 50 fake 5xx logs through the same backend that's serving the UI."

```bash
# In terminal (visible):
make demo  # or trigger manually:
curl -sf -X POST http://localhost:8000/admin/inject?scenario=cascade_retry_storm \
     -H "X-Inject-Token: ${ANOMALY_INJECTOR_TOKEN}" | jq .
```

- Switch to Tab 1 (UI)
- Click "Try this live anomaly" sample button (or paste the anomaly logs)
- Click Analyze

> "Watch the tokens stream in real time — that's SSE, server-sent events, from FastAPI through Traefik to the browser. First token in under 2 seconds."

- Show the JSON output forming: severity, summary, root_cause, runbook, related_metrics

> "The five required fields: severity, summary, root cause, runbook steps, and related metrics. Validated by Pydantic on every response."

---

### 1:15–1:45 — Traces in Tempo

- Switch to Tab 2 (Grafana)
- Open Explore → Tempo data source
- Search by service name `sre-copilot-backend`

> "Every request produces a trace. Here's the span tree: HTTP server span, prompt assembly, the Ollama host call — and this synthetic ollama.inference span. That's a backend-reconstructed span with start/end times from chunk arrival timestamps, because Metal GPU inference can't be auto-instrumented from inside the cluster. The synthetic span is honest — it carries a 'synthetic: true' attribute."

- Point at the llm.ttft_seconds attribute and the token count

---

### 1:45–2:15 — GitOps + ArgoCD

- Switch to terminal

```bash
kubectl get applications -n argocd
```

> "Thirteen ArgoCD applications. The cluster manages itself from this Git repo — push to main, ArgoCD syncs in waves. Wave 0 is platform (Traefik, Sealed Secrets, Argo Rollouts), wave 1 is observability, wave 4 is the frontend."

---

### 2:15–3:00 — Canary Rollout

- Switch to Tab 3 (Argo Rollouts Dashboard)

> "Now the canary moment. v2 of the backend adds a confidence field — you'll be able to see which responses come from v1 versus v2 as traffic shifts."

```bash
# In terminal (visible):
make demo-canary
```

- Switch to Rollouts Dashboard — show the progress bar advancing: 25% → pause → 50% → 100%

> "The AnalysisTemplate gates progression on two Prometheus queries — error rate under 5% and p95 TTFT under 2 seconds. Both are green. Traffic shifts automatically."

- Switch to Grafana SLO panel

> "SLO panel stays green throughout the rollout. No 5xx. This is what deterministic progressive delivery looks like — not chaos, not hope."

---

### 3:00 — Closing

> "Everything here — the GitOps, the canary, the traces, the eval pipeline — runs in about 13.5 GB on a local MacBook. The design decisions that made that possible are in the eight ADRs in docs/adr/. Thanks for watching."

---

## Recording Tips

- Keep the terminal font at 16pt minimum for readability in compressed Loom video.
- Mute notifications before hitting Record.
- Record at 1920×1080 or 2560×1440 (Retina). Loom will compress — higher source resolution helps.
- Do one dry run with `make demo` to verify the anomaly injection token is set and the Rollouts dashboard is accessible.
- The canary progression (25→50→100) takes ~90 seconds with the 30s pauses. This is the longest beat — account for it in timing.
- If the canary analysis fails unexpectedly during recording, abort with `kubectl argo rollouts abort backend -n sre-copilot` and restart with `make demo-canary` after resetting the image to v1.
