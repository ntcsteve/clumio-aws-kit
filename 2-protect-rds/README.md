# Step 2: protect RDS databases

Protects every RDS DB instance tagged `clumio-profile = <name>` (Aurora clusters: [2-protect-aurora](../2-protect-aurora/README.md)). They get AWS point-in-time recovery (PITR), set by Clumio, a daily SecureVault copy, and an optional monthly archive.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, organizational unit and mode from `1-connect`, so they always match; it stops if `1-connect` isn't applied.

## Run it

1. Tag what you want protected: `clumio-profile = gold` (or your profile's name).
2. In this folder, run `cp settings.example terraform.tfvars`, and set the values marked REPLACE.
3. From the repository root, run `tools/status.py --preflight`. This folder adds one protection rule to the organizational unit, and Clumio limits rules per unit (5 in a child unit, 25 in Global, as seen) without showing the limit until you hit it: preflight counts what your folders still need, and fails before you apply if they don't fit.
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-rds-<account>-<region>`, and a rule that applies it to the tagged instances.

- If a tagged database's PITR window would get shorter, the plan stops and names it. Raise `pitr_retention_days`, or set `allow_shorter_pitr = true` to accept it.
- **Tag before you plan.** The plan checks the PITR windows of what's tagged. A database tagged after apply gets this window from Clumio directly, with no check: a longer window is cut, and AWS's older backups are deleted.
- Before you apply, note each database's current window (`aws rds describe-db-instances` or the console): after a teardown, Clumio's window stays, and you set the old one back yourself.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md). For a second protection level, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-rds-silver
cp README.md settings.example *.tf ../2-protect-rds-silver/
```

Then set `name = "silver"` there.
