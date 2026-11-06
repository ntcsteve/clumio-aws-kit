# Changelog

## v1.2.2 (unreleased)

- Docs only, from a first-timer read:
  - the README's safety list says the PITR check covers only databases tagged when you plan;
  - the IAM preview's FAIL result is documented;
  - the second-profile commands end in the new folder, so `cp` can't overwrite the first profile's settings;
  - Operate names the error a protect folder shows after `1-connect` is destroyed;
  - the source-gone test says test database only, after the report;
  - "trial" replaces "proof of concept" in the settings comments;
  - one code comment now describes `pitr_now` correctly.

## v1.2.1 (2026-11-03)

- Docs only: one term per idea ("seen live", "target"), README sections without numbers that clashed with step numbers, production says which of steps 3.1 to 3.3 to run, and test comments cite dates, not private run names.

## v1.2.0 (2026-11-03)

- `tools/status.py` says PARTIAL for a bucket whose last backup skipped objects, and the report says UNFINISHED. It said PROTECTED and PROVEN, because the backup still completed. Seen live on 2026-11-03.
- `tools/status.py --report` lists each policy's frequency and retention, and `--recovery-target-minutes` says MET or MISSED beside the restore time.
- Seen live on 2026-11-02 and in the docs: one object restored; a bucket rolled back in place with Backtrack; an S3 restore with the source's key disabled; an RDS restore with the database and AWS's own backups deleted; a backup that skipped an object, and where Clumio shows it. Your restore time against a target, seen live as MET.
- The README opens with what you'll see with Clumio, and says where copies live. [Operate](docs/operate.md#delete-a-backup) says how deleting a backup works.
- Going live is one path: a fresh clone in your production account, with Terraform's state in S3. [Production](docs/production.md) replaces calling the modules from your own repository. `tools/use_s3_state.py` sets the state up.
- `tools/status.py` no longer takes `--account`, `--region` or `--unit`: it reads them from `1-connect/terraform.tfvars`. A script that passes them now stops with a usage error.
- `tools/status.py` says PROTECTED where it said OURS, in its output and in `--json`. A script that reads the old word must change.
- `tools/status.py` reads the connection's status: HTTP 200 alone no longer passes. It asks Terraform for state, so it works with any backend, and it never claims a connection whose state it can't read.
- The README's steps run from preparing to taking a trial down, and folder READMEs keep only what's unique. [Retire a production connection](docs/production.md#retire-a-production-connection) moved to Production.
- `tools/status.py` says NOT_YET, not OTHER, for a bucket whose policy hasn't attached yet. OTHER told you to remove an assignment that didn't exist.
- [3-prove](3-prove/README.md#4-optional-restore-with-the-source-gone) shows a deleted test bucket restored from Clumio's copy, seen live on S3.
- [2-protect-rds](2-protect-rds/README.md) says what turning PITR on and raising a window did live.
- The README says what you'll see, and that this kit is independent.

## v1.0.3 (2026-11-01)

Fresh clones ran live from clone to teardown on all five workloads, each with a console restore, and an AI agent that had read only the kit ran the S3 trial live from the docs alone. The S3 and Aurora run used this version's code; the last doc fixes came after it, tested offline.

- Before you take the kit down: removing the connection ends protection, so restore anything you want to keep first. `tools/status.py --teardown` says so too. [Take a trial down](README.md#take-a-trial-down) has one decision path and lists what's yours to clear, including a Clumio RDS snapshot.
- `tools/status.py --report --restore-task <id>` writes the evidence as JSON and one HTML page, with one verdict: PROVEN, UNFINISHED or UNKNOWN. PROVEN seen live on all five workloads. The restore must be of a resource this run protects: another task ID gives UNFINISHED. Seen live on S3; the other workloads are tested on task shapes read live.
- [3-prove](3-prove/README.md) gives the console steps for each workload, and says to clear a tagged copy before the report. NOT_YET says the same for a restored copy.
- `tools/status.py --teardown` says BLOCKED during a restore: seen live on all five workloads, which resolves v1.0.1's "tested offline".
- [When something goes wrong](docs/operate.md#when-something-goes-wrong) covers a resource marked tainted after a dropped connection, and an expired AWS sign-in.
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
- A resource created or tagged after its rule joins at Clumio's next discovery cycle; NOT_YET now says to allow up to a day. See [How it behaves](docs/operate.md#how-it-behaves).
- Proven live: production refuses a destroy and a switch to trial, and the retire steps work; EC2 and EBS back up under their own policies; an IAM user holding only the generated deploy policy deployed and removed the kit.

## v1.0.0 (2026-10-29)

The first release. Proven live on 2026-10-28 and 29 in a test account (us-west-2): see [Does Clumio need our keys?](docs/keys.md) and [proof/](proof/README.md) for the evidence, and [Operate](docs/operate.md#how-it-behaves) for the limits.

- A README that is the field page: why, what you'll prove, how it works, what's safe, what to prepare, and the run as a table of steps with STOP points, for people and AI agents.
- One Terraform folder per step, each with its own README, settings and state: [0-check](0-check/README.md) (preflight and the IAM preview), [1-connect](1-connect/README.md), a `2-protect-` folder per workload (S3, RDS, Aurora, EC2, EBS), and [3-prove](3-prove/README.md) (status, restore).
- Two modules, `modules/connection` and `modules/protect`, carrying every guard, for [production](docs/production.md) repositories.
- Protection by tag for S3, RDS, Aurora, EC2 and EBS volumes on their own, with one Clumio policy per workload. RDS and Aurora get PITR, SecureVault Standard and SecureVault Archive (Archive proven live on Aurora).
- Guards: wrong account or Region, a shorter PITR window, and production destroy. Before a teardown, `tools/status.py --teardown` checks no backup is running.
- `tools/status.py`: who protects each tagged resource and its last backup, a teardown check, and JSON with exit codes.
- Clumio's compliance report, set with `report_emails`.
