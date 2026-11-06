# Operate

What to do when something goes wrong, and what each status means. Run Terraform in the step's own folder, and `tools/status.py` and `0-check/preview/preview.sh` from the repository's root folder.

## When something goes wrong

Start with `tools/status.py --preflight`: it checks your setup and says what to fix.

| You see | What it means, and what to do |
|---|---|
| *Set account_id in terraform.tfvars*, or the same for `region`, `organizational_unit`, `mode`, `archive_months` or `pitr_retention_days` | A setting still holds its placeholder. Set it in that folder's `terraform.tfvars`. `tools/status.py --preflight` lists the units you can choose. `archive_months` has no default on purpose: each archive copy bills while it's kept. 0 skips Archive, and 1 shows it in a trial. |
| *AWS account ID not allowed*, or *You're signed in to AWS account …* | You're signed in to another account. Sign in to `account_id`, then run the command again. |
| *… would shorten the PITR window of …* | Clumio would set that database's PITR window shorter than it is today, and a shorter window deletes AWS's older automated backups for good. Raise `pitr_retention_days` in that folder, or, to accept it on purpose, set `allow_shorter_pitr = true` there. Then plan again. |
| *AccessDenied* on `CreateRole`, `TagRole` or `CreatePolicy` | The identity running Terraform lacks a permission. Run `0-check/preview/preview.sh --as <its ARN>`, grant what BLOCKED lists, then plan and apply again. Terraform resumes where it stopped. |
| *AccessDenied* on `DescribeDBInstances` or `DescribeDBClusters` | The identity running Terraform can't read your databases, and a profile with databases reads each one's PITR window before it changes anything. Grant what `0-check/preview/preview.sh --as <its ARN>` lists, then plan again. |
| A plan shows changes right after an apply | An interrupted apply can need a second pass: plan, read it, apply. If changes remain after that, save the plan output and contact Clumio support. |
| *… is tainted, so must be replaced*, after an apply that stopped | The apply lost its connection, and Terraform can't tell whether that resource finished. Check it in AWS. If it's healthy, run `terraform untaint '<address>'`, then plan again: it should say No changes. If it isn't, plan, read it, and apply. |
| *Your session has expired* | Your AWS sign-in ended, which can happen during a long wait. Sign in again, then run the same command. |
| *Unable to find remote state*, or *Unsupported attribute … "kit"*, in a `2-protect-` folder | This clone's `1-connect` isn't applied, or was destroyed. A `2-protect-` folder reads its account, Region, unit and mode from `1-connect`'s state in the same clone. Apply `1-connect` first (step 1), then plan again. If you're taking a trial down and destroyed `1-connect` first, apply it again, destroy the `2-protect-` folders, then destroy `1-connect`. |
| *The connection's workloads leave out …* | A `2-protect-` folder's workload isn't in `1-connect`'s `workloads`, so Clumio has no IAM for it. Add it to `workloads` in `1-connect/terraform.tfvars` (run `0-check/preview/preview.sh` to see the new IAM), plan and apply `1-connect`, then plan the protect folder again. |
| *… isn't healthy: Clumio's connection_status is …* | Clumio has this connection, but doesn't call it connected, so it can't protect anything. Check that Clumio's roles still exist in AWS, and send the status to Clumio support. |
| *… is already connected … 1-connect's state doesn't hold it* | Clumio has a connection for this account and Region, and this copy of the kit didn't make it. Find out whose it is in the Clumio console. If it's from another clone of this repository, take that trial down from that clone. If it's another team's, leave it alone, and use another account or Region, or agree the next step with them. Never `terraform import` it: this state would then own it, and its teardown would remove it. |
| *error_code 107 … Number of rules is limited to 5* (or 25) | The organizational unit has as many protection rules as Clumio allows it: 5 in a child unit, 25 in Global, as seen on 2026-10-28. Each `2-protect-` folder for RDS, Aurora, EC2 or EBS adds one rule; S3 adds none. `tools/status.py --preflight` counts what your folders still need. Free a rule you no longer need, ask Clumio support to raise the unit's limit, or use another unit, then plan and apply again. Until the rule exists, `tools/status.py` shows that folder's resources as NOT_YET. |
| *error_code 320 … already exists* | An apply was cut off after Clumio created an object. Run `terraform import <address> <ID from the Clumio console>`, then plan again. The address is the resource the error names, such as `module.protect.clumio_policy.this`. |
| *Instance cannot be destroyed* | `mode = "production"`: the production guard refuses a destroy, a switch to trial, or a new account or Region. That's on purpose. For another account or Region, use a fresh clone of the repository, as [1-connect](../1-connect/README.md) says. |
| *error_code 367*, during a teardown | Connection delete is off for your Clumio tenant. Clumio support can turn it on. |
| *BLOCKED* from `tools/status.py --teardown`, and a task stays `queued` | Teardown waits for every task on these resources. Wait and run the check again. To stop a queued task, ask Clumio support. |
| Anything else | Run again with `TF_LOG=DEBUG TF_LOG_PATH=./tf-debug.log`. The log can hold secrets: check it before you share it. |

## Read tools/status.py

`tools/status.py` lists every bucket, RDS instance, Aurora cluster and EC2 instance in the Region tagged `clumio-profile`, and every volume tagged `clumio-volume-profile`, with its last backup. It reads AWS and Clumio, and changes nothing.

