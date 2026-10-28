# The proof lab: small test data, each part encrypted under a key it names, tagged so a profile in
# deploy/ protects it. Its only purpose is to prove claims live: PROOF.md cites what it produced.
# Test accounts only. Databases have no deletion protection and skip their final snapshot: they hold
# no data. Every resource carries kitlab = proof-lab, and every name starts kitlab-<suffix>, so what
# the lab made is never in doubt.

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # A wrong sign-in stops the run before anything is created.
  default_tags {
    tags = { kitlab = "proof-lab" } # Fixed: the suffix comes from a resource, and a provider can't wait for one.
  }
}

data "aws_caller_identity" "signed_in" {}

resource "random_id" "suffix" {
  byte_length = 3 # Names unique in the account and, for buckets, in the world.

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.signed_in.account_id == var.account_id
      error_message = "You're signed in to AWS account ${data.aws_caller_identity.signed_in.account_id}, but account_id is ${var.account_id}. Sign in to the test account."
    }
  }
}

locals {
  name      = "kitlab-${random_id.suffix.hex}"
  tag       = { "clumio-profile" = var.profile }
  has       = { for p in ["s3", "rds-amk", "aurora-amk", "aurora-cmk", "bad-tag", "ec2-amk", "ec2-cmk", "ebs-amk", "ebs-cmk", "ebs-double"] : p => contains(var.parts, p) }
  key       = anytrue([for p in ["s3", "aurora-cmk", "ec2-cmk", "ebs-cmk"] : local.has[p]]) # A customer-managed key costs money and takes 7 days to delete.
  auroras   = { for k in ["amk", "cmk"] : k => k if local.has["aurora-${k}"] }
  instances = { for k in ["amk", "cmk"] : k => k if local.has["ec2-${k}"] }
  volumes   = { for k in ["amk", "cmk", "double"] : k => k if local.has["ebs-${k}"] }
  network   = local.has["rds-amk"] || length(local.auroras) + length(local.instances) + length(local.volumes) > 0
}

