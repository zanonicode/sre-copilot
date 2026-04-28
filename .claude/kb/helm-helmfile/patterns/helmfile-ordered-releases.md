# Helmfile: SRE Copilot Ordered Releases

> **Purpose**: The canonical SRE Copilot `helmfile.yaml` — verbatim from DESIGN §4.8 plus inline annotation of why each `needs:` edge exists
> **MCP Validated**: 2026-04-26

## When to Use

- This is THE helmfile for the project. Do not invent a different graph.
- Every new release added to the project must declare `needs:` against the existing graph.

## The Graph (DESIGN §4.8 verbatim)

```yaml
# helmfile.yaml
repositories:
  - name: traefik;        url: https://traefik.github.io/charts
  - name: argo;           url: https://argoproj.github.io/argo-helm
  - name: bitnami;        url: https://charts.bitnami.com/bitnami
  - name: open-telemetry; url: https://open-telemetry.github.io/opentelemetry-helm-charts
  - name: grafana;        url: https://grafana.github.io/helm-charts
  - name: sealed-secrets; url: https://bitnami-labs.github.io/sealed-secrets

releases:
  # --- platform (sync wave 0) ---
  - name: traefik;        namespace: platform;       chart: traefik/traefik
  - name: sealed-secrets; namespace: platform;       chart: sealed-secrets/sealed-secrets
                          needs: [platform/traefik]
  - name: argo-rollouts;  namespace: platform;       chart: argo/argo-rollouts
                          needs: [platform/sealed-secrets]
  # --- observability (sync wave 1) ---
  - name: loki;       namespace: observability;  chart: grafana/loki
                      needs: [platform/traefik]
  - name: tempo;      namespace: observability;  chart: grafana/tempo
                      needs: [platform/traefik]
  - name: prometheus; namespace: observability;  chart: prometheus-community/prometheus
                      needs: [platform/traefik]
  - name: grafana;    namespace: observability;  chart: grafana/grafana
                      needs: [observability/loki, observability/tempo, observability/prometheus]
  - name: otel-collector; namespace: observability; chart: open-telemetry/opentelemetry-collector
                      needs: [observability/loki, observability/tempo, observability/prometheus]
  # --- apps (sync wave 2) ---
  - name: ollama-externalname; namespace: sre-copilot; chart: ./helm/platform/ollama-externalname
  - name: redis;    namespace: sre-copilot; chart: bitnami/redis
                    needs: [sre-copilot/ollama-externalname]
  - name: backend;  namespace: sre-copilot; chart: ./helm/backend
                    needs: [sre-copilot/redis, observability/otel-collector]
  - name: frontend; namespace: sre-copilot; chart: ./helm/frontend
                    needs: [sre-copilot/backend]
```

## Why Each Edge

| Edge | Justification |
|------|---------------|
| `sealed-secrets needs traefik` | Loose ordering — keeps platform wave linear; sealed-secrets exposes no Ingress |
| `argo-rollouts needs sealed-secrets` | Same reason; serializes platform CRD installs to avoid CRD race |
| `loki/tempo/prometheus needs traefik` | Wave separator — observability comes after platform |
| `grafana needs loki+tempo+prometheus` | Datasources are provisioned at start, fail if backends missing |
| `otel-collector needs loki+tempo+prometheus` | Exporters target their endpoints — collector restarts if backends unreachable |
| `redis needs ollama-externalname` | Wave separator inside apps namespace |
| `backend needs redis + otel-collector` | Real runtime deps — backend connects to both at startup |
| `frontend needs backend` | Frontend's healthcheck calls `/api/healthz` indirectly via env |

## Sprint-Phased Activation

Not every release exists in every sprint. Use helmfile selectors or comment out:

| Sprint | Active Releases |
|--------|-----------------|
| S1 | traefik, ollama-externalname, redis, backend, frontend |
| S2 | + sealed-secrets |
| S3 | + loki, tempo, prometheus, grafana, otel-collector (observability wave) |
| S4 | + argo-rollouts (and backend swaps Deployment → Rollout) |

Recommended: keep one `helmfile.yaml` and gate via `condition:` per release:

```yaml
- name: argo-rollouts
  namespace: platform
  chart: argo/argo-rollouts
  needs: [platform/sealed-secrets]
  condition: features.canary.enabled
```

```yaml
# environments
environments:
  default:
    values:
      - features:
          canary:
            enabled: true            # flip false in S1/S2
          observability:
            enabled: true
```

## Configuration

### `helmDefaults`

```yaml
helmDefaults:
  wait: true
  timeout: 600
  createNamespace: true
  atomic: false                      # Tilt iterates; set true in CI
  recreatePods: false
```

### Selectors (operator UX)

```bash
helmfile -l namespace=platform apply       # bring up just platform
helmfile -l namespace=observability apply  # bring up LGTM
helmfile -l namespace=sre-copilot apply    # bring up apps
helmfile destroy                           # tear down in reverse needs order
```

## Example Usage

```bash
# Cold-bootstrap everything (S3+ state)
helmfile deps
helmfile diff
helmfile apply

# S1 narrow path
helmfile -l 'namespace=platform,name=traefik' apply
helmfile -l namespace=sre-copilot apply
```

## Verification

```bash
kubectl get pods -A
helm list -A
# Expect (S3): 5 platform + 5 observability + 4 apps releases
```

## See Also

- concepts/helmfile-model.md — `needs:` semantics, environments, hooks
- argocd KB → patterns/app-of-apps.md — ArgoCD takes over from helmfile in S3 (helmfile keeps working as a dev shortcut)
- ollama-local-serving KB → patterns/externalname-host-bridge.md — what the `ollama-externalname` chart contains
