# Helm + Helmfile Quick Reference

> **MCP Validated**: 2026-04-26

## Helm CLI (most-used)

| Command | Purpose |
|---------|---------|
| `helm create <name>` | Scaffold a new chart |
| `helm lint helm/backend` | Static check chart |
| `helm template backend helm/backend -f values-dev.yaml` | Render manifests to stdout (no cluster) |
| `helm install backend helm/backend -n sre-copilot --create-namespace` | Initial install |
| `helm upgrade backend helm/backend -n sre-copilot -f values-dev.yaml` | Apply changes |
| `helm diff upgrade backend helm/backend -f values-dev.yaml` | Preview changes (helm-diff plugin) |
| `helm rollback backend 1` | Revert to revision 1 |
| `helm history backend` | Show release revisions |
| `helm uninstall backend` | Remove release |

## Helmfile CLI

| Command | Purpose |
|---------|---------|
| `helmfile deps` | Resolve chart dependencies |
| `helmfile lint` | Lint every release |
| `helmfile template` | Render every release |
| `helmfile diff` | Show pending changes (uses helm-diff) |
| `helmfile sync` | Apply (install + upgrade) — idempotent |
| `helmfile apply` | Like `sync` but skips no-op upgrades |
| `helmfile destroy` | Uninstall every release |
| `helmfile -l name=backend sync` | Filter by selector |

## Chart Layout

```text
helm/backend/
├── Chart.yaml              # apiVersion: v2, name, version, appVersion
├── values.yaml             # defaults
├── values-dev.yaml         # local kind overrides
├── values-prod.yaml        # (future)
├── templates/
│   ├── _helpers.tpl        # named templates: fullname, labels, selectors
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   ├── serviceaccount.yaml
│   ├── servicemonitor.yaml # (S3, when LGTM is in)
│   └── NOTES.txt
└── .helmignore
```

## Values Precedence (highest wins)

```text
1. --set / --set-string / --set-file        (CLI)
2. -f values-x.yaml (last -f wins on conflict)
3. helmfile values: + secrets:
4. chart values.yaml                        (defaults)
```

## Standard Labels (use in _helpers.tpl)

```yaml
app.kubernetes.io/name: {{ include "backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
```

## Decision Tables

| Need | Use |
|------|-----|
| One service, simple deploy | `helm install` directly |
| Multiple coordinated releases | Helmfile with `needs:` |
| Need to preview before applying | `helm diff upgrade` or `helmfile diff` |
| Validate manifests against K8s schema | `helm template ... \| kubeconform -strict -` |
| Sensitive values | `helmfile secrets:` (sops) — but for SRE Copilot we use Sealed Secrets instead |
| Field is immutable (e.g. Service `.spec.selector`) | Delete + reinstall, or edit values to avoid the change |

## SRE Copilot Helmfile Selectors

```bash
helmfile -l namespace=platform sync       # traefik + sealed-secrets + argo-rollouts
helmfile -l namespace=observability sync  # loki + tempo + prometheus + grafana + otel-collector
helmfile -l namespace=sre-copilot sync    # ollama-externalname + redis + backend + frontend
```
