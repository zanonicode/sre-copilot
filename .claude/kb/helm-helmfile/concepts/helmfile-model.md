# Helmfile Model

> **Purpose**: Helmfile is the orchestration layer above Helm — declare every release in one file with explicit dependency ordering
> **MCP Validated**: 2026-04-26

## Why Helmfile (vs raw `helm install` loops)

| Concern | Bare Helm | Helmfile |
|---------|-----------|----------|
| Many releases in one cluster | shell loop | `releases:` list |
| Ordering between releases | manual `--wait` + retry | `needs: [ns/name]` graph |
| Per-environment values | one `-f` per command | `environments:` block |
| Diff before apply | `helm diff` per release | `helmfile diff` (all) |
| Idempotency | `upgrade --install` flag | `helmfile sync` / `apply` |
| GitOps preview in CI | scripted | `helmfile template` (one file) |

## Top-Level Structure

```yaml
# helmfile.yaml
repositories:        # helm repo list
  - name: traefik
    url: https://traefik.github.io/charts

environments:        # named contexts (dev/prod)
  default:
    values:
      - env: dev

helmDefaults:        # applied to every release
  wait: true
  timeout: 600
  createNamespace: true

releases:            # the meat
  - name: backend
    namespace: sre-copilot
    chart: ./helm/backend
    values:
      - ./helm/backend/values.yaml
    needs:
      - sre-copilot/redis
```

## The `needs:` Graph

`needs:` declares a hard ordering: helmfile installs/upgrades the dependency first and waits for it to be Ready before proceeding. Format is `<namespace>/<release-name>`.

```yaml
- name: backend
  namespace: sre-copilot
  needs:
    - sre-copilot/redis                  # data dependency
    - observability/otel-collector       # tracing target
```

This is the killer feature for SRE Copilot — the cluster bootstraps cleanly from `helmfile sync` with no manual ordering.

See `patterns/helmfile-ordered-releases.md` for the full SRE Copilot graph.

## Templating (`helmfile.yaml.gotmpl`)

If you rename to `.gotmpl`, the file itself is templated before parsing. Useful for env-driven release lists:

```yaml
releases:
{{- range $name := list "backend" "frontend" }}
  - name: {{ $name }}
    namespace: sre-copilot
    chart: ./helm/{{ $name }}
    values:
      - ./helm/{{ $name }}/values-{{ $.Environment.Values.env }}.yaml
{{- end }}
```

## Sync vs Apply vs Diff

| Command | Action |
|---------|--------|
| `helmfile diff` | Show pending changes per release (uses helm-diff) — CI-safe |
| `helmfile sync` | Install or upgrade every release; always runs upgrade even on no-op |
| `helmfile apply` | Like `sync` but skips upgrade if `diff` shows no changes |
| `helmfile destroy` | Uninstall every release in reverse `needs:` order |

For SRE Copilot the canonical local command is:

```bash
helmfile -e default apply
```

## Selectors

Filter releases without splitting files:

```bash
helmfile -l namespace=observability sync
helmfile -l name=backend diff
helmfile -l 'tier!=platform' template
```

Labels go on each release:

```yaml
releases:
  - name: backend
    namespace: sre-copilot
    labels:
      tier: app
      owner: sre-copilot
```

## Hooks (helmfile-level, not chart-level)

```yaml
releases:
  - name: backend
    chart: ./helm/backend
    hooks:
      - events: [presync]
        showlogs: true
        command: ./scripts/seal-secrets.sh
      - events: [postsync]
        command: kubectl
        args: [rollout, status, deploy/backend, -n, sre-copilot]
```

Different from Helm chart hooks (which are pod-based and run inside the cluster).

## Common Gotchas

- **`needs:` namespace must match `namespace:`** — typos silently break ordering.
- **Adding a `needs:` to an already-deployed release** doesn't retroactively reorder.
- **`wait: true`** waits for Deployments/StatefulSets to be Ready, but NOT for custom CRD resources unless the chart implements its own readiness.
- **Release names are global per namespace** — two releases with the same `name` in different namespaces are fine.

## See Also

- patterns/helmfile-ordered-releases.md — SRE Copilot's full graph
- concepts/values-inheritance.md — how environments + values combine
- patterns/lint-template-diff.md — `helmfile lint` + `template` + `diff` in CI
