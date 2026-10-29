# Step 1: connect one AWS account and Region to Clumio, with Clumio's IAM. See README.md.
# Production teams call ../modules from their own repo instead (docs/production.md); every guard lives
# in the modules. Clumio credentials come from CLUMIO_API_TOKEN and CLUMIO_API_BASE_URL in your shell.

locals {
  # Clumio's API names the Global organizational unit with the all-zero ID (read 2026-10-28).
  unit_context = var.organizational_unit == "global" ? "00000000-0000-0000-0000-000000000000" : var.organizational_unit
}

provider "clumio" {
  # Everything Terraform creates in Clumio belongs to this unit, and a connection made here puts the
  # account's resources in it. Without it, objects land in the token owner's default unit.
  clumio_organizational_unit_context = local.unit_context
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

# What the 2-protect- folders read (terraform_remote_state), so their account, Region, unit and mode
# always match this connection's.
output "kit" {
  value = {
    account_id             = module.connection.account_id
    region                 = module.connection.region
    organizational_unit_id = module.connection.organizational_unit_id
    unit_context           = local.unit_context
    mode                   = var.mode
    workloads              = var.workloads
  }
}

output "next_step" {
  value = "Connected ${module.connection.account_id}/${module.connection.region} in unit ${module.connection.organizational_unit_id} (${var.mode}). Next: tag what you want protected, then apply the 2-protect- folders you need (README.md, step 2)."
}
