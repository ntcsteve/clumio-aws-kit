# Step 2: protect S3 buckets

Protects every S3 bucket tagged `clumio-profile = <name>`. They get Backtrack (roll a bucket back in place) and a daily SecureVault copy, outside your account.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, organizational unit and mode from `1-connect`, so they always match; it stops if `1-connect` isn't applied.

## Run it

1. Tag what you want protected: `clumio-profile = gold` (or your profile's name).
2. In this folder, run `cp settings.example terraform.tfvars`, and check its values.
3. From the repository root, run `tools/status.py --preflight`. S3 adds no protection rule: buckets join through a protection group.
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-s3-<account>-<region>`, and a protection group of the tagged buckets, assigned to it. Clumio's rules don't cover S3, so buckets join through the group.

- Backtrack needs S3 Versioning on the bucket.
- Objects in Glacier storage classes aren't backed up.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md). For a second protection level, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-s3-silver
cp README.md settings.example *.tf .terraform.lock.hcl ../2-protect-s3-silver/
```

Then, before you plan there, set `name = "silver"`: two folders with the same name would make the same policy.
