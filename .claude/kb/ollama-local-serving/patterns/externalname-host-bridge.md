# ExternalName Host Bridge Chart

> **Purpose**: Tiny Helm chart (`helm/platform/ollama-externalname/`) that exposes the host Mac's Ollama as an in-cluster Service so backend Pods can use a clean cluster-DNS URL
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 1 entry #13 (`helm/platform/ollama-externalname/`)
- Whenever a Pod needs to call a service that physically lives on the developer's Mac

## Implementation

### Chart layout

```text
helm/platform/ollama-externalname/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── service.yaml
    ├── networkpolicy-companion.yaml      # placeholder; real allow-rules in S3
    └── NOTES.txt
```

### `Chart.yaml`

```yaml
apiVersion: v2
name: ollama-externalname
description: ExternalName Service exposing host Ollama to the cluster
type: application
version: 0.1.0
appVersion: "0.1.0"
```

### `values.yaml`

```yaml
namespace: sre-copilot
service:
  name: ollama
  port: 11434
externalHost: host.docker.internal           # Docker Desktop magic DNS
networkPolicy:
  enabled: false                              # full allow-rules live in helm/platform/networkpolicies (S2)
```

### `templates/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.service.name }}
  namespace: {{ .Values.namespace }}
  labels:
    app.kubernetes.io/name: ollama
    app.kubernetes.io/component: bridge
    app.kubernetes.io/managed-by: {{ .Release.Service }}
spec:
  type: ExternalName
  externalName: {{ .Values.externalHost }}
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.port }}
      protocol: TCP
```

### `templates/networkpolicy-companion.yaml`

```yaml
{{- if .Values.networkPolicy.enabled }}
# Placeholder NetworkPolicy — real allow-list lives in helm/platform/networkpolicies in S2.
# This file exists so AT-012 (default-deny) can be enforced even before S2 is shipped.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ollama-bridge-allow
  namespace: {{ .Values.namespace }}
spec:
  podSelector:
    matchLabels: { app.kubernetes.io/name: backend }
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: 192.168.0.0/16            # Docker Desktop host gateway range
      ports:
        - protocol: TCP
          port: {{ .Values.service.port }}
{{- end }}
```

### `templates/NOTES.txt`

```text
Ollama bridge installed.

Backend Pods can now reach the host Ollama via:
  http://{{ .Values.service.name }}.{{ .Values.namespace }}.svc.cluster.local:{{ .Values.service.port }}

Verify:
  kubectl run -n {{ .Values.namespace }} --rm -it test --image=curlimages/curl --restart=Never -- \
    curl -fsS http://{{ .Values.service.name }}.{{ .Values.namespace }}.svc.cluster.local:{{ .Values.service.port }}/api/tags

Make sure Ollama is running on the host and bound to 0.0.0.0:
  launchctl setenv OLLAMA_HOST 0.0.0.0:{{ .Values.service.port }}
  brew services restart ollama
```

## Helmfile Registration

```yaml
- name: ollama-externalname
  namespace: sre-copilot
  chart: ./helm/platform/ollama-externalname
  values:
    - ./helm/platform/ollama-externalname/values.yaml
```

This release has no `needs:` — it's the wave-2 entry point in `sre-copilot` namespace (per patterns/helmfile-ordered-releases.md in helm-helmfile KB).

## Configuration Cheatsheet

| Setting | Effect |
|---------|--------|
| `externalHost: host.docker.internal` | Docker Desktop only; on native Linux change to host gateway IP |
| `service.port: 11434` | Ollama default; should match `OLLAMA_HOST` port |
| `networkPolicy.enabled: false` | Defer allow-rules to dedicated `networkpolicies` chart |

## Verification

```bash
helm install ollama-externalname helm/platform/ollama-externalname \
  -n sre-copilot --create-namespace

kubectl get svc -n sre-copilot ollama
# Should show TYPE=ExternalName, EXTERNAL-IP=host.docker.internal

# DNS resolution from a Pod
kubectl run -n sre-copilot --rm -it test --image=curlimages/curl --restart=Never -- \
  nslookup ollama.sre-copilot.svc.cluster.local

# End-to-end
kubectl run -n sre-copilot --rm -it test --image=curlimages/curl --restart=Never -- \
  curl -fsS http://ollama.sre-copilot.svc.cluster.local:11434/api/tags
```

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `dial tcp: lookup host.docker.internal: no such host` | Not running on Docker Desktop (native Linux) | Use `--add-host` on kind config or set externalHost to host gateway IP |
| `connection refused` | Ollama bound to 127.0.0.1 only | `launchctl setenv OLLAMA_HOST 0.0.0.0:11434 && brew services restart ollama` |
| Service has no endpoints | Normal — ExternalName has no Pods | Not an error |
| NetworkPolicy denies traffic | NetworkPolicy doesn't allow CIDR | See concepts/kind-host-networking.md egress example |

## Migration Path (kind → EKS)

When moving to EKS with vLLM in-cluster:

1. Replace this chart with a normal ClusterIP `Service` selecting vLLM Pods.
2. The Service NAME stays `ollama` in namespace `sre-copilot` — backend's URL doesn't change.
3. Drop the host-gateway CIDR from NetworkPolicy egress.

## See Also

- concepts/kind-host-networking.md — DNS theory
- helm-helmfile KB → patterns/helmfile-ordered-releases.md — release ordering
- patterns/openai-sdk-streaming.md — what consumes this Service
