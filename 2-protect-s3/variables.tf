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