| State | What it means | What to do |
|---|---|---|
| PROTECTED | This profile's policy protects it, and a backup exists. | Nothing. |
| PARTIAL | A bucket's last backup completed, but skipped objects Clumio couldn't read. Those objects have no copy. | See which, and why, on the bucket's backup calendar in Clumio's console ([how it behaves](#how-it-behaves)). Fix that access, then run `tools/status.py` after the next backup. |
| WAITING | This profile's policy protects it; its first backup hasn't finished. | Nothing yet. If it still waits after a day, look for it in Clumio's Tasks. If nothing moves there, contact Clumio support with the resource's ID. |
| NOT_YET | Clumio hasn't found it, or hasn't applied the profile yet. A resource created or tagged after its rule joins at Clumio's next discovery cycle. | Run `tools/status.py` again later; allow up to a day. After a day with no change, contact Clumio support with the resource's ID. |
| OTHER | Another rule or policy protects it. The line names the rule. | Remove the tag that rule matches, ask its owner, or rank this profile's rule ahead of it: set `rule_before_id` in that `2-protect-` folder to the rule's ID, which the line shows, then plan and apply. The plan replaces the folder's rule, placed ahead of that one. |
| BAD_VALUE | Its `clumio-profile` tag names no profile applied here: a typo, or that profile's `2-protect-` folder isn't applied, or was taken down. | Apply that folder, or fix or remove the tag. |
| DOUBLE | A volume tagged `clumio-volume-profile` is attached to an instance the profile already protects, and an instance's backup already holds its volumes. | Remove the volume's `clumio-volume-profile` tag, or you pay for two copies. |
| OFF | No `2-protect-` folder for this kind of resource is applied with this profile's name; or a volume carries `clumio-profile` with no tagged instance; or it's an Aurora cluster's instance (tag the cluster); or DocumentDB or Neptune, which the kit doesn't support. The line says which. | Apply the `2-protect-` folder it names with that `name`, or fix the tag. A volume on its own joins with `clumio-volume-profile`. |
| UNKNOWN | Couldn't read from AWS or Clumio, so nothing is assumed. | Check your sign-in and token, then run it again. |

Two kinds are left out on purpose: the instances of a tagged Aurora cluster, because Clumio protects the cluster, and a volume carrying `clumio-profile` while attached to a tagged instance, because that instance's backup holds it.

The first line checks that the connection sits in the organizational unit set in `1-connect/terraform.tfvars`. If it doesn't, the profiles' rules can't match anything.

Exit codes, for scripts and CI: 0 nothing to do, including WAITING and NOT_YET, so 0 doesn't mean every line is PROTECTED; 1 a person must act; 2 AWS or Clumio couldn't be read. `tools/status.py --json` prints the same lines as JSON.

## How it behaves

- **Rule order is shared.** Clumio keeps every rule in a unit in one chain. Adding a profile's rule links it after the unit's current last rule, so that rule's position changes too; if another team manages its rules with Terraform, their next plan shows it. The kit sets its own rules' position once, at creation, and doesn't fight later reordering.
- **A resource created or tagged after its rule** joins at Clumio's next discovery cycle, not at once. Allow up to a day. A database that joins this way gets the profile's PITR window with no plan in between, so a longer window is cut without the plan's check. Check a database's current window before you tag it.
- **A plan that stops is still saved.** When a check stops `terraform plan -out=tfplan` (a shorter PITR window, say), Terraform still writes `tfplan`, marked as not applyable: `terraform apply tfplan` refuses it. Fix the cause and plan again.
- **The teardown check is a step you run.** Terraform runs no checks on destroy, so nothing stops a destroy while Clumio is backing up. Run `tools/status.py --teardown` first, as [Take a trial down](../README.md#take-a-trial-down) says.
- **Teardown reads running tasks by tag.** Remove a resource's tag before teardown, and its running backup isn't seen. If Clumio lists more than 20 pages of tasks for a resource, teardown says UNKNOWN rather than READY: look in Clumio's Tasks.
- **A backup can skip an object and still complete.** If Clumio can't read an object, such as one under a key whose policy denies Clumio's role, the task completes. Clumio records it on the backup: in the console, the date shows a half-filled dot, a partial backup, and its popup says how many objects failed and lets you download the list, with AWS's error for each. Seen live on S3 on 2026-11-02. `tools/status.py` reads the count from the bucket's last backup and says PARTIAL, and the report says UNFINISHED. Seen live on 2026-11-03.
- **PROTECTED during a first backup.** Clumio lists a backup from its start, so PROTECTED can show a few minutes before the first copy finishes (seen live for EC2).
- **PROTECTED right after a change of policy** can show the last backup the previous policy made, until this profile's first backup runs.

## Delete a backup

A backup deletion request takes two signatures. In the Clumio console, under **Administration**, **Backup deletion**, a Super Admin creates a request, names a second approver, and selects by date range and data source, narrowing by account, Region, asset type or backup type. To target one resource, use its Clumio entity ID from the Consumption report: a resource's AWS name or ID doesn't work here. Both people sign, and Clumio then deletes the backups. [Clumio's steps](https://documentation.commvault.com/clumio/backup_deletion.html). Charges continue until a copy's minimum retention ends.

## A second profile

For a second profile, such as `silver`, copy a `2-protect-` folder's files, never its state or `backend.tf`:

```bash
mkdir 2-protect-rds-silver
cd 2-protect-rds
cp settings.example main.tf variables.tf versions.tf .terraform.lock.hcl ../2-protect-rds-silver/
cd ../2-protect-rds-silver
cp settings.example terraform.tfvars
```

Run the last two lines in the new folder, never in `2-protect-rds`: there, `cp` would overwrite gold's settings. Then set `name = "silver"` before you plan: two folders with one name would make the same policy. With state in S3, run `tools/use_s3_state.py <bucket>` again, with the same bucket: it adds the new folder.
