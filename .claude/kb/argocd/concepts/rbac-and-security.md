# RBAC and Security

> **Purpose**: Configure ArgoCD RBAC, AppProjects, SSO, and secret management
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-22

## Overview

ArgoCD uses a Casbin-based RBAC system layered on top of Kubernetes RBAC. Policies are defined in the `argocd-rbac-cm` ConfigMap and organized around resources (applications, clusters, repositories, projects) and verbs (get, create, update, delete, sync, action, logs). AppProjects add a second layer of isolation by restricting what repos, clusters, and namespaces an Application can touch. In v3.x, RBAC inheritance between Application-level and resource-level permissions was removed — resource policies must be explicit.

## RBAC Policy Format

```text
p, <subject>, <resource>, <action>, <object>, <effect>
g, <user/group>, <role>
```

| Field | Examples |
|-------|---------|
| subject | `role:admin`, `user:alice`, `proj:myproject:developer` |
| resource | `applications`, `clusters`, `repositories`, `projects`, `logs` |
| action | `get`, `create`, `update`, `delete`, `sync`, `action`, `override`, `logs` |
| object | `*/\*` (all), `myproject/myapp`, `myproject/*` |
| effect | `allow`, `deny` |

## argocd-rbac-cm ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  # Default policy for unauthenticated/unknown users
  policy.default: role:readonly

  # Custom RBAC policies (Casbin format)
  policy.csv: |
    # Platform team: full admin
    p, role:platform-admin, applications, *, */*, allow
    p, role:platform-admin, clusters, *, *, allow
    p, role:platform-admin, repositories, *, *, allow
    p, role:platform-admin, projects, *, *, allow
    p, role:platform-admin, logs, get, */*, allow

    # Developer role: sync only on invoice-pipeline project
    p, role:developer, applications, get, invoice-pipeline/*, allow
    p, role:developer, applications, sync, invoice-pipeline/*, allow
    p, role:developer, applications, override, invoice-pipeline/*, allow
    # v3: logs require explicit permission
    p, role:developer, logs, get, invoice-pipeline/*, allow

    # Read-only role (built into ArgoCD as role:readonly)
    # p, role:readonly, applications, get, */*, allow

    # Group to role mappings (via SSO/Dex)
    g, myorg:platform-team, role:platform-admin
    g, myorg:developers, role:developer

  # v3 flag: set to false to restore v2 RBAC inheritance behavior
  # server.rbac.disableApplicationFineGrainedRBACInheritance: "false"

  # Scope for JWT claims (from OIDC provider)
  scopes: "[groups, email]"
```

## SSO with Google OIDC (Dex)

```yaml
# argocd-cm ConfigMap — configure Dex connector
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  url: https://argocd.example.com

  dex.config: |
    connectors:
      - type: google
        id: google
        name: Google
        config:
          clientID: $dex-google-client-id        # from Secret
          clientSecret: $dex-google-client-secret
          redirectURI: https://argocd.example.com/api/dex/callback
          hostedDomains:
            - myorg.com
          # Fetch Google Groups for RBAC group mapping
          serviceAccountFilePath: /etc/dex/sa/service-account.json
          adminEmail: admin@myorg.com
          fetchTransitiveGroupMembership: true
```

## Secret Management

ArgoCD itself does not decrypt secrets — Git should never contain plaintext secrets. Recommended approaches:

### Option 1: External Secrets Operator (ESO) + GCP Secret Manager

```yaml
# ExternalSecret pulls from GCP Secret Manager into a K8s Secret
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: pipeline-secrets
  namespace: invoice-pipeline-prod
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: gcp-secret-manager
    kind: ClusterSecretStore
  target:
    name: pipeline-secrets
    creationPolicy: Owner
  data:
    - secretKey: langfuse-secret-key
      remoteRef:
        key: langfuse-secret-key
        version: latest
    - secretKey: openrouter-api-key
      remoteRef:
        key: openrouter-api-key
        version: latest
---
# ClusterSecretStore: Workload Identity auth to GCP
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: gcp-secret-manager
spec:
  provider:
    gcpsm:
      projectID: invoice-pipeline-prod
      auth:
        workloadIdentity:
          clusterLocation: us-central1
          clusterName: invoice-pipeline-cluster
          serviceAccountRef:
            name: external-secrets-sa
            namespace: external-secrets
```

### Option 2: Sealed Secrets (offline encryption)

```bash
# Encrypt a secret with the cluster's public key
kubectl create secret generic my-secret \
  --from-literal=api-key=supersecret \
  --dry-run=client -o yaml | \
  kubeseal --format yaml > my-sealed-secret.yaml

# Commit my-sealed-secret.yaml to Git — safe to store
# SealedSecrets controller decrypts at deploy time
```

### Option 3: ArgoCD Vault Plugin (AVP)

```yaml
# Application using AVP for Vault secret injection
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: invoice-pipeline
  namespace: argocd
spec:
  source:
    plugin:
      name: argocd-vault-plugin-helm
      env:
        - name: HELM_ARGS
          value: "-f values-prod.yaml"
```

## Network Policies for ArgoCD

```yaml
# Restrict ArgoCD API server access to internal networks
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-server-ingress
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
  ingress:
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8    # Internal VPC only
      ports:
        - port: 8080
        - port: 8443
```

## Repository Credentials

```yaml
# Register a private Git repo (store token in Secret, not here)
apiVersion: v1
kind: Secret
metadata:
  name: gitops-repo-creds
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://github.com/myorg/invoice-pipeline-gitops
  password: <github-pat-from-secret-manager>
  username: not-used
```

## v3 RBAC Migration Checklist

| Check | Action |
|-------|--------|
| App `update` grants resource update | Add `p, role:X, applications, update/*, project/app, allow` |
| App `delete` grants resource delete | Add `p, role:X, applications, delete/*, project/app, allow` |
| Logs tab visible | Add `p, role:X, logs, get, project/*, allow` |
| Existing policies tested | Run `argocd admin settings rbac validate` |

## Common Mistakes

### Wrong — granting wildcard in default project

```yaml
policy.csv: |
  p, role:developer, applications, *, */*, allow  # Too broad
```

### Correct — scope to specific project

```yaml
policy.csv: |
  p, role:developer, applications, get, invoice-pipeline/*, allow
  p, role:developer, applications, sync, invoice-pipeline/*, allow
```

## Related

- [what-is-argocd.md](what-is-argocd.md)
- [application-model.md](application-model.md)
- [patterns/gke-integration.md](../patterns/gke-integration.md)
