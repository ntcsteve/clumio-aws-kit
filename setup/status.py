#!/usr/bin/env python3
"""Read-only checks for setup/. Nothing in AWS or Clumio changes. make runs it.

  ./status.py --preflight     before the first plan: tools, settings, AWS sign-in, Clumio token,
                              organizational unit, Region, rule slots, and any existing connection

Each check prints one line: PASS, FAIL, NOTE (worth knowing, not a failure) or SKIP (an earlier
check must pass first), with what to do next. Exit code: 0 when nothing failed, 1 otherwise.
Settings come from terraform.tfvars in this folder. Clumio credentials come from
CLUMIO_API_TOKEN and CLUMIO_API_BASE_URL. Runs on macOS's stock Python 3.9.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
GLOBAL_UNIT = "00000000-0000-0000-0000-000000000000"  # Clumio's ID for the Global unit (read 2026-10-28)
MIN_TERRAFORM = (1, 10)  # S3 state locking (use_lockfile) needs 1.10
RULE_LIMIT = 25  # Clumio's answer when full: error_code 107, "Number of rules is limited to 25"
MAX_UNITS_LISTED = 50  # Bounds the lookups when listing units to choose from
TIMEOUT_SECONDS = 30

SETTING_SHAPES = {
    "account_id": (r"^[0-9]{12}$", "your 12-digit AWS account ID"),
    "region": (r"^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-[0-9]$", "your AWS Region, such as us-west-2"),
    "organizational_unit": (r"^(global|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
                            '"global", or a unit\'s ID (listed below)'),
    "mode": (r"^(trial|production)$", '"trial" or "production"'),
}


@dataclass
class World:
    """Everything outside this script that the checks read. Tests pass fakes."""
    settings_path: str
    terraform_version: Callable[[], Optional[str]]
    aws_cli_found: Callable[[], bool]
    signed_in_account: Callable[[], Optional[str]]
    clumio_credentials_set: Callable[[], bool]
    clumio_get: Callable[..., tuple]  # (path, unit=None) -> (HTTP status, or None if unreachable; body)


# --- Preflight -----------------------------------------------------------------------------------

def preflight(world):
    """Every check, in the order a person fixes them. Returns [(state, check, detail)]."""
    results = [check_tools(world)]
    settings, settings_result = read_settings(world.settings_path)
    results.append(settings_result)
    valid = {key for key, value in settings.items() if re.match(SETTING_SHAPES[key][0], value)}

    results.append(check_sign_in(world, settings) if "account_id" in valid
                   else ("SKIP", "AWS sign-in", "needs a valid account_id"))
    token_result, regions = check_token(world)
    results.append(token_result)
    if token_result[0] != "PASS":
        for check in ("unit", "Region", "rule slots", "connection"):
            results.append(("SKIP", check, "needs a working Clumio token"))
        return results

    unit_id = None
    if "organizational_unit" in valid:
        unit_result, unit_id = check_unit(world, settings["organizational_unit"])
        results.append(unit_result)
    else:
        results.append(("FAIL", "unit", "Set organizational_unit in terraform.tfvars to one of these:\n" + list_units(world)))
    results.append(check_region(settings["region"], regions) if "region" in valid
                   else ("SKIP", "Region", "needs a valid region"))
    results.append(check_rule_slots(world, unit_id) if unit_id
                   else ("SKIP", "rule slots", "needs a valid organizational_unit"))
    results.append(check_connection(world, settings["account_id"], settings["region"])
                   if {"account_id", "region"} <= valid else ("SKIP", "connection", "needs a valid account_id and region"))
    return results


def check_tools(world):
    version = world.terraform_version()
    if version is None:
        return "FAIL", "tools", "terraform not found. Install Terraform 1.10 or later."
    if tuple(int(part) for part in version.split(".")[:2]) < MIN_TERRAFORM:
        return "FAIL", "tools", f"Terraform {version} is too old. Install Terraform 1.10 or later."
    if not world.aws_cli_found():
        return "FAIL", "tools", "the AWS CLI (aws) not found. Install AWS CLI v2."
    return "PASS", "tools", f"Terraform {version}, AWS CLI, Python {sys.version_info.major}.{sys.version_info.minor}"


def read_settings(path):
    """The four settings preflight needs, as plain one-line strings. Returns (settings, result)."""
    if not os.path.exists(path):
        return {}, ("FAIL", "settings", "terraform.tfvars not found. In setup/, run: cp settings.example terraform.tfvars, then edit it.")
    settings = {}
    with open(path, encoding="utf-8") as lines:
        for line in lines:
            found = re.match(r'^\s*(\w+)\s*=\s*"([^"]*)"', line)
            if found and found.group(1) in SETTING_SHAPES:
                settings[found.group(1)] = found.group(2)
    problems = []
    for key, (shape, meaning) in SETTING_SHAPES.items():
        if key not in settings:
            problems.append(f'{key} is missing: write it on one line, as {key} = "..."')
        elif not re.match(shape, settings[key]):
            problems.append(f"{key} is \"{settings[key]}\": set it to {meaning}")
    if problems:
        return settings, ("FAIL", "settings", "In terraform.tfvars: " + "; ".join(problems))
    return settings, ("PASS", "settings", f"{settings['account_id']}, {settings['region']}, unit {settings['organizational_unit']}, {settings['mode']}")


def check_sign_in(world, settings):
    account = world.signed_in_account()
    if account is None:
        return "FAIL", "AWS sign-in", "not signed in to AWS. Sign in (aws sso login, or aws login), then run again."
    if account != settings["account_id"]:
        return "FAIL", "AWS sign-in", f"signed in to {account}, but account_id is {settings['account_id']}. Sign in to {settings['account_id']}."
    return "PASS", "AWS sign-in", f"signed in to {account}"


def check_token(world):
    """The token works if Clumio lists its Regions. Returns (result, Region IDs)."""
    if not world.clumio_credentials_set():
        return ("FAIL", "Clumio token", "export CLUMIO_API_BASE_URL and CLUMIO_API_TOKEN first: "
                "read -rs CLUMIO_API_TOKEN && export CLUMIO_API_TOKEN"), []
    status, body = world.clumio_get("/connections/aws/regions?limit=100")
    if status is None:
        return ("FAIL", "Clumio token", "can't reach Clumio at CLUMIO_API_BASE_URL. Check the URL and your network."), []
    if status in (401, 403):
        return ("FAIL", "Clumio token", f"Clumio refused the token (HTTP {status}). It may have expired, or belong to "
                "another portal: check CLUMIO_API_BASE_URL matches it."), []
    if status != 200:
        return ("FAIL", "Clumio token", f"Clumio answered HTTP {status}. Try again; if it persists, contact Clumio support."), []
    regions = [item["id"] for item in body.get("_embedded", {}).get("items", [])]
    return ("PASS", "Clumio token", "Clumio answered"), regions


def check_unit(world, setting):
    """Returns (result, unit ID or None)."""
    if setting == "global":
        return ("PASS", "unit", "Global"), GLOBAL_UNIT
    status, body = world.clumio_get(f"/organizational-units/{setting}")
    if status == 200:
        return ("PASS", "unit", f"{body.get('name')} ({setting})"), setting
    if status == 404:
        return ("FAIL", "unit", f"no unit {setting} that this token can see. Choose one of these:\n" + list_units(world)), None
    return ("FAIL", "unit", f"Clumio answered HTTP {status} for unit {setting}. Try again."), None


def list_units(world):
    """Every unit this token can see, one per line: name, then the value to set."""
    status, body = world.clumio_get("/organizational-units?limit=100")
    if status != 200:
        return f"  (Clumio answered HTTP {status}; can't list units)"
    lines, seen = [], set()
    for top in body.get("_embedded", {}).get("items", []):
        ids = [top["id"]] + list(top.get("descendant_ids") or [])
        for unit_id in ids[:MAX_UNITS_LISTED]:
            if unit_id in seen:
                continue
            seen.add(unit_id)
            if unit_id == GLOBAL_UNIT:
                lines.append(f'  {top.get("name", "Global")}  global')
                continue
            child_status, child = world.clumio_get(f"/organizational-units/{unit_id}")
            lines.append(f"  {child.get('name', '?') if child_status == 200 else '?'}  {unit_id}")
    return "\n".join(lines) or "  (none visible to this token)"


def check_region(region, regions):
    if region in regions:
        return "PASS", "Region", f"Clumio supports {region}"
    return "FAIL", "Region", f"Clumio doesn't support {region}. Supported: {', '.join(sorted(regions))}."


def check_rule_slots(world, unit_id):
    """Rules belong to a unit, and each unit holds at most RULE_LIMIT (one observation, 2026-10-28)."""
    status, body = world.clumio_get("/policies/rules?limit=100", unit=unit_id)
    if status != 200:
        return "FAIL", "rule slots", f"Clumio answered HTTP {status} listing rules. Try again."
    used = sum(1 for rule in body.get("_embedded", {}).get("items", []) if rule.get("organizational_unit_id") == unit_id)
    if used >= RULE_LIMIT:
        return "FAIL", "rule slots", f"{used} of {RULE_LIMIT} used in this unit, so protection can't add its rules. Remove a rule you no longer need, or choose another unit."
    return "PASS", "rule slots", f"{used} of {RULE_LIMIT} used in this unit"


def check_connection(world, account, region):
    status, body = world.clumio_get(f"/connections/aws/{account}_{region}")
    if status == 404:
        return "PASS", "connection", f"{account}/{region} isn't connected yet"
    if status == 200:
        return ("NOTE", "connection", f"{account}/{region} is already connected (unit {body.get('organizational_unit_id')}). "
                "If this folder created it, carry on. If not, stop: it belongs to someone else.")
    return "FAIL", "connection", f"Clumio answered HTTP {status} for the connection. Try again."


def exit_code(results):
    return 1 if any(state == "FAIL" for state, _, _ in results) else 0


def print_results(results):
    for state, check, detail in results:
        first, *rest = detail.split("\n")
        print(f"{state:5} {check:13} {first}")
        for line in rest:
            print(f"{'':20}{line}")


# --- The real world ------------------------------------------------------------------------------

def real_world():
    return World(
        settings_path=os.path.join(HERE, "terraform.tfvars"),
        terraform_version=terraform_version,
        aws_cli_found=lambda: shutil.which("aws") is not None,
        signed_in_account=signed_in_account,
        clumio_credentials_set=lambda: bool(os.environ.get("CLUMIO_API_TOKEN") and os.environ.get("CLUMIO_API_BASE_URL")),
        clumio_get=clumio_get,
    )


def terraform_version():
    if shutil.which("terraform") is None:
        return None
    answer = subprocess.run(["terraform", "version", "-json"], capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    return json.loads(answer.stdout)["terraform_version"] if answer.returncode == 0 else None


def signed_in_account():
    try:
        answer = subprocess.run(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
                                capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return answer.stdout.strip() if answer.returncode == 0 else None


def clumio_get(path, unit=None):
    """GET from Clumio. The token goes in a header, never a URL. (None, {}) means unreachable."""
    headers = {"Authorization": f"Bearer {os.environ['CLUMIO_API_TOKEN']}", "Accept": "application/json"}
    if unit:
        headers["X-Clumio-OrganizationalUnit-Context"] = unit
    request = urllib.request.Request(os.environ["CLUMIO_API_BASE_URL"].rstrip("/") + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {}
    except (urllib.error.URLError, OSError):
        return None, {}


def main():
    parser = argparse.ArgumentParser(description="Read-only checks for setup/. Nothing changes.")
    parser.add_argument("--preflight", action="store_true", help="check everything before the first plan")
    args = parser.parse_args()
    if not args.preflight:
        parser.error("choose a check: --preflight")
    results = preflight(real_world())
    print_results(results)
    print("Next: make preview" if exit_code(results) == 0 else "Fix each FAIL above, then run make preflight again.")
    sys.exit(exit_code(results))


if __name__ == "__main__":
    main()
