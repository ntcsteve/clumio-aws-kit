# Operate

What to do when something goes wrong, and how to take a trial down. Terraform commands run in the step's own folder. Paths to `tools/status.py` and `0-check/preview/preview.sh` are written from the repository's root folder.

## When something goes wrong

Start with `tools/status.py --preflight`. It checks the tools, your settings, your AWS sign-in, the Clumio token, the organizational unit, the Region, and the unit's free rule slots, and says what to fix.

| You see | What it means, and what to do |
|---|---|
| *Set account_id in terraform.tfvars*, or the same for `region`, `organizational_unit`, `mode`, `archive_months` or `pitr_retention_days` | A setting still holds its placeholder. Set it in that folder's `terraform.tfvars`. `tools/status.py --preflight` lists the units you can choose. `archive_months` has no default on purpose: each archive copy bills until it expires, even after a trial, so use 0 for a trial. |
| *AWS account ID not allowed*, or *You're signed in to AWS account …* | You're signed in to another account. Sign in to `account_id`, then run the command again. |
| *The AWS provider uses Region …* | Only when you call the modules from your own code: your AWS provider's `region` differs from the module's `region`. Make them the same. |
| *… would shorten the PITR window of …* | Clumio would set that database's PITR window shorter than it is today, and a shorter window deletes AWS's older automated backups for good. Raise `pitr_retention_days` in that folder, or, to accept it on purpose, set `allow_shorter_pitr = true` there. Then plan again. |
| *AccessDenied* on `CreateRole`, `TagRole` or `CreatePolicy` | The identity running Terraform lacks a permission. Run `0-check/preview/preview.sh --as <its ARN>`, grant what BLOCKED lists, then plan and apply again. Terraform resumes where it stopped. |
| *AccessDenied* on `DescribeDBInstances` or `DescribeDBClusters` | The identity running Terraform can't read your databases, and a profile with databases reads each one's PITR window before it changes anything. Grant what `0-check/preview/preview.sh --as <its ARN>` lists, then plan again. |
| A plan shows changes right after an apply | An interrupted apply can need a second pass: plan, read it, apply. If changes remain after that, save the plan output and contact Clumio support. |
| *The connection's workloads leave out …* | A `2-protect-` folder's workload isn't in `1-connect`'s `workloads`, so Clumio has no IAM for it. Add it to `workloads` in `1-connect/terraform.tfvars` (run `0-check/preview/preview.sh` to see the new IAM), plan and apply `1-connect`, then plan the protect folder again. |
| *error_code 107 … Number of rules is limited to 5* (or 25) | The organizational unit has as many protection rules as Clumio allows it: 5 in a child unit, 25 in Global, as seen on 2026-10-28. Clumio shows the limit only when you hit it. Each `2-protect-` folder for RDS, Aurora, EC2 or EBS adds one rule; S3 adds none. `tools/status.py --preflight` counts what your folders still need. Free a rule you no longer need, ask Clumio support to raise the unit's limit, or use another unit, then plan and apply again. Until the rule exists, `tools/status.py` shows that folder's resources as NOT_YET. |
| *error_code 320 … already exists* | An apply was cut off after Clumio created an object. Run `terraform import <address> <ID from the Clumio console>`, then plan again. |
| *Instance cannot be destroyed* | `mode = "production"`: the production guard refuses a destroy, a switch to trial, or a new account or Region. That's on purpose. For another account or Region, copy the whole repository. |
| *error_code 367*, during a teardown | Your Clumio tenant can't delete connections. Keep the connection, or ask Clumio support. |
| Anything else | Run again with `TF_LOG=DEBUG TF_LOG_PATH=./tf-debug.log`. The log can hold secrets: check it before you share it. |

## Read tools/status.py

`tools/status.py` lists every bucket, RDS instance, Aurora cluster and EC2 instance in the Region tagged `clumio-profile`, and every volume tagged `clumio-volume-profile`, with its last backup. It reads AWS and Clumio, and changes nothing.

