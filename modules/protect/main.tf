# One workload's protection: one Clumio policy, applied to every resource of that workload tagged
# clumio-profile = <name> (EBS volumes on their own: clumio-volume-profile) in one account and Region.
# DB instances, DB clusters, EC2 instances and EBS volumes join through a rule; S3 buckets through a
# protection group, because Clumio's rules don't cover S3. Every guard lives here, so a production
# repository that calls this module gets the same checks as the 2-protect- folders.
# The caller configures both providers; the Clumio provider's organizational unit holds these objects.
# The connection must already exist, in another state (1-connect, or the caller's own root).

data "aws_caller_identity" "signed_in" {}
data "aws_region" "provider" {}

# The connection this protects. Without one, the plan stops here: "AWS connection not found".
data "clumio_aws_connection" "this" {
  account_native_id = var.account_id
  aws_region        = var.region
}

# The PITR window of each database this would protect, so a plan that would shorten one stops (see the
# policy). RDS: tagged DB instances, skipping Aurora's members, whose cluster holds the window. Aurora:
# every DB cluster in the Region, matched by tag here, because AWS has no tag filter for clusters: one
# read per cluster per plan, bounded by the account's cluster quota.
data "aws_db_instances" "tagged" {
  count = var.workload == "rds" ? 1 : 0
  tags  = { (local.tag.key) = local.tag.value }
}

data "aws_db_instance" "tagged" {
  for_each               = toset(var.workload == "rds" ? data.aws_db_instances.tagged[0].instance_identifiers : [])
  db_instance_identifier = each.value
}

data "aws_rds_clusters" "all" {
  count = var.workload == "aurora" ? 1 : 0
}

data "aws_rds_cluster" "all" {
  for_each           = toset(var.workload == "aurora" ? data.aws_rds_clusters.all[0].cluster_identifiers : [])
  cluster_identifier = each.value
}

locals {
  workload    = var.workload
  is_database = contains(["rds", "aurora"], var.workload)
  # Its own tag key for EBS, so a volume attached to a protected instance is never copied twice by accident.
  tag  = { key = var.workload == "ebs" ? "clumio-volume-profile" : "clumio-profile", value = var.name }
  name = "${var.name}-${var.workload}-${var.account_id}-${var.region}" # Unique in the tenant.
  # A tag alone matches across the whole tenant, so every selection is scoped to this account and Region.
  scope = {
    aws_tag               = { "$eq" = local.tag }
    aws_account_native_id = { "$eq" = var.account_id }
    aws_region            = { "$eq" = var.region }
  }
  # What Clumio calls each workload's resources, for the rule. S3 has no rule.
  entity = { rds = "aws_rds_instance", aurora = "aws_rds_cluster", ec2 = "aws_ec2_instance", ebs = "aws_ebs_volume" }
  # Databases whose window would get shorter, with today's window in days. Keyed by kind and name.
  pitr_now = merge(
    { for name, db in data.aws_db_instance.tagged : "RDS instance ${name}" => db.backup_retention_period if db.db_cluster_identifier == "" },
    { for name, cluster in data.aws_rds_cluster.all : "Aurora cluster ${name}" => cluster.backup_retention_period
    if lookup(cluster.tags, local.tag.key, null) == local.tag.value && !contains(["docdb", "neptune"], cluster.engine) },
  )
  shorter_pitr = { for name, days in local.pitr_now : name => days if local.is_database && days > coalesce(var.pitr_retention_days, 0) }
}

