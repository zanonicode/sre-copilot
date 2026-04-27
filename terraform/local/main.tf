terraform {
  required_version = ">= 1.6"
  required_providers {
    kind = { source = "tehcyx/kind", version = "~> 0.4" }
  }
}

resource "kind_cluster" "sre_copilot" {
  name            = "sre-copilot"
  wait_for_ready  = true
  kubeconfig_path = pathexpand("~/.kube/sre-copilot.config")

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
      kubeadm_config_patches = [yamlencode({
        kind = "InitConfiguration"
        nodeRegistration = {
          kubeletExtraArgs = { "node-labels" = "ingress-ready=true" }
        }
      })]
      extra_port_mappings {
        container_port = 80
        host_port      = 80
        protocol       = "TCP"
      }
      extra_port_mappings {
        container_port = 443
        host_port      = 443
        protocol       = "TCP"
      }
    }

    node {
      role = "worker"
      kubeadm_config_patches = [yamlencode({
        kind = "JoinConfiguration"
        nodeRegistration = {
          kubeletExtraArgs = { "node-labels" = "workload=platform" }
        }
      })]
    }

    node {
      role = "worker"
      kubeadm_config_patches = [yamlencode({
        kind = "JoinConfiguration"
        nodeRegistration = {
          kubeletExtraArgs = { "node-labels" = "workload=apps" }
        }
      })]
    }
  }
}

output "kubeconfig_path" {
  value       = kind_cluster.sre_copilot.kubeconfig_path
  description = "Path to the kubeconfig for the sre-copilot kind cluster."
}

output "cluster_name" {
  value       = kind_cluster.sre_copilot.name
  description = "Name of the kind cluster."
}
