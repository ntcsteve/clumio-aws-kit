#!/usr/bin/env python3
"""Point a fresh clone's Terraform state at your S3 bucket, before the first terraform init.

    tools/use_s3_state.py <bucket>

Writes backend.tf in 1-connect and in each 2-protect- folder, one key each, and tells each 2-protect-
folder where 1-connect's state is. It reads the account and Region from 1-connect/terraform.tfvars.
Nothing in AWS or Clumio changes, and the bucket is yours: create it first, in the same Region as your
data, with versioning and encryption on. Exit codes: 0 written, 1 refused, 2 no bucket named.
"""
import os
import re
import sys

from status import ROOT, read_settings

BUCKET_SHAPE = r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"  # S3's rule. The name lands in a Terraform file.

BACKEND = '''terraform {{
  backend "s3" {{
    bucket       = "{bucket}"
    key          = "{key}"
    region       = "{region}"
    encrypt      = true
    use_lockfile = true
  }}
}}
'''

CONNECT_STATE = '''connect_backend = "s3"
connect_config = {{
  bucket = "{bucket}"
  key    = "{key}"
  region = "{region}"
}}
'''


def step_folders():
    """1-connect and every 2-protect- folder at the repository root, copies included."""
    return sorted(name for name in os.listdir(ROOT)
                  if os.path.isdir(os.path.join(ROOT, name)) and (name == "1-connect" or name.startswith("2-protect-")))


def state_key(settings, folder):
    return f"clumio/{settings['account_id']}/{settings['region']}/{folder}/terraform.tfstate"


def write(folder, name, text):
    with open(os.path.join(ROOT, folder, name), "w", encoding="utf-8") as out:
        out.write(text)


def expected_backend(bucket, settings, folder):
    return BACKEND.format(bucket=bucket, key=state_key(settings, folder), region=settings["region"])


def refusal(bucket, settings, settings_result, folders):
    """Why nothing may be written; None when everything can be. Running it again with the same bucket is
    fine, and adds any new folder, such as a second profile."""
    if not re.match(BUCKET_SHAPE, bucket):
        return f"{bucket!r} isn't a valid S3 bucket name."
    if settings_result[0] != "PASS":
        return settings_result[2]
    for folder in folders:
        backend_path = os.path.join(ROOT, folder, "backend.tf")
        if os.path.exists(backend_path):
            with open(backend_path, encoding="utf-8") as file:
                if file.read() != expected_backend(bucket, settings, folder):
                    return f"{folder}/backend.tf is set to something else. Nothing was changed."
        elif os.path.exists(os.path.join(ROOT, folder, "terraform.tfstate")):
            # terraform init would offer to move this state, a trial's, to the production key.
            return f"{folder}/terraform.tfstate is local state. This is for a fresh clone. Nothing was changed."
    return None


def main(arguments):
    if len(arguments) != 1:
        print("Usage: tools/use_s3_state.py <bucket>")
        return 2
    bucket = arguments[0]
    folders = step_folders()
    settings, settings_result = read_settings(os.path.join(ROOT, "1-connect", "terraform.tfvars"))
    problem = refusal(bucket, settings, settings_result, folders)
    if problem:
        print(f"REFUSED: {problem}")
        return 1
    region = settings["region"]
    for folder in folders:
        write(folder, "backend.tf", expected_backend(bucket, settings, folder))
        if folder != "1-connect":
            write(folder, "connect-state.auto.tfvars",
                  CONNECT_STATE.format(bucket=bucket, key=state_key(settings, "1-connect"), region=region))
    print(f"State goes to s3://{bucket}/clumio/{settings['account_id']}/{region}/, for: {', '.join(folders)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
