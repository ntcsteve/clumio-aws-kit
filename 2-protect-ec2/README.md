# Step 2: protect EC2 instances

Protects every EC2 instance tagged `clumio-profile = <name>`. They get a daily SecureVault copy of each instance, with its attached EBS volumes.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

Follow [Protect](../README.md#protect) in the README, in this folder.

The plan creates one Clumio policy, `<name>-ec2-<account>-<region>`, and a rule that applies it to the tagged instances.

- An instance's copy already holds its attached volumes: tag the instance, not its volumes.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile: [A second profile](../docs/operate.md#a-second-profile).
