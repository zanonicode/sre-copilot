SHELL := /bin/bash
.DEFAULT_GOAL := help

CLUSTER_NAME    := sre-copilot
KUBECONFIG      := $(HOME)/.kube/sre-copilot.config
BACKEND_IMAGE   := sre-copilot/backend:latest
BACKEND_V2_IMAGE := sre-copilot/backend:v2
FRONTEND_IMAGE  := sre-copilot/frontend:latest
HELMFILE        := helmfile --environment local
KUBECTL         := kubectl --kubeconfig=$(KUBECONFIG)

# Per-machine overrides (export to shell or set via direnv .envrc)
LLM_MODEL       ?= qwen2.5:7b-instruct-q4_K_M
LLM_JUDGE_MODEL ?= llama3.1:8b-instruct-q4_K_M
INGRESS_HOST    ?= sre-copilot.localtest.me
export LLM_MODEL LLM_JUDGE_MODEL INGRESS_HOST

.PHONY: help up down seed-models demo demo-canary demo-reset smoke lint test seal detect-bridge judge

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

detect-bridge: ## Print the Docker host bridge CIDR for the current runtime
	@echo "==> Detecting Docker host bridge CIDR..."
	@HOST_IP=$$(docker run --rm --add-host=host.docker.internal:host-gateway alpine getent hosts host.docker.internal 2>/dev/null | awk '{print $$1}'); \
	if [ -z "$$HOST_IP" ]; then echo "Could not resolve host.docker.internal"; exit 1; fi; \
	CIDR=$$(echo "$$HOST_IP" | awk -F. '{print $$1"."$$2"."$$3".0/24"}'); \
	echo "Detected host IP : $$HOST_IP"; \
	echo "Suggested CIDR   : $$CIDR"; \
	echo ""; \
	echo "To use it: export HOST_BRIDGE_CIDR=$$CIDR && make up"

seed-models: ## Pull Ollama models and pre-pull all container images (run once)
	@echo "==> Pulling Ollama models (LLM_MODEL=$(LLM_MODEL), JUDGE=$(LLM_JUDGE_MODEL))..."
	until OLLAMA_KEEP_ALIVE=24h ollama pull $(LLM_MODEL); do echo "[retry] $(LLM_MODEL)"; sleep 5; done
	@if [ "$(SKIP_JUDGE)" != "1" ]; then \
		until OLLAMA_KEEP_ALIVE=24h ollama pull $(LLM_JUDGE_MODEL); do echo "[retry] $(LLM_JUDGE_MODEL)"; sleep 5; done; \
	else \
		echo "==> Skipping $(LLM_JUDGE_MODEL) (judge model) — unset SKIP_JUDGE to include"; \
	fi
	@echo "==> Pre-pulling platform images (kind, traefik)..."
	docker pull kindest/node:v1.31.0
	docker pull traefik:v3.1
	@echo "==> Building application images..."
	docker build -t $(BACKEND_IMAGE) src/backend
	docker build -t $(FRONTEND_IMAGE) src/frontend
	@echo "==> seed-models complete"

up: ## Bootstrap kind + ArgoCD; ArgoCD then reconciles all releases (GitOps)
	@echo "==> [1/5] Provisioning kind cluster via Terraform..."
	cd terraform/local && terraform init -input=false && terraform apply -auto-approve
	@echo "==> [2/5] Loading app images into kind..."
	kind load docker-image $(BACKEND_IMAGE)  --name $(CLUSTER_NAME)
	kind load docker-image $(FRONTEND_IMAGE) --name $(CLUSTER_NAME)
	@echo "==> [3/5] Bootstrap traefik via helmfile (ingress needed before ArgoCD UI is reachable)..."
	KUBECONFIG=$(KUBECONFIG) $(HELMFILE) sync --selector name=traefik
	@echo "==> [4/5] Installing ArgoCD..."
	$(KUBECTL) create namespace argocd --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) create namespace observability --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.12.0/manifests/install.yaml
	@echo "    Waiting for argocd-server to be ready (up to 5 min)..."
	$(KUBECTL) rollout status -n argocd deployment/argocd-server --timeout=300s
	@echo "==> [5/5] Applying root Application (ArgoCD reconciles all releases via app-of-apps)..."
	$(KUBECTL) apply -f argocd/bootstrap/root-app.yaml -n argocd
	@echo ""
	@echo "==> Cluster bootstrap complete. ArgoCD reconciling all releases (60-180s)."
	@echo "    Watch:  kubectl get applications -n argocd -w"
	@echo "    Visit:  https://$(INGRESS_HOST)"
	@echo "    Then:   make smoke"

