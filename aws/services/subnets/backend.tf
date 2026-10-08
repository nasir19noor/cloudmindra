terraform {
  backend "s3" {
    key = "subnets/terraform.tfstate"
    use_lockfile = true
    encrypt = true    
  }
}