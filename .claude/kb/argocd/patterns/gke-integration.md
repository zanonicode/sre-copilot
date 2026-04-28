# GKE Integration Pattern

> **Purpose**: Deploy and configure ArgoCD on GKE with Terraform, Workload Identity, and GCR access
> **MCP Validated**: 2026-04-22

## When to Use

- You're running ArgoCD on Google Kubernetes Engine (GKE)
- You need ArgoCD to pull images from Google Container Registry (GCR) or Artifact Registry
- You want pods to authenticate to GCP APIs without long-lived service account keys (Workload Identity)
- You're provisioning the GKE cluster and ArgoCD installation via Terraform

## Architecture

```text
GKE Cluster (invoice-pipeline-prod)
├── argocd namespace
│   ├── argocd-server          ← UI + API
│   ├── argocd-repo-server     ← clones Git repos
│   ├── argocd-application-controller ← reconciles Applications
│   └── argocd-dex-server      ← OIDC/SSO (optional)
│
└── invoice-pipeline-prod namespace
    ├── data-extractor         ← Workload Identity → Gemini API
    ├── bigquery-writer        ← Workload Identity → BigQuery
    └── tiff-to-png            ← Workload Identity → GCS
```

## Implementation

### 1. Terraform: GKE Cluster with Workload Identity

```hcl
# infra/modules/gke/main.tf
resource "google_container_cluster" "invoice_pipeline" {
  name     = "invoice-pipeline-${var.environment}"
  location = var.region
  project  = var.project_id

  # Remove default node pool; manage separately
  remove_default_node_pool = true
  initial_node_count       = 1

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Private cluster for prod
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }
}

resource "google_container_node_pool" "primary" {
  name       = "primary"
  cluster    = google_container_cluster.invoice_pipeline.name
  location   = var.region
  project    = var.project_id
  node_count = 2

  node_config {
    machine_type = "e2-standard-2"
    workload_metadata_config {
      mode = "GKE_METADATA"    # required for Workload Identity
    }
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
  }
}
```

### 2. Terraform: Workload Identity for pipeline services

```hcl
# infra/modules/iam/workload-identity.tf

# GCP Service Account for the data-extractor pod
resource "google_service_account" "data_extractor" {
  account_id   = "data-extractor-${var.environment}"
  display_name = "Data Extractor Workload Identity SA"
  project      = var.project_id
}

# Grant Gemini + GCS read access
resource "google_project_iam_member" "data_extractor_gemini" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.data_extractor.email}"
}

resource "google_project_iam_member" "data_extractor_gcs" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.data_extractor.email}"
}

# Bind the GCP SA to the Kubernetes SA via Workload Identity
resource "google_service_account_iam_member" "data_extractor_wi" {
  service_account_id = google_service_account.data_extractor.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[invoice-pipeline-${var.environment}/data-extractor]"
}
```

### 3. Kubernetes ServiceAccount with Workload Identity annotation

```yaml
# apps/data-extractor/base/serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: data-extractor
  namespace: invoice-pipeline-prod
  annotations:
    iam.gke.io/gcp-service-account: data-extractor-prod@invoice-pipeline-prod.iam.gserviceaccount.com
```

```yaml
# apps/data-extractor/base/deployment.yaml (ServiceAccount reference)
spec:
  template:
    spec:
      serviceAccountName: data-extractor   # links to annotated KSA above
      containers:
        - name: data-extractor
          image: gcr.io/invoice-pipeline-prod/data-extractor:latest
          env:
            - name: GOOGLE_CLOUD_PROJECT
              value: invoice-pipeline-prod
            # No GOOGLE_APPLICATION_CREDENTIALS needed — Workload Identity handles auth
```

### 4. Install ArgoCD via Terraform + Helm

```hcl
# infra/modules/argocd/main.tf
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "7.7.0"
  namespace        = "argocd"
  create_namespace = true

  values = [
    file("${path.module}/values.yaml")
  ]

  set {
    name  = "server.service.type"
    value = "ClusterIP"          # expose via Ingress, not LoadBalancer
  }

  depends_on = [google_container_cluster.invoice_pipeline]
}
```

```yaml
# infra/modules/argocd/values.yaml
server:
  extraArgs:
    - --insecure                 # TLS terminated at GKE Ingress/LB

configs:
  params:
    server.insecure: "true"

  cm:
    application.resourceTrackingMethod: annotation  # avoids label conflicts on GKE

  rbac:
    policy.default: role:readonly
    policy.csv: |
      p, role:admin, applications, *, */*, allow
      p, role:admin, clusters, *, *, allow
      g, invoice-pipeline-admins, role:admin

# Resource requests tuned for e2-standard-2 nodes
controller:
  resources:
    requests:
      cpu: 250m
      memory: 512Mi

repoServer:
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
```

### 5. GKE Ingress for ArgoCD UI

```yaml
# apps/argocd-ingress/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-ingress
  namespace: argocd
  annotations:
    kubernetes.io/ingress.class: "gce"
    kubernetes.io/ingress.global-static-ip-name: "argocd-ip"
    networking.gke.io/managed-certificates: "argocd-cert"
spec:
  rules:
    - host: argocd.invoice-pipeline.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: argocd-server
                port:
                  number: 80
---
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: argocd-cert
  namespace: argocd
spec:
  domains:
    - argocd.invoice-pipeline.example.com
```

### 6. Register GKE cluster in ArgoCD (for multi-cluster)

```bash
# Authenticate ArgoCD CLI
argocd login argocd.invoice-pipeline.example.com \
  --username admin \
  --password $(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)

# Add a second cluster (e.g., dev cluster)
argocd cluster add gke_invoice-pipeline-dev_us-central1_invoice-pipeline-dev \
  --name invoice-pipeline-dev

# Verify
argocd cluster list
```

## Verification

```bash
# Check ArgoCD pods are running
kubectl get pods -n argocd

# Verify Workload Identity is working for a pod
kubectl exec -it deploy/data-extractor -n invoice-pipeline-prod -- \
  curl -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email

# Expected output: data-extractor-prod@invoice-pipeline-prod.iam.gserviceaccount.com

# Check ArgoCD can see all applications
argocd app list
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Pod gets 403 on GCS/Gemini | Workload Identity not configured | Check KSA annotation + GCP SA binding |
| ArgoCD can't pull from Artifact Registry | Missing `artifactregistry.reader` role on ArgoCD SA | Add IAM binding |
| `ImagePullBackOff` from GCR | Node SA lacks `storage.objectViewer` on GCR bucket | Add `roles/storage.objectViewer` |
| ArgoCD UI unreachable | GKE Ingress LB not ready (can take 5-10 min) | `kubectl describe ingress argocd-ingress -n argocd` |

## See Also

- [concepts/rbac-and-security.md](../concepts/rbac-and-security.md)
- [patterns/app-of-apps.md](app-of-apps.md)
- [patterns/multi-env-promotion.md](multi-env-promotion.md)
- Kubernetes KB: [gke-workload-identity.md](../../kubernetes/patterns/gke-workload-identity.md)
