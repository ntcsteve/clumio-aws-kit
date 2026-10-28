# Your settings live in terraform.tfvars, copied from settings.example. preview/preview.sh and
# status.py read that file too. The four settings below are checked here, before the providers
# use them; the rest are checked in the modules.

variable "account_id" {
  description = "The AWS account to connect. The plan stops when you're signed in to any other account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set account_id in terraform.tfvars to your 12-digit AWS account ID."
  }
}

variable "region" {
  description = "The AWS Region your data is in, such as us-west-2."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-[0-9]$", var.region))
    error_message = "Set region in terraform.tfvars to your AWS Region, such as us-west-2."
  }
}

variable "organizational_unit" {
  description = "The Clumio organizational unit to work in: \"global\", or a unit's ID. make preflight lists them."
  type        = string

  validation {
    condition     = var.organizational_unit == "global" || can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.organizational_unit))
    error_message = "Set organizational_unit in terraform.tfvars to \"global\" or a unit's ID. Run make preflight to list them."
  }
}

variable "mode" {
  description = "\"trial\": can be torn down. \"production\": refuses destroy, and refuses a switch back to trial."
  type        = string

  validation {
    condition     = contains(["trial", "production"], var.mode)
    error_message = "Set mode in terraform.tfvars to \"trial\" (can be torn down; also for a proof of concept) or \"production\" (refuses destroy)."
  }
}

variable "profiles" {
  description = "Protection profiles, by name. Resources tagged clumio-profile = <name> get that profile's protection. Checked in modules/profile."
  type = map(object({
    s3                  = bool                 # S3 buckets: Backtrack, and a daily SecureVault copy
    databases           = bool                 # RDS and Aurora: AWS PITR, a daily SecureVault copy, a monthly archive
    keep_days           = number               # daily SecureVault copies, in days; 30 or more when s3 is on
    archive_months      = optional(number, 12) # monthly database archive, in months; 0 turns it off
    backtrack_months    = optional(number, 3)  # how far back Backtrack can roll a bucket, in months
    pitr_retention_days = optional(number)     # required with databases: Clumio sets this PITR window on every database
  }))

  # Checked here too, so the shipped placeholder stops the plan before the providers are even set up.
  validation {
    condition     = alltrue([for profile in values(var.profiles) : !profile.databases || profile.pitr_retention_days != null])
    error_message = "Set pitr_retention_days in terraform.tfvars, 1 to 35 days, for every profile with databases = true. Clumio sets that PITR window on each of its databases, longer or shorter than today."
  }
}

variable "report_emails" {
  description = "Who gets Clumio's daily compliance report for this Region. Empty means no report."
  type        = list(string)
  default     = []
}

variable "iam_prefix" {
  description = "The start of every IAM role and policy name Clumio creates. Empty means Clumio's default names."
  type        = string
  default     = ""
}

variable "iam_path" {
  description = "The IAM path for Clumio's roles and policies. \"/clumio/\" is Clumio's default, and \"/\" means no path."
  type        = string
  default     = "/clumio/"
}

variable "workloads" {
  description = "What Clumio may protect: \"s3\", \"rds\" (RDS and Aurora), \"ebs\" (EC2 and EBS). All by default."
  type        = list(string)
  default     = ["s3", "rds", "ebs"]
}

variable "role_tags" {
  description = "Tags your organization requires on IAM roles. Added to Clumio's own tag (Vendor = Clumio)."
  type        = map(string)
  default     = {}
}

variable "permissions_boundary_arn" {
  description = "The permissions boundary your organization requires on IAM roles, or empty for none."
  type        = string
  default     = ""
}

variable "pass_role_deny_list" {
  description = "Roles Clumio must never pass to a service, by ARN. Adds a policy that denies it."
  type        = list(string)
  default     = []
}