resource "clumio_policy" "this" {
  name = local.name

  # S3, Backtrack: rolls a bucket back in place from its own versions. Needs S3 Versioning.
  dynamic "operations" {
    for_each = local.workload == "s3" ? [1] : []
    content {
      type           = "aws_s3_backtrack"
      action_setting = "immediate" # Start now, not at the next window.
      slas {
        retention_duration {
          unit  = "months"
          value = var.backtrack_months
        }
        rpo_frequency {
          unit  = "days"
          value = 1
        }
      }
    }
  }

  # S3, SecureVault Standard: a daily copy in Clumio, outside your account.
  dynamic "operations" {
    for_each = local.workload == "s3" ? [1] : []
    content {
      type           = "protection_group_backup"
      action_setting = "immediate" # The first backup starts when the policy is assigned.
      slas {
        retention_duration {
          unit  = "days"
          value = var.keep_days
        }
        rpo_frequency {
          unit  = "days"
          value = 1
        }
      }
      advanced_settings {
        protection_group_backup {
          backup_tier = "cold" # Clumio's name for SecureVault Standard
        }
      }
    }
  }

  # Databases, AWS PITR: Clumio sets each database's PITR window to this, turning it on where it's off.
  # It also shortens a longer window, deleting AWS's older backups: the last precondition stops that.
  dynamic "operations" {
    for_each = local.is_database ? [1] : []
    content {
      type           = "aws_rds_resource_aws_snapshot"
      action_setting = "immediate"
      slas {
        retention_duration {
          unit  = "days"
          value = var.pitr_retention_days
        }
        rpo_frequency {
          unit  = "days"
          value = 1
        }
      }
      advanced_settings {
        aws_rds_config_sync {
          apply = "maintenance_window" # Turning backups on restarts an RDS instance: wait for its window.
        }
      }
    }
  }

  # Databases, SecureVault Standard: a daily copy in Clumio, outside your account.
  dynamic "operations" {
    for_each = local.is_database ? [1] : []
    content {
      type           = "aws_rds_resource_rolling_backup"
      action_setting = "immediate" # The first copy starts when the rule matches a database.
      slas {
        retention_duration {
          unit  = "days"
          value = var.keep_days
        }
        rpo_frequency {
          unit  = "days"
          value = 1
        }
      }
    }
  }

  # Databases, SecureVault Archive: a monthly long-term copy, made from Standard. Off at 0.
  dynamic "operations" {
    for_each = local.is_database && coalesce(var.archive_months, 0) > 0 ? [1] : []
    content {
      type           = "aws_rds_resource_granular_backup"
      action_setting = "immediate"
      slas {
        retention_duration {
          unit  = "months"
          value = var.archive_months
        }
        rpo_frequency {
          unit  = "months"
          value = 1
        }
      }
      advanced_settings {
        aws_rds_resource_granular_backup {
          backup_tier = "frozen" # Clumio's name for SecureVault Archive
        }
      }
    }
  }

  # EC2: a daily copy of each instance, with its attached EBS volumes.
  dynamic "operations" {
    for_each = local.workload == "ec2" ? [1] : []
    content {
      type           = "aws_ec2_instance_backup"
      action_setting = "immediate"
      slas {
        retention_duration {
          unit  = "days"
          value = var.keep_days
        }
        rpo_frequency {
          unit  = "days"
          value = 1
        }
      }
      advanced_settings {
        aws_ec2_instance_backup {
          backup_tier = "standard" # SecureVault Standard
        }
      }
    }
  }

  # EBS: a daily copy of each volume tagged on its own (clumio-volume-profile).
  dynamic "operations" {
    for_each = local.workload == "ebs" ? [1] : []
    content {
      type           = "aws_ebs_volume_backup"
      action_setting = "immediate"
      slas {
        retention_duration {
          unit  = "days"
          value = var.keep_days
        }
        rpo_frequency {
          unit  = "days"
          value = 1
        }
      }
      advanced_settings {
        aws_ebs_volume_backup {
          backup_tier = "standard" # SecureVault Standard
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.signed_in.account_id == var.account_id
      error_message = "You're signed in to AWS account ${data.aws_caller_identity.signed_in.account_id}, but account_id is ${var.account_id}. Sign in to ${var.account_id}, then plan again."
    }
    precondition {
      condition     = data.aws_region.provider.region == var.region
      error_message = "The AWS provider uses Region ${data.aws_region.provider.region}, but region is ${var.region}. Set the provider's region to ${var.region}."
    }
    precondition {
      condition     = data.clumio_aws_connection.this.id == "${var.account_id}_${var.region}"
      error_message = "Clumio's connection ${data.clumio_aws_connection.this.id} isn't ${var.account_id} in ${var.region}. Connect that account and Region first (1-connect)."
    }
    # Irreversible: a shorter window deletes AWS's older automated backups for good. Stop, unless the
    # person accepts it on purpose.
    precondition {
      condition     = length(local.shorter_pitr) == 0 || var.allow_shorter_pitr
      error_message = "${local.name} would shorten the PITR window of ${join(", ", [for name, days in local.shorter_pitr : "${name} (${days} days now)"])} to ${coalesce(var.pitr_retention_days, 0)} days, and a shorter window deletes AWS's older automated backups for good. Raise pitr_retention_days, or set allow_shorter_pitr = true to accept it."
    }
  }
}

# Where the person placed the rule (rule_before_id). The rule ignores Clumio's own reordering, so it
# would ignore a new rule_before_id too: instead, a change here replaces it, placed anew.
resource "terraform_data" "rule_position" {
  input = var.rule_before_id
}

# The tagged resources of this workload. Clumio applies the first rule that matches, so a rule ranked
# higher can claim them first: status.py names it, and rule_before_id moves this one up.
resource "clumio_policy_rule" "tagged" {
  count          = var.workload == "s3" ? 0 : 1
  name           = local.name
  policy_id      = clumio_policy.this.id
  before_rule_id = var.rule_before_id
  condition      = jsonencode(merge({ entity_type = { "$in" = [lookup(local.entity, var.workload, "")] } }, local.scope))

  lifecycle {
    # Clumio keeps every rule in one chain shared by the whole unit, and rewrites a rule's position
    # whenever anyone adds, moves or removes a rule. The position is a choice made at creation, not
    # a value to hold: without this, every plan would show a change and apply would fight the unit.
    ignore_changes = [before_rule_id]
    # A rule_before_id the person sets later still takes effect: the rule is replaced, placed anew.
    replace_triggered_by = [terraform_data.rule_position]
  }
}

# S3 buckets with the tag, now and later. Glacier storage classes are not backed up.
resource "clumio_protection_group" "s3" {
  count       = var.workload == "s3" ? 1 : 0
  depends_on  = [data.clumio_aws_connection.this] # After the connection is found, as the policy is.
  name        = local.name
  description = "S3 buckets tagged ${local.tag.key} = ${local.tag.value} in ${var.account_id}/${var.region}"
  bucket_rule = jsonencode(local.scope)

  object_filter {
    storage_classes = ["S3 Standard", "S3 Standard-IA", "S3 Intelligent-Tiering", "S3 One Zone-IA"]
  }
}

resource "clumio_policy_assignment" "s3" {
  count       = var.workload == "s3" ? 1 : 0
  entity_id   = clumio_protection_group.s3[0].id
  entity_type = "protection_group"
  policy_id   = clumio_policy.this.id
}

# Production only: Terraform refuses any plan that destroys this, so it refuses removing the policy, a
# switch to trial, or a new account, Region, name or workload. Same pattern as modules/connection.
resource "terraform_data" "production_guard" {
  count            = var.mode == "production" ? 1 : 0
  triggers_replace = [var.account_id, var.region, var.name, var.workload]
  depends_on       = [clumio_policy_rule.tagged, clumio_policy_assignment.s3]

  lifecycle {
    prevent_destroy = true
  }
}
