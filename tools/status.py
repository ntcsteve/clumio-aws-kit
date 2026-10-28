#!/usr/bin/env python3
"""Read-only checks for deploy/. Nothing in AWS or Clumio changes. Run it from anywhere.

  tools/status.py                 who protects each resource tagged clumio-profile (or, a volume on
                                  its own, clumio-volume-profile), and its last backup
  tools/status.py --json          the same, for machines
  tools/status.py --preflight     before the first plan: tools, settings, AWS sign-in, Clumio token,
                                  organizational unit, Region, rule slots, and any existing connection
  tools/status.py --preview       after terraform plan -out=tfplan in deploy/: what the saved plan
                                  will protect, and each tagged database's PITR window now and after
  tools/status.py --teardown      before a trial teardown: refuses in production, or while a backup runs

Every line names the state and what to do next. Exit codes: 0 nothing to do; 1 a person must act;
2 AWS or Clumio didn't answer, so nothing is assumed. Settings come from terraform.tfvars and
Terraform's state in deploy/. Clumio credentials come from CLUMIO_API_TOKEN and
CLUMIO_API_BASE_URL. Runs on macOS's stock Python 3.9.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.normpath(os.path.join(HERE, "..", "deploy"))  # The settings and the state this script reads
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
    kit: Optional[Callable[[], Optional[dict]]] = None  # Terraform's kit output, or None before deploy/ is applied
    saved_plan: Optional[Callable[[], Optional[dict]]] = None  # tfplan as JSON, or None without one
    tagged_resources: Optional[Callable[[str], list]] = None  # the tagging API's mappings in a Region
    databases: Optional[Callable[[str], dict]] = None  # name -> {"pitr": days, "cluster": its Aurora cluster or None}
    volumes: Optional[Callable[[str], dict]] = None  # volume ID -> {"instance": the instance it's attached to, or None}


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
        return {}, ("FAIL", "settings", "terraform.tfvars not found. In deploy/, run: cp settings.example terraform.tfvars, then edit it.")
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


# --- Coverage: who protects each tagged resource -------------------------------------------------

TAG_KEY = "clumio-profile"
VOLUME_TAG_KEY = "clumio-volume-profile"  # A volume on its own: see modules/profile, the volumes rule.
ACTION_STATES = {"OTHER", "BAD_VALUE", "OFF", "DOUBLE"}  # a person must change something
WORKLOADS = {"s3": "s3", "rds-instance": "databases", "rds-cluster": "databases", "ec2-instance": "ec2", "ebs-volume": "ebs_volumes"}
LABELS = {"s3": "S3 buckets", "databases": "RDS and Aurora", "ec2": "EC2 instances", "ebs_volumes": "volumes on their own"}
# How Clumio lists EC2 instances and EBS volumes, and the field that holds the AWS ID.
ASSETS = {"ec2-instance": ("/datasources/aws/ec2-instances", "instance_native_id"),
          "ebs-volume": ("/datasources/aws/ebs-volumes", "volume_native_id")}


class NothingApplied(Exception):
    """deploy/ hasn't been applied, so there's no protection to check."""


class NothingPlanned(Exception):
    """There's no saved plan (tfplan) to preview."""


class RemovalPlan(Exception):
    """The saved plan only removes resources, such as a teardown's: there's no protection to preview."""


class AwsUnavailable(Exception):
    """AWS didn't answer a read, so no resource list can be trusted."""


def coverage(world):
    """One record per tagged resource, and the connection's unit check. Raises NothingApplied."""
    kit = world.kit()
    if kit is None:
        raise NothingApplied()
    items, context = tagged(world, kit["region"])
    records = [settings_problem(item, kit["profiles"], context) or check_in_clumio(world, kit, item) for item in items]
    return records, check_connection_unit(world, kit)


