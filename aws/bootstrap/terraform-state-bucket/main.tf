module "terrafrom_state_bucket" {
  source = "git::https://github.com/nasir19noor/terraform.git//aws/modules/s3" 

  bucket  = local.bucket
}
