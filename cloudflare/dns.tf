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

# MX and DKIM records below are created and locked by Cloudflare Email Routing
# (deleting them returns error 1046). Stop tracking them in Terraform without
# destroying them; Email Routing owns them from here on.
removed {
  from = cloudflare_record.mx1_cloudmindra
  lifecycle {
    destroy = false
  }
}

removed {
  from = cloudflare_record.mx2_cloudmindra
  lifecycle {
    destroy = false
  }
}

removed {
  from = cloudflare_record.mx3_cloudmindra
  lifecycle {
    destroy = false
  }
}

removed {
  from = cloudflare_record.spf1_cloudmindra
  lifecycle {
    destroy = false
  }
}

resource "cloudflare_record" "spf2_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = local.root
  content = "v=spf1 include:_spf.mx.cloudflare.net ~all"
  type    = "TXT"
  ttl     = 3600
}

resource "cloudflare_record" "ses1_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "r6fxnmigbkkqfjleaqli3i3jbl46digj._domainkey.cloudmindra.com"
  content = "r6fxnmigbkkqfjleaqli3i3jbl46digj.dkim.amazonses.com"
  type    = "CNAME"
  proxied = false
  ttl     = 3600
}

resource "cloudflare_record" "ses2_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "egn2rumb3asbtwnbr3qyjxu7xjhg5o6m._domainkey.cloudmindra.com"
  content = "egn2rumb3asbtwnbr3qyjxu7xjhg5o6m.dkim.amazonses.com"
  type    = "CNAME"
  proxied = false
  ttl     = 3600
}

resource "cloudflare_record" "ses3_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "y7qmsarhbvazsiuo7inf2cladsy36mgj._domainkey.cloudmindra.com"
  content = "y7qmsarhbvazsiuo7inf2cladsy36mgj.dkim.amazonses.com"
  type    = "CNAME"
  proxied = false
  ttl     = 3600
}

resource "cloudflare_record" "ses_dmarc_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "_dmarc.cloudmindra.com"
  content = "v=DMARC1; p=none;"
  type    = "TXT"
  proxied = false
  ttl     = 3600
}
