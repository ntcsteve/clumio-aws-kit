# Changelog

## v1.0.0

The first release. Proven live on 2026-10-28 and 29 in a test account (us-west-2): see [Does Clumio need our keys?](docs/keys.md) and [proof/](proof/README.md) for the evidence, and [Operate](docs/operate.md#know-the-limits) for the limits.

- A README that is the field page: why, what you'll prove, how it works, what's safe, what to prepare, and the run as a table of steps with STOP points, for people and AI agents.
- One Terraform folder per step, each with its own README, settings and state: [0-check](0-check/README.md) (preflight and the IAM preview), [1-connect](1-connect/README.md), a `2-protect-` folder per workload (S3, RDS, Aurora, EC2, EBS), and [3-prove](3-prove/README.md) (status, restore).
- Two modules, `modules/connection` and `modules/protect`, carrying every guard, for [production](docs/production.md) repositories.
- Protection by tag for S3, RDS, Aurora, EC2 and EBS volumes on their own, with one Clumio policy per workload. RDS and Aurora get PITR, SecureVault Standard and SecureVault Archive (Archive proven live on Aurora).
- Guards: wrong account or Region, a shorter PITR window, and production destroy. Before a teardown, `tools/status.py --teardown` checks no backup is running.
- `tools/status.py`: who protects each tagged resource and its last backup, a teardown check, and JSON with exit codes.
- The compliance report by email (created live; the email itself not yet seen).
