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
UNIT = "11111111-2222-3333-4444-555555555555"


class WriteCapture(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.join(tempfile.mkdtemp(), "rds-20261028T000000Z")
        files = {"kitlab-aurora-cmk-describe-key": {"KeyMetadata": {"Arn": f"arn:aws:kms:us-west-2:{ACCOUNT}:key/x", "KeyManager": "CUSTOMER"}},
                 "clumio-resource": {"organizational_unit_id": UNIT, "account_native_id": ACCOUNT}}
        self.lines = capture.write_capture(self.folder, files, ACCOUNT, UNIT)

    def test_no_account_or_unit_survives_in_any_file(self):
        for name in os.listdir(self.folder):
            text = open(os.path.join(self.folder, name)).read()
            self.assertNotIn(ACCOUNT, text, name)
            self.assertNotIn(UNIT, text, name)
        self.assertIn(capture.ACCOUNT_STAND_IN, open(os.path.join(self.folder, "clumio-resource.json")).read())

    def test_the_manifest_verifies_with_shasum(self):
        check = subprocess.run(["shasum", "-a", "256", "-c", "_sha256.txt"], cwd=self.folder, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(len(self.lines), 2)

    def test_an_existing_capture_is_never_overwritten(self):
        with self.assertRaises(FileExistsError):
            capture.write_capture(self.folder, {"x": {}}, ACCOUNT, UNIT)


if __name__ == "__main__":
    unittest.main()
