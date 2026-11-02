# Your settings live in terraform.tfvars, copied from settings.example. The account, Region, unit and
# mode aren't settings here: they come from 1-connect (main.tf), so they always match. Each value is
# checked in modules/protect.

variable "name" {
  description = "The profile: resources tagged clumio-profile = <name> get this protection."
  type        = string
}

variable "keep_days" {
  description = "How long each daily SecureVault copy is kept, in days."
  type        = number
}

variable "backtrack_months" {
  description = "How far back Backtrack can roll a bucket, in months."
  type        = number
  default     = 3
}

# Where 1-connect's state is. Local for a trial. tools/use_s3_state.py sets both for production.
variable "connect_backend" {
  description = "The Terraform backend that holds 1-connect's state."
  type        = string
  default     = "local"
}

variable "connect_config" {
  description = "That backend's settings. The default is relative to the folder Terraform runs in."
  type        = any
  default     = { path = "../1-connect/terraform.tfstate" }
}
