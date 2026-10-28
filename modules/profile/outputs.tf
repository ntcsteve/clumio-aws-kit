# The profile's Clumio objects, for tools/status.py (policy, group, workloads) and for production
# callers that rank another rule against these (rule IDs).

output "policy_id" {
  description = "The profile's Clumio policy."
  value       = clumio_policy.this.id
}

output "rule_id" {
  description = "The rule that applies the policy to tagged databases and EC2 instances, or null when both are off."
  value       = one(clumio_policy_rule.tagged[*].id)
}

output "volume_rule_id" {
  description = "The rule that applies the policy to volumes tagged clumio-volume-profile, or null when ebs_volumes is off."
  value       = one(clumio_policy_rule.volumes[*].id)
}

output "protection_group_id" {
  description = "The protection group that holds tagged S3 buckets, or null when s3 is off."
  value       = var.s3 ? clumio_protection_group.s3[0].id : null
}

output "workloads" {
  description = "Which workloads this profile protects."
  value       = { s3 = var.s3, databases = var.databases, ec2 = var.ec2, ebs_volumes = var.ebs_volumes }
}
