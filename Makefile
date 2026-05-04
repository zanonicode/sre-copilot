SHELL := /bin/bash
.DEFAULT_GOAL := help

CLUSTER_NAME    := sre-copilot
KUBECONFIG      := $(HOME)/.kube/sre-copilot.config
BACKEND_IMAGE   := sre-copilot/backend:latest
BACKEND_V2_IMAGE := sre-copilot/backend:v2
FRONTEND_IMAGE  := sre-copilot/frontend:latest
ARGOCD_VERSION  := v2.14.5
ARGOCD_IMAGE    := quay.io/argoproj/argocd:$(ARGOCD_VERSION)
HELMFILE        := helmfile --environment local
KUBECTL         := kubectl --kubeconfig=$(KUBECONFIG)

# Per-machine overrides (export to shell or set via direnv .envrc)
LLM_MODEL       ?= qwen2.5:7b-instruct-q4_K_M
LLM_JUDGE_MODEL ?= llama3.1:8b-instruct-q4_K_M
INGRESS_HOST    ?= sre-copilot.localtest.me
export LLM_MODEL LLM_JUDGE_MODEL INGRESS_HOST

.PHONY: help up down seed-models demo demo-canary demo-canary-bad-prompt demo-canary-tiny-model demo-canary-broken-chunking demo-canary-bad-schema demo-canary-memory-leak demo-canary-slow demo-canary-clean demo-reset smoke lint test seal seal-add seal-judge-canary-token detect-bridge judge restart-backend rebuild-backend clean-replicasets trust-certs dashboards

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
	@echo "==> Pre-pulling platform images (kind, traefik, argocd)..."
	docker pull kindest/node:v1.31.0
	docker pull traefik:v3.1
	docker pull $(ARGOCD_IMAGE)
	@echo "==> Building application images..."
	docker build -f src/backend/Dockerfile -t $(BACKEND_IMAGE) .
	docker build -t $(FRONTEND_IMAGE) src/frontend
	@echo "==> seed-models complete"

up: ## Bootstrap kind + ArgoCD; ArgoCD then reconciles all releases (GitOps)
	@echo "==> [1/5] Provisioning kind cluster via Terraform..."
	cd terraform/local && terraform init -input=false && terraform apply -auto-approve
	@echo "==> [2/5] Loading app + platform images into kind..."
	kind load docker-image $(BACKEND_IMAGE)  --name $(CLUSTER_NAME)
	kind load docker-image $(FRONTEND_IMAGE) --name $(CLUSTER_NAME)
	@echo "    Loading ArgoCD image — kind nodes can't reliably hit quay.io"
	@echo "    behind some corporate TLS chains; pre-loading sidesteps that."
	@docker image inspect $(ARGOCD_IMAGE) > /dev/null 2>&1 || docker pull $(ARGOCD_IMAGE)
	@# Multi-arch manifest lists trip up `kind load --all-platforms` because
	@# upstream argocd ships an attestation sub-manifest whose content blob
	@# isn't pulled to the local store. Use `docker save --platform=<host>`
	@# (Docker 27+) to strip the manifest list to a single-platform export.
	@ARCH=$$(uname -m); case "$$ARCH" in \
	  arm64|aarch64) PLAT=linux/arm64 ;; \
	  x86_64|amd64)  PLAT=linux/amd64 ;; \
	  *) echo "Unsupported arch: $$ARCH"; exit 1 ;; \
	esac; \
	TARFILE=$$(mktemp -t argocd.tar.XXXXXX); \
	docker save --platform=$$PLAT $(ARGOCD_IMAGE) -o $$TARFILE && \
	kind load image-archive $$TARFILE --name $(CLUSTER_NAME); \
	rm -f $$TARFILE
	@echo "==> [3/5] Bootstrap traefik via helmfile (ingress needed before ArgoCD UI is reachable)..."
	KUBECONFIG=$(KUBECONFIG) $(HELMFILE) sync --selector name=traefik
	@echo "==> [4/5] Installing ArgoCD $(ARGOCD_VERSION)..."
	$(KUBECTL) create namespace argocd --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) create namespace observability --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/$(ARGOCD_VERSION)/manifests/install.yaml
	@echo "    Waiting for argocd-server to be ready (up to 5 min)..."
	$(KUBECTL) rollout status -n argocd deployment/argocd-server --timeout=300s
	@# Race fix: app-of-apps reconciles in <1s, but repo-server's gRPC listener
	@# binds a beat later. If root-app hits repo-server before it's listening,
	@# ArgoCD caches a sticky ComparisonError ("connection refused") and child
	@# Apps are never generated. Wait for repo-server before applying root.
	@echo "    Waiting for argocd-repo-server to be ready (up to 5 min)..."
	$(KUBECTL) rollout status -n argocd deployment/argocd-repo-server --timeout=300s
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

