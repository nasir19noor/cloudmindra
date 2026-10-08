terraform {
  backend "s3" {
    bucket = "cloudmindra.com"
    region = "ap-southeast-1"
    key = "cloudflare/terraform.tfstate"
  }
}