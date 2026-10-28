# Where these captures come from

Copied unchanged from the public repository [get-started-clumio-byok](https://github.com/ntcsteve/get-started-clumio-byok), release v1.0.0, commit `4a6dc5d`, on 2026-10-28. Each capture folder still matches its `_sha256.txt`.

They record a lab run on 2026-10-25 to 2026-10-27: Clumio backing up and restoring S3, RDS and EC2 data under AWS-managed keys (`aws/s3`, `aws/rds`, `aws/ebs`) and customer-managed keys. Key behavior belongs to Clumio and AWS, not to this kit's code, so these captures still answer the keys question.

`INDEX.md` and `PROVENANCE.txt` are part of the copy. Paths they mention, such as `../docs/PROOF.md` or `../scripts/`, refer to that repository, where the Terraform and scripts that made these captures live.
