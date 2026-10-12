resource "aws_cognito_user_pool" "cloudmindra" {
  name = local.user_pool_name

  # Customers sign in with their email address
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  username_configuration {
    case_sensitive = false
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 5
      max_length = 254
    }
  }

  password_policy {
    minimum_length                   = 10
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your CloudMindra verification code"
    email_message        = "Your CloudMindra verification code is {####}"
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Send through the existing SES domain instead of Cognito's 50 emails/day default
  email_configuration {
    email_sending_account = "DEVELOPER"
    source_arn            = local.ses_identity_arn
    from_email_address    = "CloudMindra <${local.ses_from_address}>"
  }

  # Users may enrol an authenticator app; admins should be required to in the app
  mfa_configuration = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  deletion_protection = "ACTIVE"

  lifecycle {
    # Cognito does not allow schema attributes to change after creation
    ignore_changes = [schema]
  }
}

# Hosted (managed) login at https://<domain_prefix>.auth.<region>.amazoncognito.com
resource "aws_cognito_user_pool_domain" "cloudmindra" {
  domain                = local.domain_prefix
  user_pool_id          = aws_cognito_user_pool.cloudmindra.id
  managed_login_version = 2
}

# Confidential client: the FastAPI backend exchanges the auth code for tokens,
# so it can hold the client secret and set an httpOnly session cookie
resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.user_pool_name}-web"
  user_pool_id = aws_cognito_user_pool.cloudmindra.id

  generate_secret = true

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = local.callback_urls
  logout_urls   = local.logout_urls

  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# Managed login v2 needs a branding style per client or it shows an error page
resource "aws_cognito_managed_login_branding" "web" {
  user_pool_id = aws_cognito_user_pool.cloudmindra.id
  client_id    = aws_cognito_user_pool_client.web.id

  use_cognito_provided_values = true
}

# Groups land in the "cognito:groups" token claim for backend authorization
resource "aws_cognito_user_group" "admin" {
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.cloudmindra.id
  description  = "CloudMindra staff with access to the admin dashboard"
  precedence   = 1
}

resource "aws_cognito_user_group" "customer" {
  name         = "customer"
  user_pool_id = aws_cognito_user_pool.cloudmindra.id
  description  = "Customers with access to the client portal"
  precedence   = 10
}
