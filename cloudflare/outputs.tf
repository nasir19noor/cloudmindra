output "zone_id" {
  value = data.cloudflare_zones.cloudmindra.zones[0].id
}