def tagged(world, region):
    """The resources to check, as (kind, name, tag value, tag key), and what the checks need to know.
    Left out: an Aurora instance whose cluster is tagged (Clumio protects the cluster), and a volume
    carrying the instance tag while attached to a tagged instance (that instance's backup holds it)."""
    databases = world.databases(region)
    items = []
    for resource in world.tagged_resources(region):
        parsed = parse_arn(resource["ResourceARN"])
        tags = {tag["Key"]: tag["Value"] for tag in resource.get("Tags", [])}
        key = VOLUME_TAG_KEY if parsed and parsed[0] == "ebs-volume" and VOLUME_TAG_KEY in tags else TAG_KEY
        if parsed and key in tags:
            items.append((parsed[0], parsed[1], tags[key], key))
    tagged_clusters = {name for kind, name, _, _ in items if kind == "rds-cluster"}
    context = {"instance_profiles": {name: value for kind, name, value, _ in items if kind == "ec2-instance"},
               "volumes": world.volumes(region) if any(kind == "ebs-volume" for kind, _, _, _ in items) else {},
               "clusters": {name: db["cluster"] for name, db in databases.items() if db.get("cluster")},
               "engines": {name: db.get("engine", "") for name, db in databases.items()}}
    keep = [item for item in items
            if not (item[0] == "rds-instance" and context["clusters"].get(item[1]) in tagged_clusters)
            and not (item[0] == "ebs-volume" and item[3] == TAG_KEY and attached_instance(item[1], context) in context["instance_profiles"])]
    return sorted(keep), context


def parse_arn(arn):
    """(kind, name) for a bucket, an RDS instance, an Aurora cluster, an EC2 instance or an EBS
    volume; None for anything else."""
    parts = arn.split(":")
    if parts[2] == "s3":
        return "s3", parts[5]
    if parts[2] == "rds" and parts[5] in ("db", "cluster"):
        return ("rds-instance" if parts[5] == "db" else "rds-cluster"), parts[6]
    if parts[2] == "ec2" and parts[5].startswith(("instance/", "volume/")):
        kind, name = parts[5].split("/", 1)
        return ("ec2-instance" if kind == "instance" else "ebs-volume"), name
    return None


def attached_instance(volume_id, context):
    return (context["volumes"].get(volume_id) or {}).get("instance")


def workloads_of(profile):
    """A profile's workloads, from Terraform's kit output or from a saved plan's settings."""
    on = profile.get("workloads") or profile
    return {workload: bool(on.get(workload, False)) for workload in LABELS}


def settings_problem(item, profiles, context):
    """BAD_VALUE, OFF or DOUBLE: what's wrong before Clumio is even asked; None when nothing is."""
    kind, name, value, key = item
    if kind.startswith("rds") and context["engines"].get(name) in ("docdb", "neptune"):
        return record(kind, name, value, "OFF", "DocumentDB and Neptune are not supported by this kit. Remove the tag.")
    if kind == "rds-instance" and context["clusters"].get(name):
        return record(kind, name, value, "OFF", f"it's an instance of Aurora cluster {context['clusters'][name]}, and Clumio "
                      f"protects the cluster. Tag the cluster {TAG_KEY} = {value} instead.")
    if kind == "ebs-volume" and key == TAG_KEY:
        return record(kind, name, value, "OFF", f"a volume on its own joins with {VOLUME_TAG_KEY} = {value}. "
                      "A volume attached to a tagged instance is already in that instance's backup.")
    profile = profiles.get(value)
    if profile is None:
        return record(kind, name, value, "BAD_VALUE", f'no profile named "{value}" here. Profiles: {", ".join(sorted(profiles))}. Fix the tag.')
    workload = WORKLOADS[kind]
    if not workloads_of(profile)[workload]:
        return record(kind, name, value, "OFF", f"profile {value} doesn't protect {LABELS[workload]}. "
                      f"Set {workload} = true in it, or tag this with another profile.")
    instance = attached_instance(name, context) if kind == "ebs-volume" else None
    instance_profile = profiles.get(context["instance_profiles"].get(instance))
    if instance_profile and workloads_of(instance_profile)["ec2"]:
        return record(kind, name, value, "DOUBLE", f"it's attached to {instance}, whose backup already holds it. "
                      f"Remove its {VOLUME_TAG_KEY} tag, or you pay for two copies.")
    return None


def record(kind, name, profile, state, detail, last_backup=""):
    return {"kind": kind, "name": name, "profile": profile, "state": state, "detail": detail, "last_backup": last_backup}


