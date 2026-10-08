terraform {
  backend "s3" {
    key = "vpc/terraform.tfstate"
    use_lockfile = true
    encrypt = true
  }
}