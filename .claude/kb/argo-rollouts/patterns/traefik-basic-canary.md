# Traefik Basic Canary (precise weights)

> **Purpose**: Optional upgrade from replica-based canary to Traefik weighted routing, so 25%/50%/100% are precise instead of approximated by replica counts
> **MCP Validated**: 2026-04-26

## When to Use

- You want precise canary weights and replicas count is small (2 -> can't approximate 25% with replicas)
- Traefik is already installed (it is for SRE Copilot per S1 entry #12)
- DESIGN section 4.5 uses replica-based; this pattern is the optional precision upgrade

## How It Works

Argo Rollouts manages two Services (`backend` stable and `backend-canary`) plus a `TraefikService` weighted across them. On each `setWeight` step, Argo rewrites the two `weight:` fields in the TraefikService.

```text
Traefik IngressRoute -> TraefikService (weighted)
                        ├── backend       (weight rewritten by Argo)
                        └── backend-canary (weight rewritten by Argo)
```

## Implementation

### 1. Two Services

```yaml
# helm/backend/templates/service.yaml (existing — stable)
apiVersion: v1
kind: Service
metadata: { name: {{ include "backend.fullname" . }} }
spec:
  selector: {{- include "backend.selectorLabels" . | nindent 4 }}
  ports: [{ name: http, port: 8000, targetPort: http }]
---
# helm/backend/templates/service-canary.yaml (new)
apiVersion: v1
kind: Service
metadata: { name: {{ include "backend.fullname" . }}-canary }
spec:
  selector: {{- include "backend.selectorLabels" . | nindent 4 }}
  ports: [{ name: http, port: 8000, targetPort: http }]
```

The two Services have IDENTICAL selectors. Argo Rollouts injects the `rollouts-pod-template-hash` label into each Service's selector at runtime so they only resolve to stable / canary pods respectively.

### 2. TraefikService

```yaml
# helm/backend/templates/traefik-service.yaml
apiVersion: traefik.io/v1alpha1
kind: TraefikService
metadata:
  name: {{ include "backend.fullname" . }}-traefik
spec:
  weighted:
    services:
      - name: {{ include "backend.fullname" . }}
        port: 8000
        weight: 100
      - name: {{ include "backend.fullname" . }}-canary
        port: 8000
        weight: 0
```

Initial weights: 100/0. Argo rewrites them.

### 3. IngressRoute targeting the TraefikService

```yaml
# helm/backend/templates/ingressroute.yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata: { name: {{ include "backend.fullname" . }} }
spec:
  entryPoints: [websecure]
  routes:
    - match: Host(`api.kind.local`) && PathPrefix(`/`)
      kind: Rule
      services:
        - name: {{ include "backend.fullname" . }}-traefik
          kind: TraefikService
```

### 4. Rollout strategy update

```yaml
spec:
  strategy:
    canary:
      canaryService: {{ include "backend.fullname" . }}-canary
      stableService: {{ include "backend.fullname" . }}
      trafficRouting:
        traefik:
          weightedTraefikServiceName: {{ include "backend.fullname" . }}-traefik
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - analysis: { templates: [{ templateName: backend-canary-health }] }
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
```

## Behavior

```text
Initial:                 backend=100, backend-canary=0     (all traffic stable)
After setWeight: 25:     backend=75,  backend-canary=25
After setWeight: 50:     backend=50,  backend-canary=50
After setWeight: 100:    backend=0,   backend-canary=100   (then promotes; canary becomes stable)
```

The replica count is NOT changed by Argo for traffic split (only by HPA). The router does the math.

## HPA Interaction

HPA scales the Rollout based on aggregate metrics. With Traefik routing, both canary and stable Pods serve real proportional traffic, so CPU/RAM scales naturally. No special HPA config beyond pointing it at the Rollout (see patterns/hpa-rollout-integration.md).

## Verification

```bash
# Initial weights
kubectl get traefikservice backend-traefik -n sre-copilot -o jsonpath='{.spec.weighted.services[*].weight}'
# 100 0

# Trigger canary
kubectl argo rollouts set image backend backend=sre-copilot/backend:v2 -n sre-copilot

# After step 1 (setWeight: 25)
kubectl get traefikservice backend-traefik -n sre-copilot -o jsonpath='{.spec.weighted.services[*].weight}'
# 75 25

# Generate load and confirm split
hey -n 200 -c 5 https://api.kind.local/healthz
# In Tempo, query traces by `service.version` attribute -> ~25% v2, ~75% v1
```

## Pitfalls

| Pitfall | Fix |
|---------|-----|
| Both Services route to ALL pods | Argo not injecting `rollouts-pod-template-hash` — check controller has `traffic-router` permissions |
| TraefikService weights revert to 100/0 every reconcile | Helm template re-rendering and overwriting Argo's edits — add `helm.sh/resource-policy: keep` annotation OR move TraefikService out of Helm and apply manually once |
| 404 on IngressRoute | TraefikService name in IngressRoute mismatches; double-check `{{ include ... }}` |
| SSE long-lived connections stick to one variant | Expected — TCP connection lives on one Pod. Don't reuse across deploys. |

## When Replica-Based Is Fine

For SRE Copilot demo, the replica-based default (DESIGN section 4.5) is enough. Use Traefik routing if:

- You scale `replicas` to a small number (< 4) AND
- You want the demo to show precise 25%/50% in the controller status

## See Also

- concepts/traffic-routing-modes.md — comparison of all three modes
- patterns/rollout-from-deployment.md — base Rollout this evolves from
- patterns/hpa-rollout-integration.md — scaling considerations
