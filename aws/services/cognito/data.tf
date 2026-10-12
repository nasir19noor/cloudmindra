data "aws_caller_identity" "current" {}

# cloudmindra.com is already verified in SES (DKIM records live in cloudflare/dns.tf)
locals {
  ses_identity_arn = "arn:aws:ses:${local.region}:${data.aws_caller_identity.current.account_id}:identity/${local.ses_identity}"
}
