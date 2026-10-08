output "bucket_name" {
  value = module.terrafrom_state_bucket.s3_bucket_id
}

output "bucket_arn" {
  value = module.terrafrom_state_bucket.s3_bucket_arn
}