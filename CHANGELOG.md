# Changelog

## v1.0.3 (2026-11-01)

A fresh clone ran live from clone to teardown on S3, and on RDS with a console restore. Docs and messages changed after those runs, tested offline.

- Before you take the kit down: removing the connection ends protection, so restore anything you want to keep first. `tools/status.py --teardown` says so too. The docs no longer say how long copies last after that. A Clumio snapshot of an RDS database can stay in your account.
- `tools/status.py --report --restore-task <id>` writes the evidence as JSON and one HTML page, with one verdict: PROVEN, UNFINISHED or UNKNOWN. PROVEN seen live on S3 and RDS.
- [3-prove](3-prove/README.md) gives the console steps for each workload, and says to clear a tagged copy before the report. NOT_YET says the same for a restored copy. For a bucket, the page's Resource line names its protection group.
- `tools/status.py --teardown` says BLOCKED during a restore: seen live on S3 and on an RDS console restore, which resolves v1.0.1's "tested offline".
- The compliance report email is gone. `report_emails` is removed from `modules/connection`: a caller that set it must drop it.
- The README says what Clumio is and why a restore proves it, as a first step in ResOps.

## v1.0.2 (2026-11-01)

Made for first-time readers and for AI agents. Tested offline, with a cold agent walk of the tools' stops.

- Every result has one meaning and a next step: [AGENTS.md](AGENTS.md#read-every-result-the-same-way) maps each word the tools print to what to do, and NOT_YET, WAITING, a queued task and a connection this kit didn't make now each have a way out in [Operate](docs/operate.md).
- `0-check/preview/preview.sh` exits 0 READY, 1 BLOCKED, 2 CANNOT CHECK. It exited 0 for all three. A script that calls it now sees a non-zero exit when it isn't READY.
- `tools/status.py --preflight` decides whose connection it is from `1-connect`'s state: PASS when `1-connect` made it in this unit, FAIL otherwise. It was a NOTE for both.
- The plan's `pitr_checked` output, from `modules/protect` and the RDS and Aurora folders, lists each database the PITR guard checked. Empty means it found none. A database tagged after apply still gets no check.
- [Production](docs/production.md) says what exit 0 doesn't mean, how to watch for failed backups in Clumio, to repeat step 0, and to take a trial down first in the same account and Region.
- [Does Clumio need our keys?](docs/keys.md) matches the live restores of EC2 and EBS.

## v1.0.1 (2026-10-29)

- `tools/status.py --teardown` now sees a running restore, including one started in the Clumio console. It reads each resource's tasks with no unit. Tested offline; the new request was seen working live.
- Restores, seen live: an EC2 instance and an EBS volume restored in the Clumio console kept the source's key and the original tags. A restored instance's root volume isn't deleted with it. See [3-prove](3-prove/README.md) and [Does Clumio need our keys?](docs/keys.md#what-a-restore-needs-from-you).
- A resource created or tagged after its rule joins at Clumio's next discovery cycle; NOT_YET now says to allow up to a day. See [Know the limits](docs/operate.md#know-the-limits).
- Proven live: production refuses a destroy and a switch to trial, and the retire steps work; EC2 and EBS back up under their own policies; an IAM user holding only the generated deploy policy deployed and removed the kit.

## v1.0.0 (2026-10-29)

The first release. Proven live on 2026-10-28 and 29 in a test account (us-west-2): see [Does Clumio need our keys?](docs/keys.md) and [proof/](proof/README.md) for the evidence, and [Operate](docs/operate.md#know-the-limits) for the limits.

- A README that is the field page: why, what you'll prove, how it works, what's safe, what to prepare, and the run as a table of steps with STOP points, for people and AI agents.
- One Terraform folder per step, each with its own README, settings and state: [0-check](0-check/README.md) (preflight and the IAM preview), [1-connect](1-connect/README.md), a `2-protect-` folder per workload (S3, RDS, Aurora, EC2, EBS), and [3-prove](3-prove/README.md) (status, restore).
- Two modules, `modules/connection` and `modules/protect`, carrying every guard, for [production](docs/production.md) repositories.
- Protection by tag for S3, RDS, Aurora, EC2 and EBS volumes on their own, with one Clumio policy per workload. RDS and Aurora get PITR, SecureVault Standard and SecureVault Archive (Archive proven live on Aurora).
- Guards: wrong account or Region, a shorter PITR window, and production destroy. Before a teardown, `tools/status.py --teardown` checks no backup is running.
- `tools/status.py`: who protects each tagged resource and its last backup, a teardown check, and JSON with exit codes.
- Clumio's compliance report, set with `report_emails`.
