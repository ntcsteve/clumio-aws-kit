# Step 2: protect EC2 instances

Protects every EC2 instance tagged `clumio-profile = <name>`. They get a daily SecureVault copy of each instance, with its attached EBS volumes.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

## Run it

1. Tag what to protect: `clumio-profile = gold`, or your profile's name.
2. Here, run `cp settings.example terraform.tfvars`, then check the values.
3. From the repository root, run `tools/status.py --preflight`. This folder adds one rule to the organizational unit, and a unit holds only a few: preflight checks there's room ([the limit](../docs/operate.md#when-something-goes-wrong), error 107).
4. Here, run `terraform init`, then `terraform plan -out=tfplan`. Read the plan, then run `terraform apply tfplan`.

The plan creates one Clumio policy, `<name>-ec2-<account>-<region>`, and a rule that applies it to the tagged instances.

- An instance's copy already holds its attached volumes: tag the instance, not its volumes.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile, such as `silver`, copy this folder's files, never its state:

```bash
mkdir ../2-protect-ec2-silver
cp README.md settings.example *.tf .terraform.lock.hcl ../2-protect-ec2-silver/
```

In the new folder, run `cp settings.example terraform.tfvars` and set `name = "silver"` before you plan: two folders with one name would make the same policy.
