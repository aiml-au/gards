provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "dra" {
  name     = "dra"
  location = "Australia East"
}

output "resource_group_name" {
  value = azurerm_resource_group.dra.name
}

resource "azurerm_kubernetes_cluster" "dra" {
  name                = "dra"
  location            = azurerm_resource_group.dra.location
  resource_group_name = azurerm_resource_group.dra.name
  dns_prefix          = "dra"

  default_node_pool {
    name       = "default"
    node_count = 1
    # The default nodes are so large because we are doing raster work with them
    # TODO: Refactor to use a Hi Mem node pool for raster work and reduce the default node size
    vm_size    = "Standard_B8ms"
  }

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  kubernetes_cluster_id = azurerm_kubernetes_cluster.dra.id
  name                  = "gpu"
  vm_size               = "Standard_NC24ads_A100_v4"
  node_count            = 0
  min_count             = 0
  max_count             = 1
  node_taints           = [
    "nvidia.com/gpu=:NoSchedule"
  ]
  enable_auto_scaling = true
}

output "host" {
  value     = azurerm_kubernetes_cluster.dra.kube_config.0.host
  sensitive = true
}

output "client_certificate" {
  value     = azurerm_kubernetes_cluster.dra.kube_config.0.client_certificate
  sensitive = true
}

output "client_key" {
  value     = azurerm_kubernetes_cluster.dra.kube_config.0.client_key
  sensitive = true
}

output "cluster_ca_certificate" {
  value     = azurerm_kubernetes_cluster.dra.kube_config.0.cluster_ca_certificate
  sensitive = true
}

output "kube_config" {
  value     = azurerm_kubernetes_cluster.dra.kube_config_raw
  sensitive = true
}

resource "azurerm_dns_zone" "dra" {
  name                = var.dns_zone
  resource_group_name = azurerm_resource_group.dra.name
}

output "dns_zone" {
  value = var.dns_zone
}

output "dns_nameservers" {
  value = azurerm_dns_zone.dra.name_servers
}

resource "azurerm_storage_account" "dra" {
  name                     = "dra"
  resource_group_name      = azurerm_resource_group.dra.name
  location                 = azurerm_resource_group.dra.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true
}

output "storage_account_name" {
  value = azurerm_storage_account.dra.name
}

output "storage_account_key" {
  value     = azurerm_storage_account.dra.primary_access_key
  sensitive = true
}

resource "azurerm_storage_container" "app_data" {
  name                  = "app-data"
  storage_account_name  = azurerm_storage_account.dra.name
  container_access_type = "private"
}

output "app_storage_container_name" {
  value = azurerm_storage_container.app_data.name
}