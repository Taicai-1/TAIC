# Terraform configuration for GCP deployment
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
  }
}

# Configure the Google Cloud Provider
provider "google" {
  project = var.project_id
  region  = var.region
}

# Variables
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "europe-west1"
}

variable "db_password" {
  description = "Database user password"
  type        = string
  sensitive   = true
}

# Cloud SQL instance
resource "google_sql_database_instance" "main" {
  name             = "rag-ceo-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = "db-f1-micro"
    ip_configuration {
      ipv4_enabled = true
      authorized_networks {
        value = "0.0.0.0/0"
      }
    }
  }
}

# Database
resource "google_sql_database" "database" {
  name     = "ragdb"
  instance = google_sql_database_instance.main.name
}

# Database user
resource "google_sql_user" "user" {
  name     = "raguser"
  instance = google_sql_database_instance.main.name
  password = var.db_password
}

# Cloud Run service for backend
resource "google_cloud_run_service" "backend" {
  name     = "rag-backend"
  location = var.region

  template {
    spec {
      containers {
        image = "gcr.io/${var.project_id}/rag-backend"
        ports {
          container_port = 8080
        }
        env {
          name  = "DATABASE_URL"
          value = "postgresql://${google_sql_user.user.name}:${google_sql_user.user.password}@${google_sql_database_instance.main.connection_name}/${google_sql_database.database.name}"
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

# Cloud Run service for frontend
resource "google_cloud_run_service" "frontend" {
  name     = "rag-frontend"
  location = var.region

  template {
    spec {
      containers {
        image = "gcr.io/${var.project_id}/rag-frontend"
        ports {
          container_port = 3000
        }
        env {
          name  = "NEXT_PUBLIC_API_URL"
          value = google_cloud_run_service.backend.status[0].url
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

# IAM policy for public access
resource "google_cloud_run_service_iam_policy" "backend_policy" {
  location = google_cloud_run_service.backend.location
  service  = google_cloud_run_service.backend.name

  policy_data = data.google_iam_policy.noauth.policy_data
}

resource "google_cloud_run_service_iam_policy" "frontend_policy" {
  location = google_cloud_run_service.frontend.location
  service  = google_cloud_run_service.frontend.name

  policy_data = data.google_iam_policy.noauth.policy_data
}

data "google_iam_policy" "noauth" {
  binding {
    role = "roles/run.invoker"
    members = [
      "allUsers",
    ]
  }
}

# Outputs
output "backend_url" {
  value = google_cloud_run_service.backend.status[0].url
}

output "frontend_url" {
  value = google_cloud_run_service.frontend.status[0].url
}
