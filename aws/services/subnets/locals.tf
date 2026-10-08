locals {
  config                  = yamldecode(file("../../../config.yaml"))
  region                  = local.config.aws.global.region
  subnet_count            = local.config.aws.network.subnet_count
  name                    = local.config.aws.network.subnet_name
  cidr_block  = data.terraform_remote_state.vpc.outputs.vpc_cidr_block
  vpc_id      = data.terraform_remote_state.vpc.outputs.vpc_id
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  private_subnet_cidrs = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
  igw_id = data.terraform_remote_state.vpc.outputs.igw_id
}    

