resource "cloudflare_record" "cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "cloudmindra.com"
  content = local.contabo_ip
  type    = "A"
  proxied = false
  ttl     = 3600
}

resource "cloudflare_record" "api_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "api.cloudmindra.com"
  content = local.contabo_ip
  type    = "A"
  proxied = false
  ttl     = 3600
}

resource "cloudflare_record" "mx1_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "route1.mx.cloudflare.net"
  type    = "MX"
  priority = 5
  ttl     = 3600
}

resource "cloudflare_record" "mx2_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "route2.mx.cloudflare.net"
  type    = "MX"
  priority = 10
  ttl     = 3600
}

resource "cloudflare_record" "spf" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "v=spf1 include:_spf.mx.cloudflare.net ~all"
  type    = "TXT"
  ttl     = 3600
}




















