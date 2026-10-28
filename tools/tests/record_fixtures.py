#!/usr/bin/env python3
"""Records the real AWS and Clumio answers status.py reads, so its contract tests run against real
shapes, not only against fakes we wrote. Read-only: it calls status.py's own readers, and nothing else.

  python3 tools/tests/record_fixtures.py <name>     after deploy/ is applied, signed in, token exported

Writes tests/fixtures/<name>.json. The account ID, the organizational unit's ID and Clumio's own two
AWS accounts are masked as stand-ins everywhere, keys included, so the recording replays consistently. check.sh refuses any
other 12-digit number. Read the file before committing it.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import status  # noqa: E402


def record(world):
    """Wraps each reader so every answer is kept: Clumio by path and unit, AWS by Region."""
    answers = {"clumio": {}, "tagged_resources": {}, "databases": {}, "volumes": {}, "instances": {}, "kit": None, "plan_variables": None}

    def clumio_get(path, unit=None):
        answer = world.clumio_get(path, unit=unit)
        answers["clumio"][f"{unit or ''} {path}"] = list(answer)
        return answer

    def tagged_resources(region):
        answers["tagged_resources"][region] = world.tagged_resources(region)
        return answers["tagged_resources"][region]

    def databases(region):
        answers["databases"][region] = world.databases(region)
        return answers["databases"][region]

    def volumes(region):
        answers["volumes"][region] = world.volumes(region)
        return answers["volumes"][region]

    def instances(region):
        answers["instances"][region] = sorted(world.instances(region))
        return set(answers["instances"][region])

    def kit():
        answers["kit"] = world.kit()
        return answers["kit"]

    def saved_plan():
        plan = world.saved_plan()
        answers["plan_variables"] = plan and {"variables": plan["variables"]}  # The rest of a plan isn't read.
        return plan

    recording = status.World(world.settings_path, world.terraform_version, world.aws_cli_found, world.signed_in_account,
                             world.clumio_credentials_set, clumio_get, kit, saved_plan, tagged_resources, databases, volumes, instances)
    return recording, answers


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    recording, answers = record(status.real_world())
    status.coverage(recording)
    status.teardown(recording)
    if os.path.exists(os.path.join(status.DEPLOY, "tfplan")):
        try:
            status.preview(recording)
        except status.RemovalPlan:
            pass  # A teardown's plan: nothing to preview, and nothing more to record.
    found = status.masks(status.real_world(), answers["kit"])
    if found is None:
        sys.exit("FAIL: Clumio didn't answer for the connection, so its accounts can't be masked. Nothing was saved. Run again.")
    text = status.mask(json.dumps(answers, indent=1, sort_keys=True), found)
    path = os.path.join(status.HERE, "tests", "fixtures", f"{sys.argv[1]}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as out:
        out.write(text + "\n")
    print(f"Wrote {path}. Read it before committing: accounts and unit are masked, everything else is as Clumio and AWS answered.")


if __name__ == "__main__":
    main()
