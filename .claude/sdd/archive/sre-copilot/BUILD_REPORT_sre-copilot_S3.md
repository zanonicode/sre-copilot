# BUILD REPORT: SRE Copilot — Sprint 3

## Summary

| Metric | Value |
|--------|-------|
| Manifest entries targeted | 11 (S3 only, #28–#38) |
| Manifest entries completed | 11 / 11 |
| Files created (new) | 34 |
| Files modified (existing) | 6 |
| YAML / Helm LoC added | ~1,100 |
| Python LoC added | ~350 |
| TypeScript LoC added | ~130 |
| JSON LoC added | ~300 (dashboard sources) |
| Total LoC added | ~1,880 |
| Unit tests | 36 / 36 passing (S1+S2 regression: PASS) |
| Static egress test (AT-012 unit) | 1 / 1 PASS |
| ruff | PASS (0 errors) |
| helm lint helm/backend/ | PASS |
| helm lint helm/platform/networkpolicies/ | PASS |
| yamllint (relaxed) | PASS (warnings: line-length in alert descriptions only) |
| Sub-agent failures | 0 (all executed directly) |

---

## File Inventory by Manifest Entry

| # | Path | Action | Agent | Status | Notes |
|---|------|--------|-------|--------|-------|
| 28 | `argocd/bootstrap/kustomization.yaml` | Create | direct | DONE | Points at namespace.yaml + upstream install.yaml + root-app.yaml |
| 28 | `argocd/bootstrap/namespace.yaml` | Create | direct | DONE | argocd + observability namespace manifests |
| 28 | `argocd/bootstrap/root-app.yaml` | Create | direct | DONE | Root Application pointing at argocd/applications/ on main branch |
| 28 | `argocd/bootstrap/install.yaml` | Create | direct | DONE | Comment/docs file; actual install via kustomize references upstream URL |
| 29 | `argocd/applications/traefik.yaml` | Create | direct | DONE | wave 0; path: helm/platform/traefik (wrapper chart) |
| 29 | `argocd/applications/sealed-secrets.yaml` | Create | direct | DONE | wave 0; multi-source: upstream chart + repo values ref |
| 29 | `argocd/applications/networkpolicies.yaml` | Create | direct | DONE | wave 1 |
| 29 | `argocd/applications/ollama-externalname.yaml` | Create | direct | DONE | wave 2 |
| 29 | `argocd/applications/loki.yaml` | Create | direct | DONE | wave 1; multi-source pattern for upstream chart + local values |
| 29 | `argocd/applications/tempo.yaml` | Create | direct | DONE | wave 1; multi-source |
| 29 | `argocd/applications/prometheus.yaml` | Create | direct | DONE | wave 1; multi-source |
| 29 | `argocd/applications/grafana.yaml` | Create | direct | DONE | wave 2; multi-source |
| 29 | `argocd/applications/otel-collector.yaml` | Create | direct | DONE | wave 2; multi-source |
| 29 | `argocd/applications/backend.yaml` | Create | direct | DONE | wave 3 |
| 29 | `argocd/applications/frontend.yaml` | Create | direct | DONE | wave 4 |
| 29 | `argocd/applications/observability-config.yaml` | Create | direct | DONE | wave 3; kustomize path: observability/ (dashboards + alerts) |
| 30 | `helm/observability/lgtm/loki-values.yaml` | Create | direct | DONE | SingleBinary, filesystem storage, persistence disabled, 24h retention |
| 30 | `helm/observability/lgtm/tempo-values.yaml` | Create | direct | DONE | Monolithic, local backend, persistence disabled |
| 30 | `helm/observability/lgtm/prometheus-values.yaml` | Create | direct | DONE | 12h retention, no persistence, kube-state-metrics enabled |
| 30 | `helm/observability/lgtm/grafana-values.yaml` | Create | direct | DONE | Sidecar dashboards + datasources wired (Prom + Loki + Tempo); anonymous viewer |
| 31 | `helm/observability/otel-collector/values.yaml` | Create | direct | DONE | Deployment mode, OTLP gRPC+HTTP, exporters: Tempo/Loki/Prometheus, filter healthz spans |
| 32 | `src/backend/observability/__init__.py` | Update | direct | DONE | Populated exports: init_otel, configure_logging, all metric handles, synthetic_ollama_span |
| 32 | `src/backend/observability/init.py` | Update | direct | DONE | Added http_capture_headers_server_request for traceparent; stubs were already real |
| 32 | `src/backend/main.py` | Update | direct | DONE | Added CORSMiddleware (allow traceparent header), wired init_otel(app) call |
| 33 | `helm/backend/values.yaml` | Update | direct | DONE | OTEL_EXPORTER_OTLP_ENDPOINT default set to otel-collector.observability:4317; serviceMonitor enabled |
| 33 | `helm/backend/templates/servicemonitor.yaml` | Create | direct | DONE | ServiceMonitor for Prometheus scrape; guarded by .Values.serviceMonitor.enabled |
| 33 | `helmfile.yaml.gotmpl` | Update | direct | DONE | Added grafana/open-telemetry/prometheus-community repos; added LGTM + OTel releases; wired OTEL_EXPORTER_OTLP_ENDPOINT via ADR-008 env-template; backend needs otel-collector |
| 34 | `src/frontend/observability/otel.ts` | Create | direct | DONE | WebTracerProvider + BatchSpanProcessor + FetchInstrumentation + DocumentLoadInstrumentation; W3C propagator for traceparent |
| 34 | `src/frontend/observability/web-vitals.ts` | Create | direct | DONE | CLS/FCP/FID/LCP/TTFB recorded as spans via getTracer() |
| 34 | `src/frontend/observability/index.ts` | Create | direct | DONE | Re-exports initBrowserOtel and measureWebVitals |
| 34 | `src/frontend/src/components/OtelInitializer.tsx` | Create | direct | DONE | Client component; calls initBrowserOtel + measureWebVitals on mount |
| 34 | `src/frontend/src/app/layout.tsx` | Update | direct | DONE | Imports OtelInitializer, renders it in body before nav |
| 35 | `observability/dashboards/configmaps.yaml` | Create | direct | DONE | 4 ConfigMaps with grafana_dashboard=1 label: Overview, LLM Performance, Cluster Health, Cost & Capacity |
| 35 | `observability/dashboards/*.json` | Create | direct | DONE | Source JSON files (overview, llm-performance, cluster-health, cost-capacity) |
| 36 | `observability/alerts/recording-rules.yaml` | Create | direct | DONE | PrometheusRule: availability error ratios (5m/30m/1h/6h), TTFT bad ratios (5m/30m/1h/6h), response bad ratios |
| 36 | `observability/alerts/alert-rules.yaml` | Create | direct | DONE | MWMBR alerts: 3 SLOs × fast+slow page pairs; BackendPodCrashLoop, BackendNoReplicas, OtelCollectorDown |
| 37 | `tests/integration/test_egress_denied.py` | Create | direct | DONE | AT-012: cluster-mode (kubectl exec curl) + static manifest check; skip without kubeconfig |
| 38 | `tests/smoke/test_trace_visible.py` | Create | direct | DONE | AT-001 full: SSE shape + Tempo poll within 5s + >=4 spans + ollama.inference assertion |
| — | `observability/kustomization.yaml` | Create | direct | DONE | Kustomize entrypoint for ArgoCD: includes dashboards/configmaps.yaml + both alert rules |

---

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| ruff (backend) | `ruff check src/backend/` | PASS — 0 errors |
| ruff (tests) | `ruff check tests/integration/test_egress_denied.py tests/smoke/test_trace_visible.py` | PASS |
| helm lint backend | `helm lint helm/backend/` | PASS (1 chart, 0 failures) |
| helm lint networkpolicies | `helm lint helm/platform/networkpolicies/` | PASS |
| backend import | `PYTHONPATH=src python3 -c "from backend.main import app"` | PASS |
| pytest unit (S1+S2) | `pytest tests/backend/unit/` | 35/35 PASS |
| pytest egress unit | `pytest tests/integration/test_egress_denied.py::test_egress_deny_unit_documented` | 1/1 PASS |
| pytest collect all | `pytest --collect-only -q` | 46 tests collected, 0 errors |
| yamllint | `yamllint -d relaxed argocd/ observability/alerts/` | PASS (line-length warnings only) |

---

## NetworkPolicy Update Status

The `allow-observability-egress` NetworkPolicy was **pre-wired in S2** per the BUILD_REPORT_sre-copilot_S2.md:

```yaml
# helm/platform/networkpolicies/templates/networkpolicies.yaml (already in S2)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-observability-egress
  namespace: sre-copilot
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: observability
```

This covers backend pods → OTel collector (port 4317) in the observability namespace. No additional NetworkPolicy changes were needed for S3.

**Verification:** `test_egress_deny_unit_documented` confirms the manifest includes `default-deny-egress` and the observability allow rule. PASS.

---

## ArgoCD Application Inventory

| Application | Sync Wave | Source | Target Namespace |
|-------------|-----------|--------|-----------------|
| traefik | 0 | `helm/platform/traefik` (wrapper) | platform |
| sealed-secrets | 0 | upstream `bitnami-labs/sealed-secrets` + repo values | platform |
| networkpolicies | 1 | `helm/platform/networkpolicies` | sre-copilot |
| loki | 1 | upstream `grafana/loki` + repo values | observability |
| tempo | 1 | upstream `grafana/tempo` + repo values | observability |
| prometheus | 1 | upstream `prometheus-community/prometheus` + repo values | observability |
| ollama-externalname | 2 | `helm/platform/ollama-externalname` | sre-copilot |
| grafana | 2 | upstream `grafana/grafana` + repo values | observability |
| otel-collector | 2 | upstream `open-telemetry/opentelemetry-collector` + repo values | observability |
| observability-config | 3 | `observability/` (kustomize) — dashboards + alert rules | observability |
| backend | 3 | `helm/backend` | sre-copilot |
| frontend | 4 | `helm/frontend` | sre-copilot |

**Total Applications: 12** (excl. root app — 13 including root)

**Note:** Redis was NOT included per v1.6 YAGNI removal. argo-rollouts is deferred to S4 per DESIGN.

---

## Memory Budget Recheck

| Component | DESIGN §1.2 Budget | Notes |
|-----------|-------------------|-------|
| Existing S1+S2 workloads | ~3.7 GB (traefik + backend×2 + frontend + sealed-secrets + kind overhead) | Unchanged |
| Loki (single-binary) | 350 MB budget / ~256-512 MB limit | Within budget |
| Tempo (monolithic) | 250 MB budget / ~256 MB limit | Within budget |
| Prometheus | 500 MB budget / ~512 MB-1 GB limit | Borderline — see note |
| Grafana | 180 MB budget / ~128-256 MB limit | Within budget |
| OTel Collector | 150 MB budget / ~128-256 MB limit | Within budget |
| ArgoCD (server+repo+controller) | 600 MB budget | Not yet deployed — user runs `kubectl apply -k argocd/bootstrap/` |
| **LGTM + OTel subtotal** | **~1,430 MB projected** | Slightly above DESIGN §1.2 ~1,430 MB (matches) |

**Tally:** Existing ~3.7 GB + LGTM ~1.4 GB + ArgoCD ~0.6 GB + OTel ~0.2 GB = **~5.9 GB cluster** + Ollama 5.5 GB + Docker overhead 1.5 GB + Chrome 1.5 GB = **~14.4 GB total**

**Flag:** Prometheus memory limit is 1 Gi vs 500 MB budget. Under steady-state with 12h retention and 30s scrape interval it typically sits at 400-600 MB RSS, but spikes can hit 1 GB. If memory pressure is observed, reduce `--storage.tsdb.retention.time=6h` and reduce scrape targets. This is the highest-risk component for the 16 GB budget. Flagged for v1.7 monitoring.

**Slack:** ~1.6 GB (tight but above the >1 GB safety floor at 16 GB). If Prometheus spikes to its 1 Gi limit simultaneously with Chrome, slack narrows to ~600 MB. Mitigation: keep `OLLAMA_KEEP_ALIVE=0` during non-demo sessions to free 5.5 GB.

---

## S3 Exit Gate Checklist

| Gate | Status | Notes |
|------|--------|-------|
| ArgoCD owns all workloads | READY (pending `kubectl apply -k argocd/bootstrap/`) | 12 child Applications defined with correct waves |
| Every request produces trace in Tempo ≤5s with ≥4 spans | READY (pending cluster deploy) | OTel init wired into backend main.py; synthetic ollama.inference span already in spans.py |
| All 4 Grafana dashboards display live data | READY (pending deploy) | ConfigMaps with grafana_dashboard=1 label, grafana sidecar enabled in values |
| Alertmanager/Prometheus rules for 3 SLOs with MWMBR | DONE | recording-rules.yaml + alert-rules.yaml: 3 SLOs × fast+slow pairs = 6 page alerts |
| Egress-deny test passes (AT-012) | PARTIAL (unit PASS, live-cluster needs `make up` + cluster) | Static manifest check passes; kubectl exec test skips without kubeconfig |

---

## OTel Wiring Summary (#32 detail)

The S1 stubs were already real implementations (not skeletons). The changes made in S3:

| File | Change |
|------|--------|
| `src/backend/observability/__init__.py` | Populated from empty to full exports |
| `src/backend/observability/init.py` | Added `http_capture_headers_server_request` to capture traceparent + x-request-id |
| `src/backend/main.py` | Added `CORSMiddleware` (allow traceparent header from browser), called `init_otel(app)` |
| `helm/backend/values.yaml` | Set `OTEL_EXPORTER_OTLP_ENDPOINT` default to otel-collector address |
| `helmfile.yaml.gotmpl` | Wired `OTEL_EXPORTER_OTLP_ENDPOINT` via ADR-008 env-template |

The `metrics.py` and `spans.py` were already correct implementations — no changes needed.

---

## Sub-Agent Failures

None. All 11 manifest entries executed directly without delegation.

---

## Tech Debt and Open Questions (v1.7 iterate candidates)

| # | Item | Impact | Suggested Resolution |
|---|------|--------|---------------------|
| TD-S3-1 | Prometheus memory spike risk | May exceed 16 GB budget under load | Consider reducing retention to 6h or switching to VictoriaMetrics for lower RSS |
| TD-S3-2 | ArgoCD multi-source `$values` ref requires ArgoCD 2.6+ | Sealed-secrets and LGTM apps won't sync on ArgoCD < 2.6 | Verify ArgoCD version in bootstrap install; current kustomization.yaml pulls 2.12.0 (safe) |
| TD-S3-3 | ~~Frontend OTel packages not in package.json~~ | RESOLVED — OTel packages added to `src/frontend/package.json` during build | Run `cd src/frontend && npm install` after pulling |
| TD-S3-4 | Grafana anonymous auth enables unauthenticated dashboard access | Acceptable for a local kind demo, not for anything exposed | Document in README "Grafana is read-only anonymous for demo purposes; set auth.anonymous.enabled=false for any shared environment" |
| TD-S3-5 | Tempo version constraint `1.x.x` may drift | Tempo 2.x has a different schema | Pin to `1.7.x` explicitly in production; ArgoCD image updater can handle minor bumps |
| TD-S3-6 | Dashboard ConfigMaps have hardcoded namespace `observability` | If namespace changes, ConfigMaps are orphaned | Use kustomize namePrefix/namespace in observability/kustomization.yaml |
| TD-S3-7 | `grafana_admin_password` in values.yaml is plaintext | Fine for local demo; not for any shared cluster | Seal it as a SealedSecret in S4 or read from Kubernetes secret ref |

---

## User Action Handover

After this build is pushed to Git (branch `main`), follow these steps in order:

### Step 1: Install ArgoCD

```bash
kubectl apply -k argocd/bootstrap/
kubectl rollout status -n argocd deployment/argocd-server --timeout=120s
```

### Step 2: Apply root Application

```bash
kubectl apply -f argocd/bootstrap/root-app.yaml
```

### Step 3: Watch Applications sync

```bash
kubectl get applications -n argocd -w
```

ArgoCD will sync all 12 child Applications in wave order (0 → 1 → 2 → 3 → 4).
Expected total sync time: ~3-5 minutes (LGTM charts are the heaviest).

### Step 4: Deploy LGTM stack via helmfile (parallel path)

ArgoCD manages everything declaratively. But for first-time setup, the observability namespace and LGTM may need a `helmfile sync` before ArgoCD can read the chart values (bootstrap ordering):

```bash
helmfile sync --selector namespace=observability
```

### Step 5: Apply dashboards and alert rules

These are applied by ArgoCD via the `observability-config` Application. Manually:

```bash
kubectl apply -k observability/
```

### Step 6: Verify OTel pipeline

```bash
# Port-forward Grafana
kubectl port-forward -n observability svc/grafana 3001:80 &

# Port-forward Tempo
kubectl port-forward -n observability svc/tempo 3200:3200 &

# Issue a request
curl -X POST https://sre-copilot.localtest.me/analyze/logs \
  -H 'Content-Type: application/json' \
  -d '{"log_payload": "ERROR: DataNode block_123 failed replication"}' \
  --no-buffer -s | head -5

# Check Tempo search (within 5s)
curl "http://localhost:3200/api/search?tags=service.name%3Dsre-copilot-backend&limit=1" | jq .
```

### Step 7: Run AT-012 egress test

```bash
pytest tests/integration/test_egress_denied.py -v
```

### Step 8: Run smoke test with Tempo assertion

```bash
BACKEND_URL=https://sre-copilot.localtest.me TEMPO_URL=http://localhost:3200 \
  pytest tests/smoke/test_trace_visible.py -v
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-25 | build-agent | Initial S3 build. 11 manifest entries #28–#38 completed. ArgoCD app-of-apps, LGTM stack, OTel collector, backend OTel wiring, frontend OTel SDK, 4 Grafana dashboards, MWMBR SLO alerts, AT-012 egress test, AT-001 Tempo trace test. |

---

## Status: COMPLETE (pending user `kubectl apply -k argocd/bootstrap/` + helmfile sync)
