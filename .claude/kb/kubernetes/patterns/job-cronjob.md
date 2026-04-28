# Job and CronJob

> **Purpose**: Run batch workloads to completion — one-shot Jobs and scheduled CronJobs
> **MCP Validated**: 2026-04-22

## When to Use

- **Job**: One-shot or parallel batch processing (reprocess failed invoices, DB migration)
- **CronJob**: Recurring scheduled tasks (nightly reconciliation report, hourly GCS cleanup)
- **Not Deployment**: When the workload must terminate after completion, not run indefinitely

## Implementation

```yaml
# One-shot Job: reprocess a batch of failed invoices
apiVersion: batch/v1
kind: Job
metadata:
  name: reprocess-failed-invoices-20260422
  namespace: pipeline
spec:
  completions: 1          # Total successful pod completions required
  parallelism: 1          # Pods running simultaneously
  backoffLimit: 3         # Retry on failure up to 3 times
  activeDeadlineSeconds: 3600  # Kill job after 1 hour regardless
  ttlSecondsAfterFinished: 86400  # Clean up 24h after completion
  template:
    spec:
      restartPolicy: Never  # Never or OnFailure; never use Always for Jobs
      serviceAccountName: invoice-job-sa
      containers:
        - name: reprocessor
          image: gcr.io/invoice-pipeline-prod/reprocessor:v1.0.0
          env:
            - name: BATCH_DATE
              value: "2026-04-22"
            - name: GOOGLE_CLOUD_PROJECT
              value: "invoice-pipeline-prod"
          resources:
            requests:
              cpu: "1000m"
              memory: "1Gi"
            limits:
              cpu: "4000m"
              memory: "4Gi"
---
# Parallel Job: process N invoices concurrently with a work queue
apiVersion: batch/v1
kind: Job
metadata:
  name: parallel-extract-job
  namespace: pipeline
spec:
  completions: 100       # Process 100 invoices total
  parallelism: 10        # 10 pods at once
  completionMode: Indexed  # Each pod gets a unique index (0–99)
  backoffLimit: 5
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: extractor
          image: gcr.io/invoice-pipeline-prod/extractor:v2.1.0
          env:
            - name: JOB_COMPLETION_INDEX
              valueFrom:
                fieldRef:
                  fieldPath: metadata.annotations['batch.kubernetes.io/job-completion-index']
---
# CronJob: nightly reconciliation report at 02:00 UTC
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-reconciliation
  namespace: pipeline
spec:
  schedule: "0 2 * * *"          # Cron syntax: min hour dom month dow
  timeZone: "America/Sao_Paulo"  # k8s 1.27+ supports TZ
  concurrencyPolicy: Forbid       # Skip new run if previous still running
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  startingDeadlineSeconds: 300    # Miss window by 5m → skip this run
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          serviceAccountName: reconciliation-sa
          containers:
            - name: reconciler
              image: gcr.io/invoice-pipeline-prod/reconciler:v1.0.0
              env:
                - name: BIGQUERY_DATASET
                  value: "invoice_pipeline_prod"
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `restartPolicy` | — | Must be `Never` or `OnFailure` for Jobs |
| `backoffLimit` | 6 | Retry count before marking Job failed |
| `activeDeadlineSeconds` | None | Hard timeout for the entire Job |
| `ttlSecondsAfterFinished` | None | Auto-cleanup after completion |
| `concurrencyPolicy` | `Allow` | `Forbid` prevents overlapping CronJob runs |

## Example Usage

```bash
# Trigger a CronJob manually (create a one-off Job from its template)
kubectl create job --from=cronjob/nightly-reconciliation manual-run-1 -n pipeline

# Watch Job pod logs
kubectl logs -l job-name=reprocess-failed-invoices-20260422 -n pipeline -f

# List all Jobs and their status
kubectl get jobs -n pipeline

# Delete completed Jobs older than today
kubectl delete jobs -n pipeline --field-selector status.completionTime!=
```

## See Also

- [patterns/gke-workload-identity.md](gke-workload-identity.md)
- [concepts/resource-limits.md](../concepts/resource-limits.md)
- [concepts/namespaces.md](../concepts/namespaces.md)
