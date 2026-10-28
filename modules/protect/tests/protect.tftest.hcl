# Proves offline that one call protects one workload with its own Clumio policy, selected by tag in
# this account and Region only, and refuses settings Clumio would refuse, or that would surprise you.
# Plans only: a production guard refuses destroy. Mock providers: no AWS or Clumio calls.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
  # No databases in the Region unless a run says otherwise.
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
  workload            = "rds"
  name                = "gold"
  account_id          = "123456789012"
  region              = "us-west-2"
  mode                = "trial"
  keep_days           = 30
  archive_months      = 12
  pitr_retention_days = 14
}

# --- One policy per workload, named for it --------------------------------------------------------

run "s3_gets_backtrack_and_securevault_through_a_protection_group" {
  command = plan
  variables {
    workload = "s3"
  }
  assert {
    condition     = clumio_policy.this.name == "gold-s3-123456789012-us-west-2"
    error_message = "The policy is named <profile>-<workload>-<account>-<region>."
  }
  assert {
    condition     = toset([for op in clumio_policy.this.operations : op.type]) == toset(["aws_s3_backtrack", "protection_group_backup"])
    error_message = "S3 gets Backtrack and SecureVault, nothing else."
  }
  assert {
    condition     = length(clumio_protection_group.s3) == 1 && length(clumio_policy_assignment.s3) == 1 && length(clumio_policy_rule.tagged) == 0
    error_message = "Clumio's rules don't cover S3: buckets join through a protection group, with no rule."
  }
  assert {
    condition     = jsondecode(clumio_protection_group.s3[0].bucket_rule) == { aws_tag = { "$eq" = { key = "clumio-profile", value = "gold" } }, aws_account_native_id = { "$eq" = "123456789012" }, aws_region = { "$eq" = "us-west-2" } }
    error_message = "The group takes buckets tagged clumio-profile = gold in this account and Region only."
  }
}

run "rds_gets_pitr_securevault_and_archive_for_instances_only" {
  command = plan
  assert {
    condition     = clumio_policy.this.name == "gold-rds-123456789012-us-west-2"
    error_message = "The policy is named <profile>-rds-<account>-<region>."
  }
  assert {
    condition     = toset([for op in clumio_policy.this.operations : op.type]) == toset(["aws_rds_resource_aws_snapshot", "aws_rds_resource_rolling_backup", "aws_rds_resource_granular_backup"])
    error_message = "RDS gets PITR, SecureVault Standard and Archive."
  }
  assert {
    condition = jsondecode(clumio_policy_rule.tagged[0].condition) == {
      entity_type           = { "$in" = ["aws_rds_instance"] }
      aws_tag               = { "$eq" = { key = "clumio-profile", value = "gold" } }
      aws_account_native_id = { "$eq" = "123456789012" }
      aws_region            = { "$eq" = "us-west-2" }
    }
    error_message = "The RDS rule matches tagged DB instances in this account and Region only."
  }
}

run "aurora_gets_the_same_protection_for_clusters_only" {
  command = plan
  variables {
    workload = "aurora"
  }
  assert {
    condition     = clumio_policy.this.name == "gold-aurora-123456789012-us-west-2" && jsondecode(clumio_policy_rule.tagged[0].condition).entity_type == { "$in" = ["aws_rds_cluster"] }
    error_message = "Aurora has its own policy and a rule for DB clusters only."
  }
}

run "ec2_gets_a_daily_copy_of_tagged_instances" {
  command = plan
  variables {
    workload = "ec2"
  }
  assert {
    condition     = [for op in clumio_policy.this.operations : op.type] == ["aws_ec2_instance_backup"] && jsondecode(clumio_policy_rule.tagged[0].condition).entity_type == { "$in" = ["aws_ec2_instance"] }
    error_message = "EC2 has its own policy and a rule for instances only."
  }
}

run "ebs_uses_its_own_tag_key" {
  command = plan
  variables {
    workload = "ebs"
  }
  assert {
    condition     = [for op in clumio_policy.this.operations : op.type] == ["aws_ebs_volume_backup"] && jsondecode(clumio_policy_rule.tagged[0].condition).aws_tag == { "$eq" = { key = "clumio-volume-profile", value = "gold" } }
    error_message = "EBS volumes on their own join by clumio-volume-profile, so an instance's volumes are never copied twice by accident."
  }
}

run "archive_zero_drops_the_archive_tier" {
  command = plan
  variables {
    archive_months = 0
  }
  assert {
    condition     = !contains([for op in clumio_policy.this.operations : op.type], "aws_rds_resource_granular_backup")
    error_message = "archive_months = 0 means no archive copies, and no archive bill."
  }
}

# --- Settings refused ------------------------------------------------------------------------------

run "an_unknown_workload_is_refused" {
  command = plan
  variables {
    workload = "dynamodb"
  }
  expect_failures = [var.workload]
}

run "s3_below_clumios_30_day_minimum_is_refused" {
  command = plan
  variables {
    workload  = "s3"
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
    pitr_retention_days = 36
  }
  expect_failures = [var.pitr_retention_days]
}

run "databases_without_an_archive_decision_are_refused" {
  command = plan
  variables {
    archive_months = null
  }
  expect_failures = [var.archive_months]
}

run "s3_needs_no_database_settings" {
  command = plan
  variables {
    workload            = "s3"
    archive_months      = null
    pitr_retention_days = null
  }
}

