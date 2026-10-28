#!/usr/bin/env python3
"""Records the real AWS and Clumio answers status.py reads, so its contract tests run against real
shapes, not only against fakes we wrote. Read-only: it calls status.py's own readers, and nothing else.

  python3 tools/tests/record_fixtures.py <name>     after 1-connect and a 2-protect- folder are applied, signed in, token exported

Writes tests/fixtures/<name>.json. The account ID, the organizational unit's ID and Clumio's own two
AWS accounts are masked as stand-ins everywhere, keys included, so the recording replays consistently. check.sh refuses any
other 12-digit number. Read the file before committing it.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import status  # noqa: E402

TENANT_WIDE = ("/policies/definitions", "/datasources/protection-groups")


def record(world):
    """Wraps each reader so every answer is kept: Clumio by path and unit, AWS by Region."""
    answers = {"clumio": {}, "tagged_resources": {}, "databases": {}, "volumes": {}, "instances": {}, "kit": None}

    def clumio_get(path, unit=None):
        answer = world.clumio_get(path, unit=unit)
        saved = answer
        # The policy and protection-group lists cover the whole tenant: other teams' names, accounts and
        # tags. Keep only this kit's items, the only ones status.py reads (live, 2026-10-28).
        if path.split("?")[0] in TENANT_WIDE and answers["kit"]:
            pattern = status.kit_name_pattern(answers["kit"])
            status_code, body = answer
            items = [item for item in (body.get("_embedded") or {}).get("items", []) if pattern.match(item.get("name") or "")]
            saved = (status_code, {**{k: v for k, v in body.items() if k != "_links"}, "_embedded": {"items": items}})
        # A rule that claimed a resource (OTHER) can be another team's: its name and tag condition are
        # theirs. Keep the kit's own rules whole; another rule, only its ID (cold review, 2026-10-28).
        if path.startswith("/policies/rules/") and answers["kit"]:
            status_code, body = answer
            if not status.kit_name_pattern(answers["kit"]).match(body.get("name") or ""):
                saved = (status_code, {"id": body.get("id")})
        answers["clumio"][f"{unit or ''} {path}"] = list(saved)
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

    recording = status.World(world.settings_path, world.terraform_version, world.aws_cli_found, world.signed_in_account,
                             world.clumio_credentials_set, clumio_get, kit=kit, tagged_resources=tagged_resources,
                             databases=databases, volumes=volumes, instances=instances,
                             applied_folders=world.applied_folders)
    return recording, answers


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    recording, answers = record(status.real_world())
    status.coverage(recording)
    status.teardown(recording)
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
