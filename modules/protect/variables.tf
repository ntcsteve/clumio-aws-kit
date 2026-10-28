variable "workload" {
  description = "What this call protects, with its own Clumio policy: \"s3\", \"rds\" (DB instances), \"aurora\" (DB clusters), \"ec2\" (instances, with their attached volumes) or \"ebs\" (volumes on their own)."
  type        = string

  validation {
    condition     = contains(["s3", "rds", "aurora", "ec2", "ebs"], var.workload)
    error_message = "workload must be \"s3\", \"rds\", \"aurora\", \"ec2\" or \"ebs\"."
  }
}

variable "name" {
  description = "The profile's name, such as \"gold\". Resources tagged clumio-profile = <name> (EBS: clumio-volume-profile) get this protection."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,29}$", var.name))
    error_message = "A profile name is 1 to 30 lowercase letters, digits or dashes, such as \"gold\". It becomes the tag value clumio-profile = <name>."
  }
}

variable "account_id" {
  description = "The connected AWS account. The plan stops when you're signed in to any other account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set account_id to your 12-digit AWS account ID."
  }
}

variable "region" {
  description = "The connected AWS Region."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-[0-9]$", var.region))
    error_message = "Set region to your AWS Region, such as us-west-2."
  }
}

variable "mode" {
  description = "\"trial\": can be torn down. \"production\": refuses destroy, and refuses a switch back to trial."
  type        = string

  validation {
    condition     = contains(["trial", "production"], var.mode)
    error_message = "Set mode to \"trial\" (can be torn down; also for a proof of concept) or \"production\" (refuses destroy)."
  }
}

variable "keep_days" {
  description = "How long each daily SecureVault copy is kept, in days."
  type        = number

  validation {
    condition     = var.keep_days >= 1 && floor(var.keep_days) == var.keep_days && (var.workload != "s3" || var.keep_days >= 30)
    error_message = "keep_days must be a whole number of days, and at least 30 for S3: Clumio keeps S3 copies 30 days or more."
  }
}

variable "backtrack_months" {
  description = "S3 only: how far back Backtrack can roll a bucket, in months."
  type        = number
  default     = 3

  validation {
    condition     = var.backtrack_months >= 1 && floor(var.backtrack_months) == var.backtrack_months
    error_message = "backtrack_months must be a whole number of months, at least 1."
  }
}

variable "archive_months" {
  description = "RDS and Aurora: how long each monthly archive copy is kept, in months. 0 turns the archive off. Under 12 incurs Clumio's early-deletion fee. No default: a copy kept a year bills for a year, even after a trial ends."
  type        = number
  default     = null

  validation {
    condition     = !contains(["rds", "aurora"], var.workload) || (var.archive_months != null ? var.archive_months >= 0 && floor(var.archive_months) == var.archive_months : false)
    error_message = "Set archive_months in terraform.tfvars: 0 for a trial (no archive), or the months your retention rule needs. Each archive copy bills until its retention ends, even after a trial."
  }
}

variable "pitr_retention_days" {
  description = "RDS and Aurora: the AWS PITR window Clumio sets on every tagged database, in days. It turns PITR on where it's off, and sets it up or down: a shorter window deletes AWS's older automated backups for good. No safe default."
  type        = number
  default     = null

  validation {
    condition     = !contains(["rds", "aurora"], var.workload) || (var.pitr_retention_days != null ? var.pitr_retention_days >= 1 && var.pitr_retention_days <= 35 && floor(var.pitr_retention_days) == var.pitr_retention_days : false)
    error_message = "Set pitr_retention_days in terraform.tfvars to 1 to 35 days. Clumio sets this PITR window on every tagged database, longer or shorter than today, so check their current window first."
  }
}

variable "allow_shorter_pitr" {
  description = "RDS and Aurora: accept a plan that shortens a database's PITR window. A shorter window deletes AWS's older automated backups for good, so the plan stops on it unless this is true."
  type        = bool
  default     = false
}

variable "rule_before_id" {
  description = "Place this policy's rule ahead of an existing rule, by its ID, when that rule would otherwise claim these resources. Empty puts it last. Not used for S3, which has no rule."
  type        = string
  default     = ""
}

variable "connection_workloads" {
  description = "The workloads the connection's IAM covers (1-connect's workloads), to check this one is among them. Null skips the check."
  type        = list(string)
  default     = null

  validation {
    condition     = var.connection_workloads == null || contains(coalesce(var.connection_workloads, []), var.workload)
    error_message = "The connection's workloads leave out \"${var.workload}\", so Clumio has no IAM to find these resources. Add \"${var.workload}\" to workloads in 1-connect/terraform.tfvars, then plan and apply 1-connect (0-check/preview/preview.sh shows the new IAM)."
  }
}
