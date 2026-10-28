# Steps 1 and 2: Connect, then protect

One folder, one settings file (`terraform.tfvars`), one Terraform state. Step 1 connects your account and Region to Clumio. Step 2 adds protection. Run every command here, in `deploy/`, in the shell where you exported `CLUMIO_API_BASE_URL` and `CLUMIO_API_TOKEN` in step 0.

Each step is the same three commands. The plan you read is the plan that runs:

```bash
terraform init
terraform plan -out=tfplan     # read it
terraform apply tfplan
```

## Step 1: Connect

Do [step 0](../0-check/README.md) first: it makes `terraform.tfvars` and checks it.

Leave `profiles = {}` as it is. To get Clumio's daily compliance report by email, set `report_emails` (not yet proven live). Then run the three commands.

The plan creates the connection and Clumio's IAM roles and policies: the ones step 0 showed. With `report_emails`, it adds the report; with `mode = "production"`, a guard that refuses destroy. Nothing is protected yet.

## Step 2: Protect

First, tag what you want protected. Tag before you plan: the plan checks each tagged database's PITR window, and a database tagged later skips that check.

| What | Tag |
|---|---|
| S3 bucket, RDS instance, Aurora cluster, EC2 instance | `clumio-profile = gold` |
| An EBS volume on its own (with `ebs_volumes = true`) | `clumio-volume-profile = gold` |

An EC2 instance's backup already holds its attached volumes: tag the instance, not its volumes.

Then, in `terraform.tfvars`, delete the line `profiles = {}`, and remove the `# ` from the start of each line of the example below it. Set the two values marked REPLACE:

- `archive_months`: 0 for a trial. Each archive copy bills until it expires, even after a trial ends.
- `pitr_retention_days`: the AWS point-in-time recovery window Clumio sets on every database with this profile, 1 to 35 days. It turns PITR on where it's off.

A profile is a named protection level, such as `gold`, and becomes one Clumio policy. Each workload in it is on or off. Add more profiles beside `gold` if you need more levels.

Run `terraform plan -out=tfplan`. If a tagged database's PITR window would get shorter, the plan stops and names it. A shorter window deletes AWS's older automated backups for good. Raise `pitr_retention_days`, or set `allow_shorter_pitr = true` in that profile to accept it.

Read the plan, then run `terraform apply tfplan`. The plan holds only protection: the policy, its rules, and the S3 protection group and its assignment. Then [step 3](../3-prove/README.md) shows what each tagged resource got.

## Next

[Step 3: prove it](../3-prove/README.md). To take a trial down later, see [Take a trial down](../docs/operate.md#take-a-trial-down).
