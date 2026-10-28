output "lab" {
  description = "What the lab built, for the run sheet and the evidence captures."
  value = {
    suffix  = random_id.suffix.hex
    bucket  = one(aws_s3_bucket.docs[*].id)
    bad_tag = one(aws_s3_bucket.bad_tag[*].id)
    rds_amk = one(aws_db_instance.rds_amk[*].identifier)
    auroras = { for k, c in aws_rds_cluster.aurora : k => c.cluster_identifier }
    lab_key = one(aws_kms_key.lab[*].arn)
  }
}