down: ## Destroy kind cluster and clean Terraform state
	cd terraform/local && terraform destroy -auto-approve || true
	kind delete cluster --name $(CLUSTER_NAME) || true
	@echo "==> Cluster destroyed"

demo: ## Run the full 7-minute demo script (requires make up first) — see docs/loom-script.md
	@echo "==> [Beat 0:00] Opening browser tabs..."
	@open https://$(INGRESS_HOST) 2>/dev/null || xdg-open https://$(INGRESS_HOST) 2>/dev/null || true
	@echo "    Open Grafana manually if port-forward is not running:"
	@echo "    kubectl port-forward -n observability svc/grafana 3001:80"
	@echo "    kubectl argo rollouts dashboard  (Rollouts dashboard on :3100)"
	@echo ""
	@echo "==> [Beat 0:30] Triggering cascade_retry_storm anomaly..."
	@$(KUBECTL) exec -n sre-copilot $$($(KUBECTL) get pod -n sre-copilot -l app.kubernetes.io/name=backend -o name | head -1) -- \
	     curl -sf -X POST "http://localhost:8000/admin/inject?scenario=cascade_retry_storm" \
	     -H "X-Inject-Token: $${ANOMALY_INJECTOR_TOKEN}" 2>/dev/null | jq . || \
	     curl -sf -X POST "http://localhost:8000/admin/inject?scenario=cascade_retry_storm" \
	     -H "X-Inject-Token: $${ANOMALY_INJECTOR_TOKEN}" | jq .
	@echo ""
	@echo "==> [Beat 0:30] Anomaly injected — click 'Try this live anomaly' in the UI."
	@echo "    Watch SSE tokens stream into the UI in real time."
	@echo ""
	@echo "==> [Beat 2:00] Trace tab — open Grafana → Explore → Tempo, search service=sre-copilot-backend"
	@echo "    Observe: http.server → ollama.host_call → ollama.inference (synthetic span)"
	@echo ""
	@echo "==> [Beat 3:30] Postmortem bridge — click 'Generate postmortem from this incident' in UI"
	@echo ""
	@echo "==> [Beat 4:30] Canary moment — triggering make demo-canary..."
	$(MAKE) demo-canary
	@echo ""
	@echo "==> [Beat 6:30] Resilience beat — deleting one backend pod..."
	@$(KUBECTL) delete pod -n sre-copilot -l app.kubernetes.io/name=backend --field-selector=status.phase=Running \
	     --wait=false 2>/dev/null | head -1 || true
	@echo "    Watch: kubectl get pods -n sre-copilot -l app.kubernetes.io/name=backend -w"
	@echo "    PDB keeps service available (minAvailable=1). Replacement Ready in <30s."
	@echo ""
	@echo "==> Demo complete. See docs/loom-script.md for the full narrative."

demo-canary: ## Build backend:v2, load into kind, bump Rollout image, watch progression
	@echo "==> [demo-canary] Building backend:v2 image (adds confidence: float field)..."
	docker build \
	     --build-arg ENABLE_CONFIDENCE=true \
	     -t $(BACKEND_V2_IMAGE) \
	     --label "canary=v2" \
	     src/backend
	@echo "==> [demo-canary] Loading backend:v2 into kind cluster..."
	kind load docker-image $(BACKEND_V2_IMAGE) --name $(CLUSTER_NAME)
	@echo "==> [demo-canary] Patching Rollout image to v2..."
	$(KUBECTL) patch rollout backend -n sre-copilot --type=merge \
	     -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","image":"$(BACKEND_V2_IMAGE)"}]}}}}'
	@echo "==> [demo-canary] Starting background load gen (90s) so AnalysisTemplate"
	@echo "    has http_server_duration + llm_ttft samples to evaluate..."
	@$(KUBECTL) port-forward -n sre-copilot svc/backend 8000:8000 > /tmp/sre-canary-pf.log 2>&1 & \
	PF=$$!; \
	( sleep 3; \
	  END=$$(($$(date +%s)+90)); \
	  while [ $$(date +%s) -lt $$END ]; do \
	    curl -s -o /dev/null http://localhost:8000/openapi.json & \
	    curl -s -o /dev/null -X POST http://localhost:8000/logs \
	         -H "content-type: application/json" \
	         -d '{"log_payload":"ERROR connection reset"}' & \
	    sleep 2; \
	  done; \
	  kill $$PF 2>/dev/null \
	) > /tmp/sre-canary-load.log 2>&1 &
	@echo "==> [demo-canary] Watching Rollout progression (Ctrl+C to stop watching)..."
	@echo "    Expected: 25%% → analysis pause (60s) → 50%% → 100%%"
	@echo "    Background load logs: /tmp/sre-canary-load.log"
	@echo "    For richer visualization: brew install argoproj/tap/kubectl-argo-rollouts"
	$(KUBECTL) get rollout backend -n sre-copilot -w || true

