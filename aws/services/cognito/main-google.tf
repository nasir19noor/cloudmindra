# "Sign in with Google". In Google Cloud Console the OAuth client needs:
#   Authorized JavaScript origin: https://<domain_prefix>.auth.<region>.amazoncognito.com
#   Authorized redirect URI:      https://<domain_prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse
resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.cloudmindra.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "openid email profile"
  }

  attribute_mapping = {
    email          = "email"
    email_verified = "email_verified"
    name           = "name"
    username       = "sub"
  }

  lifecycle {
    # Cognito fills these in itself; ignoring them avoids a diff on every plan
    ignore_changes = [
      provider_details["attributes_url"],
      provider_details["attributes_url_add_attributes"],
      provider_details["authorize_url"],
      provider_details["oidc_issuer"],
      provider_details["token_request_method"],
      provider_details["token_url"],
    ]
  }
}
