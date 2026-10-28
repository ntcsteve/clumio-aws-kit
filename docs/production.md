# Production

Production teams call the two modules from their own repository, with their own state backend, review and CI. The modules are the product: `deploy/` is only their first-time caller, and every guard it relies on lives in the modules, so your repository gets the same checks.

## Call the modules

Pin a release tag, so an upgrade is a reviewed change of `ref`:

```hcl
provider "clumio" {
  clumio_organizational_unit_context = "<unit ID>" # the unit the connection and its rules belong to
}

provider "aws" {
  region              = "us-west-2"
  allowed_account_ids = ["123456789012"]
}

module "connection" {
  source     = "git::https://github.com/ntcsteve/clumio-aws-kit.git//modules/connection?ref=v1.0.0"
  account_id = "123456789012"
  region     = "us-west-2"
  mode       = "production"
}

module "profile_gold" {
  source              = "git::https://github.com/ntcsteve/clumio-aws-kit.git//modules/profile?ref=v1.0.0"
  name                = "gold"
  connection_id       = module.connection.connection_id
  account_id          = "123456789012"
  region              = "us-west-2"
  mode                = "production"
  s3                  = true
  databases           = true
  keep_days           = 30
  archive_months      = 12
  pitr_retention_days = 14
}
```

Pass `connection_id` from the connection module, never a module-wide `depends_on`: it makes protection wait for Clumio's IAM, and keeps the profile's database reads at plan time, where the PITR guard needs them. `deploy/main.tf` is a complete, tested example of both calls.

## What you get, and what you don't

| Guard | Where | In your repository |
|---|---|---|
| Wrong account or Region stops the plan | Both modules | Yes |
| A shorter PITR window stops the plan, unless `allow_shorter_pitr = true` | `modules/profile` | Yes |
| `mode = "production"` refuses destroy, a switch to trial, and a new account or Region | Both modules | Yes |
| A profile's workload must have Clumio's IAM in the connection (`workloads`) | `deploy/variables.tf` only | **No:** keep each profile's workloads within the connection's `workloads` yourself |
| No backup running before a teardown | `tools/status.py --teardown` | **No:** it reads `deploy/`. Check Clumio's Tasks before removing a profile |

`tools/status.py` reads `deploy/`'s settings and state, so in v1.0 it doesn't run against your repository. Clumio's console shows each asset's policy and last backup.

## One state per account and Region

Keep one Terraform state for each account and Region, and one Clumio tenant per state. A token from another tenant can't see what a state created, and Terraform would create a second set. To protect many accounts, run the same root once per account and Region in your CI.

## Retire production

Production refuses every destroy on purpose. To retire it, see [Retire a production connection](operate.md#retire-a-production-connection).
