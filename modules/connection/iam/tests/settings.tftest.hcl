# Proves offline that the organization IAM settings are checked before anything is planned.
# What the IAM itself contains is setup/preview's job (golden tests).
# Run: terraform test (in this module; needs Terraform 1.10+). Mock providers: no AWS or Clumio calls.

mock_provider "aws" {
  # Clumio's aws-template renders IAM policies; a mock needs valid JSON for them.
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "clumio" {}

variables {
  connection = {
    token                 = "mock-token"
    role_external_id      = "mock-external-id"
    account_native_id     = "123456789012"
    aws_region            = "ap-southeast-1"
    clumio_aws_account_id = "111111111111"
    data_plane_account_id = "222222222222"
  }
}

run "a_prefix_iam_cant_use_is_refused" {
  command = plan
  variables {
    iam_prefix = "has spaces"
  }
  expect_failures = [var.iam_prefix]
}

run "a_path_without_slashes_is_refused" {
  command = plan
  variables {
    iam_path = "clumio"
  }
  expect_failures = [var.iam_path]
}

run "an_unknown_workload_is_refused" {
  command = plan
  variables {
    workloads = ["s3", "dynamodb"]
  }
  expect_failures = [var.workloads]
}

run "a_boundary_that_isnt_a_policy_arn_is_refused" {
  command = plan
  variables {
    permissions_boundary_arn = "arn:aws:iam::123456789012:role/not-a-policy"
  }
  expect_failures = [var.permissions_boundary_arn]
}
