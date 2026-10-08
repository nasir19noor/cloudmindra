data "terraform_remote_state" "vpc" {
  backend = "s3"
  config = {
    bucket = "lab.nasir.id"
    key    = "vpc/terraform.tfstate"
    region = "ap-southeast-1"
  }
}
