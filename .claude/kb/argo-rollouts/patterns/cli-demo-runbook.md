# CLI Demo Runbook (`make demo-canary`)

> **Purpose**: The exact `kubectl argo rollouts` command sequence for the live canary moment in the SRE Copilot demo (DESIGN section 8) — so the Makefile target and the screencast both work first time
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 4 entry #42 (`make demo-canary` target)
- Screencast / Loom recording (entry #54)
- Live presentation

## Prerequisites

```text
[ ] kind cluster running (`make up`)
[ ] helmfile applied (S4 state — argo-rollouts controller installed)
[ ] AnalysisTemplate applied: kubectl get analysistemplate -n sre-copilot
[ ] Rollout backend at v1, status Healthy
[ ] kubectl-argo-rollouts plugin installed (`brew install argoproj/tap/kubectl-argo-rollouts`)
[ ] Two terminals open
```

## The Demo Sequence

### Terminal 1 — Live status (run BEFORE starting)

```bash
kubectl argo rollouts get rollout backend -n sre-copilot --watch
```

This renders an auto-refreshing tree:

```text
Name:            backend
Namespace:       sre-copilot
Status:          ✔ Healthy
Strategy:        Canary
  Step:          5/5
  SetWeight:     100
  ActualWeight:  100
Images:          sre-copilot/backend:v1 (stable)
Replicas:
  Desired:       2
  Current:       2
  Updated:       2
  Ready:         2
  Available:     2
```

### Terminal 2 — Build + load + trigger

```bash
# 1. Build v2 with the visible diff (adds confidence: float to JSON output)
docker build -t sre-copilot/backend:v2 \
  --build-arg APP_VERSION=v2 \
  -f src/backend/Dockerfile src/backend/

# 2. Load into kind nodes (no registry)
kind load docker-image sre-copilot/backend:v2 --name sre-copilot

# 3. Trigger the canary
kubectl argo rollouts set image backend \
  backend=sre-copilot/backend:v2 \
  -n sre-copilot
```

### Watch Terminal 1 progress

```text
Status:          ◌ Progressing
  Step:          1/5
  SetWeight:     25
  ActualWeight:  25
Images:
  sre-copilot/backend:v1 (stable)
  sre-copilot/backend:v2 (canary)
Replicas:
  Updated:       1     ← canary pod
```

After 30s pause + AnalysisRun success:

```text
  Step:          3/5
  SetWeight:     50
```

After 30s pause:

```text
  Step:          5/5
  SetWeight:     100
Status:          ✔ Healthy
Images:          sre-copilot/backend:v2 (stable)
```

Total: ~70s if both pauses pass + analyses succeed.

## Verifying the New Field Mid-Rollout

While at `setWeight: 25`, hit the API repeatedly:

```bash
# In a third terminal
for i in {1..20}; do
  curl -sN -X POST http://localhost:8000/analyze/logs \
    -H 'Content-Type: application/json' \
    -d '{"log_payload":"INFO test"}' \
    | grep -o '"confidence"' | head -1
  echo
done
# About 1 in 4 should print "confidence" (the v2 field)
```

This is the visible proof of weighted routing.

## Force-Promote (skip the wait)

For a sub-3-minute demo:

```bash
# Skip current pause -> go to next step
kubectl argo rollouts promote backend -n sre-copilot

# OR: skip ALL remaining steps -> jump to 100%
kubectl argo rollouts promote backend --full -n sre-copilot
```

## Force-Fail (canary failure demo)

Inject 5xx via the anomaly endpoint (DESIGN section 4.x admin route) then trigger canary:

```bash
curl -X POST http://localhost:8000/admin/inject \
  -H 'X-Token: devsecret' \
  -d '{"type":"force_500","percentage":80,"duration_seconds":120}'

kubectl argo rollouts set image backend \
  backend=sre-copilot/backend:v2 -n sre-copilot
```

Within ~30s the AnalysisRun fails:

```text
Status:          ✖ Degraded
  Message:       AnalysisRun 'backend-xxxx' failed: error-rate measurement(s) failed
```

Recover:

```bash
kubectl argo rollouts undo backend -n sre-copilot
# OR
kubectl argo rollouts abort backend -n sre-copilot
kubectl argo rollouts set image backend backend=sre-copilot/backend:v1 -n sre-copilot
```

## Makefile Target

```makefile
# Makefile (excerpt)
.PHONY: demo-canary
demo-canary:
	@echo "Building backend:v2 with visible diff (adds confidence field)..."
	docker build -t sre-copilot/backend:v2 \
		--build-arg APP_VERSION=v2 \
		-f src/backend/Dockerfile src/backend/
	kind load docker-image sre-copilot/backend:v2 --name sre-copilot
	@echo "Triggering canary..."
	kubectl argo rollouts set image backend \
		backend=sre-copilot/backend:v2 \
		-n sre-copilot
	@echo "Watch progress in another terminal:"
	@echo "  kubectl argo rollouts get rollout backend -n sre-copilot --watch"
```

## Status One-Shot (CI)

```bash
# Block until rollout completes; non-zero on Degraded
kubectl argo rollouts status backend -n sre-copilot --timeout 5m
```

Use in CI smoke tests.

## Talking Points (for Loom / live presenter)

1. "The Rollout sits where the Deployment used to be — same image, same replicas, same probes."
2. "I push a new image with a `confidence` field. Watch the controller take a 25/75 split first."
3. "Behind the scenes, every 15 seconds Argo asks Prometheus: are 5xx less than 5%? Is TTFT under 2s? Both yes -> proceed."
4. "If I force a 5xx burst..." (demonstrates failure path) "...the rollout halts in Degraded. One `undo` and I'm back."

## See Also

- patterns/rollout-from-deployment.md — Rollout spec used here
- patterns/prometheus-analysis-recipe.md — what gates the steps
- patterns/abort-and-promote-flow.md — recovery details
