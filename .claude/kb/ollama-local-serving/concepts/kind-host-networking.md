# kind Host Networking (Pod → Mac host)

> **Purpose**: How Pods running inside the kind Linux VM reach a service on the Mac host (`host.docker.internal`), and the K8s ExternalName Service that gives Pods a clean cluster-DNS name for it
> **MCP Validated**: 2026-04-26

## The Problem

- Ollama listens on `127.0.0.1:11434` (or `0.0.0.0:11434`) on the macOS host.
- Pods run inside Docker Desktop's Linux VM, on a virtual bridge network.
- Pod's `localhost` is the Pod itself, not the Mac.

## Docker Desktop's Magic DNS: `host.docker.internal`

Docker Desktop on macOS injects `host.docker.internal` into every container's `/etc/hosts` (or via Docker's internal resolver) → resolves to the Mac's host IP from inside the container's network namespace. This works for kind because kind nodes are Docker containers.

```bash
# From inside any kind Pod:
kubectl exec -it deploy/backend -n sre-copilot -- \
  curl -fsS http://host.docker.internal:11434/api/tags
```

⚠️ Caveat: works on **Docker Desktop** (Mac, Windows). On native Linux Docker, `host.docker.internal` does NOT exist by default — use `--add-host` or the docker0 IP. SRE Copilot is Mac-only by design.

## Why ExternalName Service?

Pointing apps directly at `host.docker.internal` works but:

1. Couples app code to Docker-specific DNS.
2. Doesn't compose with NetworkPolicy egress rules (you'd allow by IP).
3. Doesn't survive prod migration (where the LLM is in-cluster).

Solution: a K8s `Service` of `type: ExternalName` that re-exports `host.docker.internal` under a cluster-DNS name:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: sre-copilot
spec:
  type: ExternalName
  externalName: host.docker.internal
  ports:
    - name: http
      port: 11434
      targetPort: 11434
```

Now apps use `http://ollama.sre-copilot.svc.cluster.local:11434` — same shape as any in-cluster service. The migration to vLLM-in-cluster becomes a one-line value flip (swap ExternalName → ClusterIP Service of vLLM Pods).

## How DNS Resolves It

```text
Pod queries: ollama.sre-copilot.svc.cluster.local
   ↓
CoreDNS sees Service type=ExternalName
   ↓
CoreDNS returns CNAME: host.docker.internal
   ↓
Pod queries: host.docker.internal
   ↓
Docker Desktop resolves to host gateway IP (e.g., 192.168.65.254)
   ↓
TCP connect to <gateway>:11434 → Mac host's Ollama
```

NO kube-proxy involvement. NO iptables rule. CNAME indirection only.

## NetworkPolicy Compatibility

Default-deny + explicit allow. Egress to `host.docker.internal` is by IP, not DNS — but Docker Desktop reserves a stable host gateway IP. Practical pattern: allow egress to a CIDR that includes that IP.

```yaml
# helm/platform/networkpolicies/templates/backend-egress.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-egress
  namespace: sre-copilot
spec:
  podSelector:
    matchLabels: { app.kubernetes.io/name: backend }
  policyTypes: [Egress]
  egress:
    # DNS to CoreDNS
    - to:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports: [{ protocol: UDP, port: 53 }, { protocol: TCP, port: 53 }]
    # In-cluster: redis, otel-collector, loki, tempo, prometheus
    - to:
        - podSelector:
            matchLabels: { app.kubernetes.io/name: redis }
      ports: [{ protocol: TCP, port: 6379 }]
    - to:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: observability }
      ports:
        - { protocol: TCP, port: 4317 }
        - { protocol: TCP, port: 4318 }
    # Host bridge: 192.168.0.0/16 covers Docker Desktop's host gateway
    - to:
        - ipBlock:
            cidr: 192.168.0.0/16
      ports: [{ protocol: TCP, port: 11434 }]
```

This satisfies AT-012 (`curl https://api.openai.com` from backend Pod must FAIL) — only port 11434 to host.docker.internal CIDR is allowed for non-cluster traffic.

## Verifying the Bridge

```bash
# Step 1: from a Pod, can we reach the host?
kubectl run -n sre-copilot --rm -it test --image=curlimages/curl --restart=Never -- \
  curl -fsS http://host.docker.internal:11434/api/tags

# Step 2: does the ExternalName Service work?
kubectl run -n sre-copilot --rm -it test --image=curlimages/curl --restart=Never -- \
  curl -fsS http://ollama.sre-copilot.svc.cluster.local:11434/api/tags

# Step 3: does the backend's actual DNS resolve?
kubectl exec -it deploy/backend -n sre-copilot -- \
  nslookup ollama.sre-copilot.svc.cluster.local
# Expect: CNAME → host.docker.internal → <gateway IP>
```

## Limitations

- `kubectl port-forward` to an ExternalName Service does NOT work — there's no Pod backing.
- `kube-proxy` does nothing for ExternalName. So topology-aware routing, hairpin, etc. don't apply.
- If Ollama isn't running on the host, the connection fails immediately (no graceful 503 from K8s). Backend must catch and surface (DESIGN AT-007).

## See Also

- patterns/externalname-host-bridge.md — the full Helm chart
- concepts/macos-metal-serving.md — why Ollama lives on the host
- argocd KB → patterns/app-of-apps.md — when ArgoCD takes over the chart in S3
