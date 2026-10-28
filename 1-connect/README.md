# Step 1: Connect

Connects one AWS account and Region to Clumio: the connection, and the IAM roles and policies Clumio works through, the ones [step 0](../0-check/README.md) showed. Nothing is protected yet: that's step 2.

Do step 0 first. It makes `terraform.tfvars` in this folder and checks it.

## Run it

In this folder, in the shell where you exported `CLUMIO_API_BASE_URL` and `CLUMIO_API_TOKEN`:

```bash
terraform init
terraform plan -out=tfplan     # read it
terraform apply tfplan
```

The plan creates the connection and Clumio's IAM in this account and Region. With `report_emails`, it adds Clumio's daily compliance report. With `mode = "production"`, it adds a guard that refuses destroy, here and in every `2-protect-` folder. For production, keep each folder's Terraform state somewhere safe and shared, or call the modules from your own repository: see [Production](../docs/production.md).

Run this once per account and Region. The `2-protect-` folders read the account, Region, unit and mode from here. Never change `account_id`, `region` or `organizational_unit` in an applied folder: for another account or Region, copy the whole repository.

## Next

[Step 2](../README.md#the-steps): protect each workload you need, from its own `2-protect-` folder.
