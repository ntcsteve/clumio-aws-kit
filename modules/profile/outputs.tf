# What status.py reads to tell this profile's protection from anyone else's.

output "tag" {
  description = "The tag that puts a resource in this profile."
  value       = local.tag
}

output "policy_id" {
  description = "The profile's Clumio policy."
  value       = clumio_policy.this.id
}

output "rule_id" {
  description = "The rule that applies the policy to tagged RDS and Aurora, or null when databases is off."
  value       = var.databases ? clumio_policy_rule.databases[0].id : null
}

output "protection_group_id" {
  description = "The protection group that holds tagged S3 buckets, or null when s3 is off."
  value       = var.s3 ? clumio_protection_group.s3[0].id : null
}

output "workloads" {
  description = "Which workloads this profile protects."
  value       = { s3 = var.s3, databases = var.databases }
}
