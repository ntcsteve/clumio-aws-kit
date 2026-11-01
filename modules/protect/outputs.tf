# This workload's Clumio objects. tools/status.py finds them by name in Clumio; a production caller may
# use the rule's ID to rank another rule against it.

output "policy_id" {
  description = "This workload's Clumio policy."
  value       = clumio_policy.this.id
}

output "rule_id" {
  description = "The rule that applies the policy to the tagged resources, or null for S3, which has none."
  value       = one(clumio_policy_rule.tagged[*].id)
}

output "protection_group_id" {
  description = "The protection group that holds the tagged S3 buckets, or null for other workloads."
  value       = one(clumio_protection_group.s3[*].id)
}

# The PITR guard passes when nothing is tagged, so show what it read: a plan that checked nothing must
# not look like a plan that checked everything.
output "pitr_checked" {
  description = "Each tagged database this plan checked, with its PITR window today, in days. Empty means nothing is tagged, so nothing was checked."
  value       = local.pitr_now
}
