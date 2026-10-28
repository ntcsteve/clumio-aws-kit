# For AI agents, and anyone changing this repository

This repository sets Clumio up on AWS with Terraform: it connects an AWS account and Region to Clumio, and protects S3, RDS, Aurora, EC2 and EBS by tag. Its readers are people running a trial, a proof of concept, or production. You help them in one of two ways:

1. **Help a person set it up** in their own account. The rules below keep it safe.
2. **Change the repository.** See [Changing this repository](#changing-this-repository).

## Map

| Path | What it is |
|---|---|
| `0-check/` | Step 0, read-only: preflight, and the IAM preview (`preview/`), which shows every IAM role and policy before anything exists and checks the deploy role. Its golden tests are what security reviewed |
| `1-connect/` | Step 1: the connection and Clumio's IAM, one state. Its `terraform.tfvars` holds the account, Region, unit and mode for every step |
| `2-protect-s3/`, `-rds/`, `-aurora/`, `-ec2/`, `-ebs/` | Step 2: one Clumio policy per workload, one state each. Each reads the account, Region, unit and mode from `1-connect`'s state |
| `3-prove/` | Step 3: who protects each resource, a restore, and the evidence |
| `tools/status.py` | Read-only checks: preflight, who protects each tagged resource (the kit's policies found by name in Clumio), and whether teardown is safe |
| `modules/connection/` | The product: the connection, Clumio's IAM (`iam/`), the compliance report, and every guard. Production calls it from its own repo |
| `modules/protect/` | The product: one workload's policy, selected by tag, with the PITR and production guards |
| `README.md` | The entry point: what the kit does, the four steps, what keeps a first run safe |
| `docs/keys.md` | Does Clumio need our keys? What was shown, the evidence, what a restore needs |
| `docs/production.md` | Calling the modules from a production repository, and which guards come with them |
| `docs/operate.md` | Errors and what to do, reading `tools/status.py`, the known limits, and taking a trial down |
| `proof/` | Evidence: the lab (test data under AWS-managed and customer-managed keys), the capture and checksum tools, and every saved capture. `proof/README.md` says how to run it |
| `check.sh` | Offline checks of this repository. Ends with `ALL CHECKS PASS` |
| `tests/check_test.sh` | Proves each scan in `check.sh` passes and fails when it should |


## Rules for every task

1. **Apply only a saved plan the person has read.** Plan with `terraform plan -out=tfplan`, show the person the plan, wait for their go, then run `terraform apply tfplan`. Never use `-auto-approve`. One go covers one apply.
2. **The person names the account, Region, unit and mode.** `account_id`, `region`, `organizational_unit` and `mode` come from the person, never from a guess. A wrong account on a shared Clumio tenant can protect another team's data, and change its databases' backup window.
3. **Never set `allow_shorter_pitr`.** Only the person sets it, after reading why. A shorter PITR window deletes AWS's older backups, for good.
4. **Never print a secret.** The secret here is `CLUMIO_API_TOKEN`: never print it or other environment variables. The person exports it in the shell that starts you. Terraform never writes it to state or plans. The connection's ExternalId isn't a secret (AWS says so: anyone who can read the role can see it), so plans may show it.
5. **One Clumio tenant per state.** A token from another tenant can't see what this state created, so Terraform would create a second set.
6. **Never change `account_id`, `region` or `organizational_unit` in an applied `1-connect/`.** For another target, copy the whole repository.
7. **The kit never deletes data.** Teardown follows [Take a trial down](docs/operate.md#take-a-trial-down): `tools/status.py --teardown` first, then a saved destroy plan the person has read. Production refuses it. Never tear down while the check says a backup runs.
8. **The person does the console steps:** the Clumio console, the AWS sign-in, and creating the token.

## Changing this repository

**Tests come first.** Write the test, watch it fail, then change the code. Take expected values from an independent truth, such as a saved real output, never from the code under test.

**Verify with `./check.sh`.** It ends with `ALL CHECKS PASS`. It never calls AWS or Clumio, so it proves offline behavior only. When it's all that ran, say "tested offline".

**Code runs on macOS's stock tools:** bash 3.2 and Python 3.9. Don't use bash 4 features (associative arrays, `mapfile`) or Python 3.10 features (`match`, `X | Y` types).

**Git.** The remote is public. Commit only when the person asks, stage named paths, and never push. Never commit `terraform.tfvars`, state, plans, or an account ID: examples use `123456789012`.

**Write the docs like a book:**

- Each fact lives in one place. Elsewhere, link to it.
- Every claim traces to the code or to a live run. What isn't proven says so, where the reader sees it.
- Full, short sentences. One idea per paragraph. One term per concept. No em dashes.
