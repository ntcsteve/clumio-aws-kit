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

variable "rule_before_id" {
  description = "Place this policy's rule ahead of another rule, by its ID, when tools/status.py says that rule claimed these resources first."
  type        = string
  default     = ""
}
