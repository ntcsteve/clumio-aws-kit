output "connection_id" {
  description = "The Clumio connection, for modules/profile. It's known once Clumio's IAM exists, so protection waits for it."
  value       = clumio_aws_connection.this.id
  depends_on  = [module.iam]
}

output "account_id" {
  description = "The connected AWS account."
  value       = clumio_aws_connection.this.account_native_id
}

output "region" {
  description = "The connected AWS Region."
  value       = clumio_aws_connection.this.aws_region
}

output "organizational_unit_id" {
  description = "The Clumio organizational unit the connection belongs to."
  value       = clumio_aws_connection.this.organizational_unit_id
}
