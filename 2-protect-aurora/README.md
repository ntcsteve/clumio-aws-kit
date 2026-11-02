# Step 2: protect Aurora clusters

Protects every Aurora DB cluster (and RDS Multi-AZ DB cluster) tagged `clumio-profile = <name>`. Tag the cluster, not its instances. They get AWS point-in-time recovery (PITR), set by Clumio, a daily SecureVault copy, and an optional monthly archive.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

Follow [Protect](../README.md#protect) in the README, in this folder.

The plan creates one Clumio policy, `<name>-aurora-<account>-<region>`, and a rule that applies it to the tagged clusters.

- If a tagged cluster's PITR window would get shorter, the plan stops and names it. Raise `pitr_retention_days`, or set `allow_shorter_pitr = true` to accept it.
- **Tag before you plan.** The plan checks the windows of what's tagged, and lists each cluster and its window in its `pitr_checked` output. Empty means it found none: check the tags, then plan again. A cluster tagged after apply gets this window with no check: a longer window is cut, and AWS's older backups are deleted.
- Before you apply, note each cluster's window from `pitr_checked`: after teardown the window stays as set, and you can set the old one back.
- The archive copy is built from the SecureVault copy, so its task sits at 1% until that copy is done. In a live run, all three finished within 30 minutes of apply ([evidence](../proof/evidence/archive-lab-2026-10-29/)).

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile: [A second profile](../docs/operate.md#a-second-profile).
