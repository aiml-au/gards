terraform {
  backend "gcs" {
    bucket = "aiml-dra-anomaly-data"
    prefix = ".terraform/cluster"
  }
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.78.0"
    }
  }
}