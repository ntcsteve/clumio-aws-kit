# clumio-aws-kit

Prove that Clumio backs up and restores your AWS data, from your own account, with an afternoon's work, and that teardown leaves nothing of the kit behind. For the engineer running the trial, the field engineer beside them, and AI agents helping them ([rules for agents](AGENTS.md)).

Not an official Clumio product. It uses Clumio's Terraform provider and IAM module, pinned to tested versions. For problems with the Clumio service, contact Clumio support.

## 1. Why care, and is this for you

Backups in the same account as the data fall with it: a deleted account, a stolen admin key or ransomware takes both. Clumio keeps a copy outside your account. This kit sets that up with plain Terraform, protects what you tag, and shows you each backup and a restore. You decide on evidence, not a slide.

For one AWS account and Region, and five workloads: S3, RDS, Aurora, EC2 and EBS. Not for bring your own key (BYOK), DynamoDB, or many accounts at once. You restore in the Clumio console.

## 2. What you'll prove

| You'll prove | Where to look |
|---|---|
| Your security team reviews every IAM role before anything exists | [0-check](0-check/README.md) |
| What you tag gets backed up: S3, RDS, Aurora, EC2, EBS | [Keys evidence](proof/evidence/keys-lab-2026-10-28/) |
| RDS and Aurora get AWS point-in-time recovery (PITR), a daily SecureVault Standard copy and a monthly SecureVault Archive copy | [Archive evidence](proof/evidence/archive-lab-2026-10-29/), for Aurora |
| You restore one resource and check it | [Does Clumio need our keys?](docs/keys.md) |
| Your keys stay yours, AWS-managed or customer-managed | [Does Clumio need our keys?](docs/keys.md) |
| Teardown removes everything the kit created | [Take a trial down](docs/operate.md#take-a-trial-down) |

Not yet proven live: [What isn't proven](docs/keys.md#what-isnt-proven) and [Know the limits](docs/operate.md#know-the-limits).

## 3. How it works

```
 Your AWS account                                    Clumio
 +-----------------------------+                    +-----------------------------+
 | resources you tag           |   step 1: IAM      | one policy per workload     |
 | clumio-profile = gold       | <---- roles ------ | (step 2): how often, how    |
 |                             |                    | long, which tiers           |
 | S3, RDS, Aurora, EC2, EBS   |                    |                             |
 |                             |   step 2: a rule   | copies in SecureVault,      |
 |                             | ---- matches ----> | outside your account        |
 |                             |   the tag          |                             |
 +-----------------------------+                    +-----------------------------+
```

You tag a resource. A Clumio rule matches the tag. The policy decides what Clumio copies, how often and for how long. Clumio works in your account only through the IAM roles from step 1.

## 4. Is it safe

**What it creates.** Step 1: the Clumio connection, Clumio's IAM roles and policies, EventBridge rules and an SNS topic. Step 0 shows them before they exist. Step 2: one Clumio policy per workload, with a rule (S3: a protection group).

**What it changes.** Clumio sets each tagged database's PITR window to the policy's value. Where PITR is off, it turns it on, which restarts an RDS instance at its maintenance window. During a backup, Clumio makes temporary snapshots in your account and deletes them after. Clumio's roles may do more than back up what you tag, such as change an S3 bucket's event notifications: step 0's preview lists it all.

**What stays after teardown.** Clumio's copies, until their retention ends. Each database's PITR window as Clumio set it, so note the old one first. Anything you restored.

**What stops a mistake.**

- **Wrong account:** every plan stops if you're signed in to another AWS account.
- **Shorter backups:** a plan stops if it would shorten a database's PITR window, which deletes AWS's older backups for good, unless you accept it in writing.
- **Production:** with `mode = "production"`, Terraform refuses to destroy the connection or a policy.
- **Mid-backup teardown:** `tools/status.py --teardown` says wait while Clumio is backing up. You run it; Terraform doesn't.
- **No data deleted:** the kit removes only what it created.

## 5. Plan and prepare

| What | Detail |
|---|---|
| People | Someone who may create IAM roles in the account. A security reviewer for the IAM preview. A Clumio administrator for the API token and the organizational unit |
| Tools | Terraform 1.10 or later, the AWS CLI v2, Python 3.9 or later. macOS or Linux; on Windows, WSL |
| Decide | The account and Region. The Clumio organizational unit. `mode`: `trial` for a proof of concept. `workloads`: only what you'll test, so Clumio gets no more IAM than that. What to tag, and the profile name, such as `gold`. How long to keep copies |
| Check | Each database's PITR window: set `pitr_retention_days` at least that long. One free Clumio rule slot per RDS, Aurora, EC2 or EBS folder: preflight counts them. Outbound HTTPS to the Terraform registry and your Clumio API URL. Your SCPs and data-perimeter rules: preflight can't test them, so ask your cloud security team whether they allow Clumio's cross-account roles |
| Time | About a dozen commands. First backups came within an hour in the lab; allow up to a day |
| Cost | Clumio bills each copy until its retention ends, even after teardown. An Archive copy kept under 12 months has Clumio's early-deletion fee. For a proof of concept, `archive_months = 1` shows Archive, and 0 skips it |

## 6. What to do

Run each command in the folder under Where, in one shell: the one signed in to AWS, with the Clumio details exported. **Person**: a person does it. **STOP**: wait for a person's go. **Anyone**: a person or an agent.

| Step | Who | Where | Do | Expect |
|---|---|---|---|---|
| 0.1 | Person | shell | Sign in to AWS. Export `CLUMIO_API_BASE_URL` and `CLUMIO_API_TOKEN`, as [0-check](0-check/README.md) shows | `aws sts get-caller-identity` shows your account |
| 0.2 | Person | root | `cp 1-connect/settings.example 1-connect/terraform.tfvars`, then set `account_id`, `region`, `organizational_unit`, `mode` and `workloads` (such as `["rds"]`) | Five values set |
| 0.3 | Anyone | root | `tools/status.py --preflight` | Every line PASS, or NOTE: read it |
| 0.4 | Anyone | root | `0-check/preview/preview.sh` | READY. Send the review pack to your security team |
| 1.1 | Anyone | `1-connect` | `terraform init`, then `terraform plan -out=tfplan` | A plan to create the connection and Clumio's IAM |
| STOP | Person | | Read the plan and your security team's answer. Go, or stop | |
| 1.2 | Anyone | `1-connect` | `terraform apply tfplan` | Apply complete |
| 2.1 | Person | AWS | Tag what to protect: `clumio-profile = gold` (an EBS volume on its own: `clumio-volume-profile = gold`). Note each tagged database's PITR window | Tagged before the plan; windows noted |
| 2.2 | Person | `2-protect-<workload>` | `cp settings.example terraform.tfvars`, then set any value marked REPLACE and check the rest | Settings set |
| 2.3 | Anyone | root | `tools/status.py --preflight` | Every line PASS, except the connection: NOTE |
| 2.4 | Anyone | `2-protect-<workload>` | `terraform init`, then `terraform plan -out=tfplan` | Adds one Clumio policy and its rule (S3: its protection group). Nothing to change or destroy |
| STOP | Person | | Read the plan. Go, or stop | |
| 2.5 | Anyone | `2-protect-<workload>` | `terraform apply tfplan`. Repeat 2.1 to 2.5 per workload | Apply complete |
| 3.1 | Anyone | root | `tools/status.py` | Every resource OURS. NOT_YET or WAITING until its first backup, up to a day |
| 3.2 | Person | Clumio console | Restore one resource to a new name beside the original | You open it and check it |
| 3.3 | Anyone | root | `tools/status.py --json > status-$(date -u +%Y%m%d).json` | Evidence for sign-off |

`<workload>`: `s3`, `rds`, `aurora`, `ec2` or `ebs`. Each folder's README has the detail. [Operate](docs/operate.md) explains each status and error.

**Then:** [take the trial down](docs/operate.md#take-a-trial-down), or protect production from your own repository: [Production](docs/production.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