run "a_name_that_cant_be_a_tag_value_is_refused" {
  command = plan
  variables {
    name = "Gold Tier!"
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

run "a_connection_for_another_account_or_region_is_refused" {
  command = plan
  override_data {
    target = data.clumio_aws_connection.this
    values = { id = "111111111111_us-west-2" }
  }
  expect_failures = [clumio_policy.this]
}

# --- Production --------------------------------------------------------------------------------------

run "trial_has_no_production_guard" {
  command = plan
  assert {
    condition     = length(terraform_data.production_guard) == 0
    error_message = "A trial can be torn down."
  }
}

run "production_has_the_guard" {
  command = plan
  variables {
    mode = "production"
  }
  assert {
    condition     = length(terraform_data.production_guard) == 1
    error_message = "Production must refuse destroy."
  }
}

# --- Rule position -----------------------------------------------------------------------------------

# The rule ignores Clumio's own reordering (before_rule_id), so a rule_before_id set after creation would
# be ignored too. Its own marker carries the setting, and a change to the marker replaces the rule.
run "rule_before_id_places_the_rule_and_lives_in_its_marker" {
  command = plan
  variables {
    rule_before_id = "rule-that-would-win"
  }
  assert {
    condition     = clumio_policy_rule.tagged[0].before_rule_id == "rule-that-would-win" && terraform_data.rule_position.input == "rule-that-would-win"
    error_message = "rule_before_id must place the rule ahead of the named one, and live in the marker the rule is replaced by."
  }
}

# --- The PITR guard ----------------------------------------------------------------------------------

# A shorter PITR window deletes AWS's older automated backups for good, so the plan stops on it.
run "an_rds_instance_whose_window_would_shorten_stops_the_plan" {
  command = plan
  override_data {
    target = data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 35, db_cluster_identifier = "" }
  }
  expect_failures = [clumio_policy.this]
}

run "allow_shorter_pitr_accepts_it" {
  command = plan
  variables {
    allow_shorter_pitr = true
  }
  override_data {
    target = data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 35, db_cluster_identifier = "" }
  }
  assert {
    condition     = local.shorter_pitr == { "RDS instance orders" = 35 }
    error_message = "The shorter window must still be known, and accepted."
  }
}

run "an_equal_window_passes" {
  command = plan
  override_data {
    target = data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 14, db_cluster_identifier = "" }
  }
  assert {
    condition     = local.shorter_pitr == {}
    error_message = "A window equal to pitr_retention_days doesn't shorten."
  }
}

# Aurora's instances carry their cluster's window, and Clumio protects the cluster.
run "the_rds_folder_leaves_aurora_instances_to_their_cluster" {
  command = plan
  override_data {
    target = data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders-aurora-1"] }
  }
  override_data {
    target = data.aws_db_instance.tagged["orders-aurora-1"]
    values = { backup_retention_period = 35, db_cluster_identifier = "orders-aurora" }
  }
  assert {
    condition     = local.shorter_pitr == {}
    error_message = "An Aurora instance must not count in the RDS folder."
  }
}

run "an_aurora_cluster_whose_window_would_shorten_stops_the_plan" {
  command = plan
  variables {
    workload = "aurora"
  }
  override_data {
    target = data.aws_rds_clusters.all[0]
    values = { cluster_identifiers = ["orders-aurora"] }
  }
  override_data {
    target = data.aws_rds_cluster.all["orders-aurora"]
    values = { backup_retention_period = 35, engine = "aurora-mysql", tags = { "clumio-profile" = "gold" } }
  }
  expect_failures = [clumio_policy.this]
}

run "untagged_and_unsupported_clusters_are_left_alone" {
  command = plan
  variables {
    workload = "aurora"
  }
  override_data {
    target = data.aws_rds_clusters.all[0]
    values = { cluster_identifiers = ["other", "docs"] }
  }
  override_data {
    target = data.aws_rds_cluster.all["other"]
    values = { backup_retention_period = 35, engine = "aurora-postgresql", tags = { team = "x" } }
  }
  override_data {
    target = data.aws_rds_cluster.all["docs"]
    values = { backup_retention_period = 35, engine = "docdb", tags = { "clumio-profile" = "gold" } }
  }
  assert {
    condition     = local.shorter_pitr == {}
    error_message = "Only clusters tagged with this profile, of an engine Clumio protects, count."
  }
}

run "each_database_folder_reads_only_its_own_kind" {
  command = plan
  assert {
    condition     = length(data.aws_db_instances.tagged) == 1 && length(data.aws_rds_clusters.all) == 0
    error_message = "The RDS folder reads instances only."
  }
}

run "no_database_reads_outside_the_database_folders" {
  command = plan
  variables {
    workload = "ec2"
  }
  assert {
    condition     = length(data.aws_db_instances.tagged) == 0 && length(data.aws_rds_clusters.all) == 0
    error_message = "Only the RDS and Aurora folders read databases: the deploy role may not be allowed to."
  }
}

# The connection's IAM must cover this workload, or Clumio never finds these resources. A caller that
# knows the connection's workloads (the 2-protect- folders read them from 1-connect) passes them.
run "a_workload_the_connections_iam_leaves_out_is_refused" {
  command = plan
  variables {
    connection_workloads = ["s3", "ec2"]
  }
  expect_failures = [var.connection_workloads]
}

run "a_workload_the_connection_covers_plans" {
  command = plan
  variables {
    connection_workloads = ["s3", "rds", "aurora"]
  }
}