# The customer-managed key. Its default key policy lets IAM in this account grant access, as AWS's
# default does, so Clumio's role reaches it through its IAM policy and nothing here names Clumio.
resource "aws_kms_key" "lab" {
  count                   = local.key ? 1 : 0
  description             = "${local.name}: customer-managed key for the Clumio proof lab"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "lab" {
  count         = local.key ? 1 : 0
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.lab[0].key_id
}

# S3: one versioned bucket, one object under aws/s3 and one under the lab key.
resource "aws_s3_bucket" "docs" {
  count         = local.has["s3"] ? 1 : 0
  bucket        = "${local.name}-docs"
  force_destroy = true
  tags          = local.tag
}

resource "aws_s3_bucket_versioning" "docs" {
  count  = local.has["s3"] ? 1 : 0
  bucket = aws_s3_bucket.docs[0].id
  versioning_configuration {
    status = "Enabled" # Backtrack rolls back from the bucket's own versions.
  }
}

resource "aws_s3_object" "doc" {
  for_each               = local.has["s3"] ? { "amk.txt" = null, "cmk.txt" = "cmk" } : {}
  bucket                 = aws_s3_bucket.docs[0].id
  key                    = "documents/${each.key}"
  content                = "Clumio proof lab: ${each.key}\n"
  server_side_encryption = "aws:kms"
  kms_key_id             = each.value == null ? null : aws_kms_key.lab[0].arn # null: S3 uses aws/s3
  depends_on             = [aws_s3_bucket_versioning.docs]
}

# A tag no profile has, on purpose: status must call it BAD_VALUE.
resource "aws_s3_bucket" "bad_tag" {
  count         = local.has["bad-tag"] ? 1 : 0
  bucket        = "${local.name}-bad-tag"
  force_destroy = true
  tags          = { "clumio-profile" = "${var.profile}-typo" }
}

data "aws_vpc" "default" {
  count   = local.network ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = length(data.aws_vpc.default)
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

resource "aws_db_subnet_group" "lab" {
  count      = local.has["rds-amk"] || length(local.auroras) > 0 ? 1 : 0
  name       = local.name
  subnet_ids = data.aws_subnets.default[0].ids
}

# RDS on aws/rds. PITR 7 days: a profile with a shorter window stops the plan in deploy/.
resource "aws_db_instance" "rds_amk" {
  count                       = local.has["rds-amk"] ? 1 : 0
  identifier                  = "${local.name}-rds-amk"
  engine                      = "postgres"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true # No key named: RDS uses aws/rds.
  username                    = "kitlab"
  manage_master_user_password = true # The password lives in Secrets Manager, never in state.
  db_subnet_group_name        = aws_db_subnet_group.lab[0].name
  backup_retention_period     = 7
  skip_final_snapshot         = true
  deletion_protection         = false
  publicly_accessible         = false
  apply_immediately           = true
  tags                        = local.tag
}

# Aurora MySQL: one cluster on aws/rds, one on the lab key, each with one small instance.
resource "aws_rds_cluster" "aurora" {
  for_each                    = local.auroras
  cluster_identifier          = "${local.name}-aurora-${each.key}"
  engine                      = "aurora-mysql"
  storage_encrypted           = true
  kms_key_id                  = each.key == "cmk" ? aws_kms_key.lab[0].arn : null # null: Aurora uses aws/rds
  master_username             = "kitlab"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.lab[0].name
  backup_retention_period     = 7
  skip_final_snapshot         = true
  deletion_protection         = false
  apply_immediately           = true
  tags                        = local.tag
}

# Tagged too: status must count the cluster, never its instance.
resource "aws_rds_cluster_instance" "aurora" {
  for_each            = local.auroras
  identifier          = "${local.name}-aurora-${each.key}-1"
  cluster_identifier  = aws_rds_cluster.aurora[each.key].id
  engine              = aws_rds_cluster.aurora[each.key].engine
  instance_class      = "db.t4g.medium"
  publicly_accessible = false
  apply_immediately   = true
  tags                = local.tag
}

# EC2 and EBS: everything in the default VPC's first subnet, so volumes and instances share a zone.
data "aws_subnet" "first" {
  count = length(local.instances) + length(local.volumes) > 0 ? 1 : 0
  id    = sort(data.aws_subnets.default[0].ids)[0]
}

data "aws_ssm_parameter" "amazon_linux" {
  count = length(local.instances) > 0 ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64" # AWS's own pointer to its latest image.
}

# Two small instances. Their root volumes carry the instance tag, as launch templates often copy it:
# status must count the instance and leave its volume out, because the instance's backup holds it.
resource "aws_instance" "ec2" {
  for_each                    = local.instances
  ami                         = data.aws_ssm_parameter.amazon_linux[0].value
  instance_type               = "t4g.nano"
  subnet_id                   = data.aws_subnet.first[0].id
  associate_public_ip_address = false # Nothing reaches it, and it needs nothing.
  tags                        = merge(local.tag, { Name = "${local.name}-ec2-${each.key}" })

  root_block_device {
    encrypted   = true
    kms_key_id  = each.key == "cmk" ? aws_kms_key.lab[0].arn : null # null: EBS uses aws/ebs
    volume_size = 8
    volume_type = "gp3"
    tags        = local.tag
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only.
  }
}

# Volumes on their own, tagged clumio-volume-profile. The double one is attached to the AMK instance,
# which the profile already protects: status must call it DOUBLE.
resource "aws_ebs_volume" "own" {
  for_each          = local.volumes
  availability_zone = data.aws_subnet.first[0].availability_zone
  size              = 1
  type              = "gp3"
  encrypted         = true
  kms_key_id        = each.key == "cmk" ? aws_kms_key.lab[0].arn : null # null: EBS uses aws/ebs
  tags              = { "clumio-volume-profile" = var.profile, Name = "${local.name}-ebs-${each.key}" }
}

resource "aws_volume_attachment" "double" {
  count       = local.has["ebs-double"] ? 1 : 0
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.own["double"].id
  instance_id = aws_instance.ec2["amk"].id
}
