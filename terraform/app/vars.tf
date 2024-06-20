variable "cert_manager_email" {
  description = "Email address for cert-manager ACME registration"
  default     = "aaron@aiml.team"
}

variable "db_admin_password" {
  description = "Password for the database's postgres user"
  default     = "C3uVPBMpzKtA-hBbGkrakgdt8-maDCgSyBcasX-TRCbQ7MPjSE7"
}

variable "app_hostname" {
  description = "Hostname for the web server"
  default     = "dra"
}

variable "web_image" {
  description = "The docker image for the web server"
  default     = "docker.aiml.team/products/dra/gis-predictions/web"
}

variable "predictor_image" {
  description = "The docker image for the web server"
  default     = "docker.aiml.team/products/dra/gis-predictions/predictor"
}

variable "docker_registry" {
  description = "The docker registry that hosts the app's images"
  default     = "docker.aiml.team"
}

variable "docker_registry_username" {
  description = "The username to use to authenticate with the docker registry that hosts the app's images"
  default     = "project_509_bot"
}

variable "docker_registry_password" {
  description = "The password to use to authenticate with the docker registry that hosts the app's images"
  default = "md9G9EC82TsCyZ5ovM8H"
}

variable "predictor_keda_max_replicas" {
  description = "The maximum number of replicas that KEDA will scale the predictor to"
  default     = 1
}

variable "predictor_keda_cooldown" {
  description = "The cooldown period for KEDA to scale down the predictor"
  default = 3600
}

variable "predictor_keda_stream" {
  description = "The name of the NATS stream that KEDA will monitor for messages"
  default = "RASTERS"
}

variable "predictor_keda_consumer" {
    description = "The name of the NATS consumer that KEDA will monitor for messages"
    default = "predictor_process_chunks"
}