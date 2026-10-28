# Proves offline that the connection module refuses what it must, before anything is created.
# What Clumio's IAM contains is 0-check/preview's job (golden tests). Plans only: a production guard
# refuses destroy, so an applied test could never clean up. Run: terraform test, in this module.
# Mock providers: no AWS or Clumio calls.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
  # Clumio's aws-template renders IAM policies; a mock needs valid JSON for them.
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "clumio" {}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
  mode       = "trial"
}

run "trial_has_no_production_guard" {
  command = plan
  assert {
    condition     = length(terraform_data.production_guard) == 0
    error_message = "A trial must be free to tear down: no production guard."
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

run "an_unknown_mode_is_refused" {
  command = plan
  variables {
    mode = "prod"
  }
  expect_failures = [var.mode]
}

run "a_malformed_account_id_is_refused" {
  command = plan
  variables {
    account_id = "12345"
  }
  expect_failures = [var.account_id]
}

run "a_malformed_region_is_refused" {
  command = plan
  variables {
    region = "Oregon"
  }
  expect_failures = [var.region]
}

run "signed_in_to_another_account_is_refused" {
  command = plan
  override_data {
    target = data.aws_caller_identity.signed_in
    values = { account_id = "111111111111" }
  }
  expect_failures = [clumio_aws_connection.this]
}

run "an_aws_provider_in_another_region_is_refused" {
  command = plan
  override_data {
    target = data.aws_region.provider
    values = { region = "eu-west-1" }
  }
  expect_failures = [clumio_aws_connection.this]
}

run "no_report_without_emails" {
  command = plan
  assert {
    condition     = length(clumio_report_configuration.daily_backups) == 0
    error_message = "No report_emails, no report."
  }
}

run "a_report_with_emails" {
  command = plan
  variables {
    report_emails = ["platform-oncall@example.com"]
  }
  assert {
    condition     = length(clumio_report_configuration.daily_backups) == 1
    error_message = "report_emails set, so the daily report must be planned."
  }
}

run "a_malformed_email_is_refused" {
  command = plan
  variables {
    report_emails = ["platform-oncall"]
  }
  expect_failures = [var.report_emails]
}
