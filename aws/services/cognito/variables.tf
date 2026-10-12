# Supplied by the AWS Apply workflow from GitHub secrets (TF_VAR_google_client_id / TF_VAR_google_client_secret)
variable "google_client_id" {
  description = "OAuth client ID from Google Cloud Console"
  type        = string
}

variable "google_client_secret" {
  description = "OAuth client secret from Google Cloud Console"
  type        = string
  sensitive   = true
}
