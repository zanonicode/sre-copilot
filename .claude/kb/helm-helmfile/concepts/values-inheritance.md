# Values Inheritance

> **Purpose**: Predict exactly what `.Values.x.y` will be at render time given the chain of defaults, env overrides, and CLI flags
> **MCP Validated**: 2026-04-26

## The Merge Order (lowest → highest priority)

```text
1. Subchart values.yaml                  (e.g., dependencies: redis)
2. Parent chart values.yaml              (defaults)
3. -f file1.yaml -f file2.yaml ...       (later -f wins)
4. helmfile `values:` list (per release)
5. --set / --set-string / --set-file     (CLI; highest)
```

Values are merged using deep-merge for maps and full-replace for lists.

## Lists Replace, Maps Merge

This trips everyone up.

```yaml
# values.yaml
env:
  - name: LOG_LEVEL
    value: info
  - name: PORT
    value: "8000"
```

```yaml
# values-dev.yaml — REPLACES the entire list
env:
  - name: LOG_LEVEL
    value: debug
# PORT is now MISSING
```

Workaround: keep env as a **map** and template into env-list, or always re-list every entry in overrides.

## SRE Copilot Layout

```text
helm/backend/
├── values.yaml          # production-shaped defaults (replicas: 2, prod resources)
├── values-dev.yaml      # kind overrides (replicas: 1, image.pullPolicy: Never, host.docker.internal Ollama)
└── values-prod.yaml     # (deferred to v1.1)
```

Helmfile selects per environment:

```yaml
# helmfile.yaml (excerpt)
environments:
  default:           # local kind
    values:
      - env: dev
  prod:
    values:
      - env: prod

releases:
  - name: backend
    chart: ./helm/backend
    values:
      - ./helm/backend/values.yaml
      - ./helm/backend/values-{{ .Environment.Values.env }}.yaml
```

Invoke: `helmfile sync` (default env) or `helmfile -e prod sync`.

## Subchart Values (e.g., bundled redis)

```yaml
# values.yaml of the parent chart
redis:                       # MUST match dependency name
  enabled: true
  auth:
    enabled: false
  master:
    persistence:
      enabled: false         # ephemeral for kind
```

Subchart sees these as its own `.Values.auth.enabled`, etc.

To pass values from parent **to** subchart explicitly, use `import-values:` in `Chart.yaml`.

## Global Values (cross-chart)

```yaml
# values.yaml
global:
  imageRegistry: ghcr.io/myorg
  observability:
    otelEndpoint: http://otel-collector.observability:4317
```

Any subchart can reference `.Values.global.observability.otelEndpoint`. Helmfile can hoist globals via templating:

```yaml
# helmfile.yaml
releases:
  - name: backend
    chart: ./helm/backend
    values:
      - global:
          observability:
            otelEndpoint: http://otel-collector.observability:4317
```

## `--set` Tricks

```bash
# Scalar
helm upgrade backend helm/backend --set image.tag=v2

# Nested
helm upgrade backend helm/backend --set resources.limits.cpu=1

# List index
helm upgrade backend helm/backend --set 'env[0].value=debug'

# String forced (avoid type coercion of "12345")
helm upgrade backend helm/backend --set-string image.tag=12345

# From file (cert content, etc.)
helm upgrade backend helm/backend --set-file tls.cert=./cert.pem
```

## Required + Default Idioms

```gotemplate
# Fail fast if missing
image:
  repository: {{ required "image.repository must be set" .Values.image.repository }}

# Default if absent
  tag: {{ .Values.image.tag | default .Chart.AppVersion }}
```

## Debugging Inheritance

```bash
# Dump the FINAL merged values for a release without rendering
helm template backend helm/backend -f values-dev.yaml --debug --dry-run | head -40

# Just show merged values (helmfile)
helmfile -l name=backend write-values
```

## See Also

- concepts/chart-anatomy.md — where values.yaml lives
- concepts/helmfile-model.md — environments + values templating
- patterns/common-pitfalls.md — list-merge gotcha
