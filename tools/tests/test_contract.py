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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "stage2f-protected.json")


def replay(answers):
    """A World that answers every call with what AWS and Clumio answered live."""
    def clumio_get(path, unit=None):
        key = f"{unit or ''} {path}"
        if key not in answers["clumio"]:
            raise AssertionError(f"status.py asked Clumio for {path.split('?')[0]} (unit {unit}), a call the live run never made")
        return answers["clumio"][key]

    instances = set(answers["instances"]["us-west-2"])
    # The run's settings said trial; teardown reads only the mode from them.
    handle, settings = tempfile.mkstemp(suffix=".tfvars")
    with os.fdopen(handle, "w") as out:
        out.write('mode = "trial"\n')
    return status.World(
        settings_path=settings, terraform_version=None, aws_cli_found=None, signed_in_account=None, clumio_credentials_set=None,
        clumio_get=clumio_get, kit=lambda: answers["kit"],
        tagged_resources=lambda region: answers["tagged_resources"][region], databases=lambda region: answers["databases"][region],
        volumes=lambda region: answers["volumes"][region], instances=lambda region: instances,
        applied_folders=lambda: [])


class Stage2fProtected(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as recording:
            self.world = replay(json.load(recording))
        self.addCleanup(os.remove, self.world.settings_path)

    def test_coverage_reads_every_resource_as_status_showed_it_live(self):
        # Expected: tools/status.py's live output at the recording, stage 2f: the bucket, the RDS
        # instance and the Aurora cluster OURS, each under its own workload's policy; the bad tag
        # BAD_VALUE; the volume on a tagged instance DOUBLE; the instance and the lone volume NOT_YET,
        # because the unit had no rule slot left for 2-protect-ec2 and 2-protect-ebs.
        records, connection = status.coverage(self.world)
        states = sorted((r["state"], r["kind"]) for r in records)
        self.assertEqual(states, [("BAD_VALUE", "s3"), ("DOUBLE", "ebs-volume"), ("NOT_YET", "ebs-volume"), ("NOT_YET", "ec2-instance"),
                                  ("OURS", "rds-cluster"), ("OURS", "rds-instance"), ("OURS", "s3")])
        self.assertEqual(connection[0], "PASS")
        self.assertTrue(all(r["last_backup"] for r in records if r["state"] == "OURS"))

    def test_the_kits_policies_are_found_by_name_one_per_workload(self):
        profiles = status.kit_profiles(self.world, self.world.kit())
        self.assertEqual(sorted(profiles), ["gold"])
        self.assertEqual(sorted(profiles["gold"]), ["aurora", "ebs", "ec2", "rds", "s3", "s3_group"])

    def test_teardown_reads_nothing_running_as_it_did_live(self):
        # Expected: tools/status.py --teardown said READY at the recording, with the two databases' windows.
        state, lines = status.teardown(self.world)
        self.assertEqual(state, "READY")
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