demo: ## Paced demo for Loom recording (waits for ENTER between beats so the presenter controls timing).
	@echo "==> Demo starts. Press ENTER between beats to pace with your narration."
	@echo "    Run 'make demo-canary' separately for the canary walkthrough."
	@echo ""
	@echo "[Beat 1] Opening UI..."
	@open https://$(INGRESS_HOST) 2>/dev/null || xdg-open https://$(INGRESS_HOST) 2>/dev/null || true
	@echo "    Also open: Grafana (kubectl port-forward -n observability svc/grafana 3001:80)"
	@echo "    Also open: Rollouts dashboard (kubectl argo rollouts dashboard → :3100)"
	@read -r -p "    Press ENTER to inject anomaly..." _
	@echo ""
	@echo "[Beat 2] Injecting cascade_retry_storm anomaly..."
	@$(KUBECTL) exec -n sre-copilot $$($(KUBECTL) get pod -n sre-copilot -l app.kubernetes.io/name=backend -o name | head -1) -- \
	     curl -sf -X POST "http://localhost:8000/admin/inject?scenario=cascade_retry_storm" \
	     -H "X-Inject-Token: $${ANOMALY_INJECTOR_TOKEN}" 2>/dev/null | jq . || \
	     curl -sf -X POST "http://localhost:8000/admin/inject?scenario=cascade_retry_storm" \
	     -H "X-Inject-Token: $${ANOMALY_INJECTOR_TOKEN}" | jq .
	@echo "    Click 'Try this live anomaly' in the UI; watch SSE tokens stream."
	@read -r -p "    Press ENTER when ready for the trace beat..." _
	@echo ""
	@echo "[Beat 3] Tracing"
	@echo "    Grafana → Explore → Tempo, search service=sre-copilot-backend"
	@echo "    Span tree to point out: http.server → ollama.host_call → ollama.inference (synthetic)"
	@read -r -p "    Press ENTER when ready for the postmortem beat..." _
	@echo ""
	@echo "[Beat 4] Postmortem"
	@echo "    In the UI, click 'Generate postmortem from this incident'."
	@read -r -p "    Press ENTER when ready for the resilience beat..." _
	@echo ""
	@echo "[Beat 5] Resilience — deleting one backend pod..."
	@$(KUBECTL) delete pod -n sre-copilot -l app.kubernetes.io/name=backend --field-selector=status.phase=Running \
	     --wait=false 2>/dev/null | head -1 || true
	@echo "    Watch: kubectl get pods -n sre-copilot -l app.kubernetes.io/name=backend -w"
	@echo "    PDB keeps service available (minAvailable=1). Replacement Ready in <30s."
	@echo ""
	@echo "==> Demo complete. For the canary moment, run: make demo-canary"
	@echo "    See docs/loom-script.md for the full narrative."

demo-canary: ## Build backend:v2, load into kind, bump Rollout image, watch progression
	@echo "==> [demo-canary] Building backend:v2 image (adds confidence: float field)..."
	docker build \
	     -f src/backend/Dockerfile \
	     --build-arg ENABLE_CONFIDENCE=true \
	     -t $(BACKEND_V2_IMAGE) \
	     --label "canary=v2" \
	     .
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