def check_in_clumio(world, kit, item):
    kind, name, value, _ = item
    profile = kit["profiles"][value]
    if kind == "s3":
        return check_bucket(world, kit, name, value, profile)
    asset = find_database(world, kit, name) if kind.startswith("rds") else find_asset(world, kit, kind, name)
    problem = ownership_problem(world, kind, name, value, profile, asset)
    if problem:
        return problem
    if kind.startswith("rds"):
        backups = clumio_items(world, "/backups/aws/rds-resources", {"resource_id": {"$eq": asset["id"]}}, kit["organizational_unit_id"])
        if backups is None:
            return record(kind, name, value, "UNKNOWN", "Clumio didn't answer for its backups. Run again.")
        return protected(kind, name, value, max((b.get("start_timestamp", "") for b in backups if b.get("resource_id") == asset["id"]), default=""))
    return protected(kind, name, value, asset.get("last_backup_timestamp") or "")


def ownership_problem(world, kind, name, value, profile, asset):
    """UNKNOWN, NOT_YET or OTHER for an asset Clumio returned; None when our policy protects it."""
    if asset is None:
        return record(kind, name, value, "UNKNOWN", "Clumio didn't answer. Run again; if it persists, check the token.")
    if asset == {}:
        return record(kind, name, value, "NOT_YET", "Clumio hasn't found it yet. A new resource can take up to an hour: run again then.")
    info = asset.get("protection_info") or {}
    if not info.get("policy_id"):
        return record(kind, name, value, "NOT_YET", "Clumio found it, but no policy applies yet. Run again in a few minutes.")
    if info["policy_id"] != profile["policy_id"]:
        return record(kind, name, value, "OTHER", claimed_by(world, info))
    return None


def find_database(world, kit, name):
    """Clumio's record of this database in this Region: the record, {} when Clumio hasn't found it, or None when Clumio didn't answer."""
    found = clumio_items(world, "/datasources/aws/rds-resources",
                         {"account_native_id": {"$eq": kit["account_id"]}, "name": {"$contains": name}}, kit["organizational_unit_id"])
    if found is None:
        return None
    return next((a for a in found if a.get("name") == name and a.get("aws_region") == kit["region"] and not a.get("is_deleted")), {})


def find_asset(world, kit, kind, native_id):
    """Clumio's record of an EC2 instance or EBS volume: the record, {} when not found, None when Clumio didn't answer."""
    path, field = ASSETS[kind]
    found = clumio_items(world, path, {field: {"$eq": native_id}}, kit["organizational_unit_id"])
    if found is None:
        return None
    return next((a for a in found if a.get(field) == native_id and a.get("account_native_id") == kit["account_id"]
                 and a.get("aws_region") == kit["region"] and not a.get("is_deleted")), {})


def check_bucket(world, kit, name, value, profile):
    found = clumio_items(world, "/datasources/protection-groups/s3-assets", {"bucket_name": {"$eq": name}}, kit["organizational_unit_id"])
    if found is None:
        return record("s3", name, value, "UNKNOWN", "Clumio didn't answer. Run again; if it persists, check the token.")
    asset = next((a for a in found if a.get("group_id") == profile["protection_group_id"] and not a.get("is_deleted")), None)
    if asset is None:
        return record("s3", name, value, "NOT_YET", "Clumio hasn't added it to this profile's protection group yet. "
                      "A bucket joins once Clumio's daily inventory sees its tag, up to a day: run again later.")
    if (asset.get("protection_info") or {}).get("policy_id") != profile["policy_id"]:
        return record("s3", name, value, "OTHER", claimed_by(world, asset.get("protection_info") or {}))
    return protected("s3", name, value, asset.get("last_backup_timestamp") or "")


def protected(kind, name, value, latest):
    if latest:
        return record(kind, name, value, "OURS", "", when(latest))
    return record(kind, name, value, "WAITING", "protected; its first backup hasn't finished yet. "
                  "If it still waits after a day, look in Clumio's Tasks for it.")


def claimed_by(world, info):
    """Who applied another policy: a rule, by name, or a direct assignment."""
    if not info.get("rule_id"):
        return "another policy was assigned to it directly in Clumio. Remove that assignment, or ask whoever made it."
    status_code, rule = world.clumio_get(f"/policies/rules/{info['rule_id']}")
    rule_name = rule.get("name") if status_code == 200 else info["rule_id"]
    return (f'rule "{rule_name}" claimed it first: Clumio applies the highest-ranked rule that matches. '
            "Remove the tag that rule matches, ask its owner, or rank this profile's rule higher (rule_before_id).")


