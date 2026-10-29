#!/usr/bin/env python3
"""Read-only checks of the kit in one account and Region. Nothing in AWS or Clumio changes.

  tools/status.py                 who protects each resource tagged clumio-profile (or, a volume on
                                  its own, clumio-volume-profile), and its last backup
  tools/status.py --json          the same, for machines
  tools/status.py --preflight     before the first plan: tools, settings, AWS sign-in, Clumio token,
                                  organizational unit, Region, rule slots, and any existing connection
  tools/status.py --teardown      before a trial teardown: refuses in production, or while a backup runs,
                                  and names the folders still applied
  tools/status.py --account 123456789012 --region us-west-2 --unit <unit ID or global> [--json]
                                  status of policies modules/protect made from another repository; all
                                  three together, for status and --json only

Every line names the state and what to do next. Exit codes: 0 nothing to do; 1 a person must act;
2 AWS or Clumio didn't answer, so nothing is assumed. The account, Region, unit and mode come from
1-connect/terraform.tfvars; the kit's policies are found by name in Clumio. Clumio credentials come
from CLUMIO_API_TOKEN and CLUMIO_API_BASE_URL. Runs on macOS's stock Python 3.9.
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
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CONNECT = os.path.join(ROOT, "1-connect")  # Its terraform.tfvars names the account, Region, unit and mode
GLOBAL_UNIT = "00000000-0000-0000-0000-000000000000"  # Clumio's ID for the Global unit (read 2026-10-28)
MIN_TERRAFORM = (1, 10)  # S3 state locking (use_lockfile) needs 1.10
# Clumio's rule limits, as seen live; Clumio shows no limit until you hit it (error_code 107): 25 in the
# Global unit ("Number of rules is limited to 25", v1), 5 in a child unit (2026-10-28).
RULE_LIMITS = {"global": 25, "child unit": 5}
RULE_WORKLOADS = ("rds", "aurora", "ec2", "ebs")  # each 2-protect- folder for these adds one rule; S3 adds none
MAX_UNITS_LISTED = 50  # Bounds the lookups when listing units to choose from
MAX_PAGES = 20  # Bounds a full list: 2,000 policies, groups or tasks; longer is UNKNOWN, never a partial answer
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
    kit: Optional[Callable[[], Optional[dict]]] = None  # account_id, region, organizational_unit_id (the unit's ID); None without settings
    tagged_resources: Optional[Callable[[str], list]] = None  # the tagging API's mappings in a Region
    databases: Optional[Callable[[str], dict]] = None  # name -> {"pitr": days, "cluster": its Aurora cluster or None}
    volumes: Optional[Callable[[str], dict]] = None  # volume ID -> {"instance": the instance it's attached to, or None}
    instances: Optional[Callable[[str], set]] = None  # IDs of the instances AWS describes as not terminated
    applied_folders: Optional[Callable[[], list]] = None  # the 1-connect and 2-protect- folders whose state holds resources
    pending_rule_folders: Optional[Callable[[], list]] = None  # 2-protect- folders with settings whose rule isn't applied yet


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
        return {}, ("FAIL", "settings", "1-connect/terraform.tfvars not found. In 1-connect/, run: cp settings.example terraform.tfvars, then edit it.")
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
    """Rules belong to a unit, up to its limit. Each 2-protect- folder for RDS, Aurora, EC2 or EBS adds
    one; this counts what the folders set up but not applied still need, before an apply fails halfway."""
    # The list holds every unit's rules, so this unit's can sit on any page: read them all.
    rules = clumio_items(world, "/policies/rules", None, unit_id, complete=True)
    if rules is None:
        return "FAIL", "rule slots", "Clumio didn't list the rules in full. Try again."
    used = sum(1 for rule in rules if rule.get("organizational_unit_id") == unit_id)
    kind = "global" if unit_id == GLOBAL_UNIT else "child unit"
    limit = RULE_LIMITS[kind]
    pending = world.pending_rule_folders() if world.pending_rule_folders else []
    if used + len(pending) > limit:
        need = f"{', '.join(pending)} need{'s' if len(pending) == 1 else ''} {len(pending)} more. " if pending else ""
        return ("FAIL", "rule slots", f"{used} of {limit} used in this unit (the limit Clumio showed for a {kind}). {need}"
                "Free rules you no longer need, ask Clumio support to raise the unit's limit, or use another unit.")
    if used >= limit:
        return ("NOTE", "rule slots", f"{used} of {limit} used in this unit: full. A new 2-protect- folder for RDS, Aurora, EC2 "
                "or EBS will be refused until a rule is freed or Clumio raises the limit.")
    note = f"; {', '.join(pending)} will use {len(pending)} more" if pending else ""
    return "PASS", "rule slots", f"{used} of {limit} used in this unit{note}"


def check_connection(world, account, region):
    status, body = world.clumio_get(f"/connections/aws/{account}_{region}")
    if status == 404:
        return "PASS", "connection", f"{account}/{region} isn't connected yet"
    if status == 200:
        return ("NOTE", "connection", f"{account}/{region} is already connected (unit {body.get('organizational_unit_id')}). "
                "If 1-connect created it, carry on. If not, stop: it belongs to someone else.")
    return "FAIL", "connection", f"Clumio answered HTTP {status} for the connection. Try again."


def exit_code(results):
    return 1 if any(state == "FAIL" for state, _, _ in results) else 0


# --- Coverage: who protects each tagged resource -------------------------------------------------

TAG_KEY = "clumio-profile"
VOLUME_TAG_KEY = "clumio-volume-profile"  # A volume on its own: see modules/protect, the ebs workload.
ACTION_STATES = {"OTHER", "BAD_VALUE", "OFF", "DOUBLE"}  # a person must change something
# Each kind of tagged resource, and the 2-protect- folder (workload) whose policy protects it.
WORKLOADS = {"s3": "s3", "rds-instance": "rds", "rds-cluster": "aurora", "ec2-instance": "ec2", "ebs-volume": "ebs"}
LABELS = {"s3": "S3 buckets", "rds": "RDS instances", "aurora": "Aurora clusters", "ec2": "EC2 instances", "ebs": "volumes on their own"}
# How Clumio lists EC2 instances and EBS volumes, and the field that holds the AWS ID.
ASSETS = {"ec2-instance": ("/datasources/aws/ec2-instances", "instance_native_id"),
          "ebs-volume": ("/datasources/aws/ebs-volumes", "volume_native_id")}


class NothingApplied(Exception):
    """There are no settings naming an account, Region and unit to check."""


class ClumioUnavailable(Exception):
    """Clumio didn't list the policies in full, so which are the kit's can't be known."""


