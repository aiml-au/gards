provider "kubernetes" {
  host                   = data.terraform_remote_state.cluster.outputs.host
  client_certificate     = base64decode(data.terraform_remote_state.cluster.outputs.client_certificate)
  client_key             = base64decode(data.terraform_remote_state.cluster.outputs.client_key)
  cluster_ca_certificate = base64decode(data.terraform_remote_state.cluster.outputs.cluster_ca_certificate)
}

resource "kubernetes_namespace" "nvidia" {
  metadata {
    name = "nvidia"
  }
}

resource "kubernetes_daemonset" "nvidia-device-plugin" {
  metadata {
    name      = "nvidia-device-plugin"
    namespace = kubernetes_namespace.nvidia.metadata.0.name
  }
  spec {
    selector {
      match_labels = {
        name = "nvidia-device-plugin"
      }
    }
    strategy {
      rolling_update {}
    }
    template {
      metadata {
        # Mark this pod as a critical add-on; when enabled, the critical add-on scheduler
        # reserves resources for critical add-on pods so that they can be rescheduled after
        # a failure.  This annotation works in tandem with the toleration below.
        annotations = {
          "scheduler.alpha.kubernetes.io/critical-pod" = ""
        }
        labels = {
          name = "nvidia-device-plugin"
        }
      }

      spec {
        # Allow this pod to be rescheduled while the node is in "critical add-ons only" mode.
        # This, along with the annotation above marks this pod as a critical add-on.
        toleration {
          key      = "CriticalAddonsOnly"
          operator = "Exists"
        }
        toleration {
          key      = "nvidia.com/gpu"
          operator = "Exists"
          effect   = "NoSchedule"
        }
        toleration {
          key      = "sku"
          operator = "Equal"
          value    = "gpu"
          effect   = "NoSchedule"
        }
        container {
          image = "mcr.microsoft.com/oss/nvidia/k8s-device-plugin:v0.14.1"
          name  = "nvidia-device-plugin-ctr"
          security_context {
            allow_privilege_escalation = false
            capabilities {
              drop = [
                "ALL"
              ]
            }
          }
          volume_mount {
            name       = "device-plugin"
            mount_path = "/var/lib/kubelet/device-plugins"
          }
        }
        node_selector = {
          "accelerator" = "nvidia"
        }
        volume {
          name = "device-plugin"
          host_path {
            path = "/var/lib/kubelet/device-plugins"
          }
        }
      }
    }
  }
}

resource "kubernetes_namespace" "nginx" {
  metadata {
    name = "nginx"
  }
}

data "kubernetes_service" "nginx" {
  depends_on = [
    helm_release.nginx,
    time_sleep.wait_for_nginx
  ]
  metadata {
    name      = "${helm_release.nginx.metadata.0.name}-ingress-nginx-controller"
    namespace = helm_release.nginx.namespace
  }
}

output "nginx_external_ip" {
  value = data.kubernetes_service.nginx.status.0.load_balancer.0.ingress.0.ip
}

resource "kubernetes_namespace" "cert_manager" {
  metadata {
    name = "cert-manager"
  }
}

resource "kubernetes_namespace" "keda" {
  metadata {
    name = "keda"
  }
}

resource "kubernetes_cluster_role" "keda_edit" {
  depends_on = [
    helm_release.keda
  ]
  metadata {
    name   = "keda:edit"
    labels = {
      "rbac.authorization.k8s.io/aggregate-to-admin" = "true"
      "rbac.authorization.k8s.io/aggregate-to-edit"  = "true"
    }
  }
  rule {
    api_groups = [
      "keda.sh"
    ]
    resources = [
      "clustertriggerauthentications",
      "scaledjobs",
      "scaledobjects",
      "triggerauthentications"
    ]
    verbs = [
      "create",
      "delete",
      "patch",
      "update"
    ]
  }
}

resource "kubernetes_cluster_role" "keda_view" {
  depends_on = [
    helm_release.keda
  ]
  metadata {
    name   = "keda:view"
    labels = {
      "rbac.authorization.k8s.io/aggregate-to-admin" = "true"
      "rbac.authorization.k8s.io/aggregate-to-edit"  = "true"
      "rbac.authorization.k8s.io/aggregate-to-view"  = "true"
    }
  }
  rule {
    api_groups = [
      "keda.sh"
    ]
    resources = [
      "clustertriggerauthentications",
      "scaledjobs",
      "scaledobjects",
      "triggerauthentications"
    ]
    verbs = [
      "get",
      "list",
      "watch"
    ]
  }
}

resource "kubernetes_namespace" "nats" {
  metadata {
    name = "nats"
  }
}