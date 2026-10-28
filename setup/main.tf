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

# One profile per entry in profiles. Protection waits for Clumio's IAM, and on destroy goes first.
module "profile" {
  source     = "../modules/profile"
  for_each   = var.profiles
  depends_on = [module.connection]

  name                = each.key
  account_id          = var.account_id
  region              = var.region
  mode                = var.mode
  s3                  = each.value.s3
  databases           = each.value.databases
  ec2                 = each.value.ec2
  ebs_volumes         = each.value.ebs_volumes
  keep_days           = each.value.keep_days
  archive_months      = each.value.archive_months
  backtrack_months    = each.value.backtrack_months
  pitr_retention_days = each.value.pitr_retention_days
  rule_before_id      = each.value.rule_before_id
}

# What status.py reads to tell this folder's protection from anyone else's.
output "kit" {
  value = {
    account_id             = module.connection.account_id
    region                 = module.connection.region
    organizational_unit_id = module.connection.organizational_unit_id
    mode                   = var.mode
    profiles = { for name, profile in module.profile : name => {
      tag                 = profile.tag
      volume_tag          = profile.volume_tag
      policy_id           = profile.policy_id
      rule_id             = profile.rule_id
      volume_rule_id      = profile.volume_rule_id
      protection_group_id = profile.protection_group_id
      pitr_retention_days = profile.pitr_retention_days
      workloads           = profile.workloads
    } }
  }
}

output "next_step" {
  value = "Connected ${module.connection.account_id}/${module.connection.region} in unit ${module.connection.organizational_unit_id} (${var.mode}), with ${length(var.profiles)} profile(s). Tag resources clumio-profile = <profile>, then run make status."
}
