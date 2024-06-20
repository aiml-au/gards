provider "kubernetes" {
  host                   = data.terraform_remote_state.cluster.outputs.host
  client_certificate     = base64decode(data.terraform_remote_state.cluster.outputs.client_certificate)
  client_key             = base64decode(data.terraform_remote_state.cluster.outputs.client_key)
  cluster_ca_certificate = base64decode(data.terraform_remote_state.cluster.outputs.cluster_ca_certificate)
}

resource "kubernetes_namespace" "app" {
  metadata {
    name = "app"
  }
}

resource "kubernetes_secret" "docker_registry" {
  metadata {
    name      = "docker-config"
    namespace = kubernetes_namespace.app.metadata.0.name
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = jsonencode({
      auths = {
        "${var.docker_registry}" = {
          username = var.docker_registry_username
          password = var.docker_registry_password
        }
      }
    })
  }
}

resource "kubernetes_stateful_set_v1" "web" {

  depends_on = [
    kubernetes_secret.docker_registry
  ]

  metadata {
    name      = "web"
    namespace = kubernetes_namespace.app.metadata.0.name
  }

  spec {
    service_name = "web"

    selector {
      match_labels = {
        app = "web"
      }
    }

    template {
      metadata {
        labels = {
          app = "web"
        }
      }

      spec {
        image_pull_secrets {
          name = kubernetes_secret.docker_registry.metadata.0.name
        }
        container {
          image = var.web_image
          name  = "web"
          port {
            container_port = 8000
          }
          env {
            name  = "NATS_SERVERS"
            value = data.terraform_remote_state.infrastructure.outputs.nats_servers
          }

          env {
            name  = "REMOTE_FS"
            value = "azblobv2://${data.terraform_remote_state.cluster.outputs.storage_account_name}:${data.terraform_remote_state.cluster.outputs.storage_account_key}@${data.terraform_remote_state.cluster.outputs.app_storage_container_name}"
          }

          env {
            name  = "AZURE_STORAGE_ACCOUNT"
            value = "${data.terraform_remote_state.cluster.outputs.storage_account_name}"
          }

          env {
            name  = "AZURE_STORAGE_ACCESS_KEY"
            value = "${data.terraform_remote_state.cluster.outputs.storage_account_key}"
          }

          env {
            name  = "REMOTE_CONTAINER"
            value = "${data.terraform_remote_state.cluster.outputs.app_storage_container_name}"
          }

          env {
            name  = "DB_URL"
            value = "postgres://web:s7n7Q5wPk8peGGSXfPk8pewXkA@${helm_release.db.metadata.0.name}-postgresql-hl.${helm_release.db.metadata.0.namespace}.svc.cluster.local:5432/postgres?sslmode=disable"
          }

          volume_mount {
            name       = "data-cache"
            mount_path = "/root/.cache/dra"
          }

          resources {
            limits = {
              cpu    = "4"
              memory = "40Gi"
            }
            requests = {
              cpu    = "2"
              memory = "20Gi"
            }
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "data-cache"
      }
      spec {
        access_modes = [
          "ReadWriteOnce"
        ]
        resources {
          requests = {
            storage = "100Gi"
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "web" {
  metadata {
    name      = kubernetes_stateful_set_v1.web.spec.0.service_name
    namespace = kubernetes_namespace.app.metadata.0.name
  }

  spec {
    selector = {
      app = kubernetes_stateful_set_v1.web.spec.0.template.0.metadata.0.labels.app
    }

    port {
      port        = 80
      target_port = kubernetes_stateful_set_v1.web.spec.0.template.0.spec.0.container.0.port.0.container_port
    }
  }
}

resource "kubernetes_ingress_v1" "web" {
  metadata {
    name        = "web"
    namespace   = kubernetes_namespace.app.metadata.0.name
    annotations = {
      "kubernetes.io/ingress.class"                       = "nginx"
      "cert-manager.io/cluster-issuer"                    = "letsencrypt-prod"
      "nginx.ingress.kubernetes.io/proxy-connect-timeout" = "50000"
      "nginx.ingress.kubernetes.io/proxy-read-timeout"    = "50000"
      "nginx.ingress.kubernetes.io/proxy-send-timeout"    = "50000"
      "nginx.ingress.kubernetes.io/proxy-body-size"       = "5000m"
    }
  }

  spec {
    rule {
      host = "${var.app_hostname}.${data.terraform_remote_state.cluster.outputs.dns_zone}"

      http {
        path {
          backend {
            service {
              name = kubernetes_service.web.metadata.0.name
              port {
                number = kubernetes_service.web.spec.0.port.0.port
              }
            }
          }
        }
      }
    }

    tls {
      hosts = [
        "${var.app_hostname}.${data.terraform_remote_state.cluster.outputs.dns_zone}"
      ]
      secret_name = "app-tls"
    }
  }
}

resource "kubernetes_stateful_set_v1" "predictor" {

  depends_on = [
    kubernetes_secret.docker_registry
  ]

  metadata {
    name      = "predictor"
    namespace = kubernetes_namespace.app.metadata.0.name
  }

  spec {
    service_name = "predictor"
    replicas     = "0" # KEDA will scale this up and down

    selector {
      match_labels = {
        app = "predictor"
      }
    }

    template {
      metadata {
        labels = {
          app = "predictor"
        }
      }

      spec {
        image_pull_secrets {
          name = kubernetes_secret.docker_registry.metadata.0.name
        }
        container {
          image = var.predictor_image
          name  = "predictor"

          env {
            name  = "NATS_SERVERS"
            value = data.terraform_remote_state.infrastructure.outputs.nats_servers
          }

          env {
            name  = "REMOTE_FS"
            value = "azblobv2://${data.terraform_remote_state.cluster.outputs.storage_account_name}:${data.terraform_remote_state.cluster.outputs.storage_account_key}@${data.terraform_remote_state.cluster.outputs.app_storage_container_name}"
          }

          env {
            name  = "AZURE_STORAGE_ACCOUNT"
            value = "${data.terraform_remote_state.cluster.outputs.storage_account_name}"
          }

          env {
            name  = "AZURE_STORAGE_ACCESS_KEY"
            value = "${data.terraform_remote_state.cluster.outputs.storage_account_key}"
          }

          env {
            name  = "REMOTE_CONTAINER"
            value = "${data.terraform_remote_state.cluster.outputs.app_storage_container_name}"
          }

          volume_mount {
            mount_path = "/root/.cache/dra"
            name       = "data-cache"
          }

          volume_mount {
            mount_path = "/root/.cache/huggingface"
            name       = "huggingface-cache"
          }

          volume_mount {
            mount_path = "/root/.cache/torch"
            name       = "torch-cache"
          }

          resources {
            limits = {
              cpu              = "16"
              memory           = "160Gi"
              "nvidia.com/gpu" = "1"
            }
            requests = {
              cpu              = "8"
              memory           = "80Gi"
              "nvidia.com/gpu" = "1"
            }
          }
        }
        toleration {
          key      = "gpu"
          operator = "Equal"
          value    = "true"
          effect   = "NoSchedule"
        }
      }
    }
    volume_claim_template {
      metadata {
        name = "data-cache"
      }
      spec {
        access_modes = [
          "ReadWriteOnce"
        ]
        resources {
          requests = {
            storage = "100Gi"
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "huggingface-cache"
      }
      spec {
        access_modes = [
          "ReadWriteOnce"
        ]
        resources {
          requests = {
            storage = "100Gi"
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "torch-cache"
      }
      spec {
        access_modes = [
          "ReadWriteOnce"
        ]
        resources {
          requests = {
            storage = "100Gi"
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "predictor" {
  metadata {
    name      = kubernetes_stateful_set_v1.predictor.spec.0.service_name
    namespace = kubernetes_namespace.app.metadata.0.name
  }

  spec {
    selector = {
      app = kubernetes_stateful_set_v1.predictor.spec.0.template.0.metadata.0.labels.app
    }

    cluster_ip = "None"
  }
}