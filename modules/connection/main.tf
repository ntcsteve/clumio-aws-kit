# Connects one AWS account and Region to Clumio: the connection, Clumio's IAM, and an optional daily
# compliance report. Every guard lives here, so a production repo that calls this module directly
# gets the same checks as deploy/.
# The caller configures both providers. The Clumio provider's organizational unit decides which
# unit the connection, and so the account's resources, belong to.

data "aws_caller_identity" "signed_in" {}
data "aws_region" "provider" {}

resource "clumio_aws_connection" "this" {
  account_native_id = var.account_id
  aws_region        = var.region
  description       = "Connected by Terraform (clumio-aws-kit)"

  lifecycle {
    # Clumio's IAM is created with the caller's AWS provider. Wrong account or Region there, and the
    # roles land where Clumio will never look, or in another team's account.
    precondition {
      condition     = data.aws_caller_identity.signed_in.account_id == var.account_id
      error_message = "You're signed in to AWS account ${data.aws_caller_identity.signed_in.account_id}, but account_id is ${var.account_id}. Sign in to ${var.account_id}, then plan again."
    }
    precondition {
      condition     = data.aws_region.provider.region == var.region
      error_message = "The AWS provider uses Region ${data.aws_region.provider.region}, but region is ${var.region}. Set the provider's region to ${var.region}."
    }
  }
}

module "iam" {
  source     = "./iam"
  connection = clumio_aws_connection.this

  iam_prefix               = var.iam_prefix
  iam_path                 = var.iam_path
  workloads                = var.workloads
  role_tags                = var.role_tags
  permissions_boundary_arn = var.permissions_boundary_arn
  pass_role_deny_list      = var.pass_role_deny_list
}

# Production only. Terraform refuses any plan that destroys this, so in production it refuses
# `terraform destroy`, a switch to trial (count goes to 0), and a new account or Region (replace).
# A literal prevent_destroy on the connection couldn't tell trial from production.
resource "terraform_data" "production_guard" {
  count            = var.mode == "production" ? 1 : 0
  triggers_replace = [var.account_id, var.region]
  depends_on       = [module.iam]

  lifecycle {
    prevent_destroy = true
  }
}

# Backups that fail quietly are found during an incident. This report says, by email, whether every
# asset in this Region has a backup each day, kept at least 7 days.
resource "clumio_report_configuration" "daily_backups" {
  count       = length(var.report_emails) > 0 ? 1 : 0
  name        = "daily-backups-${var.account_id}-${var.region}"
  description = "Every asset in ${var.account_id}/${var.region} has a backup each day, kept at least 7 days."

  notification {
    email_list = var.report_emails
  }

  parameter {
    controls {
      asset_backup {
        look_back_period {
          unit  = "days"
          value = 1
        }
        window_size {
          unit  = "days"
          value = 1
        }
        minimum_retention_duration {
          unit  = "days"
          value = 7
        }
      }
    }
    filters {
      asset {
        groups {
          type   = "aws"
          region = var.region
        }
      }
    }
  }
}
