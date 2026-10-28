# One protection profile: one Clumio policy, applied to every resource tagged clumio-profile = <name>
# in one account and Region. Databases and EC2 instances join through a rule; S3 buckets through a
# protection group, because Clumio's rules don't cover S3; volumes on their own through a second rule. Every guard lives here, so production repos that call this
# module directly get the same checks as setup/.
# The caller configures both providers; the Clumio provider's organizational unit holds these objects.

data "aws_caller_identity" "signed_in" {}
data "aws_region" "provider" {}

# The connection this profile protects. Without one, the plan stops here: "AWS connection not found".
# A caller that creates the connection in the same apply passes depends_on, so this read waits for it.
data "clumio_aws_connection" "this" {
  account_native_id = var.account_id
  aws_region        = var.region
}

locals {
  tag        = { key = "clumio-profile", value = var.name }
  volume_tag = { key = "clumio-volume-profile", value = var.name } # Its own key: see the volumes rule below.
  name       = "${var.name}-${var.account_id}-${var.region}"       # Unique in the tenant: one profile per account and Region.
  # A tag alone matches across the whole tenant, so every selection is scoped to this account and Region.
  scope = {
    aws_tag               = { "$eq" = local.tag }
    aws_account_native_id = { "$eq" = var.account_id }
    aws_region            = { "$eq" = var.region }
  }
  # What the profile's tag rule matches: databases and EC2 instances. S3 joins by protection group.
  rule_entities = concat(var.databases ? ["aws_rds_instance", "aws_rds_cluster"] : [], var.ec2 ? ["aws_ec2_instance"] : [])
}

resource "clumio_policy" "this" {
  name = local.name

  # S3, Backtrack: rolls a bucket back in place from its own versions. Needs S3 Versioning.
  dynamic "operations" {
    for_each = var.s3 ? [1] : []
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
    for_each = var.s3 ? [1] : []
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
  # It also shortens a longer window, deleting AWS's older backups: setup's make plan stops on that.
  dynamic "operations" {
    for_each = var.databases ? [1] : []
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
    for_each = var.databases ? [1] : []
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
    for_each = var.databases && var.archive_months > 0 ? [1] : []
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
    for_each = var.ec2 ? [1] : []
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

  # EBS: a daily copy of each volume tagged on its own.
  dynamic "operations" {
    for_each = var.ebs_volumes ? [1] : []
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
      error_message = "Clumio's connection ${data.clumio_aws_connection.this.id} isn't ${var.account_id} in ${var.region}. Connect that account and Region first (modules/connection)."
    }
  }
}

# Databases and EC2 instances with the tag. Clumio applies the first rule that matches, so a rule
# ranked higher can claim them first: status.py names it, and rule_before_id moves this one up.
resource "clumio_policy_rule" "tagged" {
  count          = length(local.rule_entities) > 0 ? 1 : 0
  name           = local.name
  policy_id      = clumio_policy.this.id
  before_rule_id = var.rule_before_id
  condition      = jsonencode(merge({ entity_type = { "$in" = local.rule_entities } }, local.scope))

  lifecycle {
    # Clumio keeps every rule in one chain shared by the whole unit, and rewrites a rule's position
    # whenever anyone adds, moves or removes a rule. The position is a choice made at creation, not
    # a value to hold: without this, every plan would show a change and apply would fight the unit.
    ignore_changes = [before_rule_id]
  }
}

# Volumes on their own, by their own tag key. An EC2 backup already holds its attached volumes, so a
# volume joins only when someone tags it clumio-volume-profile on purpose: status.py calls a tagged
# volume on a protected instance DOUBLE.
resource "clumio_policy_rule" "volumes" {
  count          = var.ebs_volumes ? 1 : 0
  name           = "${local.name}-volumes"
  policy_id      = clumio_policy.this.id
  before_rule_id = var.rule_before_id
  condition = jsonencode({
    entity_type           = { "$in" = ["aws_ebs_volume"] }
    aws_tag               = { "$eq" = local.volume_tag }
    aws_account_native_id = { "$eq" = var.account_id }
    aws_region            = { "$eq" = var.region }
  })

  lifecycle {
    ignore_changes = [before_rule_id] # As for the tag rule above: Clumio rewrites positions.
  }
}

# S3 buckets with the tag, now and later. Glacier storage classes are not backed up.
resource "clumio_protection_group" "s3" {
  count       = var.s3 ? 1 : 0
  name        = local.name
  description = "S3 buckets tagged ${local.tag.key} = ${local.tag.value} in ${var.account_id}/${var.region}"
  bucket_rule = jsonencode(local.scope)

  object_filter {
    storage_classes = ["S3 Standard", "S3 Standard-IA", "S3 Intelligent-Tiering", "S3 One Zone-IA"]
  }
}

resource "clumio_policy_assignment" "s3" {
  count       = var.s3 ? 1 : 0
  entity_id   = clumio_protection_group.s3[0].id
  entity_type = "protection_group"
  policy_id   = clumio_policy.this.id
}

# Production only: Terraform refuses any plan that destroys this, so it refuses removing the profile,
# a switch to trial, or a new account or Region. Same pattern as modules/connection.
resource "terraform_data" "production_guard" {
  count            = var.mode == "production" ? 1 : 0
  triggers_replace = [var.account_id, var.region, var.name]
  depends_on       = [clumio_policy_rule.tagged, clumio_policy_rule.volumes, clumio_policy_assignment.s3]

  lifecycle {
    prevent_destroy = true
  }
}
