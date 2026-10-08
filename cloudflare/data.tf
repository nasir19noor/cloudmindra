data "cloudflare_zones" "cloudmindra" {
  filter {
    name = local.zone_name
  }
}