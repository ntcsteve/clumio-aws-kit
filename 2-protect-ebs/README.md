# Step 2: protect EBS volumes on their own

Protects every EBS volume tagged `clumio-volume-profile = <name>`: volumes you want protected on their own, such as unattached ones. They get a daily SecureVault copy of each volume.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

Follow [Protect](../README.md#protect) in the README, in this folder.

The plan creates one Clumio policy, `<name>-ebs-<account>-<region>`, and a rule that applies it to the tagged volumes.

- Volumes have their own tag key, so none is backed up twice by accident: a volume attached to an instance that [2-protect-ec2](../2-protect-ec2/README.md) protects is already in that instance's copy. `tools/status.py` shows such a volume as DOUBLE.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile: [A second profile](../docs/operate.md#a-second-profile).