demo-canary-tiny-model: ## [F2 harness] Deploy v2 with phi3:mini (weak model) — judge gate should fire
	@echo "==> [demo-canary-tiny-model] Deploying canary with values-tiny-model.yaml overlay..."
	helm upgrade backend ./helm/backend -n sre-copilot \
	  -f helm/backend/values.yaml -f helm/backend/values-tiny-model.yaml
	@echo "==> Watch: kubectl argo rollouts get rollout backend -n sre-copilot --watch"

demo-canary-broken-chunking: ## [F2 harness] Deploy v2 with truncated log chunks — judge gate should fire (needs backend hook)
	@echo "==> [demo-canary-broken-chunking] WARNING: requires backend hook for CHUNK_MAX_CHARS env"
	helm upgrade backend ./helm/backend -n sre-copilot \
	  -f helm/backend/values.yaml -f helm/backend/values-broken-chunking.yaml

demo-canary-bad-schema: ## [F2 harness] Deploy v2 with schema regression — Layer-1 pytest catches PRE-deploy (needs backend hook)
	@echo "==> [demo-canary-bad-schema] WARNING: requires backend hook for ANALYZE_SCHEMA_OVERRIDE env"
	helm upgrade backend ./helm/backend -n sre-copilot \
	  -f helm/backend/values.yaml -f helm/backend/values-bad-schema.yaml

demo-canary-memory-leak: ## [F2 harness] Deploy v2 with memory leak — operational gate fires (needs backend hook)
	@echo "==> [demo-canary-memory-leak] WARNING: requires backend hook for MEMORY_LEAK_MB_PER_REQ middleware"
	helm upgrade backend ./helm/backend -n sre-copilot \
	  -f helm/backend/values.yaml -f helm/backend/values-memory-leak.yaml

demo-canary-slow: ## [F2 harness] Deploy v2 with 5s LLM delay — operational gate (TTFT) fires (needs backend hook)
	@echo "==> [demo-canary-slow] WARNING: requires backend hook for LLM_PRE_CALL_DELAY_S env"
	helm upgrade backend ./helm/backend -n sre-copilot \
	  -f helm/backend/values.yaml -f helm/backend/values-slow.yaml

demo-canary-clean: ## [F2 harness] Deploy v2 identity (positive control) — both gates pass, promotes to 100%
	@echo "==> [demo-canary-clean] Positive control: identity v2 deploy via stock values.yaml..."
	$(MAKE) demo-canary

demo-canary-bad-prompt: ## [F2 harness] Deploy v2 with hallucinating prompt — judge gate fires (needs backend hook)
	@echo "==> [demo-canary-bad-prompt] WARNING: requires backend hook for ANALYZE_PROMPT_TEMPLATE_PATH env"
	helm upgrade backend ./helm/backend -n sre-copilot \
	  -f helm/backend/values.yaml -f helm/backend/values-bad-prompt.yaml

demo-reset: ## Reset canary — revert backend Rollout to :latest and promote to stable
	@echo "==> [demo-reset] Reverting backend Rollout to stable image ($(BACKEND_IMAGE))..."
	$(KUBECTL) patch rollout backend -n sre-copilot --type=merge \
	     -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","image":"$(BACKEND_IMAGE)"}]}}}}'
	@echo "==> [demo-reset] Rollout reverted to $(BACKEND_IMAGE)"
	@echo "    For full canary CLI control (promote/abort), install: brew install argoproj/tap/kubectl-argo-rollouts"

