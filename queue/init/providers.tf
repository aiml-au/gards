variable "NATS_SERVERS" {
    type = string
}

terraform {
    required_providers {
        jetstream = {
            source = "nats-io/jetstream"
            version = "~> 0.0.35"
        }
    }
}

provider "jetstream" {
    servers = var.NATS_SERVERS
}