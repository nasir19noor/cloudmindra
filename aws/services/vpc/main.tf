module "vpc" {
  source = "git::https://github.com/nasir19noor/terraform.git//aws/modules/vpc" 

  cidr                                     = local.cidr_block
  instance_tenancy                         = local.instance_tenancy
  enable_dns_hostnames                     = local.enable_dns_hostnames 
  enable_dns_support                       = local.enable_dns_support 
  name                                     = local.name
}

resource "aws_internet_gateway" "igw" {
 vpc_id = module.vpc.vpc_id
 
 tags = {
   Name = local.name
 }
}






