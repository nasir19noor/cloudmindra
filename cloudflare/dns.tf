resource "cloudflare_zone_settings_override" "cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id

  settings {
    always_use_https = "on"
  }
}

resource "cloudflare_record" "cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "cloudmindra.com"
  content = "207.180.248.214"
  type    = "A"
  proxied = true
  ttl     = 1
}



























