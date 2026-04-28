# Probes and Security Context

> **Purpose**: Production-shape every Pod template — startup/readiness/liveness probes + non-root securityContext + tight resource bounds (Sprint 2 hardening pass)
> **MCP Validated**: 2026-04-26

## When to Use

- Always. This pattern is the S2 entry criterion: every chart must have probes + securityContext + resource limits before merging.

## The Three Probes

| Probe | Purpose | If it fails |
|-------|---------|-------------|
| `startupProbe` | Allow slow-starting apps to boot without liveness killing them | Pod is killed and restarted |
| `readinessProbe` | "Should I receive traffic?" | Pod removed from Service endpoints (no kill) |
| `livenessProbe` | "Am I alive?" | Pod is killed and restarted |

Order of activation: startup → readiness → liveness. Liveness only runs after startup succeeds.

## Implementation (FastAPI backend)

### Add to `values.yaml`

```yaml
probes:
  startup:
    httpGet: { path: /healthz, port: http }
    failureThreshold: 30        # 30 * 2s = 60s grace
    periodSeconds: 2
  readiness:
    httpGet: { path: /healthz, port: http }
    periodSeconds: 5
    timeoutSeconds: 2
    failureThreshold: 3
  liveness:
    httpGet: { path: /healthz, port: http }
    periodSeconds: 10
    timeoutSeconds: 2
    failureThreshold: 3

securityContext:
  pod:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile: { type: RuntimeDefault }
  container:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities: { drop: [ALL] }
```

### Update `templates/deployment.yaml`

```yaml
spec:
  template:
    spec:
      securityContext: {{- toYaml .Values.securityContext.pod | nindent 8 }}
      containers:
        - name: backend
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          ports:
            - name: http
              containerPort: {{ .Values.service.port }}
          startupProbe:   {{- toYaml .Values.probes.startup   | nindent 12 }}
          readinessProbe: {{- toYaml .Values.probes.readiness | nindent 12 }}
          livenessProbe:  {{- toYaml .Values.probes.liveness  | nindent 12 }}
          securityContext: {{- toYaml .Values.securityContext.container | nindent 12 }}
          resources: {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}                    # required because readOnlyRootFilesystem: true
```

### `/healthz` endpoint (FastAPI)

```python
# src/backend/api/health.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/healthz")
async def healthz():
    return {"status": "ok"}
```

Keep `/healthz` cheap — no DB calls, no LLM. Use `/readyz` if you need real upstream checks.

## Resource Limits

Match the chart spec from DESIGN §3 entry #24:

```yaml
resources:
  requests: { cpu: 250m, memory: 350Mi }
  limits:   { cpu: 500m, memory: 500Mi }
```

Reasoning: kind nodes have ~14 GB usable on a 16 GB Mac; ~12 Pods total → 350 Mi requests fit comfortably.

## Dockerfile Alignment

The chart's `runAsUser: 10001` requires the image to actually have that user:

```dockerfile
# src/backend/Dockerfile (excerpt)
RUN groupadd -g 10001 app && useradd -u 10001 -g 10001 -m -s /sbin/nologin app
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=2s --retries=3 CMD curl -fsS http://localhost:8000/healthz
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Error: container has runAsNonRoot and image will run as root` | Image's USER is 0 | Add `USER 10001` to Dockerfile |
| `read-only file system: '/var/log'` | App writes outside `/tmp` | Add emptyDir volumeMount or set `readOnlyRootFilesystem: false` |
| Pods stuck in `CrashLoopBackOff` after probe addition | Probe path 404s during boot | Increase `startupProbe.failureThreshold` or add `/healthz` |
| Frontend (Next.js) fails on readOnly | `.next/cache` writes | Mount `emptyDir` at `/app/.next/cache` |

## Example Usage

```bash
helm upgrade --install backend helm/backend -n sre-copilot -f helm/backend/values-dev.yaml
kubectl describe pod -l app.kubernetes.io/name=backend -n sre-copilot | grep -A8 "Liveness\|Readiness\|Startup"
kubectl get pod -n sre-copilot -w
```

## See Also

- patterns/app-chart-skeleton.md — base chart this layers onto
- otel-lgtm KB → patterns/python-fastapi-instrumentation.md — exclude /healthz from traces
- argo-rollouts KB → concepts/rollout-vs-deployment.md — probes still apply under Rollouts
