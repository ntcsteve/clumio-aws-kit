# Step 2: protect EBS volumes on their own

Protects every EBS volume tagged `clumio-volume-profile = <name>`: volumes you want protected on their own, such as unattached ones. They get a daily SecureVault copy of each volume.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, organizational unit and mode from `1-connect`, so they always match; it stops if `1-connect` isn't applied.

## Run it

1. Tag what you want protected: `clumio-volume-profile = gold` (or your profile's name).
2. In this folder, run `cp settings.example terraform.tfvars`, and set the values marked REPLACE.
3. From the repository root, run `tools/status.py --preflight`: it checks that `1-connect`'s `workloads` covers this folder.
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-ebs-<account>-<region>`, and a rule that applies it to the tagged volumes.

- Its own tag key, so a volume is never backed up twice by accident: a volume attached to an instance [2-protect-ec2](../2-protect-ec2/README.md) protects is already in that instance's copy. `tools/status.py` calls a volume tagged both ways DOUBLE.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md). For a second protection level, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-ebs-silver
cp README.md settings.example *.tf ../2-protect-ebs-silver/
```

Then set `name = "silver"` there.
