provider "helm" {
  kubernetes {
    host                   = data.terraform_remote_state.cluster.outputs.host
    client_certificate     = base64decode(data.terraform_remote_state.cluster.outputs.client_certificate)
    client_key             = base64decode(data.terraform_remote_state.cluster.outputs.client_key)
    cluster_ca_certificate = base64decode(data.terraform_remote_state.cluster.outputs.cluster_ca_certificate)
  }
}

resource "helm_release" "predictor_scaled_object" {
  name       = "predictor-scaled-object"
  namespace  = kubernetes_stateful_set_v1.predictor.metadata.0.namespace
  chart      = "raw"
  repository = "https://helm-charts.wikimedia.org/stable/"
  version    = "0.3.0"

  values = [
    <<-EOF
    resources:
    - apiVersion: keda.sh/v1alpha1
      kind: ScaledObject
      metadata:
        namespace: ${kubernetes_stateful_set_v1.predictor.metadata.0.namespace}
        name: predictor
      spec:
        minReplicaCount: 0
        maxReplicaCount: ${var.predictor_keda_max_replicas}
        scaleTargetRef:
          name: ${kubernetes_stateful_set_v1.predictor.metadata.0.name}
          kind: StatefulSet
        cooldownPeriod: ${var.predictor_keda_cooldown}
        triggers:
          - type: nats-jetstream
            metadata:
              account: "$G"
              natsServerMonitoringEndpoint: ${data.terraform_remote_state.infrastructure.outputs.nats_monitoring}
              stream: ${var.predictor_keda_stream}
              consumer: ${var.predictor_keda_consumer} # Will fail silently if this name is wrong
              lagThreshold: "10"
    EOF
  ]
}

resource "kubernetes_config_map" "db_init" {
  metadata {
    name      = "db-init"
    namespace = kubernetes_namespace.app.metadata.0.name
  }

  data = {
    "schema.sql"      = file("${path.module}/../../db/config/schema.sql")
  }
}

resource "helm_release" "db" {
  chart      = "postgresql"
  version    = "13.2.2"
  name       = "db"
  namespace  = kubernetes_namespace.app.metadata.0.name
  repository = "https://charts.bitnami.com/bitnami"

  set {
    name = "auth.postgresPassword"
    value = var.db_admin_password
  }

  set {
    name  = "primary.initdb.scriptsConfigMap"
    value = kubernetes_config_map.db_init.metadata.0.name
  }
}