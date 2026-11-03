"""Contract tests: status.py against the real AWS and Clumio answers recorded live in stage 2f
(fixtures/stage2f-protected.json, 2026-10-28 15:00 UTC, masked; only this kit's policies and groups
kept from Clumio's tenant-wide lists; the same assets' task lists asked with no unit, re-read live
2026-10-29 when teardown began asking that way), not against fakes we wrote. If a
change to status.py misreads a real answer's shape, these fail. Run: python3 -m unittest discover -s
tests, in tools/."""
import json
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
FIXTURE = os.path.join(FIXTURES, "stage2f-protected.json")
# Recorded live on 2026-11-03 at 00:50 UTC, masked: one bucket whose backup skipped an object
# under a key that denied Clumio, and one whose backup skipped nothing.
PARTIAL_FIXTURE = os.path.join(FIXTURES, "b41-partial.json")


def load(path):
    with open(path) as recording:
        return json.load(recording)


def bucket_backup_read(answers, asset_id):
    """The recorded answer to status.py's read of one bucket's backups, by the bucket's Clumio asset ID."""
    return next(answer for key, answer in answers["clumio"].items()
                if "/backups/protection-groups/s3-assets?" in key and asset_id in urllib.parse.unquote(key))


def with_bucket_backup_read(answers):
    """Stage 2f's recording, plus the one read status.py added after it: a bucket's backups (2026-11-03).
    That bucket is gone, so this read can't be recorded for it. Its answer is the 2026-11-03 run's real answer for a bucket
    whose backup skipped nothing, moved to 2f's bucket by asset ID; every other answer is 2f's own."""
    partial = load(PARTIAL_FIXTURE)
    clean_id = "85982216-ee46-51c3-81ee-4f292fce085b"  # kitlab-1178d6-docs in the 2026-11-03 recording
    stage2f_id = "8dc43a62-3c2d-51a2-b9f7-a00b5cd215d1"  # kitlab-c19bd0-docs in the 2f recording
    key = next(key for key in partial["clumio"] if clean_id in urllib.parse.unquote(key)
               and "/backups/protection-groups/s3-assets?" in key)
    answer = json.loads(json.dumps(bucket_backup_read(partial, clean_id)).replace(clean_id, stage2f_id)
                        .replace("kitlab-1178d6-docs", "kitlab-c19bd0-docs"))
    answers["clumio"][key.replace(clean_id, stage2f_id)] = answer
    return answers


def replay(answers):
    """A World that answers every call with what AWS and Clumio answered live."""
    def clumio_get(path, unit=None):
        key = f"{unit or ''} {path}"
        if key not in answers["clumio"]:
            raise AssertionError(f"status.py asked Clumio for {path.split('?')[0]} (unit {unit}), a call the live run never made")
        return answers["clumio"][key]

    # The run's settings said trial; teardown reads only the mode from them.
    handle, settings = tempfile.mkstemp(suffix=".tfvars")
    with os.fdopen(handle, "w") as out:
        out.write('mode = "trial"\n')
    return status.World(
        settings_path=settings, terraform_version=None, aws_cli_found=None, signed_in_account=None, clumio_credentials_set=None,
        clumio_get=clumio_get, kit=lambda: answers["kit"],
        tagged_resources=lambda region: answers["tagged_resources"][region], databases=lambda region: answers["databases"][region],
        volumes=lambda region: answers["volumes"][region], instances=lambda region: set(answers["instances"][region]),
        applied_folders=lambda: [])


