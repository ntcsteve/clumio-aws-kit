# The first-time path: connect one AWS account and Region to Clumio, then protect it. See README.md.
# Production teams call ../modules from their own repo instead (docs/production.md). Every guard lives in
# the modules except the workloads check in variables.tf, which needs both modules' settings at once.
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

# One profile per entry in profiles. connection_id makes protection wait for Clumio's IAM, and on
# destroy go first. No module-wide depends_on: it would defer the profile's database reads to apply,
# and fail the plan.
module "profile" {
  source   = "../modules/profile"
  for_each = var.profiles

  name                = each.key
  connection_id       = module.connection.connection_id
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
  allow_shorter_pitr  = each.value.allow_shorter_pitr
  rule_before_id      = each.value.rule_before_id
}

# What tools/status.py reads to tell this folder's protection from anyone else's, plus the rule IDs
# for ranking another rule against these.
output "kit" {
  value = {
    account_id             = module.connection.account_id
    region                 = module.connection.region
    organizational_unit_id = module.connection.organizational_unit_id
    profiles = { for name, profile in module.profile : name => {
      policy_id           = profile.policy_id
      rule_id             = profile.rule_id
      volume_rule_id      = profile.volume_rule_id
      protection_group_id = profile.protection_group_id
      workloads           = profile.workloads
    } }
  }
}

output "next_step" {
  value = "Connected ${module.connection.account_id}/${module.connection.region} in unit ${module.connection.organizational_unit_id} (${var.mode}), with ${length(var.profiles)} profile(s). Tag resources clumio-profile = <profile>, then, from the repository's root folder, run tools/status.py (3-prove/README.md)."
}
