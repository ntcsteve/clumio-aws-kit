variable "connection" {
  description = "The clumio_aws_connection this IAM serves: the resource itself, or the preview's stand-ins."
  type = object({
    token                 = string
    role_external_id      = string
    account_native_id     = string
    aws_region            = string
    clumio_aws_account_id = string
    data_plane_account_id = string
  })
}

variable "iam_prefix" {
  description = "The start of every IAM role and policy name Clumio creates. Empty means Clumio's default names."
  type        = string
  default     = ""

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{0,36}$", var.iam_prefix))
    error_message = "iam_prefix must be at most 36 characters: letters, digits and + = , . @ _ - only."
  }
}

variable "iam_path" {
  description = "The IAM path for Clumio's roles and policies. \"/clumio/\" is Clumio's default, and \"/\" means no path."
  type        = string
  default     = "/clumio/"

  validation {
    condition     = can(regex("^/([A-Za-z0-9+=,.@_-]+/)*$", var.iam_path))
    error_message = "iam_path must start and end with / (such as / or /clumio/)."
  }
}

variable "workloads" {
  description = "What Clumio may protect, by 2-protect folder: \"s3\", \"rds\", \"aurora\", \"ec2\", \"ebs\". All by default."
  type        = list(string)
  default     = ["s3", "rds", "aurora", "ec2", "ebs"]

  validation {
    condition     = length(var.workloads) > 0 && alltrue([for w in var.workloads : contains(["s3", "rds", "aurora", "ec2", "ebs"], w)])
    error_message = "workloads must be one or more of \"s3\", \"rds\", \"aurora\", \"ec2\", \"ebs\"."
  }
}

variable "role_tags" {
  description = "Tags your organization requires on IAM roles. Added to Clumio's own tag (Vendor = Clumio)."
  type        = map(string)
  default     = {}
}

variable "permissions_boundary_arn" {
  description = "The permissions boundary your organization requires on IAM roles, or empty for none. It must allow what Clumio's policies grant, or backups fail."
  type        = string
  default     = ""

  validation {
    condition     = var.permissions_boundary_arn == "" || can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:policy/", var.permissions_boundary_arn))
    error_message = "permissions_boundary_arn must be a managed policy ARN (arn:aws:iam::<account>:policy/...) or \"\"."
  }
}

variable "pass_role_deny_list" {
  description = "Roles Clumio must never pass to a service, by ARN. Adds a policy that denies it."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for r in var.pass_role_deny_list : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/", r))])
    error_message = "pass_role_deny_list must hold role ARNs only (arn:aws:iam::<account>:role/...)."
  }
}
