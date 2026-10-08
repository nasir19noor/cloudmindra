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
  priority = 63
  ttl     = 3600
}

resource "cloudflare_record" "mx2_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "route2.mx.cloudflare.net"
  type    = "MX"
  priority = 49
  ttl     = 3600
}

resource "cloudflare_record" "mx3_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "route3.mx.cloudflare.net"
  type    = "MX"
  priority = 41
  ttl     = 3600
}


resource "cloudflare_record" "spf1_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "cf2024-1._domainkey.cloudmindra.com"
  content = "v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAiweykoi+o48IOGuP7GR3X0MOExCUDY/BCRHoWBnh3rChl7WhdyCxW3jgq1daEjPPqoi7sJvdg5hEQVsgVRQP4DcnQDVjGMbASQtrY4WmB1VebF+RPJB2ECPsEDTpeiI5ZyUAwJaVX7r6bznU67g7LvFq35yIo4sdlmtZGV+i0H4cpYH9+3JJ78km4KXwaf9xUJCWF6nxeD+qG6Fyruw1Qlbds2r85U9dkNDVAS3gioCvELryh1TxKGiVTkg4wqHTyHfWsp7KD3WQHYJn0RyfJJu6YEmL77zonn7p2SRMvTMP3ZEXibnC9gz3nnhR6wcYL8Q7zXypKTMD58bTixDSJwIDAQAB"
  type    = "TXT"
  ttl     = 3600
}

resource "cloudflare_record" "spf2_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "v=spf1 include:_spf.mx.cloudflare.net ~all"
  type    = "TXT"
  ttl     = 3600
}




















