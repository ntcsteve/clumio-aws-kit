# Step 2: protect rds. One Clumio policy for the tagged resources of this workload. See README.md.
# Clumio credentials come from CLUMIO_API_TOKEN and CLUMIO_API_BASE_URL in your shell.

# The account, Region, unit and mode, from 1-connect's state, so they always match its connection. Until
# 1-connect is applied, the plan stops here: "Unable to find remote state".
data "terraform_remote_state" "connect" {
  backend = "local"
  config = {
    path = "${path.root}/../1-connect/terraform.tfstate" # Moved 1-connect's state elsewhere? Point here too.
  }
}

locals {
  connect = data.terraform_remote_state.connect.outputs.kit
}

provider "clumio" {
  clumio_organizational_unit_context = local.connect.unit_context # The connection's unit, so its rules can match.
}

provider "aws" {
  region              = local.connect.region
  allowed_account_ids = [local.connect.account_id] # A second guard: the module checks the account too.
}

module "protect" {
  source = "../modules/protect"

  workload             = "rds"
  name                 = var.name
  account_id           = local.connect.account_id
  region               = local.connect.region
  mode                 = local.connect.mode
  connection_workloads = local.connect.workloads
  keep_days            = var.keep_days
  archive_months       = var.archive_months
  pitr_retention_days  = var.pitr_retention_days
  allow_shorter_pitr   = var.allow_shorter_pitr
  rule_before_id       = var.rule_before_id
}

output "policy" {
  description = "This folder's Clumio policy."
  value       = { name = "${var.name}-rds-${local.connect.account_id}-${local.connect.region}", id = module.protect.policy_id }
}
