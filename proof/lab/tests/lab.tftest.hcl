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
  mock_data "aws_subnet" {
    defaults = { availability_zone = "us-west-2a" }
  }
  mock_data "aws_ssm_parameter" {
    defaults = { value = "ami-0123456789abcdef0" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-west-2:123456789012:key/00000000-0000-0000-0000-000000000000" } # apply runs need a valid ARN
  }
}
mock_provider "random" {}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
  profile    = "gold"
  parts      = ["s3", "rds-amk", "aurora-amk", "aurora-cmk", "bad-tag", "ec2-amk", "ec2-cmk", "ebs-amk", "ebs-cmk", "ebs-double"]
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

run "instances_carry_the_profile_tag_and_volumes_on_their_own_the_volume_tag" {
  command = plan
  assert {
    condition     = alltrue([for i in aws_instance.ec2 : i.tags["clumio-profile"] == "gold"]) && length(aws_instance.ec2) == 2
    error_message = "Both instances must carry clumio-profile = <profile>."
  }
  assert {
    condition     = alltrue([for i in aws_instance.ec2 : i.root_block_device[0].tags["clumio-profile"] == "gold"])
    error_message = "Root volumes carry the instance tag, as launch templates often copy it: status must not list them."
  }
  assert {
    condition     = alltrue([for v in aws_ebs_volume.own : v.tags["clumio-volume-profile"] == "gold" && v.encrypted]) && length(aws_ebs_volume.own) == 3
    error_message = "Volumes on their own (amk, cmk, double) must carry clumio-volume-profile = <profile>, encrypted."
  }
  assert {
    condition     = length(aws_volume_attachment.double) == 1
    error_message = "The double volume must be attached to the protected AMK instance, so status shows DOUBLE."
  }
}

run "instances_and_volumes_are_encrypted_and_reachable_by_no_one" {
  command = plan
  assert {
    condition     = alltrue([for i in aws_instance.ec2 : i.root_block_device[0].encrypted && i.associate_public_ip_address == false && i.metadata_options[0].http_tokens == "required"])
    error_message = "Instances must have encrypted root volumes, no public IP, and IMDSv2 only."
  }
}

# proof/capture.py reads instances and volumes from this output: without them it would capture no
# EC2 or EBS evidence. Apply with the mock provider, so every ID is known.
run "the_output_names_every_instance_and_volume_for_the_capture" {
  command = apply
  assert {
    condition     = join(",", keys(output.lab.instances)) == "amk,cmk" && output.lab.instances["amk"] == aws_instance.ec2["amk"].id
    error_message = "The lab output must name each instance's ID by its key, for proof/capture.py."
  }
  assert {
    condition     = join(",", keys(output.lab.volumes)) == "amk,cmk,double" && output.lab.volumes["cmk"] == aws_ebs_volume.own["cmk"].id
    error_message = "The lab output must name each volume's ID by its key, for proof/capture.py."
  }
}

run "the_double_volume_needs_the_amk_instance" {
  command = plan
  variables {
    parts = ["ebs-double"]
  }
  expect_failures = [var.parts]
}