demo-reset: ## Reset canary — revert backend Rollout to :latest and promote to stable
	@echo "==> [demo-reset] Reverting backend Rollout to stable image ($(BACKEND_IMAGE))..."
	$(KUBECTL) patch rollout backend -n sre-copilot --type=merge \
	     -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","image":"$(BACKEND_IMAGE)"}]}}}}'
	@echo "==> [demo-reset] Rollout reverted to $(BACKEND_IMAGE)"
	@echo "    For full canary CLI control (promote/abort), install: brew install argoproj/tap/kubectl-argo-rollouts"

restart-backend: ## Trigger an in-place restart of the backend Rollout (Argo-Rollouts native, no plugin needed)
	@echo "==> [restart-backend] Setting spec.restartAt — Argo Rollouts will roll pods respecting canary strategy..."
	$(KUBECTL) patch rollout backend -n sre-copilot --type=merge \
	     -p "{\"spec\":{\"restartAt\":\"$$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}"
	@echo "==> [restart-backend] Watching pods... (Ctrl+C to stop)"
	$(KUBECTL) get pods -n sre-copilot -l app.kubernetes.io/name=backend -w || true

clean-replicasets: ## Delete all ReplicaSets with 0 desired/current/ready replicas across managed namespaces
	@echo "==> [clean-replicasets] Pruning idle ReplicaSets across managed namespaces..."
	@for ns in argocd observability platform sre-copilot; do \
	  echo "  -- namespace: $$ns"; \
	  $(KUBECTL) get rs -n $$ns -o json 2>/dev/null \
	    | jq -r '.items[] | select(.spec.replicas==0 and (.status.replicas//0)==0 and (.status.readyReplicas//0)==0) | .metadata.name' \
	    | while read rs; do \
	        [ -z "$$rs" ] && continue; \
	        $(KUBECTL) delete rs -n $$ns "$$rs" --wait=false; \
	      done; \
	done
	@echo "==> [clean-replicasets] Done. Going forward, revisionHistoryLimit=3 on backend/frontend prevents new accumulation."

