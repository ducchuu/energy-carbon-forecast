terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

data "archive_file" "ingestor_source_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../ingestion"
  output_path = "${path.module}/ingestor-source.zip"
}

resource "google_storage_bucket" "function_source" {
  name                        = "${var.project_id}-function-source"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
}

resource "google_storage_bucket_object" "ingestor_source_zip" {
  name   = "ingestor-source-${data.archive_file.ingestor_source_zip.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.ingestor_source_zip.output_path
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_service_account" "ingest_sa" {
  account_id   = "energy-ingest-sa"
  display_name = "ENTSO-E and TenneT Ingestion Cloud Function SA"
}

resource "google_service_account" "scheduler_sa" {
  account_id   = "energy-scheduler-sa"
  display_name = "Cloud Scheduler OIDC Invoker SA"
}

resource "google_service_account" "ui_sa" {
  account_id   = "energy-streamlit-ui-sa"
  display_name = "Streamlit Dashboard Service SA"
}

resource "google_secret_manager_secret" "entsoe_api_key" {
  secret_id = "entsoe-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "ingest_secret_access" {
  secret_id = google_secret_manager_secret.entsoe_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ingest_sa.email}"
}

resource "google_secret_manager_secret" "tennet_api_key" {
  secret_id = var.tennet_api_key_secret_name
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "ingest_tennet_secret_access" {
  secret_id = google_secret_manager_secret.tennet_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ingest_sa.email}"
}

resource "google_bigquery_dataset" "bronze" {
  dataset_id = "energy_bronze_${var.environment}"
  location   = "EU"
}

resource "google_bigquery_dataset" "silver" {
  dataset_id = "energy_silver_${var.environment}"
  location   = "EU"
}

resource "google_bigquery_dataset" "gold" {
  dataset_id = "energy_gold_${var.environment}"
  location   = "EU"
}

resource "google_project_iam_member" "ingest_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.ingest_sa.email}"
}

resource "google_bigquery_dataset_iam_member" "ingest_bronze_editor" {
  dataset_id = google_bigquery_dataset.bronze.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ingest_sa.email}"
}

resource "google_project_iam_member" "ui_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.ui_sa.email}"
}

resource "google_bigquery_dataset_iam_member" "ui_gold_viewer" {
  dataset_id = google_bigquery_dataset.gold.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.ui_sa.email}"
}

resource "google_bigquery_dataset_iam_member" "ui_gold_editor" {
  dataset_id = google_bigquery_dataset.gold.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ui_sa.email}"
}

resource "google_bigquery_dataset_iam_member" "ui_silver_viewer" {
  dataset_id = google_bigquery_dataset.silver.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.ui_sa.email}"
}

resource "google_cloudfunctions2_function" "entsoe_ingestor" {
  name     = "entsoe-ingestor-fn"
  location = var.region

  build_config {
    runtime     = "python311"
    entry_point = "ingest_entsoe_data"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.ingestor_source_zip.name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    min_instance_count    = 0
    available_memory      = "512M"
    timeout_seconds       = 120
    service_account_email = google_service_account.ingest_sa.email

    environment_variables = {
      GCP_PROJECT_ID = var.project_id
      BQ_DATASET     = google_bigquery_dataset.bronze.dataset_id
      BIDDING_ZONE   = "10YNL----------L"
    }

    secret_environment_variables {
      key        = "ENTSOE_API_KEY"
      project_id = var.project_id
      secret     = google_secret_manager_secret.entsoe_api_key.secret_id
      version    = "latest"
    }

    secret_environment_variables {
      key        = "TENNET_API_KEY"
      project_id = var.project_id
      secret     = google_secret_manager_secret.tennet_api_key.secret_id
      version    = "latest"
    }
  }
}

resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  location = google_cloudfunctions2_function.entsoe_ingestor.location
  service  = google_cloudfunctions2_function.entsoe_ingestor.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

resource "google_cloud_scheduler_job" "hourly_generation_trigger" {
  name             = "trigger-entsoe-hourly-generation"
  schedule         = "5 * * * *"
  time_zone        = "Europe/Amsterdam"
  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
    body = base64encode(jsonencode({
      job_type       = "actual_generation"
      lookback_hours = 24
    }))
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
    }
  }
}

resource "google_cloud_scheduler_job" "daily_day_ahead_trigger" {
  name             = "trigger-entsoe-day-ahead-forecasts"
  schedule         = "0 14 * * *"
  time_zone        = "Europe/Amsterdam"
  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
    body = base64encode(jsonencode({
      job_type      = "day_ahead_prices_and_forecasts"
      horizon_hours = 36
    }))
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
    }
  }
}

resource "google_cloud_scheduler_job" "tennet_realtime_trigger" {
  name             = "trigger-tennet-realtime-telemetry"
  schedule         = "15 * * * *"
  time_zone        = "Europe/Amsterdam"
  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
    body = base64encode(jsonencode({
      job_type         = "tennet_realtime"
      lookback_minutes = 60
      lookback_hours   = 24
    }))
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
    }
  }
}

resource "google_artifact_registry_repository" "energy_docker_repo" {
  location      = var.region
  repository_id = "energy-pipeline-containers"
  format        = "DOCKER"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-untagged-and-old-images"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "86400s"
    }
  }

  cleanup_policies {
    id     = "keep-only-latest-revision"
    action = "KEEP"
    most_recent_versions {
      keep_count = 1
    }
  }
}

resource "google_cloud_run_v2_service" "dashboard" {
  name     = "energy-optimizer-dashboard"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.ui_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.dashboard_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "BQ_DATASET_GOLD"
        value = google_bigquery_dataset.gold.dataset_id
      }

      env {
        name  = "BQ_DATASET_SILVER"
        value = google_bigquery_dataset.silver.dataset_id
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

locals {
  effective_dashboard_invokers = toset(
    concat(
      var.dashboard_authorized_members,
      var.dashboard_allow_unauthenticated ? ["allUsers"] : []
    )
  )
}

resource "google_cloud_run_v2_service_iam_member" "dashboard_authorized_invokers" {
  for_each = local.effective_dashboard_invokers
  location = google_cloud_run_v2_service.dashboard.location
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = each.value
}

#resource "google_billing_budget" "budget" {
#  billing_account = var.billing_account
#  display_name    = "Energy Pipeline Budget - ${var.environment}"
#
#  amount {
#    specified_amount {
#      currency_code = "USD"
#      units         = var.monthly_budget_usd
#    }
#  }
#  threshold_rules {
#    threshold_percent = 0.5
#  }
#  threshold_rules {
#    threshold_percent = 0.9
#  }
#  threshold_rules {
#    threshold_percent = 1.0
#  }

#  all_updates_rule {
#    monitoring_notification_channels = [
#      google_monitoring_notification_channel.email_alert.id,
#    ]
#  }
#}

resource "google_monitoring_notification_channel" "email_alert" {
  display_name = "Email Alerts"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "cf_error_alert" {
  display_name = "Cloud Function Error Alert - ${var.environment}"
  combiner     = "OR"
  conditions {
    display_name = "Cloud Function Execution Errors"
    condition_threshold {
      filter          = "resource.type = \"cloud_function\" AND metric.type = \"cloudfunctions.googleapis.com/function/execution_count\" AND metric.labels.status != \"ok\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  notification_channels = [
    google_monitoring_notification_channel.email_alert.id,
  ]
}
