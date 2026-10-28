output "ingestion_function_url" {
  description = "The URL of the ingestion Cloud Run Function"
  value       = google_cloudfunctions2_function.entsoe_ingestor.service_config[0].uri
}

output "dashboard_url" {
  description = "The URL of the commercial energy dispatch dashboard"
  value       = google_cloud_run_v2_service.dashboard.uri
}
