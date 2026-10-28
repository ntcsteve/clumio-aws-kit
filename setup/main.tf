# The first-time path: connect one AWS account and Region to Clumio. Run it with make (see Makefile).
# Production teams call ../modules from their own repo instead; every guard lives in the modules.
# Clumio credentials come from CLUMIO_API_TOKEN and CLUMIO_API_BASE_URL in your shell.

locals {
  # Clumio's API names the Global organizational unit with the all-zero ID (read 2026-10-28).
  global_unit = "00000000-0000-0000-0000-000000000000"
}

provider "clumio" {
  # Everything Terraform creates in Clumio belongs to this unit, and a connection made here puts the
  # account's resources in it. Without it, objects land in the token owner's default unit.
  clumio_organizational_unit_context = var.organizational_unit == "global" ? local.global_unit : var.organizational_unit
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # A second guard: the module checks the account too.
}

module "connection" {
  source = "../modules/connection"

  account_id               = var.account_id
  region                   = var.region
  mode                     = var.mode
  report_emails            = var.report_emails
  iam_prefix               = var.iam_prefix
  iam_path                 = var.iam_path
  workloads                = var.workloads
  role_tags                = var.role_tags
  permissions_boundary_arn = var.permissions_boundary_arn
  pass_role_deny_list      = var.pass_role_deny_list
}

output "next_step" {
  value = "Connected ${module.connection.account_id}/${module.connection.region} in unit ${module.connection.organizational_unit_id} (${var.mode}). make apply has checked that a new plan shows no changes."
}