rebuild-backend: ## Rebuild backend image, load into kind, bump rolloutTrigger via git so ArgoCD reconciles. One-shot dev loop.
	@echo "==> [rebuild-backend] Building $(BACKEND_IMAGE) (context=repo root)..."
	docker build -f src/backend/Dockerfile -t $(BACKEND_IMAGE) .
	@echo "==> [rebuild-backend] Loading into kind cluster '$(CLUSTER_NAME)'..."
	kind load docker-image $(BACKEND_IMAGE) --name $(CLUSTER_NAME)
	@echo "==> [rebuild-backend] Bumping rolloutTrigger in helm/backend/values.yaml..."
	@TS=$$(date -u +%Y-%m-%dT%H-%M-%SZ); \
	  sed -i.bak -E "s|^(rolloutTrigger: ).*|\1\"rebuild-$$TS\"|" helm/backend/values.yaml && \
	  rm -f helm/backend/values.yaml.bak && \
	  echo "    -> rolloutTrigger=rebuild-$$TS"
	@echo "==> [rebuild-backend] Committing and pushing so ArgoCD picks it up..."
	git add helm/backend/values.yaml
	git commit -m "chore(backend): rebuild trigger $$(date -u +%Y-%m-%dT%H:%M:%SZ)" || echo "    (no changes — skipping commit)"
	git push || echo "    (push failed — push manually if needed)"
	@echo "==> [rebuild-backend] Forcing ArgoCD refresh..."
	$(KUBECTL) annotate application backend -n argocd argocd.argoproj.io/refresh=hard --overwrite
	@echo "==> [rebuild-backend] Done. Watch with: kubectl --kubeconfig=$(KUBECONFIG) get rollout backend -n sre-copilot -w"

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

trust-certs: ## Install mkcert local CA + mint wildcard cert for *.localtest.me, plumb into Traefik via TLSStore default
	@command -v mkcert > /dev/null 2>&1 || { \
	  echo "==> [trust-certs] mkcert not installed."; \
	  echo "    macOS:  brew install mkcert nss"; \
	  echo "    Linux:  see https://github.com/FiloSottile/mkcert#installation"; \
	  exit 1; \
	}
	@echo "==> [trust-certs] Installing local root CA into system + browser trust stores..."
	mkcert -install
	@mkdir -p .certs
	@if [ ! -f .certs/localtest.me.pem ] || [ ! -f .certs/localtest.me-key.pem ]; then \
	  echo "==> [trust-certs] Minting wildcard cert for *.localtest.me + localtest.me..."; \
	  cd .certs && mkcert -cert-file localtest.me.pem -key-file localtest.me-key.pem \
	    "*.localtest.me" "localtest.me" "*.sre-copilot.localtest.me"; \
	else \
	  echo "==> [trust-certs] Cert already exists at .certs/localtest.me.pem (delete to re-mint)."; \
	fi
	@echo "==> [trust-certs] Creating TLS Secret in platform namespace..."
	$(KUBECTL) create namespace platform --dry-run=client -o yaml | $(KUBECTL) apply -f -
	$(KUBECTL) create secret tls localtest-me-tls -n platform \
	  --cert=.certs/localtest.me.pem --key=.certs/localtest.me-key.pem \
	  --dry-run=client -o yaml | $(KUBECTL) apply -f -
	@echo "==> [trust-certs] Applying Traefik TLSStore default (one cert serves all IngressRoutes)..."
	@printf 'apiVersion: traefik.io/v1alpha1\nkind: TLSStore\nmetadata:\n  name: default\n  namespace: platform\nspec:\n  defaultCertificate:\n    secretName: localtest-me-tls\n' \
	  | $(KUBECTL) apply -f -
	@echo ""
	@echo "==> [trust-certs] Done. Restart your browser to pick up the new CA."
	@echo "    Verify:  curl -v https://api.sre-copilot.localtest.me/healthz  (no -k needed!)"

