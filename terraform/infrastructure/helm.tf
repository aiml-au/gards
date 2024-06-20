provider "helm" {
  kubernetes {
    host                   = data.terraform_remote_state.cluster.outputs.host
    client_certificate     = base64decode(data.terraform_remote_state.cluster.outputs.client_certificate)
    client_key             = base64decode(data.terraform_remote_state.cluster.outputs.client_key)
    cluster_ca_certificate = base64decode(data.terraform_remote_state.cluster.outputs.cluster_ca_certificate)
  }
}

resource "helm_release" "nginx" {
  name       = "nginx"
  namespace  = kubernetes_namespace.nginx.metadata.0.name
  chart      = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  version    = "4.8.2"

  set {
    name  = "controller.service.annotations.\"service\\.beta\\.kubernetes\\.io/azure-load-balancer-health-probe-request-path\""
    value = "/healthz"
  }
}

resource "time_sleep" "wait_for_nginx" {
  depends_on = [
    helm_release.nginx
  ]
  create_duration = "60s"
}

resource "helm_release" "cert_manager" {
  name       = "cert-manager"
  namespace  = kubernetes_namespace.cert_manager.metadata.0.name
  chart      = "cert-manager"
  repository = "https://charts.jetstack.io"
  version    = "1.13.1"

  set {
    name  = "installCRDs"
    value = "true"
  }
}

resource "helm_release" "cert_issuer" {
  depends_on = [
    helm_release.cert_manager,
    helm_release.nginx
  ]
  name       = "cert-issuer"
  namespace  = kubernetes_namespace.cert_manager.metadata.0.name
  chart      = "raw"
  repository = "https://helm-charts.wikimedia.org/stable/"
  version    = "0.3.0"

  values = [
    <<-EOF
    resources:
    - apiVersion: cert-manager.io/v1
      kind: ClusterIssuer
      metadata:
        name: letsencrypt-prod
      spec:
        acme:
          email: ${var.cert_manager_email}
          server: https://acme-v02.api.letsencrypt.org/directory
          privateKeySecretRef:
            name: lets-encrypt-prod-account-key
          solvers:
          - http01:
              ingress:
                class: nginx
      EOF
  ]
}

resource "helm_release" "keda" {
  name       = "keda"
  namespace  = kubernetes_namespace.keda.metadata.0.name
  chart      = "keda"
  repository = "https://kedacore.github.io/charts"
  version    = "2.12.0"
}

resource "time_sleep" "wait_for_keda" {
  depends_on = [
    helm_release.keda
  ]
  create_duration = "60s"
}

resource "helm_release" "nats" {
  name  = "queue"
  namespace = kubernetes_namespace.nats.metadata.0.name
  chart = "nats"
  repository = "https://nats-io.github.io/k8s/helm/charts/"
  version = "1.1.2"

  set {
    name = "config.jetstream.enabled"
    value = "true"
  }
}

resource "time_sleep" "wait_for_nats" {
  depends_on = [
    helm_release.nats
  ]
  create_duration = "60s"
}

output "nats_servers" {
  value = "nats://${helm_release.nats.name}-nats-headless.${helm_release.nats.namespace}.svc.cluster.local:4222"
}

output "nats_monitoring" {
  value = "${helm_release.nats.name}-nats-headless.${helm_release.nats.namespace}.svc.cluster.local:8222"
}