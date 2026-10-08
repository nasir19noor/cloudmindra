locals {
  config                  = yamldecode(file("../../../config.yaml"))
  region                  = local.config.aws.global.region
  bucket                  = local.config.aws.global.state_bucket
}    