"""Contract tests: status.py against the real AWS and Clumio answers recorded live in stage 2d
(fixtures/stage2d-protected.json, 2026-10-28 11:05 UTC, masked), not against fakes we wrote. If a
change to status.py misreads a real answer's shape, these fail. Run: python3 -m unittest discover -s
tests, in tools/."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "stage2d-protected.json")


def replay(answers):
    """A World that answers every call with what AWS and Clumio answered live."""
    def clumio_get(path, unit=None):
        key = f"{unit or ''} {path}"
        if key not in answers["clumio"]:
            raise AssertionError(f"status.py asked Clumio for {path.split('?')[0]} (unit {unit}), a call the live run never made")
        return answers["clumio"][key]

    # The recording predates status.py's instance check. Both lab instances were running when it was
    # made (they were destroyed at 11:49 UTC), so the live instances are the two tagged ones.
    instances = {arn.rsplit("/", 1)[1] for arn in (r["ResourceARN"] for r in answers["tagged_resources"]["us-west-2"]) if ":instance/" in arn}
    # The run's settings said trial; teardown reads only the mode from them.
    handle, settings = tempfile.mkstemp(suffix=".tfvars")
    with os.fdopen(handle, "w") as out:
        out.write('mode = "trial"\n')
    return status.World(
        settings_path=settings, terraform_version=None, aws_cli_found=None, signed_in_account=None, clumio_credentials_set=None,
        clumio_get=clumio_get, kit=lambda: answers["kit"],
        tagged_resources=lambda region: answers["tagged_resources"][region], databases=lambda region: answers["databases"][region],
        volumes=lambda region: answers["volumes"][region], instances=lambda region: instances)


class Stage2dProtected(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as recording:
            self.world = replay(json.load(recording))
        self.addCleanup(os.remove, self.world.settings_path)

    def test_coverage_reads_every_resource_as_status_showed_it_live(self):
        # Expected: tools/status.py's live output at 11:00 UTC the same day (RESULTS, stage 2d step 9):
        # 8 OURS, the bad tag BAD_VALUE, the volume on a protected instance DOUBLE. The tagging API also
        # listed both Aurora clusters under their resource IDs; those must not appear.
        records, connection = status.coverage(self.world)
        states = {}
        for r in records:
            states[r["state"]] = states.get(r["state"], 0) + 1
        self.assertEqual(states, {"OURS": 8, "BAD_VALUE": 1, "DOUBLE": 1})
        self.assertEqual(connection[0], "PASS")
        self.assertFalse([r["name"] for r in records if r["name"].startswith("cluster-")])
        self.assertTrue(all(r["last_backup"] for r in records if r["state"] == "OURS"))

    def test_teardown_reads_nothing_running_as_it_did_live(self):
        # Expected: tools/status.py --teardown said READY at 11:00 UTC, with the three databases' windows.
        state, lines = status.teardown(self.world)
        self.assertEqual(state, "READY")
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
