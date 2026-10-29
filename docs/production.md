# Production

Production teams call the two modules from their own repository, with their own state backend, review and CI. The modules are the product: the step folders are their first-time callers, and every guard lives in the modules, so your repository gets the same checks.

## Call the modules

Use separate roots, as the step folders do: one for the connection, and one per workload you protect, each with its own state. A protect root looks the connection up, so apply the connection first.

```hcl
# Root: connect
terraform {
  required_providers {
    clumio = { source = "clumio-code/clumio", version = "0.24.2" }
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "clumio" {
  clumio_organizational_unit_context = "<unit ID>" # the Global unit is 00000000-0000-0000-0000-000000000000
}

provider "aws" {
  region              = "us-west-2"
  allowed_account_ids = ["123456789012"]
}

module "connection" {
  source     = "git::https://github.com/ntcsteve/clumio-aws-kit.git//modules/connection?ref=v1.0.1"
  account_id = "123456789012"
  region     = "us-west-2"
  mode       = "production"
  workloads  = ["rds", "aurora"]
}
```

```hcl
# Root: protect RDS. The same terraform and provider blocks as above.
module "protect" {
  source               = "git::https://github.com/ntcsteve/clumio-aws-kit.git//modules/protect?ref=v1.0.1"
  workload             = "rds"
  name                 = "gold"
  account_id           = "123456789012"
  region               = "us-west-2"
  mode                 = "production"
  connection_workloads = ["rds", "aurora"] # the connection's workloads: a missing one stops the plan
  keep_days            = 30
  archive_months       = 12
  pitr_retention_days  = 14
}
```

Keep the connection and each protect call in separate roots: in one root, the connection doesn't exist yet when the protect call looks it up at plan time. `1-connect/` and `2-protect-*/` are complete, tested examples.

## What you get

| Guard | In your repository |
|---|---|
| Wrong account or Region stops the plan | Yes, in both modules |
| A shorter PITR window stops the plan, unless `allow_shorter_pitr = true` | Yes, in `modules/protect` |
| `mode = "production"` refuses destroy, a switch to trial, and a new account, Region, name or workload | Yes, in both modules |
| A workload the connection's IAM leaves out stops the plan | Yes, when you pass `connection_workloads` |
| No backup running before a teardown | **No:** `tools/status.py --teardown` reads `1-connect`'s settings and refuses in production. Check Clumio's Tasks before removing protection |

`tools/status.py --account <ID> --region <Region> --unit <unit>` shows who protects each tagged resource, for policies `modules/protect` made in any repository: it finds them by name in Clumio. Add `--json` for CI; the exit code is 0 when nothing needs a person.

## One state per root

Keep one Terraform state per root, per account and Region, and one Clumio tenant across them. A token from another tenant can't see what a state created, and Terraform would create a second set. To protect many accounts, run the same roots once per account and Region in your CI.

## Retire production

Production refuses every destroy on purpose. To retire it, in each protect root first and the connection root last:

1. Remove the guard from state: `terraform state rm 'module.protect.terraform_data.production_guard[0]'` (in the connection root, `module.connection.terraform_data.production_guard[0]`). It's a marker with nothing behind it in AWS or Clumio, so this deletes nothing.
2. Set `mode = "trial"`, then plan and apply once: no resource changes.
3. Check Clumio's Tasks for running backups, then plan the destroy, read it, and apply it.
