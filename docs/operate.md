# Operate

What to do when something goes wrong, and how to take a trial down. Terraform commands run in `deploy/`. Paths to `tools/status.py` and `0-check/preview/preview.sh` are written from the repository's root folder.

## When something goes wrong

Start with `tools/status.py --preflight`. It checks the tools, your settings, your AWS sign-in, the Clumio token, the organizational unit, the Region, and the unit's free rule slots, and says what to fix.

| You see | What it means, and what to do |
|---|---|
| *Set account_id in terraform.tfvars*, or the same for `region`, `organizational_unit`, `mode`, `archive_months` or `pitr_retention_days` | A setting still holds its placeholder. Set it in `deploy/terraform.tfvars`. `tools/status.py --preflight` lists the units you can choose. `archive_months` has no default on purpose: each archive copy bills until it expires, even after a trial, so use 0 for a trial. |
| *AWS account ID not allowed*, or *You're signed in to AWS account …* | You're signed in to another account. Sign in to `account_id`, then run the command again. |
| *The AWS provider uses Region …* | Only when you call the modules from your own code: your AWS provider's `region` differs from the module's `region`. Make them the same. |
| *Profile gold would shorten the PITR window of …* | Clumio would set that database's PITR window shorter than it is today, and a shorter window deletes AWS's older automated backups for good. Raise `pitr_retention_days` in the profile, or, to accept it on purpose, set `allow_shorter_pitr = true` in that profile. Then plan again. |
| *AccessDenied* on `CreateRole`, `TagRole` or `CreatePolicy` | The identity running Terraform lacks a permission. Run `0-check/preview/preview.sh --as <its ARN>`, grant what BLOCKED lists, then plan and apply again. Terraform resumes where it stopped. |
| *AccessDenied* on `DescribeDBInstances` or `DescribeDBClusters` | The identity running Terraform can't read your databases, and a profile with databases reads each one's PITR window before it changes anything. Grant what `0-check/preview/preview.sh --as <its ARN>` lists, then plan again. |
| A plan shows changes right after an apply | An interrupted apply can need a second pass: plan, read it, apply. If changes remain after that, save the plan output and contact Clumio support. |
| *A profile protects a workload the connection's workloads leave out* | A profile turns on S3, databases, EC2 or volumes, but `workloads` leaves out the IAM Clumio needs for them. Add it to `workloads` (run `0-check/preview/preview.sh` to see the new IAM), or turn the workload off in the profile. |
| *error_code 107 … Number of rules is limited to 25* | The organizational unit has as many protection rules as Clumio allows. Each profile adds one rule, two with `ebs_volumes`. Remove a rule you no longer need, or choose another unit, then plan and apply again. `tools/status.py --preflight` shows how many are used. |
| *error_code 320 … already exists* | An apply was cut off after Clumio created an object. Run `terraform import <address> <ID from the Clumio console>`, then plan again. |
| *Instance cannot be destroyed* | `mode = "production"`: the production guard refuses a destroy, a switch to trial, or a new account or Region. That's on purpose. For another account or Region, copy `deploy/` to a new folder. |
| *error_code 367*, during a teardown | Your Clumio tenant can't delete connections. Keep the connection, or ask Clumio support. |
| Anything else | Run again with `TF_LOG=DEBUG TF_LOG_PATH=./tf-debug.log`. The log can hold secrets: check it before you share it. |

## Read tools/status.py

`tools/status.py` lists every bucket, RDS instance, Aurora cluster and EC2 instance in the Region tagged `clumio-profile`, and every volume tagged `clumio-volume-profile`, with its last backup. It reads AWS and Clumio, and changes nothing.

