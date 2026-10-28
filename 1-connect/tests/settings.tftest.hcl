# Proves offline that 1-connect plans with valid settings, refuses ones that would fail quietly later,
# and hands the 2-protect- folders what they read. Plans only; mock providers.

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
mock_provider "clumio" {}

variables {
  account_id          = "123456789012"
  region              = "us-west-2"
  organizational_unit = "global"
  mode                = "trial"
}

run "matching_settings_plan" {
  command = plan
}

# The 2-protect- folders take their unit context, mode and workloads from here, so all of them match.
run "global_becomes_clumios_all_zero_unit_for_the_protect_folders" {
  command = plan
  variables {
    workloads = ["s3", "aurora"]
  }
  assert {
    condition     = output.kit.unit_context == "00000000-0000-0000-0000-000000000000" && output.kit.mode == "trial" && output.kit.workloads == tolist(["s3", "aurora"])
    error_message = "The kit output must carry the unit context Clumio uses, the mode and the workloads."
  }
}

run "a_unit_id_is_passed_through" {
  command = plan
  variables {
    organizational_unit = "11111111-2222-3333-4444-555555555555"
  }
  assert {
    condition     = output.kit.unit_context == "11111111-2222-3333-4444-555555555555"
    error_message = "A unit ID is the context as written."
  }
}

run "an_unknown_mode_is_refused" {
  command = plan
  variables {
    mode = "staging"
  }
  expect_failures = [var.mode]
}
