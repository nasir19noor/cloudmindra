terraform {
  backend "s3" {
    key          = "cognito/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}
