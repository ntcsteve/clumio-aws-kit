# Proves offline that 2-protect-rds takes the account, Region, unit and mode from 1-connect, and
# protects only rds. Plans only; mock providers, and 1-connect's state stood in by an override.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
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

override_data {
  target = data.terraform_remote_state.connect
  values = {
    outputs = {
      kit = {
        account_id   = "123456789012", region = "us-west-2", organizational_unit_id = "11111111-2222-3333-4444-555555555555"
        unit_context = "11111111-2222-3333-4444-555555555555", mode = "trial", workloads = ["s3", "rds", "aurora", "ec2", "ebs"]
      }
    }
  }
}

variables {
  name                = "gold"
  keep_days           = 30
  archive_months      = 0
  pitr_retention_days = 7
}

run "it_protects_rds_in_1_connects_account_and_region" {
  command = plan
  assert {
    condition     = output.policy.name == "gold-rds-123456789012-us-west-2"
    error_message = "The policy is named for this workload, in 1-connect's account and Region."
  }
}

run "the_plan_shows_the_databases_it_checked" {
  command = plan
  override_data {
    target = module.protect.data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = module.protect.data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 7, db_cluster_identifier = "" }
  }
  assert {
    condition     = output.pitr_checked == { "RDS instance orders" = 7 }
    error_message = "This folder's plan must show what the PITR guard read."
  }
}
