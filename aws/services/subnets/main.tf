module "public_subnets" {
  source = "git::https://github.com/nasir19noor/terraform.git//aws/modules/subnet"

  vpc_id                  = local.vpc_id
  region                  = local.region
  subnet_count            = local.subnet_count
  cidr_blocks             = local.public_subnet_cidrs
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name}-public"
    Tier = "public"
  }
}

module "private_subnets" {
  source = "git::https://github.com/nasir19noor/terraform.git//aws/modules/subnet"

  vpc_id                  = local.vpc_id
  region                  = local.region
  subnet_count            = local.subnet_count
  cidr_blocks             = local.private_subnet_cidrs
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name}-private"
    Tier = "private"
  }
}