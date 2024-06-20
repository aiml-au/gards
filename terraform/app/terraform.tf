terraform {
  backend "gcs" {
    bucket = "aiml-dra-anomaly-data"
    prefix = ".terraform/app"
  }
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.78.0"
    }
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

data "terraform_remote_state" "infrastructure" {
  backend = "gcs"

  config = {
    bucket = "aiml-dra-anomaly-data"
    prefix = ".terraform/infrastructure"
  }
}

data "terraform_remote_state" "cluster" {
  backend = "gcs"

  config = {
    bucket = "aiml-dra-anomaly-data"
    prefix = ".terraform/cluster"
  }
}