# Production

Deploy to production from a fresh clone of this kit, with the same steps you ran in your test account. The one difference is where Terraform keeps its state.

## Before you start

- **Use a fresh clone,** one per account and Region. A copy of your test clone carries that account's state, and its plan would destroy that connection.
- **Create a bucket for Terraform's state,** in the same Region as your data, with versioning and encryption on and public access blocked. State on one laptop goes with that laptop.
- **Let the identity that runs Terraform use it:** `s3:ListBucket` on the bucket, and `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on its `clumio/*` keys.
- **Take down any trial in this account and Region first:** [Take a trial down](../README.md#take-a-trial-down). An account and Region have one Clumio connection, and one state manages it.

## Deploy

1. Do steps 0.1 and 0.2 in the [README](../README.md#what-to-do), with `mode = "production"`.
2. From the repository's root folder, run `tools/use_s3_state.py <bucket>`. It writes `backend.tf` in `1-connect` and in each `2-protect-` folder, one key each, and tells each `2-protect-` folder where `1-connect`'s state is. Run it before the first `terraform init`.
3. Carry on from step 0.3 through step 3.1. Steps 3.2 and 3.3, a restore and its report, are for your test account: run them here only if your own process asks for a restore test in production. New settings can mean new IAM, so your security team reviews this pack too.

To work from another machine, make a fresh clone, copy your `terraform.tfvars` files and any second profile's folder, run the tool with the same bucket, and run `terraform init` in each folder you applied before any check.

Seen live on 2026-11-02 for S3: a fresh clone in production mode, state in S3, on an identity holding only the generated deploy policy, `tools/status.py`'s reads and the state bucket's permissions, from a second machine too, through to retiring it.

## What you get

| Guard | In production |
|---|---|
| Wrong account or Region stops the plan | Yes |
| A shorter PITR window stops the plan, unless `allow_shorter_pitr = true` | Yes |
| Terraform refuses destroy, a switch to trial, and a new account, Region, name or workload | Yes |
| A workload the connection's IAM leaves out stops the plan | Yes |
| `tools/status.py --teardown` | Says REFUSED. Retiring production is a deliberate act: [Retire a production connection](#retire-a-production-connection) |

## Watch your backups

Terraform doesn't report a failed backup, and `tools/status.py` shows the last backup's time, plus PARTIAL for a bucket whose last backup skipped objects. Its [exit code](operate.md#read-toolsstatuspy) doesn't catch a failed or missed backup. Watch them in Clumio:

- **Alerts** show a failed backup or restore.
- **Reports** show whether each asset has a backup. Set up Clumio's compliance report in its console.
- **Name who reads them.** Clumio recommends [checking its reports every day](https://documentation.commvault.com/clumio/best_practices_for_clumios_platform.html).

## Retire a production connection

The production guards refuse every destroy, so retiring production is a deliberate act. Do it only when you mean to stop protecting this account and Region. Before you start, restore anything you want to keep, and talk to Clumio about any backups you need.

Seen live on 2026-11-02 with state in S3: production refused a teardown and a destroy; the steps below then removed everything.

1. In each folder you applied, remove its guard from Terraform's state. Each guard is a marker with nothing behind it in AWS or Clumio, so this deletes nothing:

   ```bash
   terraform state rm 'module.protect.terraform_data.production_guard[0]'      # in each 2-protect- folder
   terraform state rm 'module.connection.terraform_data.production_guard[0]'   # in 1-connect
   ```

2. Set `mode = "trial"` in `1-connect/terraform.tfvars`, then in `1-connect` run `terraform plan -out=tfplan` and `terraform apply tfplan`. With the guards gone from state, this changes no resource: it records the trial mode the `2-protect-` folders read.
3. Take it down as a trial: [Take a trial down](../README.md#take-a-trial-down). The state bucket is yours: delete its `clumio/` keys, or the bucket, when you're finished.
