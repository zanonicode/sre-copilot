# Abort and Promote Flow

> **Purpose**: When AnalysisRun fails (or you want to manually promote / abort), what state machine the Rollout enters and which CLI command produces which transition
> **MCP Validated**: 2026-04-26

## When to Use

- Rollout enters `Degraded` after canary fails
- Operator wants to skip a `pause:` step
- Rolling back an in-progress bad release

## State Machine

```text
                        ┌────────────────────────────────────────────────┐
                        │                                                │
                        ▼                                                │
   set image       ┌─────────────┐  step done    ┌─────────────┐         │
   ┌──────────────►│ Progressing │──────────────►│   Healthy   │◄────────┤
   │               └─────────────┘               └─────────────┘         │
   │                  │      │                                           │
   │                  │      │ pause hit                                 │
   │                  │      └─────────────┐                             │
   │                  │                    ▼                             │
   │                  │             ┌─────────────┐  promote             │
   │                  │             │   Paused    │─────────────────────►│
   │                  │             └─────────────┘                      │
   │                  │                    │ abort                       │
   │                  │                    ▼                             │
   │                  │             ┌─────────────┐                      │
   │                  │             │  Aborted    │                      │
   │                  │             └─────────────┘                      │
   │                  │                                                  │
   │                  │ analysis FAIL                                    │
   │                  ▼                                                  │
   │           ┌─────────────┐  undo                                     │
   │           │  Degraded   │──────────────────────────────────────────►│
   │           └─────────────┘                                           │
   │                                                                    ▼
   └──────────── (image roll-back via set image v1) ◄──────────── (back to Healthy on prev rev)
```

## Phase Reference

| Phase | What it means | Recovery |
|-------|---------------|----------|
| **Healthy** | All steps complete, all replicas Ready, latest revision live | Nothing to do |
| **Progressing** | Stepping through `steps:`; AnalysisRuns in flight | Wait OR `promote` to skip pauses |
| **Paused** | Hit a `pause: {}` (no `duration:`) — waiting for human | `kubectl argo rollouts promote` |
| **Degraded** | AnalysisRun Failed OR canary pods can't go Ready | `kubectl argo rollouts undo` to roll back |
| **Aborted** | User called `abort`; rollout halted but NOT reverted | `kubectl argo rollouts undo` OR `retry` |

## Commands

### Promote (skip current pause / step)

```bash
kubectl argo rollouts promote backend -n sre-copilot
```

Advances by one step. If the next step is also a pause, you'll need to promote again.

### Promote --full (skip ALL remaining steps)

```bash
kubectl argo rollouts promote backend --full -n sre-copilot
```

Jumps straight to `setWeight: 100`. Useful for "we trust this canary, ship it" override or for ending a demo quickly.

### Abort

```bash
kubectl argo rollouts abort backend -n sre-copilot
```

Halts the rollout in place. Does NOT roll back — canary pods still exist, weight stays where it was. Status -> `Aborted`. Use this when you want to investigate before deciding.

### Undo (roll back)

```bash
kubectl argo rollouts undo backend -n sre-copilot
# Roll back to specific revision
kubectl argo rollouts undo backend --to-revision=3 -n sre-copilot
```

Replaces the current image with the previous one. Triggers a new Rollout (going through the same steps in reverse direction). Status -> `Progressing` -> `Healthy`.

### Retry (after Degraded)

```bash
kubectl argo rollouts retry rollout backend -n sre-copilot
```

Re-runs the failed AnalysisRun without changing the image. Use when the failure was transient (e.g., Prometheus was momentarily unavailable -> AnalysisRun Errored).

## Common Scenarios

### Scenario 1: Canary fails analysis -> roll back

```bash
# Status: Degraded after AnalysisRun failure
kubectl argo rollouts status backend -n sre-copilot
# Degraded — AnalysisRun 'backend-xxxx' failed: error-rate

# Inspect why
kubectl describe analysisrun backend-xxxx -n sre-copilot
# Will show measured values vs threshold

# Roll back
kubectl argo rollouts undo backend -n sre-copilot
# Rollout starts going back to previous image
kubectl argo rollouts get rollout backend -n sre-copilot --watch
# ... eventually Healthy on prev image
```

### Scenario 2: Slow burn — abort to investigate

```bash
# At setWeight: 50, you notice latency creeping up but NOT failing yet
kubectl argo rollouts abort backend -n sre-copilot
# Rollout pauses at 50/50 split

# Investigate via dashboards / Tempo

# Decision A: roll back
kubectl argo rollouts undo backend -n sre-copilot

# Decision B: continue (looks fine after investigation)
kubectl argo rollouts retry rollout backend -n sre-copilot
```

### Scenario 3: AnalysisRun errored (Prom unreachable)

```bash
# Rollout shows: AnalysisRun in Error state
# Error: Post "http://prometheus...": dial tcp: no such host

# Fix Prometheus connectivity first
kubectl get svc -n observability prometheus-operated

# Then retry
kubectl argo rollouts retry rollout backend -n sre-copilot
```

### Scenario 4: Force-promote during demo

```bash
# Don't want to wait 60s of pauses
kubectl argo rollouts promote backend --full -n sre-copilot
# Immediately ramps to 100%
```

## Helm Upgrade Behavior

When the Helm chart changes (image tag bumped), `helm upgrade backend ...` patches the Rollout spec. The controller notices the new image and starts the canary flow automatically. So in S4, every chart-image-tag change goes through the canary by design.

To force a non-canary deploy (emergency hotfix), patch the Rollout to set `pause: {duration: 0}` on every step OR temporarily change strategy to a stub `blueGreen` (don't recommend for SRE Copilot — keep it simple, use `promote --full`).

## Visibility During Recovery

```bash
# History of revisions
kubectl argo rollouts history rollout backend -n sre-copilot

# Diff between current and previous
kubectl argo rollouts get rollout backend -n sre-copilot

# All AnalysisRuns
kubectl get analysisrun -n sre-copilot --sort-by=.metadata.creationTimestamp
```

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| `undo` doesn't immediately revert traffic | Same canary flow runs in reverse — takes ~60s |
| `abort` then `helm upgrade` -> stuck Aborted | After abort, image swap creates a new attempt; if abort sticks, do `kubectl argo rollouts retry` |
| AnalysisRun Failed but Rollout shows Healthy | Background analysis Failed AFTER rollout completed — controller doesn't roll back retroactively. Use Prom alert (otel-lgtm KB) for this case. |

## See Also

- patterns/cli-demo-runbook.md — happy-path demo flow
- patterns/prometheus-analysis-recipe.md — what fires the failure
- concepts/analysis-templates.md — AnalysisRun status enum
