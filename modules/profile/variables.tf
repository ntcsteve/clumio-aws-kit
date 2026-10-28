variable "name" {
  description = "The profile's name, such as \"gold\". Resources tagged clumio-profile = <name> are protected by it."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,29}$", var.name))
    error_message = "A profile name is 1 to 30 lowercase letters, digits or dashes, such as \"gold\". It becomes the tag value clumio-profile = <name>."
  }
}

variable "connection_id" {
  description = "The Clumio connection this profile protects: modules/connection's connection_id output, or \"<account_id>_<region>\" when the connection lives in another state."
  type        = string
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

variable "s3" {
  description = "Protect S3 buckets tagged with this profile: Backtrack, and a daily SecureVault copy."
  type        = bool
}

variable "databases" {
  description = "Protect RDS instances and Aurora clusters tagged with this profile: AWS PITR, a daily SecureVault copy, and a monthly archive."
  type        = bool
}

variable "ec2" {
  description = "Protect EC2 instances tagged with this profile: a daily SecureVault copy of each instance and its attached volumes."
  type        = bool
  default     = false
}

variable "ebs_volumes" {
  description = "Protect EBS volumes tagged clumio-volume-profile = <name>: a daily SecureVault copy of each volume on its own. A volume attached to a protected instance is already in that instance's copy."
  type        = bool
  default     = false

  # Checked on the last workload, so every workload setting is known.
  validation {
    condition     = var.s3 || var.databases || var.ec2 || var.ebs_volumes
    error_message = "Turn on at least one workload in this profile: s3, databases, ec2 or ebs_volumes."
  }
}

variable "keep_days" {
  description = "How long each daily SecureVault copy is kept, in days."
  type        = number

  validation {
    condition     = var.keep_days >= 1 && floor(var.keep_days) == var.keep_days && (!var.s3 || var.keep_days >= 30)
    error_message = "keep_days must be a whole number of days, and at least 30 when s3 is on: Clumio keeps S3 copies 30 days or more."
  }
}

variable "archive_months" {
  description = "How long each monthly archive copy of a database is kept, in months. 0 turns the archive off. Under 12 incurs Clumio's early-deletion fee. No default: a copy kept a year bills for a year, even after a trial ends."
  type        = number

  validation {
    condition     = var.archive_months >= 0 && floor(var.archive_months) == var.archive_months
    error_message = "archive_months must be a whole number of months: 0 turns the archive off."
  }
}

variable "backtrack_months" {
  description = "How far back Backtrack can roll an S3 bucket, in months."
  type        = number
  default     = 3

  validation {
    condition     = var.backtrack_months >= 1 && floor(var.backtrack_months) == var.backtrack_months
    error_message = "backtrack_months must be a whole number of months, at least 1."
  }
}

variable "pitr_retention_days" {
  description = "The AWS PITR window Clumio sets on every database with this profile, in days. It turns PITR on where it's off, and sets it up or down: a shorter window deletes AWS's older automated backups for good. Required when databases is on: there's no safe default."
  type        = number
  default     = null

  validation {
    condition     = !var.databases || (var.pitr_retention_days != null ? var.pitr_retention_days >= 1 && var.pitr_retention_days <= 35 && floor(var.pitr_retention_days) == var.pitr_retention_days : false)
    error_message = "Set pitr_retention_days to 1 to 35 days. Clumio sets this PITR window on every database with this profile, longer or shorter than today, so check their current window first."
  }
}

variable "allow_shorter_pitr" {
  description = "Accept a plan that shortens a database's PITR window. A shorter window deletes AWS's older automated backups for good, so the plan stops on it unless this is true."
  type        = bool
  default     = false
}

variable "rule_before_id" {
  description = "Place this profile's rule ahead of an existing rule, by its ID, when that rule would otherwise claim these databases. Empty puts it last."
  type        = string
  default     = ""
}
