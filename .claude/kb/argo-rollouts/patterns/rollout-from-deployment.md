# Rollout from Deployment (Migration Recipe)

> **Purpose**: Replace the backend's existing `Deployment` (S1 chart) with a `Rollout` CRD (S4 chart) without downtime — two paths: inline-template (preferred for SRE Copilot) and `workloadRef` (zero-edit migration)
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 4 entry #40 (`helm/backend/` Deployment -> Rollout swap)
- Whenever you want canary semantics on a workload that's currently a Deployment

## Path A: Inline Template (CHOSEN for SRE Copilot)

Replace `templates/deployment.yaml` with `templates/rollout.yaml`. Same PodTemplateSpec, different kind.

### `helm/backend/templates/rollout.yaml`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: {{ include "backend.fullname" . }}
  labels: {{- include "backend.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicas }}
  revisionHistoryLimit: 5
  selector:
    matchLabels: {{- include "backend.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels: {{- include "backend.selectorLabels" . | nindent 8 }}
    spec:
      serviceAccountName: {{ include "backend.fullname" . }}
      securityContext: {{- toYaml .Values.securityContext.pod | nindent 8 }}
      containers:
        - name: backend
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - { name: http, containerPort: {{ .Values.service.port }} }
          envFrom:
            - configMapRef: { name: {{ include "backend.fullname" . }} }
          env:
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: {{ .Values.otel.endpoint | quote }}
          startupProbe:   {{- toYaml .Values.probes.startup   | nindent 12 }}
          readinessProbe: {{- toYaml .Values.probes.readiness | nindent 12 }}
          livenessProbe:  {{- toYaml .Values.probes.liveness  | nindent 12 }}
          resources: {{- toYaml .Values.resources | nindent 12 }}
          securityContext: {{- toYaml .Values.securityContext.container | nindent 12 }}
          volumeMounts:
            - { name: tmp, mountPath: /tmp }
      volumes:
        - { name: tmp, emptyDir: {} }
  strategy:
    canary:
      maxSurge: 1
      maxUnavailable: 0
      analysis:
        templates: [{ templateName: backend-canary-health }]
        startingStep: 1
        args:
          - name: service-name
            value: {{ include "backend.fullname" . }}
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - analysis: { templates: [{ templateName: backend-canary-health }] }
        - setWeight: 50
        - pause: { duration: 30s }
        - setWeight: 100
```

### Update HPA to target the Rollout

```yaml
# templates/hpa.yaml
spec:
  scaleTargetRef:
    apiVersion: argoproj.io/v1alpha1   # was apps/v1
    kind: Rollout                      # was Deployment
    name: {{ include "backend.fullname" . }}
```

### Delete the old Deployment template

`templates/deployment.yaml` -> remove (or guard with `{{- if not .Values.canary.enabled }}` for sprint-phased rollout).

### values.yaml addition

```yaml
canary:
  enabled: true
  steps:
    - setWeight: 25
    - pauseDuration: 30s
    - setWeight: 50
    - pauseDuration: 30s
    - setWeight: 100
```

(Extract steps to values for tunability — optional.)

## Path B: workloadRef (Zero-Edit Migration)

Use when you don't want to copy the PodTemplateSpec into the Rollout (e.g., upstream chart you can't fork easily). Argo will scale the Deployment to 0 and own its pods.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata: { name: backend }
spec:
  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend                          # the EXISTING Deployment
  replicas: 2
  strategy:
    canary:
      steps:
        - setWeight: 25
        - pause: { duration: 30s }
        - setWeight: 100
```

After this Rollout is applied, run `kubectl scale deploy/backend --replicas=0` (Argo does it automatically too). The Deployment becomes a template-source; the Rollout owns the pods.

## Migration Sequence (no downtime)

```bash
# 1. Install controller (S4 entry #39)
helm upgrade --install argo-rollouts argo/argo-rollouts -n platform

# 2. Install AnalysisTemplate first (controller needs it before Rollout references it)
kubectl apply -f deploy/rollouts/analysis-templates/backend-canary-health.yaml

# 3. Switch chart Deployment -> Rollout (Path A)
helm upgrade backend helm/backend -n sre-copilot -f helm/backend/values-dev.yaml
# Argo Rollout takes over; Deployment is removed by helm; Pods cycle through canary
# (no canary on first apply since no previous version to compare; rolls straight to 100%)

# 4. Verify
kubectl argo rollouts get rollout backend -n sre-copilot
# Status: Healthy

# 5. Trigger a real canary by changing the image
make demo-canary
# (sets image to backend:v2 -> Rollout starts canary flow)
```

## Configuration

| Setting | Value | Why |
|---------|-------|-----|
| `revisionHistoryLimit: 5` | 5 | Keep last 5 ReplicaSets for `undo` |
| `maxSurge: 1` | 1 | One extra Pod during transition (safe for `replicas:2`) |
| `maxUnavailable: 0` | 0 | Never below current replica count |
| `analysis.startingStep: 1` | 1 | Background analysis kicks in after first weight change |

## Verification

```bash
# Status
kubectl argo rollouts get rollout backend -n sre-copilot

# AnalysisRun history
kubectl get analysisrun -n sre-copilot

# Old Deployment is gone (Path A) or scaled to 0 (Path B)
kubectl get deploy -n sre-copilot
```

## Pitfalls

| Pitfall | Fix |
|---------|-----|
| HPA still references Deployment | Update `scaleTargetRef.kind: Rollout` |
| First apply rolls straight to 100% (no canary) | Expected — no previous Rollout revision to compare. Real canary on the SECOND `set image`. |
| ServiceMonitor selector breaks | Selector matches pod-template labels; both Deployment and Rollout produce identical labels — no change needed |
| AnalysisTemplate not found | Apply it BEFORE the first Rollout reconcile, or controller logs `template not found` and the run fails |

## See Also

- patterns/prometheus-analysis-recipe.md — backend-canary-health template
- patterns/cli-demo-runbook.md — `kubectl argo rollouts` flow during demo
- patterns/hpa-rollout-integration.md — HPA wiring detail
- helm-helmfile KB -> patterns/app-chart-skeleton.md — base chart this evolves from
