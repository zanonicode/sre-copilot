# Runbook: Backend Pod Loss

**Symptom:** One of the two backend replicas disappears. The UI may briefly show an error if the user was mid-request on the lost replica. Recovery is automatic via Kubernetes PDB and the readiness probe.

**Root causes:** OOM kill (backend exceeded 500Mi limit), node eviction, manual `kubectl delete pod`, rolling Rollout step, or host machine RAM pressure.

---

## Immediate Triage

```bash
# 1. Check current pod state
kubectl get pods -n sre-copilot -l app.kubernetes.io/name=backend

# 2. Inspect the lost pod's events / exit code
kubectl describe pod -n sre-copilot <pod-name>

# 3. Check if PDB is allowing the deletion
kubectl get pdb -n sre-copilot backend-pdb -o yaml
# Expected: disruptionsAllowed >= 1 only when both pods are Ready

# 4. Check recent Prometheus backend error rate
# Port-forward Grafana: kubectl port-forward -n observability svc/grafana 3001:80 &
# Open http://localhost:3001 → SRE Copilot Overview → Availability panel
```

---

## Resolution

### Case 1: OOM kill

Check the exit code in `kubectl describe pod`:

```
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
```

**Immediate fix:** the replacement pod will start automatically. The user's in-flight request is lost (they must re-submit). The PDB ensures at least 1 replica remains available during the replacement.

**Root cause fix:** reduce backend memory usage or increase the limit.

```bash
# Temporarily increase limits (Rollout / Deployment will re-apply on next sync)
kubectl set resources deployment/backend -n sre-copilot \
  --limits=memory=700Mi --requests=memory=400Mi

# Or adjust helm/backend/values.yaml and re-sync via ArgoCD
```

Check for memory leaks if OOM kills recur: look at the `llm.active_requests` OTel counter — if it monotonically increases without decreasing, SSE streams are not being closed properly.

### Case 2: Node eviction

```bash
# Check which node the pod was on
kubectl get pod <pod-name> -n sre-copilot -o wide

# Check node conditions
kubectl describe node <node-name> | grep -A5 Conditions

# If the node has memory pressure, free RAM on the host:
#   - Stop Ollama (saves ~5.5 GB): ollama stop
#   - Close Chrome tabs
#   - Or trigger model unload: curl -X DELETE http://localhost:11434/api/blobs/...
```

### Case 3: During a canary Rollout

If pod loss happens during an Argo Rollouts canary step, this may be expected (the Rollout is managing pod lifecycle). Check:

```bash
kubectl argo rollouts get rollout backend -n sre-copilot
```

If the Rollout is healthy and progressing, no action needed — the PDB protects availability. If the Rollout is paused or aborted:

```bash
# Abort the canary (reverts to stable image)
kubectl argo rollouts abort backend -n sre-copilot

# Or promote to 100% if the analysis is passing
kubectl argo rollouts promote backend -n sre-copilot
```

---

## Verification

After recovery:

```bash
# Both replicas should be Running and Ready
kubectl get pods -n sre-copilot -l app.kubernetes.io/name=backend

# Run a smoke request
curl -sf -X POST http://localhost:8000/analyze/logs \
  -H 'Content-Type: application/json' \
  -d '{"log_payload":"ERROR DataNode blk_123 replication failed"}' \
  | head -c 100

# Check error rate in Prometheus
kubectl exec -n observability deploy/prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=sum(rate(http_server_duration_milliseconds_count{http_response_status_code=~"5.."}[1m]))' \
  | python3 -m json.tool
```

---

## Related

- AT-006: Backend pod loss (PDB) — service stays available, replacement Ready in <30s
- [ADR-006: Backend statelessness](../adr/0006-backend-statelessness.md)
