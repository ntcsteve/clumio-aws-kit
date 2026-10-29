# Step 2: protect RDS databases

Protects every RDS DB instance tagged `clumio-profile = <name>` (Aurora clusters: [2-protect-aurora](../2-protect-aurora/README.md)). They get AWS point-in-time recovery (PITR), set by Clumio, a daily SecureVault copy, and an optional monthly archive.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

## Run it

1. Tag what to protect: `clumio-profile = gold`, or your profile's name.
2. Here, run `cp settings.example terraform.tfvars`, then set the values marked REPLACE.
3. From the repository root, run `tools/status.py --preflight`. This folder adds one rule to the organizational unit, and a unit holds only a few: preflight checks there's room ([the limit](../docs/operate.md#when-something-goes-wrong), error 107).
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-rds-<account>-<region>`, and a rule that applies it to the tagged instances.

- If a tagged database's PITR window would get shorter, the plan stops and names it. Raise `pitr_retention_days`, or set `allow_shorter_pitr = true` to accept it.
- Where PITR is off, Clumio turns it on at the next maintenance window, because turning it on restarts an RDS instance.
- **Tag before you plan.** The plan checks the windows of what's tagged. A database tagged after apply gets this window with no check: a longer window is cut, and AWS's older backups are deleted.
- Before you apply, note each database's window (`aws rds describe-db-instances` or the console): after teardown, Clumio's window stays, and you set the old one back.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-rds-silver
cp README.md settings.example *.tf .terraform.lock.hcl ../2-protect-rds-silver/
```

In the new folder, run `cp settings.example terraform.tfvars` and set `name = "silver"` before you plan: two folders with one name would make the same policy.
