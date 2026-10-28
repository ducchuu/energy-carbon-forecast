variable "project_id" {
  description = "The GCP Project ID"
  type        = string
}

variable "region" {
  description = "The GCP Region"
  type        = string
  default     = "europe-west4"
}

variable "environment" {
  description = "Deployment environment (dev, prod)"
  type        = string
  default     = "dev"
}

variable "billing_account" {
  description = "The GCP Billing Account ID"
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly FinOps budget alert threshold in USD"
  type        = string
  default     = "5"
}

variable "alert_email" {
  description = "The email address for FinOps budget and execution error alerts"
  type        = string
  default     = "alerts@example.com"
}

variable "tennet_api_key_secret_name" {
  description = "The Secret ID in GCP Secret Manager for TenneT API key"
  type        = string
  default     = "tennet-api-key"
}

variable "dashboard_image" {
  description = "The container image URI for the Streamlit commercial dashboard"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "dashboard_allow_unauthenticated" {
  description = "Allow public browser access to the Cloud Run dashboard without IAP"
  type        = bool
  default     = true
}

variable "dashboard_authorized_members" {
  description = "List of IAM members authorized to access the Cloud Run dashboard"
  type        = list(string)
  default     = []
}
