# Traffic Routing Modes

> **Purpose**: How Rollouts actually splits traffic between stable and canary — three modes (replica-based, traffic-router, SMI) and why SRE Copilot uses Traefik weighted routing for precise canary
> **MCP Validated**: 2026-04-26

## The Three Modes

### 1. Replica-Based (default — no traffic router needed)

Argo simulates `setWeight: 25` by adjusting the count of canary vs stable Pods so their RATIO matches:

```text
setWeight: 25, replicas: 4 → 3 stable + 1 canary (1/4 = 25%)
setWeight: 25, replicas: 2 → can't do — rounds to 1/2 = 50%
```

Service routes equally across all matching Pods (kube-proxy round-robin). The "weight" is approximated by replica count.

**Pros**: zero infra (just the controller). Works on plain kind. Simplest mental model.

**Cons**: low precision at small replica counts. Step changes momentarily over- or under-shoot.

For SRE Copilot with `replicas: 2`, this means the 25% step is really 50% effective. That's acceptable for a demo — we still get the visual + the analysis gate.

### 2. Traffic-Router (Traefik / Nginx / Istio / ALB)

Argo manages an Ingress / IngressRoute / VirtualService that has a precise weight knob. Pod counts no longer drive split.

```text
setWeight: 25 → router sends exactly 25% of requests to canary Service, 75% to stable
```

Both stable + canary Services exist; replicas can be sized by HPA independently.

**Pros**: precise weights, decouples scaling from canary math.

**Cons**: requires the traffic router AND Argo's integration block.

### 3. SMI (Service Mesh Interface)

Use Linkerd / Open Service Mesh / Istio's SMI shim. Argo writes `TrafficSplit` resources. Same precision as traffic-router. SRE Copilot does NOT install a mesh — skipped.

## SRE Copilot Choice: Traefik weighted routing (S4)

In Sprint 4, the demo benefits from precise 25 → 50 → 100 transitions. Traefik is already installed. Argo Rollouts has built-in Traefik support.

### Configuration

Add to the Rollout spec:

```yaml
spec:
  strategy:
    canary:
      canaryService:  backend-canary           # ClusterIP service selecting only canary pods
      stableService:  backend                  # the existing one
      trafficRouting:
        traefik:
          weightedTraefikServiceName: backend-traefik
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - analysis: { templates: [{ templateName: backend-canary-health }] }
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
```

Two extra K8s objects:

```yaml
# helm/backend/templates/service-canary.yaml
apiVersion: v1
kind: Service
metadata: { name: backend-canary }
spec:
  selector: { app: backend }                    # selector matches both — Argo overrides via pod-template-hash label
  ports: [{ name: http, port: 8000, targetPort: http }]
```

```yaml
# helm/backend/templates/traefik-service.yaml
apiVersion: traefik.io/v1alpha1
kind: TraefikService
metadata: { name: backend-traefik }
spec:
  weighted:
    services:
      - name: backend
        port: 8000
        weight: 100                             # Argo will rewrite both weights
      - name: backend-canary
        port: 8000
        weight: 0
```

Traefik `IngressRoute` then targets `backend-traefik@kubernetescrd` instead of `backend`. Argo updates the two `weight` fields on every step.

## Replica-Based Fallback (S4 minimum)

If Traefik integration is too much complexity for the demo, fall back to replica-based by deleting `trafficRouting:` and the canary Service. Bump `replicas: 4` so 25% precision works.

DESIGN §4.5 spec uses replica-based (no `trafficRouting` block) — that is the official MVP path. Traefik integration is documented here as optional.

## Sticky Sessions Caveat

Replica-based canary doesn't pin a user to one variant — every request is independent. If your app holds in-memory session state (we don't), a user could see version flip-flop mid-session. SSE long-lived connections survive because the connection is to one Pod for its lifetime.

## See Also

- patterns/traefik-basic-canary.md — full Traefik recipe
- patterns/rollout-from-deployment.md — base Rollout spec
- patterns/hpa-rollout-integration.md — HPA + traffic-router interaction
