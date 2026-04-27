# AWS Migration: Running SRE Copilot on EKS

This document describes how this stack would migrate from a local kind cluster to AWS EKS. It is a reference architecture — not a runbook. The intent is to demonstrate that the local kind stack was designed to be migrated cleanly, not to document that the migration has been done.

---

## Component Substitution Map

| Local (kind) | AWS (EKS) | Notes |
|---|---|---|
| kind cluster | EKS cluster | Managed Kubernetes control plane |
| Ollama on host | vLLM on GPU nodes (Karpenter-managed) | Eliminates the ExternalName hack; vLLM speaks the same OpenAI API |
| ExternalName Service → host | ClusterIP Service → vLLM Deployment | Drop-in replacement — backend code unchanged |
| Traefik ingress | AWS Load Balancer Controller + ALB | IngressClass switch; TLS via ACM |
| Sealed Secrets | AWS Secrets Manager via External Secrets Operator | IRSA for pod-level secret access |
| Terraform local (kind) | Terraform AWS (EKS module) | Node groups, VPC, IRSA, IAM roles |
| docker build (arm64) | ECR + CodeBuild or GitHub Actions (multi-arch) | GHCR images already pushed in release workflow |
| hostBridgeCIDR NetworkPolicy | VPC-CIDR-aware NetworkPolicy or Security Groups | Parameterized via ADR-008 pattern — swap the CIDR value |

---

## GPU Node Configuration (vLLM)

The biggest architectural delta is the inference layer. On macOS, Ollama uses Metal MPS. On AWS, the GPU fleet is typically NVIDIA A10G (g5 instances) or A100 (p4d).

### Karpenter NodePool for GPU nodes

```yaml
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: gpu-inference
spec:
  template:
    metadata:
      labels:
        workload: inference
    spec:
      nodeClassRef:
        name: al2-gpu
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: [on-demand]
        - key: node.kubernetes.io/instance-type
          operator: In
          values: [g5.2xlarge, g5.4xlarge]
        - key: kubernetes.io/arch
          operator: In
          values: [amd64]
      taints:
        - key: nvidia.com/gpu
          value: "true"
          effect: NoSchedule
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 10m
```

### vLLM Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-inference
  namespace: sre-copilot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vllm-inference
  template:
    spec:
      nodeSelector:
        workload: inference
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
      containers:
        - name: vllm
          image: vllm/vllm-openai:latest
          args:
            - "--model"
            - "Qwen/Qwen2.5-7B-Instruct"
            - "--port"
            - "11434"
          resources:
            limits:
              nvidia.com/gpu: "1"
          ports:
            - containerPort: 11434
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: sre-copilot
spec:
  selector:
    app: vllm-inference
  ports:
    - port: 11434
      targetPort: 11434
```

The Service is named `ollama` — identical to the local ExternalName Service. **Backend code requires zero changes.** The `OLLAMA_BASE_URL` ConfigMap value points at `http://ollama.sre-copilot.svc.cluster.local:11434/v1` in both environments.

---

## IRSA for Secrets Manager

The local stack uses Sealed Secrets (kubeseal + in-cluster controller). On EKS, the idiomatic pattern is AWS Secrets Manager + External Secrets Operator + IRSA.

### IRSA setup (Terraform excerpt)

```hcl
module "irsa_backend" {
  source = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"

  role_name             = "sre-copilot-backend"
  attach_policy_arns    = [aws_iam_policy.backend_secrets.arn]
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["sre-copilot:backend"]
    }
  }
}

resource "aws_iam_policy" "backend_secrets" {
  name = "sre-copilot-backend-secrets"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = ["arn:aws:secretsmanager:*:*:secret:sre-copilot/*"]
    }]
  })
}
```

### External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: backend-secrets
  namespace: sre-copilot
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: backend-secrets
  data:
    - secretKey: ANOMALY_INJECTOR_TOKEN
      remoteRef:
        key: sre-copilot/backend
        property: ANOMALY_INJECTOR_TOKEN
```

---

## AWS Load Balancer Controller

Replace Traefik with the AWS Load Balancer Controller for the ALB Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sre-copilot
  namespace: sre-copilot
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:...
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
spec:
  rules:
    - host: sre-copilot.your-domain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend
                port:
                  number: 3000
```

---

## NetworkPolicy in VPC

The local `hostBridgeCIDR` NetworkPolicy becomes a VPC CIDR-scoped policy. Since vLLM is now in-cluster, the Ollama egress policy is replaced by same-namespace egress (already in the `networkpolicies` chart). No structural policy changes needed.

---

## Cost Reference (us-east-1, on-demand, approximate)

| Component | Instance | $/hr |
|-----------|----------|------|
| EKS control plane | Managed | $0.10 |
| Worker nodes (3× m6g.large) | Graviton | $0.19 each |
| GPU inference node (g5.2xlarge) | NVIDIA A10G | $1.21 |
| ALB | Per-hour + LCU | ~$0.02 |
| **Total (demo cluster)** | | **~$1.90/hr** |

For a demo cluster that runs 8 hours/day, ~$15/day. For always-on staging, Karpenter's consolidation policy shuts down the GPU node when inference traffic is idle — saving $1.21/hr during off-hours.

---

## Migration Checklist

- [ ] Provision EKS cluster via `terraform/aws/` (not included in MVP — see v1.1 backlog)
- [ ] Push images to ECR or GHCR (release workflow already does GHCR)
- [ ] Deploy vLLM on GPU NodePool; verify `ollama list` equivalent via vLLM API
- [ ] Swap ExternalName Service → ClusterIP pointing at vLLM
- [ ] Install AWS Load Balancer Controller; update Ingress annotations
- [ ] Install External Secrets Operator; configure ClusterSecretStore → Secrets Manager
- [ ] Replace Sealed Secrets ExternalSecret with ESO ExternalSecret
- [ ] Run `make smoke` with `BACKEND_URL=https://sre-copilot.your-domain.com`
- [ ] Run `pytest tests/eval/structural/` to confirm SSE contract unchanged

The application code, Helm charts (other than ExternalName Service), Argo Rollouts manifests, and eval pipeline require no changes.
