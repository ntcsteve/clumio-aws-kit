# Proves offline that deploy/ refuses settings that would fail quietly later. Plans only; mock providers.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_db_instances" {
    defaults = { instance_identifiers = [] }
  }
  mock_data "aws_rds_clusters" {
    defaults = { cluster_identifiers = [] }
  }
}
mock_provider "clumio" {
  mock_data "clumio_aws_connection" {
    defaults = { id = "123456789012_us-west-2" }
  }
}

variables {
  account_id          = "123456789012"
  region              = "us-west-2"
  organizational_unit = "global"
  mode                = "trial"
  profiles = {
    gold = { s3 = true, databases = true, ec2 = true, keep_days = 30, archive_months = 0, pitr_retention_days = 7 }
  }
}

run "matching_settings_plan" {
  command = plan
}

run "a_profile_workload_the_connection_leaves_out_is_refused" {
  command = plan
  variables {
    workloads = ["s3", "rds"]
  }
  expect_failures = [var.profiles]
}

run "an_unset_archive_retention_is_refused" {
  command = plan
  variables {
    profiles = {
      gold = { s3 = true, databases = true, keep_days = 30, archive_months = null, pitr_retention_days = 7 }
    }
  }
  expect_failures = [var.profiles]
}

run "a_database_profile_without_a_pitr_window_is_refused" {
  command = plan
  variables {
    profiles = {
      gold = { s3 = true, databases = true, keep_days = 30, archive_months = 0 }
    }
  }
  expect_failures = [var.profiles]
}

# The first apply creates the connection and the profile together. The profile's database reads must
# still run at plan: deferred, their for_each fails it (spike S4). The module's own tests prove the
# PITR guard stops a shorter window; here, that allow_shorter_pitr reaches it.
run "a_tagged_database_plans_with_the_connection_in_the_same_apply" {
  command = plan
  override_data {
    target = module.profile["gold"].data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = module.profile["gold"].data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 7, db_cluster_identifier = "" }
  }
}

run "allow_shorter_pitr_reaches_the_profile" {
  command = plan
  variables {
    profiles = {
      gold = { s3 = true, databases = true, ec2 = true, keep_days = 30, archive_months = 0, pitr_retention_days = 7, allow_shorter_pitr = true }
    }
  }
  override_data {
    target = module.profile["gold"].data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = module.profile["gold"].data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 35, db_cluster_identifier = "" }
  }
}
