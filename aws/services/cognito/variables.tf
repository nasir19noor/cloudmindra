# Supplied by the AWS Apply workflow from GitHub secrets (TF_VAR_google_client_id / TF_VAR_google_client_secret)
variable "google_client_id" {
  description = "OAuth client ID from Google Cloud Console"
  type        = string

  validation {
    condition     = length(trimspace(var.google_client_id)) > 0
    error_message = "google_client_id is empty. Add the GOOGLE_CLIENT_ID repository secret in GitHub."
  }
}

variable "google_client_secret" {
  description = "OAuth client secret from Google Cloud Console"
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.google_client_secret)) > 0
    error_message = "google_client_secret is empty. Add the GOOGLE_CLIENT_SECRET repository secret in GitHub."
  }
}
