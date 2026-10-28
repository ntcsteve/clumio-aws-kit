terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    clumio = {
      source  = "clumio-code/clumio"
      version = ">= 0.24.2, < 0.25.0"
    }
  }
}
