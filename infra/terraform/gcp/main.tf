terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-southeast1"
}
variable "name" {
  type    = string
  default = "telesales"
}
variable "admin_cidr" {
  type        = string
  description = "Trusted administrator IP/CIDR for the Kubernetes control plane."
}
resource "google_project_service" "apis" {
  for_each           = toset(["compute.googleapis.com", "container.googleapis.com", "sqladmin.googleapis.com", "redis.googleapis.com", "artifactregistry.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com"])
  service            = each.key
  disable_on_destroy = false
}
resource "google_compute_network" "main" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}
resource "google_compute_subnetwork" "main" {
  name                     = var.name
  ip_cidr_range            = "10.0.0.0/20"
  network                  = google_compute_network.main.id
  private_ip_google_access = true
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.4.0.0/14"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.1.0.0/20"
  }
}
resource "google_container_cluster" "main" {
  name                = var.name
  location            = var.region
  enable_autopilot    = true
  network             = google_compute_network.main.id
  subnetwork          = google_compute_subnetwork.main.id
  deletion_protection = true
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }
  master_authorized_networks_config {
    cidr_blocks {
      cidr_block   = var.admin_cidr
      display_name = "administrator"
    }
  }
  release_channel { channel = "REGULAR" }
}
resource "google_compute_global_address" "services" {
  name          = "${var.name}-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}
resource "google_service_networking_connection" "services" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.services.name]
}
resource "google_sql_database_instance" "main" {
  name                = "${var.name}-postgres"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = true
  depends_on          = [google_service_networking_connection.services]
  settings {
    tier              = "db-custom-2-7680"
    availability_type = "REGIONAL"
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
  }
}
resource "google_sql_database" "main" {
  name     = "app_db"
  instance = google_sql_database_instance.main.name
}
resource "google_redis_instance" "main" {
  name                    = "${var.name}-redis"
  tier                    = "STANDARD_HA"
  memory_size_gb          = 1
  region                  = var.region
  authorized_network      = google_compute_network.main.id
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  depends_on              = [google_project_service.apis]
}
resource "google_artifact_registry_repository" "main" {
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}
resource "google_secret_manager_secret" "runtime" {
  secret_id = "${var.name}-runtime"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
output "cluster_name" { value = google_container_cluster.main.name }
output "sql_connection_name" { value = google_sql_database_instance.main.connection_name }
output "registry" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${var.name}" }
output "redis_host" { value = google_redis_instance.main.host }

resource "google_compute_router" "egress" {
  name    = "${var.name}-egress"
  region  = var.region
  network = google_compute_network.main.id
}
resource "google_compute_router_nat" "egress" {
  name                               = "${var.name}-egress"
  router                             = google_compute_router.egress.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
