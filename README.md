# clumio-aws-kit

Set Clumio up on AWS with Terraform: connect one account and Region, then back up S3 buckets, RDS databases, Aurora clusters, EC2 instances and EBS volumes by tag. Every guard that keeps a first run safe is built in, and each claim says whether it was checked live.

This is not an official Clumio product. It uses Clumio's Terraform provider and IAM module, pinned to tested versions. For problems with the Clumio service, contact Clumio support.

## Choose your path

| You want to | Go to |
|---|---|
| Know whether Clumio needs your encryption keys | [Does Clumio need our keys?](docs/keys.md) |
| Run a trial or a proof of concept | [The steps](#the-steps) below |
| Protect production from your own repository | [Production](docs/production.md) |
| Fix something, read status, or take a trial down | [Operate](docs/operate.md) |

## The steps

Each step is a folder with its own README. Read them in order. Each Terraform folder holds one job, its own settings and its own state.

| Step | Folder | What it does | Changes anything? |
|---|---|---|---|
| 0 | [0-check](0-check/README.md) | Checks your tools, sign-in, token and settings, and shows every IAM role Clumio will create | No |
| 1 | [1-connect](1-connect/README.md) | Connects your account and Region to Clumio, with Clumio's IAM roles | Yes |
| 2 | [2-protect-s3](2-protect-s3/README.md), [-rds](2-protect-rds/README.md), [-aurora](2-protect-aurora/README.md), [-ec2](2-protect-ec2/README.md), [-ebs](2-protect-ebs/README.md) | One Clumio policy per workload, for what you tag `clumio-profile = gold` (EBS volumes on their own: `clumio-volume-profile = gold`). Use only the ones you need | Yes |
| 3 | [3-prove](3-prove/README.md) | Shows who protects each resource, then you restore one | Only the restore you start |

Every Terraform folder works the same way: `cp settings.example terraform.tfvars`, set the values, then `terraform init`, `terraform plan -out=tfplan`, read it, `terraform apply tfplan`.

```
0-check ──> 1-connect ──> 2-protect-<workload>, any you need ──> 3-prove
read-only   once per      one policy each: s3, rds, aurora,       status,
            account and   ec2, ebs                                 restore
            Region
```

To take a trial down, reverse the numbers: see [Take a trial down](docs/operate.md#take-a-trial-down).

## What keeps a first run safe

- **Wrong account:** every plan stops if you're signed in to another AWS account.
- **Shorter backups:** a plan stops if it would shorten a database's point-in-time recovery window, which deletes AWS's older backups for good, unless you accept it in writing.
- **Production:** with `mode = "production"`, Terraform refuses to destroy the connection or any protection.
- **Mid-backup teardown:** `tools/status.py --teardown` tells you to wait while Clumio is still backing up. It's a step you run: Terraform doesn't check this.
- **No data deleted:** the kit removes only what it created. Backups stay until their retention ends.

## You need

Terraform 1.10 or later, the AWS CLI v2, Python 3.9 or later, an AWS sign-in to the account, and a Clumio API token. macOS and Linux; on Windows, WSL.

## What it doesn't do

Bring your own key (BYOK), DynamoDB, other backup products, many accounts at once, or restores. You restore in the Clumio console. What has and hasn't been proven live is in [Does Clumio need our keys?](docs/keys.md#what-isnt-proven) and [Operate](docs/operate.md#know-the-limits).

## License

Apache-2.0. See [LICENSE](LICENSE).
