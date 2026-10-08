# --- Public: route to IGW ---
resource "aws_route_table" "public" {
  vpc_id = local.vpc_id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = local.igw_id
  }

  tags = {
    Name = "${local.name}-public-rt"
    Tier = "public"
  }
}

resource "aws_route_table_association" "public" {
  count          = local.subnet_count
  subnet_id      = module.public_subnets.subnet_ids[count.index]
  route_table_id = aws_route_table.public.id
}