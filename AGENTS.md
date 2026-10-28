# For AI agents, and anyone changing this repository

This repository sets Clumio up on AWS with Terraform: it connects an AWS account and Region to Clumio, and protects S3, RDS, Aurora, EC2 and EBS by tag. Its readers are people running a trial, a proof of concept, or production. You help them in one of two ways:

1. **Help a person set it up** in their own account. The rules below keep it safe.
2. **Change the repository.** See [Changing this repository](#changing-this-repository).

## Map

| Path | What it is |
|---|---|
| `setup/` | The first-time path: one settings file (`terraform.tfvars`, from `settings.example`) and the `make` commands. Connects one account and Region |
| `setup/status.py` | Read-only checks; `make preflight` runs it |
| `setup/preview/` | Shows every IAM role and policy before anything exists, and checks the deploy role. Its golden tests are what security reviewed |
| `modules/connection/` | The product: the connection, Clumio's IAM (`iam/`), the compliance report, and every guard. Production calls it from its own repo |
| `docs/operate.md` | Errors and what to do, and taking a trial down |
| `check.sh` | Offline checks of this repository. Ends with `ALL CHECKS PASS` |
| `tests/check_test.sh` | Proves each scan in `check.sh` passes and fails when it should |

This repository is being built in stages. Each stage adds its folders to this map.

## Rules for every task

1. **Use the `make` commands in `setup/`.** Outside them, plan with `terraform plan -out=tfplan`, show the person the plan, wait for their go, then run `terraform apply tfplan`. Never use `-auto-approve`. One go covers one apply.
2. **The person names the account, Region, unit and mode.** `account_id`, `region`, `organizational_unit` and `mode` come from the person, never from a guess. A wrong account on a shared Clumio tenant can protect another team's data, and change its databases' backup window.
3. **Never set `i_understand_byok_is_permanent`.** Only the person sets it, after reading why. Bring your own key binds the whole Clumio tenant to one key, for good.
4. **Never print a secret.** The secret here is `CLUMIO_API_TOKEN`: never print it or other environment variables. The person exports it in the shell that starts you. Terraform never writes it to state or plans. The connection's ExternalId isn't a secret (AWS says so: anyone who can read the role can see it), so plans may show it.
5. **One Clumio tenant per state.** A token from another tenant can't see what this state created, so Terraform would create a second set.
6. **Never change `account_id`, `region` or `organizational_unit` in an applied `setup/`.** Copy the folder for another target instead.
7. **The kit never deletes data.** Teardown is `make teardown`, then `make apply` after the person has read the plan. It refuses in production.
8. **The person does the console steps:** the Clumio console, the AWS sign-in, and creating the token.

## Changing this repository

**Tests come first.** Write the test, watch it fail, then change the code. Take expected values from an independent truth, such as a saved real output, never from the code under test.

**Verify with `./check.sh`.** It ends with `ALL CHECKS PASS`. It never calls AWS or Clumio, so it proves offline behavior only. When it's all that ran, say "tested offline".

**Code runs on macOS's stock tools:** bash 3.2, Python 3.9 and GNU Make 3.81. Don't use bash 4 features (associative arrays, `mapfile`), Python 3.10 features (`match`, `X | Y` types), or Make 3.82 features (`.ONESHELL`).

**Git.** The remote is public. Commit only when the person asks, stage named paths, and never push. Never commit `terraform.tfvars`, state, plans, or an account ID: examples use `123456789012`.

**Write the docs like a book:**

- Each fact lives in one place. Elsewhere, link to it.
- Every claim traces to the code or to a live run. What isn't proven says so, where the reader sees it.
- Full, short sentences. One idea per paragraph. One term per concept. No em dashes.
