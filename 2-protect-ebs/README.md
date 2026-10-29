# Step 2: protect EBS volumes on their own

Protects every EBS volume tagged `clumio-volume-profile = <name>`: volumes you want protected on their own, such as unattached ones. They get a daily SecureVault copy of each volume.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

## Run it

1. Tag what to protect: `clumio-volume-profile = gold`, or your profile's name.
2. Here, run `cp settings.example terraform.tfvars`, then check the values.
3. From the repository root, run `tools/status.py --preflight`. This folder adds one rule to the organizational unit, and a unit holds only a few: preflight checks there's room ([the limit](../docs/operate.md#when-something-goes-wrong), error 107).
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-ebs-<account>-<region>`, and a rule that applies it to the tagged volumes.

- Volumes have their own tag key, so none is backed up twice by accident: a volume attached to an instance that [2-protect-ec2](../2-protect-ec2/README.md) protects is already in that instance's copy. `tools/status.py` shows such a volume as DOUBLE.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-ebs-silver
cp README.md settings.example *.tf .terraform.lock.hcl ../2-protect-ebs-silver/
```

In the new folder, run `cp settings.example terraform.tfvars` and set `name = "silver"` before you plan: two folders with one name would make the same policy.