class Stage2fProtected(unittest.TestCase):
    def setUp(self):
        self.world = replay(with_bucket_backup_read(load(FIXTURE)))
        self.addCleanup(os.remove, self.world.settings_path)

    def test_coverage_reads_every_resource_as_status_showed_it_live(self):
        # Expected: tools/status.py's live output at the recording, stage 2f: the bucket, the RDS
        # instance and the Aurora cluster PROTECTED, each under its own workload's policy; the bad tag
        # BAD_VALUE; the volume on a tagged instance DOUBLE; the instance and the lone volume NOT_YET,
        # because the unit had no rule slot left for 2-protect-ec2 and 2-protect-ebs.
        records, connection = status.coverage(self.world)
        states = sorted((r["state"], r["kind"]) for r in records)
        self.assertEqual(states, [("BAD_VALUE", "s3"), ("DOUBLE", "ebs-volume"), ("NOT_YET", "ebs-volume"), ("NOT_YET", "ec2-instance"),
                                  ("PROTECTED", "rds-cluster"), ("PROTECTED", "rds-instance"), ("PROTECTED", "s3")])
        self.assertEqual(connection[0], "PASS")
        self.assertTrue(all(r["last_backup"] for r in records if r["state"] == "PROTECTED"))

    def test_the_report_reads_the_real_answers_and_names_what_is_missing(self):
        # Expected from the same run: not finished. Four resources weren't PROTECTED, and no restore had run.
        report = status.evidence(self.world, None, "2026-10-28T15:00:00Z")
        self.assertEqual(report["verdict"], "UNFINISHED")
        self.assertEqual(len(report["gaps"]), 5)
        page = status.render_html(report)
        for resource in report["resources"]:
            self.assertIn(resource["name"], page)

    # The expected terms are read by hand from the saved answer: the settings stage 2f applied.
    def test_the_report_shows_each_policys_frequency_and_retention(self):
        terms = status.evidence(self.world, None, "2026-10-28T15:00:00Z")["policies"]
        s3 = [t for t in terms if t["policy"].startswith("gold-s3-")]
        self.assertEqual([(t["copy"], t["every"], t["kept_for"]) for t in s3],
                         [("SecureVault Standard", "1 day", "30 days"), ("Backtrack", "1 day", "3 months")])
        rds = [t for t in terms if t["policy"].startswith("gold-rds-")]
        self.assertEqual([(t["copy"], t["every"], t["kept_for"]) for t in rds],
                         [("AWS PITR", "1 day", "7 days"), ("SecureVault Standard", "1 day", "7 days")])

    def test_the_kits_policies_are_found_by_name_one_per_workload(self):
        profiles = status.kit_profiles(self.world, self.world.kit())
        self.assertEqual(sorted(profiles), ["gold"])
        self.assertEqual(sorted(profiles["gold"]), ["aurora", "ebs", "ec2", "rds", "s3", "s3_group"])

    def test_teardown_reads_nothing_running_as_it_did_live(self):
        # Expected: tools/status.py --teardown said READY at the recording, with the two databases' windows.
        state, lines = status.teardown(self.world)
        self.assertEqual(state, "READY")
        self.assertEqual(len(lines), 2)


class PartialBackup(unittest.TestCase):
    def setUp(self):
        self.world = replay(load(PARTIAL_FIXTURE))
        self.addCleanup(os.remove, self.world.settings_path)

    def test_a_backup_that_skipped_an_object_reads_partial_as_it_did_live(self):
        # Expected: tools/status.py's live output on 2026-11-03 at 00:49 UTC: the bucket with the
        # denied object PARTIAL, skipped 1; the other PROTECTED; exit 1.
        records, connection = status.coverage(self.world)
        states = {r["name"]: r["state"] for r in records}
        self.assertEqual(states, {"kitlab-1178d6-denied": "PARTIAL", "kitlab-1178d6-docs": "PROTECTED"})
        self.assertIn("skipped 1 object", next(r["detail"] for r in records if r["state"] == "PARTIAL"))
        self.assertEqual(status.coverage_exit_code(records, connection), 1)

    def test_the_report_names_the_partial_bucket(self):
        # Expected from the same run: UNFINISHED, the denied bucket PARTIAL, and no restore recorded.
        report = status.evidence(self.world, None, "2026-11-03T00:50:03Z")
        self.assertEqual(report["verdict"], "UNFINISHED")
        self.assertTrue(report["gaps"][0].startswith("kitlab-1178d6-denied: PARTIAL."))


if __name__ == "__main__":
    unittest.main()