def check_connection_unit(world, kit):
    """The connection must sit in the unit the profiles live in, or their rules never match it."""
    status_code, body = world.clumio_get(f"/connections/aws/{kit['account_id']}_{kit['region']}")
    if status_code == 200 and body.get("organizational_unit_id") == kit["organizational_unit_id"]:
        return "PASS", "connection", f"{kit['account_id']}/{kit['region']} is connected, in this folder's unit"
    if status_code == 200:
        return ("FAIL", "connection", f"{kit['account_id']}/{kit['region']} is connected in unit {body.get('organizational_unit_id')}, "
                f"not {kit['organizational_unit_id']}, so these profiles' rules can't match it. Set organizational_unit to the connection's unit.")
    if status_code == 404:
        return "FAIL", "connection", f"{kit['account_id']}/{kit['region']} isn't connected. Plan and apply deploy/: deploy/README.md, step 1."
    return "UNKNOWN", "connection", f"Clumio answered HTTP {status_code} for the connection. Run again."


def coverage_exit_code(records, unit_result):
    states = {r["state"] for r in records} | {unit_result[0]}
    if "FAIL" in states or states & ACTION_STATES:
        return 1
    return 2 if "UNKNOWN" in states else 0


def clumio_items(world, path, condition, unit=None, complete=False):
    """A filtered Clumio list, or None when Clumio didn't answer 200, or, with complete, when the
    answer has more than one page. Callers re-check each item: a filter Clumio ignored must never
    turn into a wrong answer."""
    query = urllib.parse.quote(json.dumps(condition))
    status_code, body = world.clumio_get(f"{path}?limit=100&filter={query}", unit=unit)
    if status_code != 200 or (complete and (body.get("total_pages_count") or 1) > 1):
        return None
    return body.get("_embedded", {}).get("items", [])


def when(timestamp):
    """Clumio's 2026-10-28T05:00:00Z as 2026-10-28 05:00 UTC."""
    return timestamp[:16].replace("T", " ") + " UTC" if timestamp else ""


# --- Preview: what the saved plan will protect ---------------------------------------------------

WILL_PROTECT = {"s3": "Backtrack, and a daily SecureVault copy",
                "ec2-instance": "a daily SecureVault copy of the instance and its attached volumes",
                "ebs-volume": "a daily SecureVault copy of this volume"}


def preview(world):
    """One line per tagged resource: what the saved plan does to it. Raises NothingPlanned."""
    plan = world.saved_plan()
    if plan is None:
        raise NothingPlanned()
    actions = [change["change"]["actions"] for change in plan.get("resource_changes", [])]
    if ["delete"] in actions and all(action in (["delete"], ["no-op"]) for action in actions):
        raise RemovalPlan()
    settings = {key: value["value"] for key, value in plan["variables"].items()}
    profiles, region = settings["profiles"], settings["region"]
    databases = world.databases(region)
    items, context = tagged(world, region)
    lines = []
    for kind, name, value, key in items:
        problem = settings_problem((kind, name, value, key), profiles, context)
        if problem:
            lines.append(problem)
        elif kind.startswith("rds"):
            lines.append(pitr_line(kind, name, value, databases.get(name, {}).get("pitr"), profiles[value]))
        else:
            lines.append(record(kind, name, value, "WILL_PROTECT", WILL_PROTECT[kind]))
    return lines


def pitr_line(kind, name, value, now, profile):
    """A database's PITR window now and after. modules/profile has already stopped a plan that shortens
    a window without allow_shorter_pitr, so this only shows it."""
    after = profile["pitr_retention_days"]
    if now is None:
        return record(kind, name, value, "WILL_PROTECT", f"PITR window: {after} days after (now unknown)")
    change = "shorter" if after < now else ("longer" if after > now else "unchanged")
    return record(kind, name, value, "WILL_PROTECT", f"PITR window: {now} days now, {after} days after: {change}")


# --- Teardown: is it safe to remove protection now? ----------------------------------------------