| State | What it means | What to do |
|---|---|---|
| OURS | This profile's policy protects it, and a backup exists. | Nothing. |
| WAITING | This profile's policy protects it; its first backup hasn't finished. | Nothing yet. If it still waits after a day, look for it in Clumio's Tasks. |
| NOT_YET | Clumio hasn't found it, or hasn't applied the profile yet. | Run `tools/status.py` again in an hour. |
| OTHER | Another rule or policy protects it. The line names the rule. | Remove the tag that rule matches, ask its owner, or rank this profile's rule ahead of it: set `rule_before_id` in the profile to that rule's ID, then plan and apply. The plan replaces the profile's rules, placed ahead of that one. |
| BAD_VALUE | Its `clumio-profile` tag names no profile here, such as a typo. | Fix the tag. |
| DOUBLE | A volume tagged `clumio-volume-profile` is attached to an instance the profile already protects, and an instance's backup already holds its volumes. | Remove the volume's `clumio-volume-profile` tag, or you pay for two copies. |
| OFF | Its profile doesn't protect that kind of resource, or a volume carries `clumio-profile` but no attached instance does. | Turn the workload on in the profile, or tag it with another profile. A volume on its own joins with `clumio-volume-profile`. |
| UNKNOWN | AWS or Clumio didn't answer, so nothing is assumed. | Check your sign-in and token, then run it again. |

Two kinds are left out on purpose: Aurora's instances, because Clumio protects their cluster, and a volume carrying `clumio-profile` while attached to a tagged instance, because that instance's backup holds it.

The first line checks that the connection sits in the organizational unit set in `deploy/terraform.tfvars`. If it doesn't, the profiles' rules can't match anything.

Exit codes, for scripts and CI: 0 nothing to do, 1 a person must act, 2 AWS or Clumio didn't answer. `tools/status.py --json` prints the same lines as JSON.

After `terraform plan -out=tfplan`, `tools/status.py --preview` shows what the saved plan will protect: each tagged resource, and each database's PITR window now and after. A plan that would shorten a window without `allow_shorter_pitr` has already stopped, in the profile module.

## Know the limits

- **Rule order is shared.** Clumio keeps every rule in a unit in one chain. Adding a profile's rule links it after the unit's current last rule, so that rule's position changes too; if another team manages its rules with Terraform, their next plan shows it. The kit sets its own rules' position once, at creation, and doesn't fight later reordering.
- **A database tagged after apply** gets the profile's PITR window from Clumio directly, with no plan in between, so a longer window is cut without the plan's check. Check a database's current window before you tag it.
- **The teardown check is a step you run.** Terraform runs no checks on destroy, so nothing stops a destroy while Clumio is backing up. Run `tools/status.py --teardown` first, as [Take a trial down](#take-a-trial-down) says.
- **Teardown reads running tasks by tag.** Remove a resource's tag before teardown, and its running backup isn't seen. If Clumio lists more than one page of tasks for a resource, teardown says UNKNOWN rather than READY: look in Clumio's Tasks.
- **The preview doesn't read who protects a resource today.** A resource another rule already claims shows WILL_PROTECT in the preview, then OTHER in `tools/status.py`.
- **OURS right after a change of policy** can show the last backup the previous policy made, until this profile's first backup runs.

## Take a trial down

1. Run `tools/status.py --teardown`. It checks that Clumio isn't backing up these resources. With `mode = "production"`, or while a backup runs, it says why to wait, and you stop here.
2. On READY, in `deploy/`, run `terraform plan -destroy -out=tfplan`, and read the plan.
3. Run `terraform apply tfplan`. Terraform removes protection first, then the connection.
4. Run `terraform state list`. It prints nothing when everything this folder created is gone.

Backups Clumio already made stay until their retention ends. Each database keeps the PITR window Clumio set: step 1 lists them, so you can set them back yourself.

## Retire a production connection

The production guards refuse every destroy, so retiring production is a deliberate act. Do it only when you mean to stop protecting this account and Region.

1. Remove the guards from Terraform's state: the connection's, and one per profile. Each is a marker with nothing behind it in AWS or Clumio, so this deletes nothing:

   ```bash
   terraform state rm 'module.connection.terraform_data.production_guard[0]'
   terraform state rm 'module.profile["gold"].terraform_data.production_guard[0]'   # once per profile
   ```

2. Set `mode = "trial"` in `deploy/terraform.tfvars`.
3. Take it down as a trial: [Take a trial down](#take-a-trial-down).
