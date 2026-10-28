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

## Take a trial down

`make teardown` runs `terraform destroy`, which shows what it will remove and asks you to type `yes`. With `mode = "production"` it stops before removing anything. Backups Clumio already made stay until their retention ends.
