# Changelog

## v1.0.0

The first release. Proven live on 2026-10-28 in a test account (us-west-2): see [Does Clumio need our keys?](docs/keys.md) for the evidence, and [Operate](docs/operate.md#know-the-limits) for the limits.

- One Terraform folder per step, each with its own README, settings and state: [0-check](0-check/README.md) (preflight and the IAM preview), [1-connect](1-connect/README.md), a `2-protect-` folder per workload (S3, RDS, Aurora, EC2, EBS), and [3-prove](3-prove/README.md) (status, restore).
- Two modules, `modules/connection` and `modules/protect`, carrying every guard, for [production](docs/production.md) repositories.
- Protection by tag for S3, RDS, Aurora, EC2 and EBS volumes on their own, with one Clumio policy per workload.
- Guards: wrong account or Region, a shorter PITR window, production destroy, and teardown during a backup.
- `tools/status.py`: who protects each tagged resource and its last backup, a teardown check, and JSON with exit codes.
- The compliance report by email (created live; the email itself not yet seen).
