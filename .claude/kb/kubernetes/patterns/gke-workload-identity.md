# GKE Workload Identity

> **Purpose**: Grant GKE pods keyless access to GCP APIs by binding Kubernetes Service Accounts to Google Service Accounts
> **MCP Validated**: 2026-04-22

## When to Use

- Any GKE pod that calls GCP APIs (GCS, BigQuery, Pub/Sub, Secret Manager, Gemini)
- Replacing JSON key files in containers — key rotation is automatic, no secrets to manage
- Multi-tenant clusters where different namespaces need different GCP permissions

## Implementation

```bash
# 1. Enable Workload Identity on the GKE cluster
gcloud container clusters update invoice-pipeline-cluster \
  --workload-pool=invoice-pipeline-prod.svc.id.goog \
  --region=us-central1

# 2. Enable on the node pool
gcloud container node-pools update default-pool \
  --cluster=invoice-pipeline-cluster \
  --workload-metadata=GKE_METADATA \
  --region=us-central1

# 3. Create Google Service Account (GSA)
gcloud iam service-accounts create invoice-extractor-sa \
  --project=invoice-pipeline-prod \
  --display-name="Invoice Extractor Service Account"

# 4. Grant the GSA the GCP permissions it needs
gcloud projects add-iam-policy-binding invoice-pipeline-prod \
  --member="serviceAccount:invoice-extractor-sa@invoice-pipeline-prod.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding invoice-pipeline-prod \
  --member="serviceAccount:invoice-extractor-sa@invoice-pipeline-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# 5. Allow the KSA to impersonate the GSA (the Workload Identity binding)
gcloud iam service-accounts add-iam-policy-binding \
  invoice-extractor-sa@invoice-pipeline-prod.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:invoice-pipeline-prod.svc.id.goog[pipeline/invoice-extractor-ksa]"
```

```yaml
# 6. Create the Kubernetes Service Account (KSA) with the annotation
apiVersion: v1
kind: ServiceAccount
metadata:
  name: invoice-extractor-ksa
  namespace: pipeline
  annotations:
    iam.gke.io/gcp-service-account: invoice-extractor-sa@invoice-pipeline-prod.iam.gserviceaccount.com
---
# 7. Reference the KSA in the Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: invoice-extractor
  namespace: pipeline
spec:
  template:
    spec:
      serviceAccountName: invoice-extractor-ksa   # ← KSA with WI annotation
      containers:
        - name: extractor
          image: gcr.io/invoice-pipeline-prod/extractor:v2.1.0
          # No GOOGLE_APPLICATION_CREDENTIALS needed — ADC picks up WI automatically
          env:
            - name: GOOGLE_CLOUD_PROJECT
              value: "invoice-pipeline-prod"
```

### Terraform Module for Workload Identity

```hcl
# Create GSA
resource "google_service_account" "extractor" {
  account_id   = "invoice-extractor-sa"
  display_name = "Invoice Extractor SA"
  project      = var.project_id
}

# Grant BigQuery access
resource "google_project_iam_member" "extractor_bq" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.extractor.email}"
}

# Workload Identity binding
resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.extractor.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/${var.ksa_name}]"
}
```

## Configuration

| Component | Purpose |
|-----------|---------|
| `--workload-pool` | Enables WI on cluster; format: `PROJECT.svc.id.goog` |
| `iam.gke.io/gcp-service-account` annotation | Links KSA → GSA |
| `roles/iam.workloadIdentityUser` | Allows KSA to impersonate GSA |
| `GKE_METADATA` on node pool | Enables metadata server for token exchange |

## Example Usage

```bash
# Verify WI is working from inside the pod
kubectl exec -it <pod> -n pipeline -- \
  curl -s -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email

# Should return: invoice-extractor-sa@invoice-pipeline-prod.iam.gserviceaccount.com

# Debug: check KSA annotation
kubectl describe serviceaccount invoice-extractor-ksa -n pipeline
```

## See Also

- [patterns/job-cronjob.md](job-cronjob.md)
- [concepts/namespaces.md](../concepts/namespaces.md)
- [concepts/configmaps-secrets.md](../concepts/configmaps-secrets.md)
