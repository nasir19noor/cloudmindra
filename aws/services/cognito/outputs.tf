output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.cloudmindra.id
}

output "cognito_user_pool_arn" {
  value = aws_cognito_user_pool.cloudmindra.arn
}

output "cognito_user_pool_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

# Read with: terraform output -raw cognito_user_pool_client_secret
output "cognito_user_pool_client_secret" {
  value     = aws_cognito_user_pool_client.web.client_secret
  sensitive = true
}

# The backend validates JWTs against ${issuer}/.well-known/jwks.json
output "cognito_issuer_url" {
  value = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.cloudmindra.id}"
}

output "cognito_domain_url" {
  value = "https://${aws_cognito_user_pool_domain.cloudmindra.domain}.auth.${local.region}.amazoncognito.com"
}
