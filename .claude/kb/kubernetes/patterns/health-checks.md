# Health Checks

> **Purpose**: Configure liveness, readiness, and startup probes to drive pod lifecycle correctly
> **MCP Validated**: 2026-04-22

## When to Use

- Every container serving traffic needs a readiness probe so it only receives requests when ready
- Long-initialisation apps (JVM, model loading) need a startup probe to prevent premature liveness failures
- Use liveness only for deadlock/hung-process detection, not slow startup

## Implementation

```yaml
containers:
  - name: invoice-extractor
    image: gcr.io/invoice-pipeline-prod/extractor:v2.1.0
    ports:
      - containerPort: 8080

    # Startup probe: allows up to 5m for slow starts
    # Liveness is suspended until startupProbe succeeds
    startupProbe:
      httpGet:
        path: /health/startup
        port: 8080
      failureThreshold: 30   # 30 × 10s = 5 minutes max startup time
      periodSeconds: 10

    # Liveness probe: restarts pod if it becomes unresponsive / deadlocked
    livenessProbe:
      httpGet:
        path: /health/live
        port: 8080
      initialDelaySeconds: 0   # startupProbe already guards the delay
      periodSeconds: 15
      failureThreshold: 3      # 3 consecutive failures → restart
      timeoutSeconds: 5

    # Readiness probe: removes pod from Service endpoints while not ready
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
      failureThreshold: 3
      successThreshold: 1
      timeoutSeconds: 3
```

### Minimal HTTP Health Endpoint (Python / FastAPI)

```python
from fastapi import FastAPI, Response

app = FastAPI()
_ready = False

@app.on_event("startup")
async def on_startup():
    global _ready
    await load_model()   # or warm up connections
    _ready = True

@app.get("/health/startup")
def startup():
    return {"status": "ok"}

@app.get("/health/live")
def liveness():
    return {"status": "ok"}

@app.get("/health/ready")
def readiness(response: Response):
    if not _ready:
        response.status_code = 503
        return {"status": "not ready"}
    return {"status": "ok"}
```

### gRPC Health Check

```yaml
livenessProbe:
  grpc:
    port: 50051
    service: ""   # empty = server-wide health
  periodSeconds: 10
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `initialDelaySeconds` | 0 | Seconds after container start before first probe |
| `periodSeconds` | 10 | How often to probe |
| `failureThreshold` | 3 | Consecutive failures before action |
| `successThreshold` | 1 | Consecutive successes to mark healthy (readiness only) |
| `timeoutSeconds` | 1 | Probe timeout — set higher than P99 response time |

## Example Usage

```bash
# Check why a pod isn't ready
kubectl describe pod <name> -n pipeline | grep -A 10 "Conditions:"

# Watch probe events live
kubectl get events -n pipeline --field-selector reason=Unhealthy -w
```

## See Also

- [patterns/rolling-deployments.md](rolling-deployments.md)
- [concepts/pods.md](../concepts/pods.md)
- [concepts/deployments.md](../concepts/deployments.md)
