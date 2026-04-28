# App Chart Skeleton (Backend / Frontend)

> **Purpose**: Lift-able minimum-viable chart for an HTTP service: Deployment + Service + ConfigMap + HPA + PDB + ServiceAccount
> **MCP Validated**: 2026-04-26

## When to Use

- Every app in `helm/{backend,frontend,redis-wrap,...}` follows this shape
- Use as the starting point; add ServiceMonitor (S3) and Rollout (S4) on top

## Implementation

### Layout

```text
helm/backend/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
└── templates/
    ├── _helpers.tpl
    ├── deployment.yaml
    ├── service.yaml
    ├── configmap.yaml
    ├── hpa.yaml
    ├── pdb.yaml
    ├── serviceaccount.yaml
    └── NOTES.txt
```

### `Chart.yaml`

```yaml
apiVersion: v2
name: backend
description: SRE Copilot FastAPI backend
type: application
version: 0.1.0
appVersion: "0.1.0"
```

### `values.yaml`

```yaml
image:
  repository: sre-copilot/backend
  tag: ""                 # default → .Chart.AppVersion
  pullPolicy: IfNotPresent
replicas: 2
service:
  port: 8000
  type: ClusterIP
resources:
  requests: { cpu: 250m, memory: 350Mi }
  limits:   { cpu: 500m, memory: 500Mi }
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 4
  targetCPUUtilizationPercentage: 70
pdb:
  enabled: true
  minAvailable: 1
config:
  OLLAMA_BASE_URL: http://ollama.sre-copilot.svc.cluster.local:11434/v1
  OLLAMA_MODEL: qwen2.5:7b-instruct-q4_K_M
  LOG_LEVEL: info
otel:
  enabled: false                                          # flipped on in S3
  endpoint: http://otel-collector.observability:4317
serviceAccount:
  create: true
```

### `values-dev.yaml` (kind overrides)

```yaml
image:
  pullPolicy: Never                  # we `kind load` locally
replicas: 1
config:
  LOG_LEVEL: debug
autoscaling:
  enabled: false
```

### `templates/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "backend.fullname" . }}
  labels: {{- include "backend.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels: {{- include "backend.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels: {{- include "backend.selectorLabels" . | nindent 8 }}
    spec:
      serviceAccountName: {{ include "backend.fullname" . }}
      containers:
        - name: backend
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: {{ .Values.service.port }}
          envFrom:
            - configMapRef:
                name: {{ include "backend.fullname" . }}
          {{- if .Values.otel.enabled }}
          env:
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: {{ .Values.otel.endpoint | quote }}
          {{- end }}
          resources: {{- toYaml .Values.resources | nindent 12 }}
```

### `templates/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "backend.fullname" . }}
  labels: {{- include "backend.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  selector: {{- include "backend.selectorLabels" . | nindent 4 }}
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: http
```

### `templates/configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "backend.fullname" . }}
data:
{{- range $k, $v := .Values.config }}
  {{ $k }}: {{ $v | quote }}
{{- end }}
```

### `templates/hpa.yaml`

```yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "backend.fullname" . }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment                                  # swap to Rollout in S4
    name: {{ include "backend.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }} }
{{- end }}
```

### `templates/pdb.yaml`

```yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "backend.fullname" . }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels: {{- include "backend.selectorLabels" . | nindent 6 }}
{{- end }}
```

### `templates/serviceaccount.yaml`

```yaml
{{- if .Values.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "backend.fullname" . }}
{{- end }}
```

## Configuration Cheatsheet

| Setting | Where | Effect |
|---------|-------|--------|
| `replicas` | values.yaml | Initial Deployment size (HPA may override) |
| `pdb.minAvailable` | values.yaml | Eviction protection during node drain |
| `autoscaling.targetCPUUtilizationPercentage` | values.yaml | HPA scale trigger |
| `image.pullPolicy: Never` | values-dev.yaml | Use local kind-loaded image |

## Example Usage

```bash
helm dependency update helm/backend
helm lint helm/backend
helm template backend helm/backend -f helm/backend/values-dev.yaml | kubeconform -strict -
helm upgrade --install backend helm/backend -n sre-copilot --create-namespace -f helm/backend/values-dev.yaml
kubectl rollout status deploy/backend -n sre-copilot
```

## See Also

- patterns/probes-and-security.md — add probes + securityContext (S2 update)
- patterns/helmfile-ordered-releases.md — register in helmfile.yaml
- argo-rollouts KB → patterns/rollout-from-deployment.md — swap Deployment → Rollout (S4)
