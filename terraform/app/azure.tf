provider "azurerm" {
  features {}
}

resource "azurerm_dns_a_record" "app" {
  name                = var.app_hostname
  zone_name           = data.terraform_remote_state.cluster.outputs.dns_zone
  resource_group_name = data.terraform_remote_state.cluster.outputs.resource_group_name
  ttl                 = 300
  records             = [data.terraform_remote_state.infrastructure.outputs.nginx_external_ip]
}