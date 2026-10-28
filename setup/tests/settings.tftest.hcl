# Proves offline that setup/ refuses settings that would fail quietly later. Plans only; mock providers.

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