| State | What it means | What to do |
|---|---|---|
| OURS | This profile's policy protects it, and a backup exists. | Nothing. |
| WAITING | This profile's policy protects it; its first backup hasn't finished. | Nothing yet. If it still waits after a day, look for it in Clumio's Tasks. |
| NOT_YET | Clumio hasn't found it, or hasn't applied the profile yet. | Run `tools/status.py` again in an hour; for a bucket, allow up to a day. |
| OTHER | Another rule or policy protects it. The line names the rule. | Remove the tag that rule matches, ask its owner, or rank this profile's rule ahead of it: set `rule_before_id` in that `2-protect-` folder to the rule's ID, which the line shows, then plan and apply. The plan replaces the folder's rule, placed ahead of that one. |
| BAD_VALUE | Its `clumio-profile` tag names no profile here, such as a typo. | Fix the tag. |
| DOUBLE | A volume tagged `clumio-volume-profile` is attached to an instance the profile already protects, and an instance's backup already holds its volumes. | Remove the volume's `clumio-volume-profile` tag, or you pay for two copies. |
| OFF | No `2-protect-` folder for this kind of resource is applied with this profile's name; or a volume carries `clumio-profile` with no tagged instance; or it's an Aurora cluster's instance (tag the cluster); or DocumentDB or Neptune, which the kit doesn't support. The line says which. | Apply the `2-protect-` folder it names with that `name`, or fix the tag. A volume on its own joins with `clumio-volume-profile`. |
| UNKNOWN | AWS or Clumio didn't answer, so nothing is assumed. | Check your sign-in and token, then run it again. |

Two kinds are left out on purpose: Aurora's instances, because Clumio protects their cluster, and a volume carrying `clumio-profile` while attached to a tagged instance, because that instance's backup holds it.

The first line checks that the connection sits in the organizational unit set in `1-connect/terraform.tfvars`. If it doesn't, the profiles' rules can't match anything.

Exit codes, for scripts and CI: 0 nothing to do, 1 a person must act, 2 AWS or Clumio didn't answer. `tools/status.py --json` prints the same lines as JSON.

## Know the limits

- **Rule order is shared.** Clumio keeps every rule in a unit in one chain. Adding a profile's rule links it after the unit's current last rule, so that rule's position changes too; if another team manages its rules with Terraform, their next plan shows it. The kit sets its own rules' position once, at creation, and doesn't fight later reordering.
- **A database tagged after apply** gets the profile's PITR window from Clumio directly, with no plan in between, so a longer window is cut without the plan's check. Check a database's current window before you tag it.
- **A plan that stops is still saved.** When a check stops `terraform plan -out=tfplan` (a shorter PITR window, say), Terraform still writes `tfplan`, marked as not applyable: `terraform apply tfplan` refuses it. Fix the cause and plan again.
- **The teardown check is a step you run.** Terraform runs no checks on destroy, so nothing stops a destroy while Clumio is backing up. Run `tools/status.py --teardown` first, as [Take a trial down](#take-a-trial-down) says.
- **Teardown reads running tasks by tag.** Remove a resource's tag before teardown, and its running backup isn't seen. If Clumio lists more than 20 pages of tasks for a resource, teardown says UNKNOWN rather than READY: look in Clumio's Tasks.
- **OURS right after a change of policy** can show the last backup the previous policy made, until this profile's first backup runs.

## Take a trial down

Reverse the steps: each protect folder first, the connection last. A protect folder needs the connection to plan its own removal, so `1-connect` goes last.

1. Keep every tag in place until the teardown is done: the check finds running backups through them. Run `tools/status.py --teardown`. It checks that Clumio isn't backing up these resources, and lists every folder at the repository root named `1-connect`, or starting with `2-protect-`, that still has something applied in its local state. With `mode = "production"` in `1-connect/terraform.tfvars`, or while a backup runs, it says why to wait, and you stop here.
2. In each `2-protect-` folder you applied: `terraform plan -destroy -out=tfplan`, read it, `terraform apply tfplan`.
3. Then in `1-connect`: the same three commands.
4. In each folder, `terraform state list` prints nothing when it's all gone.

If `1-connect` was destroyed first, the `2-protect-` folders can no longer plan: they read its state. Apply `1-connect` again (step 1), destroy the `2-protect-` folders, then destroy `1-connect`.

5. Remove the `clumio-profile` and `clumio-volume-profile` tags, so a later setup doesn't pick these resources up without anyone deciding to.

Backups Clumio already made stay until their retention ends. Each database keeps the PITR window Clumio set: the teardown check in step 1 lists them, and you set back the windows you noted before step 2.

## Retire a production connection

The production guards refuse every destroy, so retiring production is a deliberate act. Do it only when you mean to stop protecting this account and Region.

1. In each folder you applied, remove its guard from Terraform's state. Each guard is a marker with nothing behind it in AWS or Clumio, so this deletes nothing:

   ```bash
   terraform state rm 'module.protect.terraform_data.production_guard[0]'      # in each 2-protect- folder
   terraform state rm 'module.connection.terraform_data.production_guard[0]'   # in 1-connect
   ```

2. Set `mode = "trial"` in `1-connect/terraform.tfvars`, then in `1-connect` run `terraform plan -out=tfplan` and `terraform apply tfplan`. With the guards gone from state, this changes no resource: it records the trial mode the `2-protect-` folders read.
3. Take it down as a trial: [Take a trial down](#take-a-trial-down).