def teardown(world):
    """("REFUSED" | "BLOCKED" | "READY" | "UNKNOWN", lines to show). Raises NothingApplied."""
    kit = world.kit()
    if kit is None:
        raise NothingApplied()
    if kit["mode"] == "production":
        return "REFUSED", ["mode is production, so teardown is refused. To retire production on purpose, "
                           "see Retire a production connection in docs/operate.md."]
    unit = kit["organizational_unit_id"]
    watched = [(f"protection group of profile {name}", p["protection_group_id"]) for name, p in kit["profiles"].items() if p["protection_group_id"]]
    items, _ = tagged(world, kit["region"])
    ours = [(kind, name) for kind, name, value, _ in items if kind != "s3" and value in kit["profiles"]]
    for kind, name in ours:
        asset = find_database(world, kit, name) if kind.startswith("rds") else find_asset(world, kit, kind, name)
        if asset is None:
            return "UNKNOWN", ["Clumio didn't answer, so running backups can't be ruled out. Run again."]
        if asset:
            watched.append((name, asset["id"]))
    running = []
    for label, asset_id in watched:
        # Every page, or no answer: a task on page two must never read as nothing running.
        tasks = clumio_items(world, "/tasks", {"primary_entity.id": {"$eq": asset_id}}, unit, complete=True)
        if tasks is None:
            return "UNKNOWN", [f"Clumio didn't answer in full for {label}, so running backups can't be ruled out. "
                               "Look in Clumio's Tasks; teardown waits until nothing runs."]
        running += [f"task {t['id']} ({t.get('type', 'backup')}) for {label}: {t['status']}" for t in tasks
                    if t.get("status") in ("queued", "in_progress", "aborting") and (t.get("primary_entity") or {}).get("id") == asset_id]
    if running:
        return "BLOCKED", running + ["Run tools/status.py --teardown again when they end: removing protection mid-backup leaves Clumio's tasks stuck."]
    databases = world.databases(kit["region"])
    return "READY", [f"{name}: PITR window {databases[name]['pitr']} days, as Clumio set it. It stays after teardown: change it yourself if you need to."
                     for kind, name in ours if kind.startswith("rds") and name in databases]


def print_results(results):
    for state, check, detail in results:
        first, *rest = detail.split("\n")
        print(f"{state:5} {check:13} {first}")
        for line in rest:
            print(f"{'':20}{line}")


# --- The real world ------------------------------------------------------------------------------

def real_world():
    return World(
        settings_path=os.path.join(DEPLOY, "terraform.tfvars"),
        terraform_version=terraform_version,
        aws_cli_found=lambda: shutil.which("aws") is not None,
        signed_in_account=signed_in_account,
        clumio_credentials_set=lambda: bool(os.environ.get("CLUMIO_API_TOKEN") and os.environ.get("CLUMIO_API_BASE_URL")),
        clumio_get=clumio_get,
        kit=terraform_kit,
        saved_plan=terraform_saved_plan,
        tagged_resources=aws_tagged_resources,
        databases=aws_databases,
        volumes=aws_volumes,
    )


def run_json(command, timeout=60):
    """Run a read-only command and parse its JSON output; None when it fails."""
    try:
        answer = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=DEPLOY)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return json.loads(answer.stdout) if answer.returncode == 0 and answer.stdout.strip() else None


def terraform_kit():
    """The kit output from this folder's state: account, Region, unit, mode and each profile's IDs."""
    return run_json(["terraform", "output", "-json", "kit"])


def terraform_saved_plan():
    if not os.path.exists(os.path.join(DEPLOY, "tfplan")):
        return None
    return run_json(["terraform", "show", "-json", "tfplan"], timeout=120)


def aws_tagged_resources(region):
    """Every bucket, database, instance and volume in the Region carrying either tag. One call per tag
    key: the tagging API ANDs the keys of a single call."""
    found = {}
    for key in (TAG_KEY, VOLUME_TAG_KEY):
        answer = run_json(["aws", "resourcegroupstaggingapi", "get-resources", "--region", region, "--tag-filters", f"Key={key}",
                           "--resource-type-filters", "s3", "rds:db", "rds:cluster", "ec2:instance", "ec2:volume", "--output", "json"], timeout=120)
        if answer is None:
            raise AwsUnavailable(f"AWS didn't list the resources tagged {key} in {region}. Check your sign-in, then run again.")
        found.update({r["ResourceARN"]: r for r in answer.get("ResourceTagMappingList", [])})
    return list(found.values())


