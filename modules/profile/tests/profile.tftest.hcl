# Proves offline that a profile builds the right Clumio objects for its workloads, and refuses
# settings Clumio would refuse, or that would surprise you, before anything is created.
# Plans only: a production guard refuses destroy. Mock providers: no AWS or Clumio calls.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
}
mock_provider "clumio" {}

variables {
  name                = "gold"
  account_id          = "123456789012"
  region              = "us-west-2"
  mode                = "trial"
  s3                  = true
  databases           = true
  keep_days           = 30
  archive_months      = 12
  backtrack_months    = 3
  pitr_retention_days = 14
}

run "both_workloads_share_one_policy" {
  command = plan
  assert {
    condition     = clumio_policy.this.name == "gold-123456789012-us-west-2"
    error_message = "One policy per profile, named after the profile, account and Region."
  }
  assert {
    condition     = length(clumio_policy_rule.databases) == 1 && length(clumio_protection_group.s3) == 1 && length(clumio_policy_assignment.s3) == 1
    error_message = "Databases need the rule; S3 needs the protection group and its assignment."
  }
  assert {
    condition = toset([for op in clumio_policy.this.operations : op.type]) == toset([
      "aws_s3_backtrack", "protection_group_backup",
      "aws_rds_resource_aws_snapshot", "aws_rds_resource_rolling_backup", "aws_rds_resource_granular_backup",
    ])
    error_message = "The policy must hold S3 Backtrack and SecureVault, and RDS PITR, SecureVault Standard and Archive."
  }
}

run "the_database_rule_matches_the_tag_in_this_account_and_region_only" {
  command = plan
  assert {
    condition = jsondecode(clumio_policy_rule.databases[0].condition) == {
      entity_type           = { "$in" = ["aws_rds_instance", "aws_rds_cluster"] }
      aws_tag               = { "$eq" = { key = "clumio-profile", value = "gold" } }
      aws_account_native_id = { "$eq" = "123456789012" }
      aws_region            = { "$eq" = "us-west-2" }
    }
    error_message = "The rule must match RDS and Aurora tagged clumio-profile = gold, in this account and Region only."
  }
}

run "the_s3_group_matches_the_tag_in_this_account_and_region_only" {
  command = plan
  assert {
    condition = jsondecode(clumio_protection_group.s3[0].bucket_rule) == {
      aws_tag               = { "$eq" = { key = "clumio-profile", value = "gold" } }
      aws_account_native_id = { "$eq" = "123456789012" }
      aws_region            = { "$eq" = "us-west-2" }
    }
    error_message = "The group must hold buckets tagged clumio-profile = gold, in this account and Region only."
  }
}

run "s3_only_has_no_rule" {
  command = plan
  variables {
    databases           = false
    pitr_retention_days = null
  }
  assert {
    condition     = length(clumio_policy_rule.databases) == 0 && length(clumio_protection_group.s3) == 1
    error_message = "S3 alone needs only its protection group."
  }
}

run "databases_only_have_no_protection_group" {
  command = plan
  variables {
    s3        = false
    keep_days = 7
  }
  assert {
    condition     = length(clumio_protection_group.s3) == 0 && length(clumio_policy_rule.databases) == 1
    error_message = "Databases alone need only their rule."
  }
}

run "archive_zero_drops_the_archive_tier" {
  command = plan
  variables {
    archive_months = 0
  }
  assert {
    condition     = !contains([for op in clumio_policy.this.operations : op.type], "aws_rds_resource_granular_backup")
    error_message = "archive_months = 0 turns the Archive tier off."
  }
}

run "a_profile_with_no_workload_is_refused" {
  command = plan
  variables {
    s3        = false
    databases = false
  }
  expect_failures = [var.databases]
}

run "s3_below_clumios_30_day_minimum_is_refused" {
  command = plan
  variables {
    keep_days = 7
  }
  expect_failures = [var.keep_days]
}

run "databases_without_a_pitr_window_are_refused" {
  command = plan
  variables {
    pitr_retention_days = null
  }
  expect_failures = [var.pitr_retention_days]
}

run "a_pitr_window_aws_cant_set_is_refused" {
  command = plan
  variables {
    pitr_retention_days = 40
  }
  expect_failures = [var.pitr_retention_days]
}

run "a_name_that_cant_be_a_tag_value_is_refused" {
  command = plan
  variables {
    name = "Gold Tier"
  }
  expect_failures = [var.name]
}

run "signed_in_to_another_account_is_refused" {
  command = plan
  override_data {
    target = data.aws_caller_identity.signed_in
    values = { account_id = "111111111111" }
  }
  expect_failures = [clumio_policy.this]
}

run "trial_has_no_production_guard" {
  command = plan
  assert {
    condition     = length(terraform_data.production_guard) == 0
    error_message = "A trial must be free to tear down."
  }
}

run "production_has_the_guard" {
  command = plan
  variables {
    mode = "production"
  }
  assert {
    condition     = length(terraform_data.production_guard) == 1
    error_message = "Production must carry the guard that refuses destroy."
  }
}
