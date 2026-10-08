resource "cloudflare_record" "cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "cloudmindra.com"
  content = local.contabo_ip
  type    = "A"
  proxied = true
  ttl     = 1
}




















