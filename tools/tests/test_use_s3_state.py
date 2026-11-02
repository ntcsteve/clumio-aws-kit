"""tools/use_s3_state.py: expected files are written out by hand, from the spike of 2026-11-02."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import use_s3_state  # noqa: E402

SETTINGS = 'account_id = "123456789012"\nregion = "ap-southeast-1"\norganizational_unit = "global"\nmode = "production"\n'

BACKEND = '''terraform {
  backend "s3" {
    bucket       = "acme-tfstate"
    key          = "clumio/123456789012/ap-southeast-1/1-connect/terraform.tfstate"
    region       = "ap-southeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
'''

CONNECT_STATE = '''connect_backend = "s3"
connect_config = {
  bucket = "acme-tfstate"
  key    = "clumio/123456789012/ap-southeast-1/1-connect/terraform.tfstate"
  region = "ap-southeast-1"
}
'''


class UseS3State(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for folder in ("0-check", "1-connect", "2-protect-rds", "2-protect-s3"):
            os.makedirs(os.path.join(self.root, folder))
        self.write("1-connect/terraform.tfvars", SETTINGS)

    def write(self, path, text):
        with open(os.path.join(self.root, path), "w") as out:
            out.write(text)

    def read(self, path):
        with open(os.path.join(self.root, path)) as file:
            return file.read()

    def exists(self, path):
        return os.path.exists(os.path.join(self.root, path))

    def run_tool(self, *arguments):
        printed = io.StringIO()
        with mock.patch.object(use_s3_state, "ROOT", self.root), contextlib.redirect_stdout(printed):
            code = use_s3_state.main(list(arguments))
        return code, printed.getvalue()

    def test_writes_one_backend_per_folder_each_with_its_own_key(self):
        code, _ = self.run_tool("acme-tfstate")
        self.assertEqual(code, 0)
        self.assertEqual(self.read("1-connect/backend.tf"), BACKEND)
        self.assertEqual(self.read("2-protect-rds/backend.tf"), BACKEND.replace("/1-connect/", "/2-protect-rds/"))
        self.assertEqual(self.read("2-protect-s3/backend.tf"), BACKEND.replace("/1-connect/", "/2-protect-s3/"))
        self.assertFalse(self.exists("0-check/backend.tf"))

    def test_each_protect_folder_reads_1_connects_state_from_the_bucket(self):
        self.run_tool("acme-tfstate")
        self.assertEqual(self.read("2-protect-rds/connect-state.auto.tfvars"), CONNECT_STATE)
        self.assertEqual(self.read("2-protect-s3/connect-state.auto.tfvars"), CONNECT_STATE)
        self.assertFalse(self.exists("1-connect/connect-state.auto.tfvars"))

    def test_a_copied_protect_folder_is_included(self):
        os.makedirs(os.path.join(self.root, "2-protect-rds-silver"))
        self.run_tool("acme-tfstate")
        self.assertIn("/2-protect-rds-silver/", self.read("2-protect-rds-silver/backend.tf"))

    def test_what_it_writes_is_terraform_formatted(self):
        self.run_tool("acme-tfstate")
        for path in ("1-connect/backend.tf", "2-protect-rds/connect-state.auto.tfvars"):
            answer = subprocess.run(["terraform", "fmt", "-check", path], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(answer.returncode, 0, path)

    def test_a_folder_already_set_refuses_and_writes_nothing(self):
        self.write("2-protect-s3/backend.tf", "already here\n")
        code, printed = self.run_tool("acme-tfstate")
        self.assertEqual(code, 1)
        self.assertIn("2-protect-s3/backend.tf", printed)
        self.assertFalse(self.exists("1-connect/backend.tf"))
        self.assertEqual(self.read("2-protect-s3/backend.tf"), "already here\n")

    def test_running_it_again_with_the_same_bucket_changes_nothing(self):
        self.run_tool("acme-tfstate")
        code, _ = self.run_tool("acme-tfstate")
        self.assertEqual(code, 0)
        self.assertEqual(self.read("1-connect/backend.tf"), BACKEND)

    def test_a_new_second_profile_folder_is_added(self):
        self.run_tool("acme-tfstate")
        os.makedirs(os.path.join(self.root, "2-protect-rds-silver"))
        code, _ = self.run_tool("acme-tfstate")
        self.assertEqual(code, 0)
        self.assertIn("/2-protect-rds-silver/", self.read("2-protect-rds-silver/backend.tf"))
        self.assertEqual(self.read("2-protect-rds-silver/connect-state.auto.tfvars"), CONNECT_STATE)

    def test_another_bucket_refuses_and_writes_nothing(self):
        self.run_tool("acme-tfstate")
        code, printed = self.run_tool("other-bucket")
        self.assertEqual(code, 1)
        self.assertIn("1-connect/backend.tf", printed)
        self.assertEqual(self.read("1-connect/backend.tf"), BACKEND)

    # terraform init would offer to move this state, a trial's, to the production key.
    def test_a_folder_with_local_state_refuses_and_writes_nothing(self):
        self.write("2-protect-s3/terraform.tfstate", "{}")
        code, printed = self.run_tool("acme-tfstate")
        self.assertEqual(code, 1)
        self.assertIn("2-protect-s3/terraform.tfstate", printed)
        self.assertIn("fresh clone", printed)
        self.assertFalse(self.exists("1-connect/backend.tf"))

    def test_settings_not_set_refuses_and_names_them(self):
        self.write("1-connect/terraform.tfvars", 'account_id = "ACCOUNT-ID-REPLACE-THIS"\nregion = "REGION-REPLACE-THIS"\n')
        code, printed = self.run_tool("acme-tfstate")
        self.assertEqual(code, 1)
        self.assertIn("account_id", printed)
        self.assertFalse(self.exists("1-connect/backend.tf"))

    def test_no_settings_file_refuses(self):
        os.remove(os.path.join(self.root, "1-connect/terraform.tfvars"))
        code, _ = self.run_tool("acme-tfstate")
        self.assertEqual(code, 1)

    def test_a_bucket_name_s3_wouldnt_allow_refuses(self):
        # It lands in a Terraform file, so it's checked before it's written.
        for bucket in ('acme"\n  evil', "UPPER", "a", "has_underscore", "-leading"):
            code, _ = self.run_tool(bucket)
            self.assertEqual(code, 1, bucket)
        self.assertFalse(self.exists("1-connect/backend.tf"))

    def test_no_bucket_says_how_to_run_it(self):
        code, printed = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("use_s3_state.py <bucket>", printed)


if __name__ == "__main__":
    unittest.main()
