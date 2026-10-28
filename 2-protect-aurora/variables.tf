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

variable "archive_months" {
  description = "How long each monthly archive copy is kept, in months. 0 turns the archive off. No default: each copy bills until it expires."
  type        = number
}

variable "pitr_retention_days" {
  description = "The AWS PITR window Clumio sets on every tagged database, in days (1 to 35)."
  type        = number
}

variable "allow_shorter_pitr" {
  description = "Accept a plan that shortens a database's PITR window, which deletes AWS's older automated backups for good."
  type        = bool
  default     = false
}

variable "rule_before_id" {
  description = "Place this policy's rule ahead of another rule, by its ID, when tools/status.py says that rule claimed these resources first."
  type        = string
  default     = ""
}
