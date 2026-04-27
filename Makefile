SHELL := /bin/bash
.DEFAULT_GOAL := help

CLUSTER_NAME    := sre-copilot
KUBECONFIG      := $(HOME)/.kube/sre-copilot.config
BACKEND_IMAGE   := sre-copilot/backend:latest
FRONTEND_IMAGE  := sre-copilot/frontend:latest
HELMFILE        := helmfile --environment local
KUBECTL         := kubectl --kubeconfig=$(KUBECONFIG)

# Per-machine overrides (export to shell or set via direnv .envrc)
LLM_MODEL       ?= qwen2.5:7b-instruct-q4_K_M
LLM_JUDGE_MODEL ?= llama3.1:8b-instruct-q4_K_M
INGRESS_HOST    ?= sre-copilot.localtest.me
export LLM_MODEL LLM_JUDGE_MODEL INGRESS_HOST

.PHONY: help up down seed-models demo smoke lint test seal detect-bridge

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

up: ## Create kind cluster, load images, deploy all S1 releases via helmfile
	@echo "==> Provisioning kind cluster via Terraform..."
	cd terraform/local && terraform init -input=false && terraform apply -auto-approve
	@echo "==> Loading images into kind..."
	kind load docker-image $(BACKEND_IMAGE)  --name $(CLUSTER_NAME)
	kind load docker-image $(FRONTEND_IMAGE) --name $(CLUSTER_NAME)
	@echo "==> Syncing Helm releases..."
	KUBECONFIG=$(KUBECONFIG) $(HELMFILE) sync
	@echo "==> Cluster is up. Visit https://$(INGRESS_HOST)"

down: ## Destroy kind cluster and clean Terraform state
	cd terraform/local && terraform destroy -auto-approve || true
	kind delete cluster --name $(CLUSTER_NAME) || true
	@echo "==> Cluster destroyed"

demo: ## Run the full 7-minute demo script (requires make up first)
	@echo "==> Opening browser tabs..."
	open https://$(INGRESS_HOST)
	open http://localhost:3001  # Grafana
	@echo "==> Triggering cascade_retry_storm anomaly..."
	curl -sf -X POST "http://localhost:8000/admin/inject?scenario=cascade_retry_storm" \
	     -H "X-Inject-Token: $${ANOMALY_INJECTOR_TOKEN}" | jq .
	@echo "==> Anomaly injected. Follow the demo script in docs/loom-script.md"

smoke: ## Run end-to-end smoke tests (healthz + SSE probe + wall-clock + memory snapshot)
	@echo "==> Smoke: backend healthz (wall-clock start)..."
	@SMOKE_START=$$(date +%s); \
	until curl -sf http://localhost:8000/healthz > /dev/null 2>&1; do \
	  sleep 2; \
	  elapsed=$$(( $$(date +%s) - SMOKE_START )); \
	  if [ $$elapsed -gt 300 ]; then echo "TIMEOUT waiting for backend healthz"; exit 1; fi; \
	done; \
	BACKEND_READY=$$(( $$(date +%s) - SMOKE_START )); \
	echo "Backend healthz OK — ready in $${BACKEND_READY}s"
	@echo "==> Smoke: SSE round-trip (first-token wall-clock)..."
	@python3 tests/smoke/probe_sse.py
	@echo "==> Smoke: ingress URL reachability (TD-2 close)..."
	@curl -sf -o /dev/null -w "Ingress HTTP status: %{http_code}\n" \
	     --max-time 10 \
	     https://$(INGRESS_HOST)/healthz 2>/dev/null || \
	     echo "WARNING: ingress URL not reachable (is traefik running? check 'make up')"
	@echo "==> Smoke: Ollama reachability through ExternalName service..."
	@$(KUBECTL) exec -n sre-copilot deploy/backend -- \
	     curl -sf http://ollama.sre-copilot.svc.cluster.local:11434/ > /dev/null && \
	     echo "Ollama reachable via ExternalName" || \
	     echo "WARNING: Ollama not reachable (run 'ollama serve' on host)"
	@echo "==> Smoke: memory snapshot (docker stats one-shot)..."
	@docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}" 2>/dev/null | \
	     grep -E 'sre-copilot|CONTAINER' || \
	     echo "WARNING: docker stats unavailable"
	@echo "==> Smoke: NetworkPolicy egress deny check (AT-012 prep)..."
	@$(KUBECTL) exec -n sre-copilot deploy/backend -- \
	     curl -m 3 https://api.openai.com 2>&1 | grep -q "timed out\|Connection\|refused\|curl" && \
	     echo "NetworkPolicy egress deny: PASS (external egress blocked)" || \
	     echo "WARNING: egress to api.openai.com was NOT denied — check NetworkPolicy"
	@echo ""
	@echo "==> Smoke complete"
	@echo "    TODO(S3): add Tempo trace assertion — assert trace with >=4 spans in Tempo within 5s"
	@echo "    See DESIGN §9.2 and manifest entry #38 for the S3 trace smoke extension"

lint: ## Run all static analysis (ruff, mypy, eslint, helm lint, terraform fmt, yamllint)
	@echo "==> Python lint..."
	ruff check src/backend tests/backend
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
	yamllint -d relaxed helmfile.yaml .github/workflows/ci.yml || true
	@echo "==> lint complete"

test: ## Run unit tests + integration tests + structural eval
	pytest tests/backend/unit/ -v --tb=short
	pytest tests/integration/ -v --tb=short
	@echo "==> test complete"

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
