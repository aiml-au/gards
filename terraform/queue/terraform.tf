terraform {
  required_providers {
    jetstream = {
        source = "nats-io/jetstream"
        version = "0.0.35"
    }
  }
}

data "terraform_remote_state" "app" {
  backend = "local"

  config = {
    path = "../app/terraform.tfstate"
  }
}