def aws_volumes(region):
    """Each volume, and the instance it's attached to, for DOUBLE."""
    answer = run_json(["aws", "ec2", "describe-volumes", "--region", region, "--output", "json"], timeout=120)
    if answer is None:
        raise AwsUnavailable(f"AWS didn't list the volumes in {region}. Check your sign-in, then run again.")
    return {v["VolumeId"]: {"instance": next((a["InstanceId"] for a in v.get("Attachments", [])), None)} for v in answer.get("Volumes", [])}


def aws_databases(region):
    """Each database's PITR window, and the Aurora cluster an instance belongs to."""
    instances = run_json(["aws", "rds", "describe-db-instances", "--region", region, "--output", "json"], timeout=120)
    clusters = run_json(["aws", "rds", "describe-db-clusters", "--region", region, "--output", "json"], timeout=120)
    if instances is None or clusters is None:
        raise AwsUnavailable(f"AWS didn't list the databases in {region}. Check your sign-in, then run again.")
    found = {c["DBClusterIdentifier"]: {"pitr": c.get("BackupRetentionPeriod"), "cluster": None, "engine": c.get("Engine", "")}
             for c in clusters.get("DBClusters", [])}
    for i in instances.get("DBInstances", []):
        found[i["DBInstanceIdentifier"]] = {"pitr": i.get("BackupRetentionPeriod"), "cluster": i.get("DBClusterIdentifier"),
                                            "engine": i.get("Engine", "")}
    return found


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


def print_records(records):
    if not records:
        print(f"No resource in this Region carries the tag {TAG_KEY}. Tag what you want protected: {TAG_KEY} = <profile>.")
        return
    for r in records:
        print(f"{r['state']:12} {r['kind']:13} {r['name']:32} {r['profile']:10} {r['last_backup'] or '-':20} {r['detail']}")


def run_status(as_json):
    records, unit_result = coverage(real_world())
    code = coverage_exit_code(records, unit_result)
    if as_json:
        print(json.dumps({"connection": dict(zip(("state", "check", "detail"), unit_result)), "resources": records, "exit_code": code}, indent=1))
        return code
    print_results([unit_result])
    print_records(records)
    counts = {}
    for r in records:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print("Summary: " + (", ".join(f"{n} {state}" for state, n in sorted(counts.items())) or "nothing tagged"))
    return code


def run_preview():
    lines = preview(real_world())
    print("What the saved plan protects, by tag:")
    print_records(lines)
    return 0


def run_teardown():
    state, lines = teardown(real_world())
    print(f"{state}: " + {"REFUSED": "teardown is refused.", "BLOCKED": "Clumio is still working on this folder's resources:",
                          "READY": "nothing is running. Left behind after teardown:", "UNKNOWN": ""}[state])
    for line in lines:
        print(f"  {line}")
    return 0 if state == "READY" else (2 if state == "UNKNOWN" else 1)


def main():
    parser = argparse.ArgumentParser(description="Read-only checks for deploy/. Nothing changes.")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--preflight", action="store_true", help="check everything before the first plan")
    choice.add_argument("--preview", action="store_true", help="what the saved plan will protect")
    choice.add_argument("--teardown", action="store_true", help="whether teardown is safe now")
    parser.add_argument("--json", action="store_true", help="coverage as JSON, for machines")
    args = parser.parse_args()
    try:
        if args.preflight:
            results = preflight(real_world())
            print_results(results)
            print("Next: 0-check/preview/preview.sh" if exit_code(results) == 0 else "Fix each FAIL above, then run tools/status.py --preflight again.")
            sys.exit(exit_code(results))
        sys.exit(run_preview() if args.preview else run_teardown() if args.teardown else run_status(args.json))
    except NothingApplied:
        print("Nothing is applied in deploy/ yet: plan and apply it first (deploy/README.md).")
        sys.exit(1)
    except NothingPlanned:
        print("There's no saved plan to preview: in deploy/, run terraform plan -out=tfplan.")
        sys.exit(1)
    except RemovalPlan:
        print("The saved plan in deploy/ only removes resources, such as a teardown's, so it protects nothing. "
              "Read it with terraform show tfplan.")
        sys.exit(1)
    except AwsUnavailable as error:
        print(f"UNKNOWN: {error}")
        sys.exit(2)


if __name__ == "__main__":
    main()