dashboards: ## Regenerate Grafana ConfigMaps from observability/dashboards/*.json and apply to cluster (force-reload via delete-then-recreate)
	@echo "==> [dashboards] Regenerating ConfigMaps from JSON source of truth..."
	python3 observability/dashboards/regen-configmaps.py
	@# Delete-then-recreate is the only reliable update path: Grafana's
	@# dashboard provisioner caches the in-DB version once a UID has been
	@# registered, so a kubectl apply on a changed ConfigMap may not actually
	@# update the rendered panels (the sidecar updates the file but Grafana's
	@# content-compare sometimes decides 'no change'). Delete drops the
	@# dashboard from Grafana's DB; re-apply causes a clean re-import.
	@echo "==> [dashboards] Dropping existing ConfigMaps so Grafana removes them from DB..."
	$(KUBECTL) delete configmap -n observability -l grafana_dashboard=1 --ignore-not-found 2>&1 | tail -5
	@echo "==> [dashboards] Waiting for sidecar to delete the dashboard files..."
	@sleep 6
	@echo "==> [dashboards] Re-applying fresh ConfigMaps..."
	$(KUBECTL) apply --server-side --force-conflicts \
	     --field-manager=sre-copilot-dashboards \
	     -f observability/dashboards/configmaps.yaml
	@echo "==> [dashboards] Done. Grafana will re-import within ~10s. Hard-refresh (Cmd-Shift-R) to see."
	@echo "    URL: https://grafana.$(INGRESS_HOST)"

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
	     https://api.$(INGRESS_HOST)/healthz 2>/dev/null || \
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
	@echo "==> Chart cross-ref check (Rollout->AnalysisTemplate)..."
	python3 scripts/check-chart-cross-refs.py
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
	PYTHONPATH=src python3 tests/eval/judge/run_judge.py

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

seal-add: ## Add a key to an EXISTING sealed secret without losing the other keys. Usage: make seal-add SECRET_NAME=backend-secrets KEY=JUDGE_CANARY_TOKEN VALUE=xxx
	@if [ -z "$(SECRET_NAME)" ] || [ -z "$(KEY)" ] || [ -z "$(VALUE)" ]; then \
	  echo "Usage: make seal-add SECRET_NAME=<name> KEY=<key> VALUE=<value>"; \
	  echo "Adds KEY=VALUE to deploy/secrets/<SECRET_NAME>.sealed.yaml without overwriting other keys."; \
	  exit 1; \
	fi
	@if [ ! -f deploy/secrets/$(SECRET_NAME).sealed.yaml ]; then \
	  echo "ERROR: deploy/secrets/$(SECRET_NAME).sealed.yaml does not exist."; \
	  echo "       Use 'make seal SECRET_NAME=$(SECRET_NAME) KEY=$(KEY) VALUE=$(VALUE)' for first key."; \
	  exit 1; \
	fi
	@echo "==> Merging $(KEY) into existing $(SECRET_NAME).sealed.yaml..."
	$(KUBECTL) create secret generic $(SECRET_NAME) \
	  --namespace sre-copilot \
	  --from-literal=$(KEY)=$(VALUE) \
	  --dry-run=client -o yaml | \
	kubeseal \
	  --kubeconfig $(KUBECONFIG) \
	  --controller-namespace platform \
	  --controller-name sealed-secrets \
	  --format yaml \
	  --merge-into deploy/secrets/$(SECRET_NAME).sealed.yaml
	@echo "==> Updated deploy/secrets/$(SECRET_NAME).sealed.yaml ($(KEY) added)"
	@echo "    Apply with: kubectl apply -f deploy/secrets/$(SECRET_NAME).sealed.yaml"

seal-judge-canary-token: ## Generate a random JUDGE_CANARY_TOKEN, write to .env, seal into backend-secrets
	@TOKEN=$$(openssl rand -hex 32); \
	echo "==> Generated 32-byte hex token (will not be printed)"; \
	if grep -q '^export JUDGE_CANARY_TOKEN=' .env 2>/dev/null; then \
	  sed -i.bak "s|^export JUDGE_CANARY_TOKEN=.*|export JUDGE_CANARY_TOKEN=\"$$TOKEN\"|" .env && rm -f .env.bak; \
	  echo "    Updated JUDGE_CANARY_TOKEN in .env"; \
	else \
	  echo "export JUDGE_CANARY_TOKEN=\"$$TOKEN\"" >> .env; \
	  echo "    Appended JUDGE_CANARY_TOKEN to .env"; \
	fi; \
	$(MAKE) seal-add SECRET_NAME=backend-secrets KEY=JUDGE_CANARY_TOKEN VALUE="$$TOKEN"
