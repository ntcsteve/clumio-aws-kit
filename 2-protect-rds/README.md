# Step 2: protect RDS databases

Protects every RDS DB instance tagged `clumio-profile = <name>` (Aurora clusters: [2-protect-aurora](../2-protect-aurora/README.md)). They get AWS point-in-time recovery (PITR), set by Clumio, a daily SecureVault copy, and an optional monthly archive.

Do [step 1](../1-connect/README.md) first. This folder reads the account, Region, unit and mode from `1-connect`, so they always match. It stops if `1-connect` isn't applied.

Follow [Protect](../README.md#protect) in the README, in this folder.

The plan creates one Clumio policy, `<name>-rds-<account>-<region>`, and a rule that applies it to the tagged instances.

- If a tagged database's PITR window would get shorter, the plan stops and names it. Raise `pitr_retention_days`, or set `allow_shorter_pitr = true` to accept it.
- Where PITR is off, Clumio turns it on at the next maintenance window, because turning it on restarts an RDS instance.
- **Tag before you plan.** The plan checks the windows of what's tagged, and lists each database and its window in its `pitr_checked` output. Empty means it found none: check the tags, then plan again. A database tagged after apply gets this window with no check: a longer window is cut, and AWS's older backups are deleted.
- Before you apply, note each database's window from `pitr_checked`: after teardown the window stays as set, and you can set the old one back.

## Next

Protect another workload, or go to [step 3](../3-prove/README.md).

For a second profile: [A second profile](../docs/operate.md#a-second-profile).
