#!/usr/bin/env python3
"""Saves the evidence for the lab's key claims: what AWS and Clumio say about each lab resource's key,
protection and backups. Read-only: it only describes, lists and reads.

  python3 proof/capture.py <set> <capture name> [restored database ...]

Run after the lab is applied and protected, signed in to the lab's account, with CLUMIO_API_TOKEN and
CLUMIO_API_BASE_URL exported. Reads the lab's names from proof/lab's Terraform output. Writes
proof/evidence/<set>/<capture name>-<UTC time>/: one raw JSON answer per file, the account ID and
the organizational unit's ID masked as stand-ins, and _sha256.txt. Name restored databases to
capture their key and tags too.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "setup"))
import status  # noqa: E402  The one Clumio client, shared with make status.

ACCOUNT_STAND_IN = "123456789012"
UNIT_STAND_IN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def aws(region, *args):
    """One read-only AWS CLI call, as parsed JSON. A failed call stops the capture: half a capture
    would read as evidence of absence."""
    answer = subprocess.run(["aws", *args, "--region", region, "--output", "json"], capture_output=True, text=True, timeout=120)
    if answer.returncode != 0:
        sys.exit(f"FAIL: aws {' '.join(args)}: {answer.stderr.strip()}")
    return json.loads(answer.stdout or "{}")


def clumio(path, unit):
    status_code, body = status.clumio_get(path, unit=unit)
    if status_code != 200:
        sys.exit(f"FAIL: Clumio answered HTTP {status_code} for {path.split('?')[0]}")
    return body


def key_facts(region, key_id):
    """Who manages the key, its aliases, and for an AWS-managed key, the policy AWS wrote."""
    facts = {"describe-key": aws(region, "kms", "describe-key", "--key-id", key_id),
             "list-aliases": aws(region, "kms", "list-aliases", "--key-id", key_id)}
    if facts["describe-key"]["KeyMetadata"]["KeyManager"] == "AWS":
        facts["key-policy"] = aws(region, "kms", "get-key-policy", "--key-id", key_id, "--policy-name", "default")
    return facts


def database_facts(region, name, cluster, unit, account):
    kind = "describe-db-clusters" if cluster else "describe-db-instances"
    flag = "--db-cluster-identifier" if cluster else "--db-instance-identifier"
    described = aws(region, "rds", kind, flag, name)
    record = (described.get("DBClusters") or described.get("DBInstances"))[0]
    facts = {kind: described, "tags": aws(region, "rds", "list-tags-for-resource", "--resource-name",
                                          record.get("DBClusterArn") or record.get("DBInstanceArn"))}
    facts.update(key_facts(region, record["KmsKeyId"]))
    query = status.urllib.parse.quote(json.dumps({"account_native_id": {"$eq": account}, "name": {"$contains": name}}))
    found = clumio(f"/datasources/aws/rds-resources?limit=100&filter={query}", unit)
    facts["clumio-resource"] = found
    for asset in found.get("_embedded", {}).get("items", []):
        if asset.get("name") == name and asset.get("aws_region") == region:
            backups = status.urllib.parse.quote(json.dumps({"resource_id": {"$eq": asset["id"]}}))
            facts["clumio-backups"] = clumio(f"/backups/aws/rds-resources?limit=100&filter={backups}", unit)
    return facts


def bucket_facts(region, bucket, unit):
    facts = {f"head-{key}": aws(region, "s3api", "head-object", "--bucket", bucket, "--key", f"documents/{key}")
             for key in ("amk.txt", "cmk.txt")}
    for key in ("amk.txt", "cmk.txt"):
        facts.update({f"{key}-{name}": value for name, value in key_facts(region, facts[f"head-{key}"]["SSEKMSKeyId"]).items()})
    query = status.urllib.parse.quote(json.dumps({"bucket_name": {"$eq": bucket}}))
    facts["clumio-s3-assets"] = clumio(f"/datasources/protection-groups/s3-assets?limit=100&filter={query}", unit)
    return facts


def write_capture(folder, files, account, unit):
    """Writes each answer with the account and unit masked, then the manifest. Returns the manifest."""
    os.makedirs(folder)
    lines = []
    for name, answer in sorted(files.items()):
        text = json.dumps(answer, indent=1, sort_keys=True, default=str).replace(account, ACCOUNT_STAND_IN).replace(unit, UNIT_STAND_IN) + "\n"
        with open(os.path.join(folder, f"{name}.json"), "w") as out:
            out.write(text)
        lines.append(f"{hashlib.sha256(text.encode()).hexdigest()}  {name}.json")
    with open(os.path.join(folder, "_sha256.txt"), "w") as out:
        out.write("\n".join(lines) + "\n")
    return lines


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    evidence_set, capture, restored = sys.argv[1], sys.argv[2], sys.argv[3:]
    lab = subprocess.run(["terraform", "output", "-json", "lab"], capture_output=True, text=True, cwd=os.path.join(HERE, "lab"))
    kit = status.terraform_kit()
    if lab.returncode != 0 or kit is None:
        sys.exit("FAIL: apply proof/lab and setup first: no lab or kit output to read.")
    lab, region, unit, account = json.loads(lab.stdout), kit["region"], kit["organizational_unit_id"], kit["account_id"]
    files = {}
    if lab["bucket"]:
        files.update({f"s3-{name}": value for name, value in bucket_facts(region, lab["bucket"], unit).items()})
    databases = [(lab["rds_amk"], False)] if lab["rds_amk"] else []
    databases += [(name, True) for name in lab["auroras"].values()] + [(name, True) for name in restored]
    for name, cluster in databases:
        files.update({f"{name}-{fact}": value for fact, value in database_facts(region, name, cluster, unit, account).items()})
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = os.path.join(HERE, "evidence", evidence_set, f"{capture}-{when}")
    write_capture(folder, files, account, unit)
    print(f"Wrote {len(files)} answers to {folder}. Read them, then run proof/verify-evidence.sh.")


if __name__ == "__main__":
    main()
