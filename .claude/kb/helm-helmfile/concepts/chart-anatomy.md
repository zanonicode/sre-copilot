# Chart Anatomy

> **Purpose**: Mental model of every file in a Helm chart and what role it plays at render time
> **MCP Validated**: 2026-04-26

## What a Chart Is

A Helm chart is a directory containing Go-templated Kubernetes manifests plus metadata. `helm install` (or `template`) walks `templates/`, executes Go templates against the merged values, and emits a stream of YAML documents to apply.

## Required Files

```text
mychart/
├── Chart.yaml         # REQUIRED: chart identity + version
├── values.yaml        # REQUIRED (by convention): default values
├── templates/         # REQUIRED: every *.yaml here is rendered
│   └── _helpers.tpl   # OPTIONAL but standard: named template defs
└── .helmignore        # OPTIONAL: glob patterns excluded from package
```

### `Chart.yaml`

```yaml
apiVersion: v2          # v2 = Helm 3
name: backend
description: SRE Copilot FastAPI backend
type: application       # vs library
version: 0.1.0          # CHART version (SemVer; bump on template changes)
appVersion: "1.0.0"     # APP version (string; what's inside the image)
dependencies:           # OPTIONAL: subcharts pulled by `helm dep up`
  - name: redis
    version: "19.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: redis.enabled
```

Two versions exist on purpose: the chart can change shape (templates) without the app changing, and vice-versa.

### `values.yaml`

The single source of defaults. Anything referenced via `.Values.x.y` must have a default here, or be guarded with `default` / `required`.

```yaml
image:
  repository: sre-copilot/backend
  tag: ""               # default to .Chart.AppVersion in template
  pullPolicy: IfNotPresent
replicas: 2
resources:
  requests: { cpu: 250m, memory: 350Mi }
  limits:   { cpu: 500m, memory: 500Mi }
service:
  port: 8000
ingress:
  enabled: false
```

### `templates/_helpers.tpl`

Named templates (Go `define`) reused across manifest files. Standard set:

```gotemplate
{{- define "backend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "backend.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "backend.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "backend.labels" -}}
app.kubernetes.io/name: {{ include "backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
```

### `templates/<resource>.yaml`

Each file produces 0..n manifests. Files starting with `_` are partials and are NOT rendered. `NOTES.txt` is rendered into the post-install message.

### `.helmignore`

Patterns excluded from `helm package`. Default ignores `.git`, `*.swp`, `.DS_Store`, etc. Add `values-dev.yaml` if you do not want dev overrides shipped in the tarball.

## Render Pipeline

```text
Chart.yaml + values.yaml
        +
helmfile values / -f overrides / --set
        ↓
   merged .Values + built-ins (.Release, .Chart, .Files, .Capabilities)
        ↓
   Go template engine walks templates/*.yaml
        ↓
   YAML stream → kubectl apply (server-side)
```

## Built-in Objects (most-used)

| Object | Example | Purpose |
|--------|---------|---------|
| `.Release.Name` | `backend` | Release name from `helm install <name>` |
| `.Release.Namespace` | `sre-copilot` | Target namespace |
| `.Chart.Name` / `.Chart.AppVersion` | `backend` / `1.0.0` | From Chart.yaml |
| `.Values.x.y` | `.Values.image.tag` | Merged values |
| `.Files.Get "configs/foo.json"` | — | Slurp non-template files |
| `.Capabilities.KubeVersion.GitVersion` | `v1.31.0` | Conditional templating per cluster |

## See Also

- concepts/values-inheritance.md — how `.Values` is built
- patterns/app-chart-skeleton.md — minimal real chart
- concepts/lifecycle-and-hooks.md — when each manifest is applied
