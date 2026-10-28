# Proof

Every claim in this repository traces to a capture here: what AWS and Clumio answered, saved as raw JSON, masked, with a checksum manifest.

## Check the evidence

No AWS account is needed:

```bash
proof/verify-evidence.sh
```

It checks every capture against its `_sha256.txt` and ends with `RESULT: OK`. It also prints a root hash of all manifests: keep it somewhere outside this repository, and compare it later to see whether any manifest changed.

`evidence/keys-lab-2026-10/` holds the captures from an earlier lab run, copied unchanged from [get-started-clumio-byok](https://github.com/ntcsteve/get-started-clumio-byok). Its `SOURCE.md` says where they come from.

## The lab

`lab/` builds small test data for a profile in `deploy/` to protect: an S3 bucket with an object under `aws/s3` and one under a customer-managed key, RDS on `aws/rds`, Aurora on `aws/rds` and on the customer-managed key, EC2 instances and volumes on `aws/ebs` and on the key, a bucket with a bad tag, and a volume tagged to show DOUBLE in `tools/status.py`. Each part is built only when listed in `parts`.

**A test account only.** It bills while it runs, about $5 a day with every part. Clumio's copies stay until their retention ends. The customer-managed key waits 7 days before AWS deletes it.

1. Connect the account and Region with `deploy/`, with a profile that protects every workload you list.
2. In `proof/lab`, run `cp settings.example terraform.tfvars`, and set the test account, the Region and the profile.
3. `terraform init`, `terraform plan -out=tfplan`, read the plan, `terraform apply tfplan`.
4. When `tools/status.py` shows the lab protected, save the evidence: `python3 proof/capture.py <set> <capture name>`.
5. Take it down: `deploy/` as [Take a trial down](../docs/operate.md#take-a-trial-down) says; then in `proof/lab`, `terraform plan -destroy -out=tfplan` and `terraform apply tfplan`.

## The tools

| Tool | What it does |
|---|---|
| `verify-evidence.sh` | Checks every capture against its checksums. Read-only and offline |
| `capture.py` | Saves what AWS and Clumio say about each lab resource's key, protection and backups. Read-only. Masks the account and the organizational unit |
| `../tools/tests/record_fixtures.py` | Saves the real answers `status.py` reads, as fixtures for its contract tests |
