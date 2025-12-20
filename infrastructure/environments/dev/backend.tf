terraform {
  backend "s3" {
    bucket         = "cse363-terraform-state"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "cse363-terraform-locks"
  }
}

