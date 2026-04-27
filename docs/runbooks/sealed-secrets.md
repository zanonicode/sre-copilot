# Runbook: Sealed Secrets

## Overview

Sealed Secrets lets you safely commit encrypted Kubernetes Secrets to Git. The
`sealed-secrets-controller` (running in the `platform` namespace) holds the private key and
decrypts `SealedSecret` objects back into regular Kubernetes Secrets at runtime.

## Prerequisites

- `make up` has been run (cluster is live, sealed-secrets-controller is running in `platform`)
- `kubeseal` is installed locally: `brew install kubeseal`

## Sealing a new secret

```bash
# One-step workflow using the Makefile target:
make seal SECRET_NAME=backend-secrets KEY=ANOMALY_INJECTOR_TOKEN VALUE=your-token-here

# This will:
# 1. Create a plain Secret manifest in /tmp (never written to disk permanently)
# 2. Pipe it through kubeseal against the live controller's public key
# 3. Write the sealed output to deploy/secrets/backend-secrets.sealed.yaml
# 4. Stage the file for git commit
```

The sealed file is safe to commit. The plaintext value never touches the repository.

## Manual workflow (equivalent to `make seal`)

```bash
# Step 1: create a plain Secret locally — never commit this file
kubectl create secret generic backend-secrets \
  --namespace sre-copilot \
  --from-literal=ANOMALY_INJECTOR_TOKEN=your-token-here \
  --dry-run=client -o yaml > /tmp/backend-secrets.yaml

# Step 2: seal it against the live cluster's controller public key
kubeseal \
  --kubeconfig ~/.kube/sre-copilot.config \
  --controller-namespace platform \
  --controller-name sealed-secrets \
  --format yaml \
  < /tmp/backend-secrets.yaml \
  > deploy/secrets/backend-secrets.sealed.yaml

# Step 3: discard the plaintext
rm /tmp/backend-secrets.yaml

# Step 4: commit the sealed file
git add deploy/secrets/backend-secrets.sealed.yaml
git commit -m "chore: seal backend-secrets for sre-copilot"
```

## Applying a sealed secret to the cluster

```bash
kubectl apply -f deploy/secrets/backend-secrets.sealed.yaml --kubeconfig ~/.kube/sre-copilot.config

# Verify the controller unsealed it into a real Secret:
kubectl get secret backend-secrets -n sre-copilot --kubeconfig ~/.kube/sre-copilot.config
```

## Rotating a secret

1. Run `make seal` with the new value — the sealed file gets overwritten
2. Commit and push the new sealed file
3. Apply: `kubectl apply -f deploy/secrets/backend-secrets.sealed.yaml`
4. Bounce the backend pod to pick up the new env value:
   `kubectl rollout restart deploy/backend -n sre-copilot`

## Key rotation (controller re-keying)

If the cluster is destroyed and recreated (`make down && make up`), the Sealed Secrets
controller generates a **new keypair**. All previously sealed files are now unreadable.
You must re-seal all secrets with `make seal` against the new controller.

This is expected behaviour for a local dev cluster. For long-lived clusters, export the
controller key as a backup: `kubectl get secret -n platform -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml`.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `kubeseal: error: cannot fetch public key` | Controller not running | `kubectl get pods -n platform` — is sealed-secrets pod Ready? |
| Secret appears but value is wrong | Sealed against old key | Re-seal with `make seal`, apply, rollout restart |
| `cannot unseal` error in controller logs | Sealed against different cluster | Re-seal against the current cluster |
