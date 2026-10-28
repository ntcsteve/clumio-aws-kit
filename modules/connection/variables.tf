variable "account_id" {
  description = "The AWS account to connect. The plan stops when you're signed in to any other account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set account_id to your 12-digit AWS account ID."
  }
}

variable "region" {
  description = "The AWS Region your data is in, such as us-west-2."
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

variable "report_emails" {
  description = "Who gets Clumio's daily compliance report for this Region: whether every asset has a backup each day. Empty means no report."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.report_emails : can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", e))])
    error_message = "report_emails must be email addresses, such as platform-oncall@example.com."
  }
}

# Clumio's IAM settings. Checked in ./iam, which 0-check/preview calls too.

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
  description = "What Clumio may protect, by 2-protect folder: \"s3\", \"rds\", \"aurora\", \"ec2\", \"ebs\". All by default."
  type        = list(string)
  default     = ["s3", "rds", "aurora", "ec2", "ebs"]
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
