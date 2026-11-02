# Clumio Get Started AWS Kit

Prove that [Clumio by Commvault](https://www.clumio.com/) protects and restores your AWS data, from your own account, in two sittings, then take it down. For the engineer running the trial, the forward deployed engineer, and AI agents helping them ([rules for agents](AGENTS.md)).

This kit uses Clumio's Terraform provider and IAM module, pinned to tested versions. It's an independent kit, not an official Clumio or Commvault product. Clumio is a trademark of its owner. For the Clumio service, contact Clumio support. For this kit, open an issue.

## 1. Why care, and is this for you

Backups in the same account as the data fall with it: a deleted account, a stolen admin key or ransomware takes both. Clumio describes where your backups live as [a dedicated, air-gapped, immutable vault outside your cloud account](https://www.clumio.com/platform). This kit sets Clumio up with plain Terraform, protects what you tag, and shows you each backup and a restore. You decide on evidence.

This is a first step in [Resilience Operations (ResOps)](https://www.commvault.com/explore/resilience-operations), Commvault's discipline for recovering within defined impact tolerances, and proving it with evidence. Backup answers "do we have copies?". This kit proves a restore, and leaves you the evidence.

This kit covers one AWS account and Region, and five workloads: S3, RDS, Aurora, EC2 and EBS. You restore in the Clumio console.

## 2. What you'll see

| You'll see | Where to look |
|---|---|
| Every IAM role and permission Clumio gets, before anything exists | [0-check](0-check/README.md) |
| What you tag, backed up: S3, RDS, Aurora, EC2, EBS | [Keys evidence](proof/evidence/keys-lab-2026-10-28/) |
| How often it runs and how long copies stay, in one policy per workload | [Each protect folder's settings](2-protect-rds/settings.example) |
| One policy running your database's AWS point-in-time recovery (PITR), a daily SecureVault Standard copy and a monthly SecureVault Archive copy | [Archive evidence](proof/evidence/archive-lab-2026-10-29/), for Aurora |
| Your own data restored, and how long it took | [3-prove](3-prove/README.md#2-restore-one) |
| Copies outside your account: [in your data's Region by default](https://www.clumio.com/platform), the setting this kit leaves in place | [How it works](#3-how-it-works) |
| Your keys staying yours, AWS-managed or customer-managed | [Does Clumio need our keys?](docs/keys.md) |
| A verdict and the evidence behind it, for sign-off | [3-prove](3-prove/README.md#3-keep-the-evidence) |
| Backups, restores and failures, in Clumio's Tasks, Alerts and Reports | [Watch your backups](docs/production.md#watch-your-backups) |
| Teardown removing everything the kit created | [Take a trial down](#take-a-trial-down) |

See also [Not covered here](docs/keys.md#not-covered-here) and [How it behaves](docs/operate.md#how-it-behaves).

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

## 4. What it touches

**What it creates.** Step 1: the Clumio connection, Clumio's IAM roles and policies, EventBridge rules and an SNS topic. Step 0 shows them before they exist. Step 2: one Clumio policy per workload, with a rule (S3: a protection group).

**What it changes.** Clumio sets each tagged database's PITR window to the policy's value. Where PITR is off, it turns it on, which restarts an RDS instance at its maintenance window. During a backup, Clumio uses snapshots in your account. Step 0's preview lists every permission Clumio's roles hold, such as changing an S3 bucket's event notifications.

**Before you take it down.** Removing the connection ends protection for that account and Region, so restore anything you want to keep first. Each database's PITR window stays as the policy set it, so note it before step 2. [Take a trial down](#take-a-trial-down) lists what's yours to clear.

**What stops a mistake.**

- **Wrong account:** every plan stops if you're signed in to another AWS account.
- **Shorter backups:** a plan stops if it would shorten a database's PITR window, which deletes AWS's older backups for good, unless you accept it in writing.
- **Production:** with `mode = "production"`, Terraform refuses to destroy the connection or a policy.
- **Mid-backup teardown:** `tools/status.py --teardown` says wait while Clumio is backing up. You run it; Terraform doesn't.
- **Your resources:** the kit removes only what it created.

## 5. Plan and prepare

| What | Detail |
|---|---|
| People | Someone who may create IAM roles in the account. A security reviewer for the IAM preview. A Clumio administrator for the API token and the organizational unit |
| Tools | Terraform 1.10 or later, the AWS CLI v2, Python 3.9 or later. macOS or Linux; on Windows, WSL |
| Decide | The account and Region. The Clumio organizational unit. `mode`: `trial` for a test account. `workloads`: only what you'll test, so Clumio gets no more IAM than that. What to tag, and the profile name, such as `gold`. How long to keep copies |
| Check | Each database's PITR window: set `pitr_retention_days` at least that long. One free Clumio rule slot per RDS, Aurora, EC2 or EBS folder: preflight counts them. Outbound HTTPS to the Terraform registry and your Clumio API URL. Your SCPs and data-perimeter rules: preflight can't test them, so ask your cloud security team whether they allow Clumio's cross-account roles |
| Time | About a dozen commands, in two sittings: steps 0 to 1.1 before your security team's review, 1.2 onward after it. First backups came within an hour in the lab; allow up to a day |
| Cost | Clumio bills each copy while it's kept. Archive is built for 12 months or longer: a shorter copy has an early-deletion fee. To see Archive in a test, set `archive_months = 1`; 0 skips it |

## 6. What to do

Run each command in the folder under Where, in one shell: the one signed in to AWS, with the Clumio details exported. **Person**: a person does it. **STOP**: wait for a person's go. **Anyone**: a person or an agent. `<workload>` is `s3`, `rds`, `aurora`, `ec2` or `ebs`. [Operate](docs/operate.md) explains each status and error.

### Prepare

See everything Clumio will get, before anything exists.

| Step | Who | Where | Do | Expect |
|---|---|---|---|---|
| 0.1 | Person | shell | Sign in to AWS. Export `CLUMIO_API_BASE_URL` and `CLUMIO_API_TOKEN`, as [0-check](0-check/README.md) shows | `aws sts get-caller-identity` shows your account |
| 0.2 | Person | root | `cp 1-connect/settings.example 1-connect/terraform.tfvars`, then set `account_id`, `region`, `organizational_unit`, `mode` and `workloads` (such as `["rds"]`) | Five values set |
| 0.3 | Anyone | root | `tools/status.py --preflight` | Every line PASS, or NOTE: read it |
| 0.4 | Anyone | root | `0-check/preview/preview.sh` | READY: send the review pack to your security team. BLOCKED or CANNOT CHECK: stop, and see [0-check](0-check/README.md) |

### Connect

Give Clumio its roles in your account, once your security team agrees.

| Step | Who | Where | Do | Expect |
|---|---|---|---|---|
| 1.1 | Anyone | `1-connect` | `terraform init`, then `terraform plan -out=tfplan` | A plan to create the connection and Clumio's IAM. Nothing to change or destroy |
| STOP | Person | | Read the plan and your security team's answer. Go, or stop | |
| 1.2 | Anyone | `1-connect` | `terraform apply tfplan` | Apply complete |

### Protect

Tag what matters, and set how long to keep it. Repeat per workload.

| Step | Who | Where | Do | Expect |
|---|---|---|---|---|
| 2.1 | Person | AWS | Tag what to protect: `clumio-profile = gold` (an EBS volume on its own: `clumio-volume-profile = gold`). Note each tagged database's PITR window | Tagged before the plan; windows noted |
| 2.2 | Person | `2-protect-<workload>` | `cp settings.example terraform.tfvars`, then set any value marked REPLACE and check the rest | Settings set |
| 2.3 | Anyone | root | `tools/status.py --preflight` | Every line PASS, or NOTE: read it |
| 2.4 | Anyone | `2-protect-<workload>` | `terraform init`, then `terraform plan -out=tfplan` | Adds one Clumio policy and its rule (S3: its protection group), and markers that create nothing. Nothing to change or destroy. RDS and Aurora: `pitr_checked` lists each database. Empty means none found: stop, and check the tags |
| STOP | Person | | Read the plan. Go, or stop | |
| 2.5 | Anyone | `2-protect-<workload>` | `terraform apply tfplan` | Apply complete |

### Prove

See the backup, restore it, and keep the evidence.

| Step | Who | Where | Do | Expect |
|---|---|---|---|---|
| 3.1 | Anyone | root | `tools/status.py` | Every resource PROTECTED. NOT_YET or WAITING until its first backup, up to a day |
| 3.2 | Person | Clumio console | Restore one resource to a new name beside the original: [the steps per workload](3-prove/README.md#2-restore-one) | You open it and check it, and note the task ID. If the copy carries a profile tag, delete it or remove the tag |
| 3.3 | Anyone | root | `tools/status.py --report --restore-task <task ID>` | PROVEN, with a JSON file and an HTML page for sign-off. UNFINISHED lists what's missing |

To go live, use a fresh clone in your production account: [Production](docs/production.md).

### Take a trial down

Leave the test account as you found it. Removing the connection ends protection for this account and Region, so restore anything you want to keep first. Each protect folder goes first and the connection last, because a protect folder needs the connection to plan its own removal.

| Step | Who | Where | Do | Expect |
|---|---|---|---|---|
| 4.1 | Person | AWS | Restore anything you want to keep, and remove the copy's profile tag. Delete the test copies you don't need. Leave the originals' tags in place: the next check finds running backups through them | Only what you're keeping remains |
| 4.2 | Anyone | root | `tools/status.py --teardown` | READY: go on. BLOCKED: wait, then run it again. REFUSED: this is production, see [Retire a production connection](docs/production.md#retire-a-production-connection). UNKNOWN: fix what it says, then run it again |
| 4.3 | Anyone | a `2-protect-` folder you applied | `terraform plan -destroy -out=tfplan` | A plan to destroy what that folder added |
| STOP | Person | | Read the plan. Go, or stop | |
| 4.4 | Anyone | the same folder | `terraform apply tfplan` | Destroy complete. Repeat 4.3 and 4.4 per folder |
| 4.5 | Anyone | `1-connect` | `terraform plan -destroy -out=tfplan` | A plan to destroy the connection and Clumio's IAM |
| STOP | Person | | Read the plan. Go, or stop | |
| 4.6 | Anyone | `1-connect` | `terraform apply tfplan` | Destroy complete |
| 4.7 | Anyone | each folder you applied | `terraform state list` | Prints nothing |
| 4.8 | Person | AWS, Clumio console | Clear what's yours, below | Nothing of the trial left |

Terraform removes only what the kit made. The rest is yours:

| What | When | What to do |
|---|---|---|
| Restored copies and objects | Any time | Delete what you don't need. Terraform can't see them |
| Each database's PITR window | After 4.7 | It stays as the policy set it. A shorter window deletes AWS's older backups: set back the window you noted only if that's what you want |
| The profile tags | After 4.7 | Remove `clumio-profile` and `clumio-volume-profile`, so a later setup doesn't pick these resources up |
| Clumio's RDS snapshot | After 4.7 | One may remain in your account, named `clumio-airgap-encrypted-…`, under RDS manual snapshots. Delete it when you're finished |
| Your Clumio API token | After 4.7 | Revoke it in the Clumio console, where you created it, unless you still need it |

## License

Apache-2.0. See [LICENSE](LICENSE).
