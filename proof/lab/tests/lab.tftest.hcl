# Proves offline that the lab builds only what you ask for, encrypts each part under the key it
# claims, and refuses the wrong account. Plans only; mock provider: no AWS calls.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
  mock_data "aws_vpc" {
    defaults = { id = "vpc-0123456789abcdef0" }
  }
  mock_data "aws_subnets" {
    defaults = { ids = ["subnet-0a", "subnet-0b"] }
  }
}
mock_provider "random" {}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
  profile    = "gold"
  parts      = ["s3", "rds-amk", "aurora-amk", "aurora-cmk", "bad-tag"]
}

run "every_part_is_built_and_tagged_for_the_profile" {
  command = plan
  assert {
    condition     = length(aws_s3_bucket.docs) == 1 && length(aws_db_instance.rds_amk) == 1 && length(aws_rds_cluster.aurora) == 2 && length(aws_s3_bucket.bad_tag) == 1
    error_message = "Each listed part must be built."
  }
  assert {
    condition     = aws_s3_bucket.docs[0].tags["clumio-profile"] == "gold" && aws_db_instance.rds_amk[0].tags["clumio-profile"] == "gold" && alltrue([for c in aws_rds_cluster.aurora : c.tags["clumio-profile"] == "gold"])
    error_message = "Every part must carry clumio-profile = <profile>, so the profile protects it."
  }
  assert {
    condition     = aws_s3_bucket.bad_tag[0].tags["clumio-profile"] == "gold-typo"
    error_message = "The bad-tag bucket must carry a value no profile has, so status shows BAD_VALUE."
  }
}

# Which key each part gets is only known after apply; the live evidence shows it (describe-db-*,
# head-object). Offline, a plan can show that everything is encrypted, and with KMS.
run "every_database_and_object_is_encrypted_with_kms" {
  command = plan
  assert {
    condition     = aws_db_instance.rds_amk[0].storage_encrypted && alltrue([for c in aws_rds_cluster.aurora : c.storage_encrypted])
    error_message = "Every lab database must be encrypted: unencrypted test data proves nothing about real databases."
  }
  assert {
    condition     = alltrue([for o in aws_s3_object.doc : o.server_side_encryption == "aws:kms"])
    error_message = "Both objects must use KMS: one under aws/s3, one under the lab key."
  }
  assert {
    condition     = length(aws_kms_key.lab) == 1 && aws_kms_key.lab[0].enable_key_rotation
    error_message = "The lab's customer-managed key must exist, with rotation on, as a real one would."
  }
}

run "only_the_listed_parts_are_built" {
  command = plan
  variables {
    parts = ["s3"]
  }
  assert {
    condition     = length(aws_db_instance.rds_amk) == 0 && length(aws_rds_cluster.aurora) == 0 && length(aws_s3_bucket.bad_tag) == 0
    error_message = "Parts not listed must not be built: each one costs money."
  }
  assert {
    condition     = length(aws_kms_key.lab) == 1
    error_message = "s3 holds a customer-managed-key object, so it needs the lab key."
  }
}

run "no_lab_key_when_nothing_needs_one" {
  command = plan
  variables {
    parts = ["rds-amk"]
  }
  assert {
    condition     = length(aws_kms_key.lab) == 0
    error_message = "A key costs money and waits 7 days to delete: only make it when a part needs it."
  }
}

run "an_unknown_part_is_refused" {
  command = plan
  variables {
    parts = ["s3", "dynamodb"]
  }
  expect_failures = [var.parts]
}

run "signed_in_to_another_account_is_refused" {
  command = plan
  override_data {
    target = data.aws_caller_identity.signed_in
    values = { account_id = "111111111111" }
  }
  expect_failures = [random_id.suffix]
}
