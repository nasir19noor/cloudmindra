terraform {
  backend "s3" {
    bucket = "lab.nasir.id"
    region = "ap-southeast-1"
    key = "cloudflare/terraform.tfstate"
  }
}