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
  name                = "gold"
  connection_id       = "123456789012_us-west-2"
  account_id          = "123456789012"
  region              = "us-west-2"
  mode                = "trial"
  s3                  = true
  databases           = true
  keep_days           = 30
  archive_months      = 12
  backtrack_months    = 3
  pitr_retention_days = 14
  ec2                 = false
  ebs_volumes         = false
}

run "both_workloads_share_one_policy" {
  command = plan
  assert {
    condition     = clumio_policy.this.name == "gold-123456789012-us-west-2"
    error_message = "One policy per profile, named after the profile, account and Region."
  }
  assert {
    condition     = length(clumio_policy_rule.tagged) == 1 && length(clumio_protection_group.s3) == 1 && length(clumio_policy_assignment.s3) == 1
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
    condition = jsondecode(clumio_policy_rule.tagged[0].condition) == {
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
    condition     = length(clumio_policy_rule.tagged) == 0 && length(clumio_protection_group.s3) == 1
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
    condition     = length(clumio_protection_group.s3) == 0 && length(clumio_policy_rule.tagged) == 1
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
  expect_failures = [var.ebs_volumes]
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

# Old step 2 looked the connection up before protecting anything. Clumio's own lookup stops the plan
# with "AWS connection not found"; this guards that what it found is this account and Region.
run "a_connection_for_another_account_or_region_is_refused" {
  command = plan
  override_data {
    target = data.clumio_aws_connection.this
    values = { id = "111111111111_us-west-2" }
  }
  expect_failures = [clumio_policy.this]
}

run "the_rule_can_be_ranked_ahead_of_another" {
  command = plan
  variables {
    rule_before_id = "rule-that-would-win"
  }
  assert {
    condition     = clumio_policy_rule.tagged[0].before_rule_id == "rule-that-would-win"
    error_message = "rule_before_id must place this profile's rule ahead of the named rule."
  }
}

# The rules ignore Clumio's own reordering (before_rule_id), so a rule_before_id set after creation
# would be ignored too, and status's advice for OTHER would do nothing. Its own marker carries the
# setting, and a change to the marker replaces the rules (replace_triggered_by), placing them anew.
run "a_new_rule_before_id_has_a_marker_that_replaces_the_rules" {
  command = plan
  variables {
    rule_before_id = "rule-that-would-win"
    ebs_volumes    = true
  }
  assert {
    condition     = terraform_data.rule_position.input == "rule-that-would-win"
    error_message = "rule_before_id must live in the marker the rules are replaced by."
  }
}

run "ec2_joins_the_profiles_tag_rule_and_the_policy" {
  command = plan
  variables {
    ec2 = true
  }
  assert {
    condition     = jsondecode(clumio_policy_rule.tagged[0].condition).entity_type == { "$in" = ["aws_rds_instance", "aws_rds_cluster", "aws_ec2_instance"] }
    error_message = "With ec2 on, the tag rule must match EC2 instances too: one rule, one tag."
  }
  assert {
    condition     = contains([for op in clumio_policy.this.operations : op.type], "aws_ec2_instance_backup")
    error_message = "The policy must back up EC2 instances, with their attached volumes."
  }
}

run "ec2_alone_has_a_tag_rule_for_instances_only" {
  command = plan
  variables {
    s3                  = false
    databases           = false
    ec2                 = true
    keep_days           = 7
    pitr_retention_days = null
  }
  assert {
    condition     = jsondecode(clumio_policy_rule.tagged[0].condition).entity_type == { "$in" = ["aws_ec2_instance"] }
    error_message = "EC2 alone: the rule matches instances only."
  }
}

run "volumes_have_their_own_rule_and_their_own_tag" {
  command = plan
  variables {
    ebs_volumes = true
  }
  assert {
    condition = jsondecode(clumio_policy_rule.volumes[0].condition) == {
      entity_type           = { "$in" = ["aws_ebs_volume"] }
      aws_tag               = { "$eq" = { key = "clumio-volume-profile", value = "gold" } }
      aws_account_native_id = { "$eq" = "123456789012" }
      aws_region            = { "$eq" = "us-west-2" }
    }
    error_message = "Volumes join only through clumio-volume-profile, so a volume an instance already covers isn't backed up twice by accident."
  }
  assert {
    condition     = contains([for op in clumio_policy.this.operations : op.type], "aws_ebs_volume_backup")
    error_message = "The profile's one policy must back up volumes on their own."
  }
}

run "no_volume_rule_unless_asked" {
  command = plan
  assert {
    condition     = length(clumio_policy_rule.volumes) == 0
    error_message = "No volume rule unless ebs_volumes is on: each rule takes a slot in the unit."
  }
}

# A shorter PITR window deletes AWS's older automated backups for good, so the plan stops on it,
# here in the module, so a production repo calling it gets the same stop as deploy/.
run "a_database_whose_pitr_window_would_shorten_stops_the_plan" {
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

run "allow_shorter_pitr_accepts_a_shorter_window" {
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

run "a_longer_or_equal_window_passes" {
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

# An Aurora instance carries its cluster's window, and Clumio protects the cluster: judge the cluster.
run "an_aurora_instance_is_judged_by_its_cluster" {
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
    error_message = "An Aurora instance must not count on its own."
  }
}

run "a_tagged_aurora_cluster_whose_window_would_shorten_stops_the_plan" {
  command = plan
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

run "no_database_reads_without_databases" {
  command = plan
  variables {
    databases = false
  }
  assert {
    condition     = length(data.aws_db_instances.tagged) == 0 && length(data.aws_rds_clusters.all) == 0
    error_message = "A profile without databases must not read them: the deploy role may not be allowed to."
  }
}

# AWS names instances and clusters in separate namespaces, so an instance and a cluster can share a
# name. Each must be judged on its own: one must never hide the other's shorter window.
run "an_instance_and_a_cluster_with_the_same_name_are_both_judged" {
  command = plan
  variables {
    allow_shorter_pitr  = true
    pitr_retention_days = 7
  }
  override_data {
    target = data.aws_db_instances.tagged[0]
    values = { instance_identifiers = ["orders"] }
  }
  override_data {
    target = data.aws_db_instance.tagged["orders"]
    values = { backup_retention_period = 35, db_cluster_identifier = "" }
  }
  override_data {
    target = data.aws_rds_clusters.all[0]
    values = { cluster_identifiers = ["orders"] }
  }
  override_data {
    target = data.aws_rds_cluster.all["orders"]
    values = { backup_retention_period = 7, engine = "aurora-mysql", tags = { "clumio-profile" = "gold" } }
  }
  assert {
    condition     = local.shorter_pitr == { "RDS instance orders" = 35 }
    error_message = "The cluster named orders must not hide the instance named orders."
  }
}