smoke: ## Run end-to-end smoke tests (healthz + SSE + ingress + Ollama + memory + NP egress)
	@$(KUBECTL) port-forward -n sre-copilot svc/backend 8000:8000 > /tmp/sre-smoke-pf.log 2>&1 & \
	PF=$$!; trap "kill $$PF 2>/dev/null" EXIT; \
	sleep 3; \
	echo "==> Smoke: backend healthz..."; \
	SMOKE_START=$$(date +%s); \
	until curl -sf http://localhost:8000/healthz > /dev/null 2>&1; do \
	  sleep 2; \
	  if [ $$(( $$(date +%s) - SMOKE_START )) -gt 60 ]; then echo "TIMEOUT waiting for backend healthz"; exit 1; fi; \
	done; \
	echo "  Backend healthz OK — ready in $$(( $$(date +%s) - SMOKE_START ))s"; \
	echo "==> Smoke: SSE round-trip..."; \
	python3 tests/smoke/probe_sse.py || echo "  WARNING: SSE probe failed"; \
	echo "==> Smoke: ingress URL reachability..."; \
	curl -sf -o /dev/null -w "  Ingress HTTP status: %{http_code}\n" --max-time 10 \
	     https://$(INGRESS_HOST)/healthz 2>/dev/null || \
	     echo "  WARNING: ingress URL not reachable"; \
	echo "==> Smoke: Ollama reachability through ExternalName service..."; \
	BPOD=$$($(KUBECTL) get pod -n sre-copilot -l app.kubernetes.io/name=backend -o name | head -1); \
	$(KUBECTL) exec -n sre-copilot $$BPOD -- python -c "import socket,sys; s=socket.socket(); s.settimeout(3); s.connect(('ollama.sre-copilot.svc.cluster.local',11434)); print('  Ollama reachable via ExternalName')" 2>&1 | tail -1; \
	echo "==> Smoke: memory snapshot..."; \
	docker stats --no-stream --format "  {{.Name}}: {{.MemUsage}}" 2>/dev/null | grep sre-copilot || echo "  WARNING: docker stats unavailable"; \
	echo "==> Smoke: NetworkPolicy egress-deny check (AT-012)..."; \
	$(KUBECTL) exec -n sre-copilot $$BPOD -- python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('api.openai.com',443)); print('  WARNING: egress NOT denied')" 2>&1 | grep -q "WARNING" && echo "  WARNING: egress NOT denied" || echo "  NetworkPolicy egress deny: PASS"; \
	echo ""; echo "==> Smoke complete"

lint: ## Run all static analysis (ruff, mypy, eslint, helm lint, terraform fmt, yamllint)
	@echo "==> Python lint..."
	ruff check src/backend tests/
	mypy src/backend --ignore-missing-imports || true
	@echo "==> Helm lint..."
	helm lint helm/backend
	helm lint helm/frontend
	helm lint helm/platform/traefik
	helm lint helm/platform/ollama-externalname
	helm lint helm/platform/networkpolicies
	@echo "==> Terraform fmt check..."
	terraform fmt -check terraform/local/ || true
	@echo "==> YAML lint..."
	yamllint -d relaxed helmfile.yaml .github/workflows/ci.yml .github/workflows/nightly-eval.yml || true
	@echo "==> lint complete"

test: ## Run unit + integration tests + Layer-1 structural eval (AT-008, AT-010)
	pytest tests/backend/unit/ -v --tb=short
	pytest tests/integration/ -v --tb=short
	pytest tests/eval/structural/ -v --tb=short
	@echo "==> test complete"

judge: ## Run Layer-2 Llama judge eval (AT-011) — requires live cluster + Ollama
	@echo "==> Running Layer-2 Llama judge (requires backend on localhost:8000 + Ollama)..."
	PYTHONPATH=src python tests/eval/judge/run_judge.py

seal: ## Seal a secret for the cluster's Sealed Secrets controller. Usage: make seal SECRET_NAME=my-secret KEY=mykey VALUE=myval
	@if [ -z "$(SECRET_NAME)" ] || [ -z "$(KEY)" ] || [ -z "$(VALUE)" ]; then \
	  echo "Usage: make seal SECRET_NAME=<name> KEY=<key> VALUE=<value>"; \
	  echo "Example: make seal SECRET_NAME=backend-secrets KEY=ANOMALY_INJECTOR_TOKEN VALUE=changeme"; \
	  exit 1; \
	fi
	@echo "==> Creating plain Secret locally (not committed)..."
	$(KUBECTL) create secret generic $(SECRET_NAME) \
	  --namespace sre-copilot \
	  --from-literal=$(KEY)=$(VALUE) \
	  --dry-run=client -o yaml > /tmp/$(SECRET_NAME).yaml
	@echo "==> Sealing with kubeseal (controller in platform namespace)..."
	kubeseal \
	  --kubeconfig $(KUBECONFIG) \
	  --controller-namespace platform \
	  --controller-name sealed-secrets \
	  --format yaml \
	  < /tmp/$(SECRET_NAME).yaml \
	  > deploy/secrets/$(SECRET_NAME).sealed.yaml
	@rm -f /tmp/$(SECRET_NAME).yaml
	@echo "==> Sealed secret written to deploy/secrets/$(SECRET_NAME).sealed.yaml"
	@echo "    This file is safe to commit. The plain secret was discarded."
	@git add deploy/secrets/$(SECRET_NAME).sealed.yaml 2>/dev/null || true
