# Step 2: protect Aurora clusters

Protects every Aurora DB cluster (and RDS Multi-AZ DB cluster) tagged `clumio-profile = <name>`. Tag the cluster, not its instances. They get AWS point-in-time recovery (PITR), set by Clumio, a daily SecureVault copy, and an optional monthly archive.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, organizational unit and mode from `1-connect`, so they always match; it stops if `1-connect` isn't applied.

## Run it

1. Tag what you want protected: `clumio-profile = gold` (or your profile's name).
2. In this folder, run `cp settings.example terraform.tfvars`, and set the values marked REPLACE.
3. From the repository root, run `tools/status.py --preflight`: it checks that `1-connect`'s `workloads` covers this folder.
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-aurora-<account>-<region>`, and a rule that applies it to the tagged clusters.

- If a tagged cluster's PITR window would get shorter, the plan stops and names it. Raise `pitr_retention_days`, or set `allow_shorter_pitr = true` to accept it.
- **Tag before you plan.** The plan checks the PITR windows of what's tagged. A cluster tagged after apply gets this window from Clumio directly, with no check: a longer window is cut, and AWS's older backups are deleted.
- Before you apply, note each cluster's current window (`aws rds describe-db-clusters` or the console): after a teardown, Clumio's window stays, and you set the old one back yourself.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md). For a second protection level, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-aurora-silver
cp README.md settings.example *.tf ../2-protect-aurora-silver/
```

Then set `name = "silver"` there.
