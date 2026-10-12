locals {
  config           = yamldecode(file("../../../config.yaml"))
  region           = local.config.aws.global.region
  user_pool_name   = local.config.aws.cognito.user_pool_name
  domain_prefix    = local.config.aws.cognito.domain_prefix
  ses_identity     = local.config.aws.cognito.ses_identity
  ses_from_address = local.config.aws.cognito.ses_from_address
  callback_urls    = local.config.aws.cognito.callback_urls
  logout_urls      = local.config.aws.cognito.logout_urls
}
