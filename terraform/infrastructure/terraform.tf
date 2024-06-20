terraform {
  backend "gcs" {
    bucket = "aiml-dra-anomaly-data"
    prefix = ".terraform/infrastructure"
  }

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11.0"
    }
    jetstream = {
      source  = "nats-io/jetstream"
      version = "~> 0.0.35"
    }
  }
}

data "terraform_remote_state" "cluster" {
  backend = "gcs"

  config = {
    bucket = "aiml-dra-anomaly-data"
    prefix = ".terraform/cluster"
  }
}