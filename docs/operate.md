# Operate

What to do when something goes wrong, and how to take a trial down. Every command here runs in `setup/`.

## When something goes wrong

Start with `make preflight`. It checks the tools, your settings, your AWS sign-in, the Clumio token, the organizational unit, the Region, and the unit's free rule slots, and says what to fix.

| You see | What it means, and what to do |
|---|---|
| *Set account_id in terraform.tfvars*, or the same for `region`, `organizational_unit` or `mode` | A setting still holds its placeholder. Set it in `terraform.tfvars`. `make preflight` lists the units you can choose. |
| *AWS account ID not allowed*, or *You're signed in to AWS account …* | You're signed in to another account. Sign in to `account_id`, then run the command again. |
| *The AWS provider uses Region …* | Only when you call the modules from your own code: your AWS provider's `region` differs from the module's `region`. Make them the same. |
| *AccessDenied* on `CreateRole`, `TagRole` or `CreatePolicy` | The identity running Terraform lacks a permission. Run `make preview DEPLOY_ROLE=<its ARN>`, grant what BLOCKED lists, then `make plan` and `make apply` again. Terraform resumes where it stopped. |
| *A new plan still shows changes*, after `make apply` | An interrupted apply can need a second pass: `make plan`, read it, `make apply`. If changes remain after that, save the plan output and contact Clumio support. |
| *error_code 320 … already exists* | An apply was cut off after Clumio created an object. Run `terraform import <address> <ID from the Clumio console>`, then `make plan`. |
| *Instance cannot be destroyed* | `mode = "production"`: the production guard refuses a destroy, a switch to trial, or a new account or Region. That's on purpose. For another account or Region, copy `setup/` to a new folder. |
| *error_code 367*, from `make teardown` | Your Clumio tenant can't delete connections. Keep the connection, or ask Clumio support. |
| Anything else | Run again with `TF_LOG=DEBUG TF_LOG_PATH=./tf-debug.log`. The log can hold secrets: check it before you share it. |

## Read make status

`make status` lists every bucket, RDS instance and Aurora cluster in the Region tagged `clumio-profile`, with its last backup. It reads AWS and Clumio, and changes nothing. `make apply` runs it at the end.

| State | What it means | What to do |
|---|---|---|
| OURS | This profile's policy protects it, and a backup exists. | Nothing. |
| WAITING | This profile's policy protects it; its first backup hasn't finished. | Nothing yet. If it still waits after a day, look for it in Clumio's Tasks. |
| NOT_YET | Clumio hasn't found it, or hasn't applied the profile yet. | Run `make status` again in an hour. |
| OTHER | Another rule or policy protects it. The line names the rule. | Remove the tag that rule matches, ask its owner, or rank this profile's rule higher (`rule_before_id` in the module). |
| BAD_VALUE | Its `clumio-profile` tag names no profile here, such as a typo. | Fix the tag. |
| OFF | Its profile doesn't protect that kind of resource. | Turn the workload on in the profile, or tag it with another profile. |
| UNKNOWN | AWS or Clumio didn't answer, so nothing is assumed. | Check your sign-in and token, then run it again. |

The first line checks that the connection sits in the organizational unit set in `terraform.tfvars`. If it doesn't, the profiles' rules can't match anything.

Exit codes, for scripts and CI: 0 nothing to do, 1 a person must act, 2 AWS or Clumio didn't answer. `./status.py --json` prints the same lines as JSON.

`make plan` shows, after the plan, what it will protect: each tagged resource, and each database's PITR window now and after, marked SHORTER when Clumio will cut it.

## Take a trial down

1. Run `make teardown`. It first checks that Clumio isn't backing up these resources, then saves a plan that removes everything this folder created, and shows it. With `mode = "production"`, or while a backup runs, it stops before saving anything.
2. Read the plan, then run `make apply`. It applies that plan, then checks that nothing is left in Terraform's state.

Backups Clumio already made stay until their retention ends. Each database keeps the PITR window Clumio set: `make teardown` lists them, so you can set them back yourself.

## If you run Terraform directly

Every guard lives in Terraform, so plain `terraform plan` and `terraform apply` stop at the same wrong account, placeholder or production destroy as `make` does. What you give up: `terraform apply` plans again and asks you to type `yes`, instead of applying the plan you read, and nothing checks the result afterwards. `make apply` checks that a new plan shows no changes, or after a teardown, that nothing is left.

## Retire a production connection

The production guard refuses every destroy, so retiring production is a deliberate act in three steps. Do it only when you mean to stop protecting this account and Region.

1. Remove the guard from Terraform's state. It's a marker with nothing behind it in AWS or Clumio, so this deletes nothing:

   ```bash
   terraform state rm 'module.connection.terraform_data.production_guard[0]'
   ```

2. Set `mode = "trial"` in `terraform.tfvars`.
3. Take it down as a trial: `make teardown`, read the plan, `make apply`.
