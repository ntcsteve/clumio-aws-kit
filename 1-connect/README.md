# Step 1: Connect

Connects one AWS account and Region to Clumio: the connection, and the IAM roles and policies Clumio works through, the ones [step 0](../0-check/README.md) showed. Nothing is protected yet: that's step 2.

Do step 0 first. It makes `terraform.tfvars` in this folder and checks it.

Follow [Connect](../README.md#connect) in the README, in this folder.

The plan creates the connection and Clumio's IAM in this account and Region.

With `mode = "production"`, it adds a guard that refuses destroy, here and in every `2-protect-` folder.

Run this once per account and Region. The `2-protect-` folders read their settings from here, so once applied, never change `account_id`, `region` or `organizational_unit`. For another account or Region, use a fresh clone of the repository, never a copy of this one: a copy carries this state, and its plan would destroy this connection. Going live: [Production](../docs/production.md).

## Next

[Step 2](../README.md#6-what-to-do): protect each workload you need, from its own `2-protect-` folder.
