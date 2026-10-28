# preview/preview.sh reads this file too, so the preview and the apply use the same versions.
# Keep any backend block in backend.tf, never here: the preview refuses to run with one.
terraform {
  required_version = ">= 1.10"
  required_providers {
    clumio = {
      source  = "clumio-code/clumio"
      version = "0.24.2" # Exact, with the lock file: an upgrade is a deliberate change.
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
