output "vpc_id" {
  value = module.vpc.vpc_id
}

output "vpc_name" {
  value = module.vpc.vpc_name
}

output "vpc_arn" {
  value = module.vpc.vpc_arn
}

output "vpc_cidr_block" {
  description = "The CIDR block of the VPC"
  value       = module.vpc.vpc_cidr_block
}

output "default_security_group_id" {
  description = "The ID of the security group created by default on VPC creation"
  value       = module.vpc.default_security_group_id
}

# output "main_route_table_id" {
#   description = "The ID of the route table created by default on VPC creation"
#   value       = module.vpc.main_route_table_id
# }

output "igw_id" {
  description = "igw id"
  value       = aws_internet_gateway.igw.id
}