locals {
  config                  = yamldecode(file("../../../config.yaml"))
  cidr_block              = local.config.aws.network.cidr_block
  region                  = local.config.aws.global.region
  name                    = local.config.aws.network.vpc_name
  description             = local.config.aws.network.description
  instance_tenancy        = local.config.aws.network.instance_tenancy
  enable_dns_hostnames    = local.config.aws.network.enable_dns_hostnames
  enable_dns_support      = local.config.aws.network.enable_dns_support
}    

