"""Tests for proof/capture.py's writer: nothing identifying survives, and the manifest verifies with
shasum, as a skeptic would check it. Run: python3 -m unittest discover -s tests, in proof/."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import capture  # noqa: E402

ACCOUNT = "98765" "4321098"  # built at run time, so this file holds no real-looking account
CLUMIO = "87654" "3210987"
UNIT = "11111111-2222-3333-4444-555555555555"
MASKS = {ACCOUNT: "123456789012", UNIT: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", CLUMIO: "111111111111"}


class WriteCapture(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.join(tempfile.mkdtemp(), "rds-20261028T000000Z")
        files = {"kitlab-aurora-cmk-describe-key": {"KeyMetadata": {"Arn": f"arn:aws:kms:us-west-2:{ACCOUNT}:key/x", "KeyManager": "CUSTOMER"}},
                 "clumio-resource": {"organizational_unit_id": UNIT, "account_native_id": ACCOUNT, "clumio_aws_account_id": CLUMIO}}
        self.lines = capture.write_capture(self.folder, files, MASKS)

    def test_no_account_or_unit_survives_in_any_file(self):
        for name in os.listdir(self.folder):
            text = open(os.path.join(self.folder, name)).read()
            for real in (ACCOUNT, UNIT, CLUMIO):
                self.assertNotIn(real, text, name)
        self.assertIn("123456789012", open(os.path.join(self.folder, "clumio-resource.json")).read())

    def test_the_manifest_verifies_with_shasum(self):
        check = subprocess.run(["shasum", "-a", "256", "-c", "_sha256.txt"], cwd=self.folder, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(len(self.lines), 2)

    def test_an_existing_capture_is_never_overwritten(self):
        with self.assertRaises(FileExistsError):
            capture.write_capture(self.folder, {"x": {}}, MASKS)


class AwsCalls(unittest.TestCase):
    # Live, 2026-10-28: one head-object call hung past 120 seconds, and the capture died with a traceback.
    def test_a_call_that_times_out_stops_with_a_fail_naming_it(self):
        def hang(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 120)
        original, capture.subprocess.run = capture.subprocess.run, hang
        try:
            with self.assertRaises(SystemExit) as stop:
                capture.aws("us-west-2", "s3api", "head-object", "--bucket", "b", "--key", "k")
        finally:
            capture.subprocess.run = original
        self.assertIn("FAIL: aws s3api head-object", str(stop.exception))
        self.assertIn("didn't answer", str(stop.exception))


class LabOutput(unittest.TestCase):
    def test_a_lab_output_without_instances_or_volumes_is_named(self):
        # An older lab output lacked these, and the capture then saved no EC2 or EBS evidence at all.
        self.assertEqual(capture.missing_lab_outputs({"bucket": "b", "rds_amk": "r", "auroras": {}}), ["instances", "volumes"])

    def test_a_full_lab_output_passes(self):
        lab = {"bucket": None, "rds_amk": None, "auroras": {}, "instances": {}, "volumes": {}}
        self.assertEqual(capture.missing_lab_outputs(lab), [])


if __name__ == "__main__":
    unittest.main()
