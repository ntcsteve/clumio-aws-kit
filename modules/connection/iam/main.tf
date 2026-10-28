# Clumio's IAM in one connected account and Region, from Clumio's published template.

locals {
  # Clumio's template has three IAM switches; the kit names workloads by 2-protect folder.
  is_s3  = contains(var.workloads, "s3")
  is_rds = contains(var.workloads, "rds") || contains(var.workloads, "aurora") # DB instances and DB clusters
  is_ebs = contains(var.workloads, "ec2") || contains(var.workloads, "ebs")    # EC2 instances and EBS volumes
}
# Two callers: modules/connection, with the real connection, and 0-check/preview, with stand-ins, so
# what the security team previews is exactly what the connection creates.

module "aws_template" {
  source  = "clumio-code/aws-template/clumio"
  version = "0.42.0" # An exact version, so the preview shows exactly what this creates.

  clumio_token          = var.connection.token
  role_external_id      = var.connection.role_external_id
  aws_account_id        = var.connection.account_native_id
  aws_region            = var.connection.aws_region
  clumio_aws_account_id = var.connection.clumio_aws_account_id
  data_plane_account_id = var.connection.data_plane_account_id # Limits S3 backup copies to Clumio's own account.

  iam_entities_identifier = var.iam_prefix
  path                    = var.iam_path
  is_s3_enabled           = local.is_s3
  is_rds_enabled          = local.is_rds
  is_ebs_enabled          = local.is_ebs

  # Optional organization IAM rules. Clumio's own role tag is always kept.
  clumio_iam_role_tags       = merge({ Vendor = "Clumio" }, var.role_tags)
  permissions_boundary_arn   = var.permissions_boundary_arn
  clumio_pass_role_deny_list = var.pass_role_deny_list
}
