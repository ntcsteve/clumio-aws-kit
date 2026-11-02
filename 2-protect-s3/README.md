# Step 2: protect S3 buckets

Protects every S3 bucket tagged `clumio-profile = <name>`. They get Backtrack (roll a bucket back in place) and a daily SecureVault copy, outside your account.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

Follow [Protect](../README.md#protect) in the README, in this folder.

The plan creates one Clumio policy, `<name>-s3-<account>-<region>`, and a protection group of the tagged buckets, assigned to it.

- Backtrack needs S3 Versioning on the bucket.
- Objects in Glacier storage classes aren't backed up.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile: [A second profile](../docs/operate.md#a-second-profile).