class AwsUnavailable(Exception):
    """AWS didn't answer a read, so no resource list can be trusted."""


def coverage(world):
    """One record per tagged resource, and the connection's unit check. Raises NothingApplied."""
    kit = world.kit()
    if kit is None:
        raise NothingApplied()
    profiles = kit_profiles(world, kit)
    items, context = tagged(world, kit["region"])
    records = [settings_problem(item, profiles, context) or check_in_clumio(world, kit, profiles, item) for item in items]
    return records, check_connection_unit(world, kit)


def kit_name_pattern(kit):
    """The names modules/protect gives policies and groups in this account and Region: profile, workload."""
    return re.compile(r"^([a-z0-9][a-z0-9-]*)-(s3|rds|aurora|ec2|ebs)-" + re.escape(f"{kit['account_id']}-{kit['region']}") + "$")


def kit_profiles(world, kit):
    """{profile: {workload: policy ID, "s3_group": group ID}}: the kit's policies, found by the names
    modules/protect gives them, <profile>-<workload>-<account>-<region>, in the unit. Another team's
    policy, or another account's or Region's, never matches. Raises ClumioUnavailable."""
    pattern = kit_name_pattern(kit)
    unit = kit["organizational_unit_id"]
    policies = clumio_items(world, "/policies/definitions", None, unit, complete=True)
    groups = clumio_items(world, "/datasources/protection-groups", None, unit, complete=True)
    if policies is None or groups is None:
        raise ClumioUnavailable("Clumio didn't list this unit's policies in full, so which are the kit's can't be known. Run again.")
    profiles = {}
    for policy in policies:
        found = pattern.match(policy.get("name") or "")
        if found:
            profiles.setdefault(found.group(1), {})[found.group(2)] = policy["id"]
    for group in groups:
        found = pattern.match(group.get("name") or "")
        if found and found.group(2) == "s3" and not group.get("is_deleted"):
            profiles.setdefault(found.group(1), {})["s3_group"] = group["id"]
    return profiles


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
    # The tagging API isn't the list of what exists (read live, 2026-10-28): it lists each Aurora
    # cluster a second time, under its resource ID, and keeps listing terminated instances and deleted
    # volumes for a while. Keep only what AWS's own describe calls say exists. Buckets are taken as listed.
    kinds = {kind for kind, _, _, _ in items}
    volumes = world.volumes(region) if "ebs-volume" in kinds else {}
    existing = {"rds-instance": databases, "rds-cluster": databases, "ebs-volume": volumes,
                "ec2-instance": world.instances(region) if "ec2-instance" in kinds else set()}
    items = [item for item in items if item[0] == "s3" or item[1] in existing[item[0]]]
    tagged_clusters = {name for kind, name, _, _ in items if kind == "rds-cluster"}
    context = {"instance_profiles": {name: value for kind, name, value, _ in items if kind == "ec2-instance"},
               "volumes": volumes,
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
        return record(kind, name, value, "BAD_VALUE", f'no 2-protect- folder with name = "{value}" is applied here '
                      f'(applied: {", ".join(sorted(profiles)) or "none"}). Apply one, or fix or remove the tag.')
    workload = WORKLOADS[kind]
    if workload not in profile:
        return record(kind, name, value, "OFF", f'no 2-protect-{workload} folder with name = "{value}" is applied, so nothing protects '
                      f"{LABELS[workload]} for it (profile {value} has: {', '.join(sorted(w for w in profile if w in LABELS))}). "
                      f"Apply 2-protect-{workload}, or tag this with another profile.")
    instance = attached_instance(name, context) if kind == "ebs-volume" else None
    instance_profile = profiles.get(context["instance_profiles"].get(instance))
    if instance_profile and "ec2" in instance_profile:
        return record(kind, name, value, "DOUBLE", f"it's attached to {instance}, whose backup already holds it. "
                      f"Remove its {VOLUME_TAG_KEY} tag, or you pay for two copies.")
    return None


def record(kind, name, profile, state, detail, last_backup=""):
    return {"kind": kind, "name": name, "profile": profile, "state": state, "detail": detail, "last_backup": last_backup}


def check_in_clumio(world, kit, profiles, item):
    kind, name, value, _ = item
    profile = profiles[value]
    if kind == "s3":
        return check_bucket(world, kit, name, value, profile)
    asset = find_database(world, kit, name) if kind.startswith("rds") else find_asset(world, kit, kind, name)
    problem = ownership_problem(world, kind, name, value, profile[WORKLOADS[kind]], asset, kit["organizational_unit_id"])
    if problem:
        return problem
    if kind.startswith("rds"):
        backups = clumio_items(world, "/backups/aws/rds-resources", {"resource_id": {"$eq": asset["id"]}}, kit["organizational_unit_id"], complete=True)
        if backups is None:
            return record(kind, name, value, "UNKNOWN", "Clumio didn't answer for its backups. Run again.")
        return protected(kind, name, value, max((b.get("start_timestamp", "") for b in backups if b.get("resource_id") == asset["id"]), default=""))
    return protected(kind, name, value, asset.get("last_backup_timestamp") or "")


def ownership_problem(world, kind, name, value, our_policy, asset, unit):
    """UNKNOWN, NOT_YET or OTHER for an asset Clumio returned; None when our policy protects it."""
    if asset is None:
        return record(kind, name, value, "UNKNOWN", "Clumio didn't answer. Run again; if it persists, check the token.")
    if asset == {}:
        return record(kind, name, value, "NOT_YET", "Clumio hasn't found it yet. A new resource can take up to an hour: run again then.")
    info = asset.get("protection_info") or {}
    if not info.get("policy_id"):
        return record(kind, name, value, "NOT_YET", "Clumio found it, but no policy applies yet. Clumio attaches a resource created or "
                      "tagged after its rule at its next discovery cycle: run again later, and allow up to a day.")
    if info["policy_id"] != our_policy:
        return record(kind, name, value, "OTHER", claimed_by(world, info, unit))
    return None


def find_database(world, kit, name):
    """Clumio's record of this database in this Region: the record, {} when Clumio hasn't found it, or None when Clumio didn't answer."""
    found = clumio_items(world, "/datasources/aws/rds-resources",
                         {"account_native_id": {"$eq": kit["account_id"]}, "name": {"$contains": name}}, kit["organizational_unit_id"], complete=True)
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
    asset = next((a for a in found if a.get("group_id") == profile.get("s3_group") and not a.get("is_deleted")), None)
    if asset is None:
        return record("s3", name, value, "NOT_YET", "Clumio hasn't added it to this profile's protection group yet. "
                      "A bucket joins once Clumio's daily inventory sees its tag, up to a day: run again later.")
    if (asset.get("protection_info") or {}).get("policy_id") != profile["s3"]:
        return record("s3", name, value, "OTHER", claimed_by(world, asset.get("protection_info") or {}, kit["organizational_unit_id"]))
    return protected("s3", name, value, asset.get("last_backup_timestamp") or "")


def protected(kind, name, value, latest):
    if latest:
        return record(kind, name, value, "OURS", "", when(latest))
    return record(kind, name, value, "WAITING", "protected; its first backup hasn't finished yet. "
                  "If it still waits after a day, look in Clumio's Tasks for it.")


def claimed_by(world, info, unit):
    """Who applied another policy: a rule, by name and ID (rule_before_id takes the ID), or a direct
    assignment. A rule is found only in its unit's context (live, 2026-10-28: 404 without it)."""
    if not info.get("rule_id"):
        return "another policy was assigned to it directly in Clumio. Remove that assignment, or ask whoever made it."
    status_code, rule = world.clumio_get(f"/policies/rules/{info['rule_id']}", unit=unit)
    rule_name = f'"{rule.get("name")}" ({info["rule_id"]})' if status_code == 200 else info["rule_id"]
    return (f"rule {rule_name} claimed it first: Clumio applies the highest-ranked rule that matches. Remove the tag that "
            f"rule matches, ask its owner, or rank this folder's rule ahead of it: rule_before_id = \"{info['rule_id']}\".")


def check_connection_unit(world, kit):
    """The connection must sit in the unit the profiles live in, or their rules never match it."""
    status_code, body = world.clumio_get(f"/connections/aws/{kit['account_id']}_{kit['region']}")
    if status_code == 200 and body.get("organizational_unit_id") == kit["organizational_unit_id"]:
        return "PASS", "connection", f"{kit['account_id']}/{kit['region']} is connected, in this folder's unit"
    if status_code == 200:
        return ("FAIL", "connection", f"{kit['account_id']}/{kit['region']} is connected in unit {body.get('organizational_unit_id')}, "
                f"not {kit['organizational_unit_id']}, so these profiles' rules can't match it. Set organizational_unit to the connection's unit.")
    if status_code == 404:
        return "FAIL", "connection", f"{kit['account_id']}/{kit['region']} isn't connected. Plan and apply 1-connect (1-connect/README.md)."
    return "UNKNOWN", "connection", f"Clumio answered HTTP {status_code} for the connection. Run again."


def coverage_exit_code(records, unit_result):
    states = {r["state"] for r in records} | {unit_result[0]}
    if "FAIL" in states or states & ACTION_STATES:
        return 1
    return 2 if "UNKNOWN" in states else 0


def clumio_items(world, path, condition, unit=None, complete=False):
    """A filtered Clumio list, or None when Clumio didn't answer 200. With complete, every page, by
    following each answer's _links._next (Clumio pages by cursor and gives no page count; read live,
    2026-10-28), up to MAX_PAGES; a list longer than that is None too, never a partial answer. Callers
    re-check each item: a filter Clumio ignored must never turn into a wrong answer."""
    query = f"&filter={urllib.parse.quote(json.dumps(condition))}" if condition else ""
    page, items = f"{path}?limit=100{query}", []
    for _ in range(MAX_PAGES if complete else 1):
        status_code, body = world.clumio_get(page, unit=unit)
        if status_code != 200:
            return None
        items += body.get("_embedded", {}).get("items", [])
        page = ((body.get("_links") or {}).get("_next") or {}).get("href")
        if not complete or not page:
            return items
    return None


def when(timestamp):
    """Clumio's 2026-10-28T05:00:00Z as 2026-10-28 05:00 UTC."""
    return timestamp[:16].replace("T", " ") + " UTC" if timestamp else ""


# --- Masks: what a saved answer must never carry --------------------------------------------------

ACCOUNT_STAND_IN = "123456789012"
UNIT_STAND_IN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
# Clumio's own two AWS accounts appear in the connection's answer, and in what Clumio shares with this
# account. Stand-ins from check.sh's allowlist.
CLUMIO_ACCOUNT_STAND_INS = {"clumio_aws_account_id": "111111111111", "data_plane_account_id": "222222222222"}


def masks(world, kit):
    """{real ID: stand-in} for this account, the unit, and Clumio's two accounts, or None when Clumio
    didn't answer for the connection: without it, Clumio's accounts are unknown and a save could leak them."""
    status_code, connection = world.clumio_get(f"/connections/aws/{kit['account_id']}_{kit['region']}")
    if status_code != 200:
        return None
    found = {kit["account_id"]: ACCOUNT_STAND_IN, kit["organizational_unit_id"]: UNIT_STAND_IN}
    found.update({connection[field]: stand_in for field, stand_in in CLUMIO_ACCOUNT_STAND_INS.items() if connection.get(field)})
    return found


def mask(text, found):
    for real, stand_in in found.items():
        text = text.replace(real, stand_in)
    return text


# --- Teardown: is it safe to remove protection now? ----------------------------------------------

def teardown(world):
    """("REFUSED" | "BLOCKED" | "READY" | "UNKNOWN", lines to show). Raises NothingApplied, ClumioUnavailable."""
    # The mode as the person set it in 1-connect/terraform.tfvars. Terraform's production guard is the
    # hard stop; this says so first, in words. No readable mode: never READY (cold review, 2026-10-28).
    settings, _ = read_settings(world.settings_path)
    if settings.get("mode") not in ("trial", "production"):
        return "UNKNOWN", [f"no mode in {world.settings_path}, so production can't be ruled out. Set it up as 0-check/README.md says."]
    if settings["mode"] == "production":
        return "REFUSED", ["mode is production in 1-connect/terraform.tfvars, so teardown is refused. To retire production "
                           "on purpose, see Retire a production connection in docs/operate.md."]
    kit = world.kit()
    if kit is None:
        raise NothingApplied()
    unit = kit["organizational_unit_id"]
    profiles = kit_profiles(world, kit)
    watched = [(f"protection group of profile {name}", p["s3_group"]) for name, p in profiles.items() if p.get("s3_group")]
    items, _ = tagged(world, kit["region"])
    ours = [(kind, name) for kind, name, value, _ in items if kind != "s3" and value in profiles]
    for kind, name in ours:
        asset = find_database(world, kit, name) if kind.startswith("rds") else find_asset(world, kit, kind, name)
        if asset is None:
            return "UNKNOWN", ["Clumio didn't answer, so running backups can't be ruled out. Run again."]
        if asset:
            watched.append((name, asset["id"]))
    running = []
    for label, asset_id in watched:
        # Every page, or no answer: a task on page two must never read as nothing running. No unit
        # context: asked inside the unit, Clumio left out a restore started in the console (seen live,
        # 2026-10-29). The filter keeps the answer to this asset's own tasks.
        tasks = clumio_items(world, "/tasks", {"primary_entity.id": {"$eq": asset_id}}, None, complete=True)
        if tasks is None:
            return "UNKNOWN", [f"Clumio didn't answer in full for {label}, so running backups can't be ruled out. "
                               "Look in Clumio's Tasks; teardown waits until nothing runs."]
        running += [f"task {t['id']} ({t.get('type', 'backup')}) for {label}: {t['status']}" for t in tasks
                    if t.get("status") in ("queued", "in_progress", "aborting") and (t.get("primary_entity") or {}).get("id") == asset_id]
    if running:
        return "BLOCKED", running + ["Run tools/status.py --teardown again when they end: removing protection mid-backup leaves Clumio's tasks stuck."]
    databases = world.databases(kit["region"])
    lines = [f"{name}: PITR window {databases[name]['pitr']} days now. It stays after teardown: set back the window you noted, if you need to."
             for kind, name in ours if kind.startswith("rds") and name in databases]
    applied = world.applied_folders()
    if applied:
        protect = [folder for folder in applied if folder != "1-connect"]
        lines.append("Still applied: " + ", ".join(protect + (["1-connect"] if "1-connect" in applied else []))
                     + ". Destroy each 2-protect- folder first, 1-connect last (docs/operate.md, Take a trial down).")
    return "READY", lines


def print_results(results):
    for state, check, detail in results:
        first, *rest = detail.split("\n")
        print(f"{state:5} {check:13} {first}")
        for line in rest:
            print(f"{'':20}{line}")


# --- The real world ------------------------------------------------------------------------------

def real_world(flags=None):
    settings_path = os.path.join(CONNECT, "terraform.tfvars")
    return World(
        settings_path=settings_path,
        terraform_version=terraform_version,
        aws_cli_found=lambda: shutil.which("aws") is not None,
        signed_in_account=signed_in_account,
        clumio_credentials_set=lambda: bool(os.environ.get("CLUMIO_API_TOKEN") and os.environ.get("CLUMIO_API_BASE_URL")),
        clumio_get=clumio_get,
        kit=lambda: kit_from(flags) if flags else kit_from(read_settings(settings_path)[0]),
        tagged_resources=aws_tagged_resources,
        databases=aws_databases,
        volumes=aws_volumes,
        instances=aws_instances,
        applied_folders=applied_folders,
        pending_rule_folders=pending_rule_folders,
    )


def run_json(command, timeout=60):
    """Run a read-only command and parse its JSON output; None when it fails."""
    try:
        answer = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return json.loads(answer.stdout) if answer.returncode == 0 and answer.stdout.strip() else None


def flag_problem(account, region, unit, mode_flag):
    """Why the --account, --region and --unit flags can't be used as given, or None. They name the
    account to check for status and --json; preflight and teardown read 1-connect's settings, mode
    included, so a flag there would check one account and report another (cold review, 2026-10-28)."""
    given = [flag for flag in (account, region, unit) if flag]
    if not given:
        return None
    if len(given) < 3:
        return "Give --account, --region and --unit together, or none of them."
    if mode_flag:
        return "--account, --region and --unit work with status and --json only. --preflight and --teardown read 1-connect/terraform.tfvars."
    return None


def kit_from(settings):
    """The account, Region and unit to check, from 1-connect's settings or the flags; None when any is
    missing or malformed. The unit becomes the ID Clumio uses: "global" is the all-zero ID."""
    if not all(key in settings and re.match(SETTING_SHAPES[key][0], settings[key]) for key in ("account_id", "region", "organizational_unit")):
        return None
    unit = settings["organizational_unit"]
    return {"account_id": settings["account_id"], "region": settings["region"],
            "organizational_unit_id": GLOBAL_UNIT if unit == "global" else unit}


def pending_rule_folders():
    """The 2-protect- folders for RDS, Aurora, EC2 or EBS (copies too, such as 2-protect-rds-silver) that
    have settings but no rule in their state yet: each will add one rule to the unit."""
    found = []
    for folder in sorted(os.listdir(ROOT)):
        workload = folder[len("2-protect-"):].split("-")[0] if folder.startswith("2-protect-") else ""
        if workload not in RULE_WORKLOADS or not os.path.exists(os.path.join(ROOT, folder, "terraform.tfvars")):
            continue
        try:
            with open(os.path.join(ROOT, folder, "terraform.tfstate"), encoding="utf-8") as file:
                applied = any(r.get("type") == "clumio_policy_rule" for r in json.load(file).get("resources", []))
        except (OSError, ValueError):
            applied = False
        if not applied:
            found.append(folder)
    return found


def applied_folders():
    """The 1-connect and 2-protect- folders at the repository root whose local state holds resources."""
    found = []
    for folder in sorted(os.listdir(ROOT)):
        state = os.path.join(ROOT, folder, "terraform.tfstate")
        if (folder == "1-connect" or folder.startswith("2-protect-")) and os.path.exists(state):
            try:
                with open(state, encoding="utf-8") as file:
                    if json.load(file).get("resources"):
                        found.append(folder)
            except (OSError, ValueError):
                found.append(folder)  # Unreadable: say so by listing it, never assume it's empty.
    return found


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


def aws_instances(region):
    """The IDs of the instances in the Region that aren't terminated or being terminated."""
    answer = run_json(["aws", "ec2", "describe-instances", "--region", region, "--filters",
                       "Name=instance-state-name,Values=pending,running,stopping,stopped", "--query",
                       "Reservations[].Instances[].InstanceId", "--output", "json"], timeout=120)
    if answer is None:
        raise AwsUnavailable(f"AWS didn't list the instances in {region}. Check your sign-in, then run again.")
    return set(answer)


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


def run_status(as_json, flags=None):
    records, unit_result = coverage(real_world(flags))
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


def run_teardown():
    state, lines = teardown(real_world())
    print(f"{state}: " + {"REFUSED": "teardown is refused.", "BLOCKED": "Clumio is still working on this folder's resources:",
                          "READY": "nothing is running. Left behind after teardown:", "UNKNOWN": ""}[state])
    for line in lines:
        print(f"  {line}")
    return 0 if state == "READY" else (2 if state == "UNKNOWN" else 1)


def main():
    parser = argparse.ArgumentParser(description="Read-only checks of the kit in one account and Region. Nothing changes.")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--preflight", action="store_true", help="check everything before the first plan")
    choice.add_argument("--teardown", action="store_true", help="whether teardown is safe now")
    parser.add_argument("--json", action="store_true", help="coverage as JSON, for machines")
    parser.add_argument("--account", help="with --region and --unit: check this account instead of 1-connect's settings")
    parser.add_argument("--region")
    parser.add_argument("--unit", help='"global", or a unit\'s ID')
    args = parser.parse_args()
    problem = flag_problem(args.account, args.region, args.unit, args.preflight or args.teardown)
    if problem:
        parser.error(problem)
    flags = {"account_id": args.account, "region": args.region, "organizational_unit": args.unit} if args.account else None
    if not args.preflight and not (os.environ.get("CLUMIO_API_TOKEN") and os.environ.get("CLUMIO_API_BASE_URL")):
        print("Export your Clumio details first (0-check/README.md): export CLUMIO_API_BASE_URL=<your API URL>, "
              "then read -rs CLUMIO_API_TOKEN && export CLUMIO_API_TOKEN")
        sys.exit(2)
    try:
        if args.preflight:
            results = preflight(real_world())
            print_results(results)
            print("Ready. Next: the step you're on (README.md, What to do)." if exit_code(results) == 0 else "Fix each FAIL above, then run tools/status.py --preflight again.")
            sys.exit(exit_code(results))
        sys.exit(run_teardown() if args.teardown else run_status(args.json, flags))
    except NothingApplied:
        print("No account, Region and unit to check: set them in 1-connect/terraform.tfvars (0-check/README.md), "
              "or pass --account, --region and --unit.")
        sys.exit(1)
    except (AwsUnavailable, ClumioUnavailable) as error:
        print(f"UNKNOWN: {error}")
        sys.exit(2)


if __name__ == "__main__":
    main()
