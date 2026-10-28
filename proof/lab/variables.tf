variable "account_id" {
  description = "A test AWS account. The lab creates billable resources: never point it at production."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set account_id in terraform.tfvars to your test account's 12-digit ID."
  }
}

variable "region" {
  description = "The AWS Region connected in 1-connect/, such as us-west-2."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-[0-9]$", var.region))
    error_message = "Set region in terraform.tfvars to the Region connected in 1-connect/, such as us-west-2."
  }
}

variable "profile" {
  description = "The name set in the 2-protect- folders that should protect the lab: every part is tagged clumio-profile = <profile>."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,29}$", var.profile))
    error_message = "Set profile in terraform.tfvars to the name set in the 2-protect- folders, such as \"gold\"."
  }
}

variable "parts" {
  description = "What to build. s3: a versioned bucket with an aws/s3 object and a lab-key object. rds-amk: RDS Postgres on aws/rds. aurora-amk and aurora-cmk: Aurora MySQL on aws/rds, and on the lab key. bad-tag: a bucket whose tag names no profile. ec2-amk and ec2-cmk: small instances whose root volumes use aws/ebs, and the lab key. ebs-amk and ebs-cmk: unattached volumes, tagged on their own. ebs-double: a volume tagged on its own, attached to the ec2-amk instance."
  type        = list(string)

  validation {
    condition     = length(var.parts) > 0 && alltrue([for p in var.parts : contains(["s3", "rds-amk", "aurora-amk", "aurora-cmk", "bad-tag", "ec2-amk", "ec2-cmk", "ebs-amk", "ebs-cmk", "ebs-double"], p)])
    error_message = "parts must be one or more of \"s3\", \"rds-amk\", \"aurora-amk\", \"aurora-cmk\", \"bad-tag\", \"ec2-amk\", \"ec2-cmk\", \"ebs-amk\", \"ebs-cmk\", \"ebs-double\"."
  }

  validation {
    condition     = !contains(var.parts, "ebs-double") || contains(var.parts, "ec2-amk")
    error_message = "ebs-double attaches its volume to the ec2-amk instance: list ec2-amk too."
  }
}
