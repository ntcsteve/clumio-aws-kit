# Step 2: protect EC2 instances

Protects every EC2 instance tagged `clumio-profile = <name>`. They get a daily SecureVault copy of each instance, with its attached EBS volumes.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, organizational unit and mode from `1-connect`, so they always match; it stops if `1-connect` isn't applied.

## Run it

1. Tag what you want protected: `clumio-profile = gold` (or your profile's name).
2. In this folder, run `cp settings.example terraform.tfvars`, and set the values marked REPLACE.
3. From the repository root, run `tools/status.py --preflight`: it checks that `1-connect`'s `workloads` covers this folder.
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-ec2-<account>-<region>`, and a rule that applies it to the tagged instances.

- An instance's copy already holds its attached volumes: tag the instance, not its volumes.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md). For a second protection level, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-ec2-silver
cp README.md settings.example *.tf ../2-protect-ec2-silver/
```

Then set `name = "silver"` there.
