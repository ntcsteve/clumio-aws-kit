#!/usr/bin/env python3
"""Turn a `terraform show -json` plan of Clumio's aws-template module into a review pack.

    extract.py <plan.json> <out_dir> <account_id> <region> <work_dir>

Writes <out_dir>/summary.md, <out_dir>/policies/*.json (including deploy-role-policy.json) and
<work_dir>/deploy-check.tsv (what preview.sh asks the IAM simulator). Reads only the plan
file: no AWS, no network. Called by preview.sh.
"""
import json
import os
import re
import sys
from collections import namedtuple

# Stand-ins preview.sh passes for values Clumio issues at connect time. Must match preview.sh.
PLACEHOLDERS = {
    "PREVIEWCLUMIOTOKEN": "<CLUMIO_TOKEN>",
    "PREVIEWEXTERNALID": "<EXTERNAL_ID>",
    "111111111111": "<CLUMIO_AWS_ACCOUNT_ID>",
    "222222222222": "<CLUMIO_DATA_PLANE_ACCOUNT_ID>",
}
NEW_ARN = "<ARN(s) of resources created in the same run>"
POLICY_TYPES = ("aws_iam_policy", "aws_iam_role_policy")


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    plan_file, out, account, region, work = sys.argv[1:]
    plan_text = open(plan_file).read()
    missing = [p for p in PLACEHOLDERS if p not in plan_text]
    if missing:
        sys.exit(f"FAIL: placeholders {missing} not in the plan: preview.sh and extract.py disagree")

    masks = {account: "<ACCOUNT_ID>", **PLACEHOLDERS}
    plan_json = json.loads(plan_text)
    call = template_call(plan_json["configuration"]["root_module"])
    if call is None:
        sys.exit("FAIL: no clumio-code/aws-template module call in the plan: preview.sh and extract.py disagree")
    plan = Plan(plan_json, call["module"], masks)
    # The settings and module version come from the plan itself (setup's terraform.tfvars).
    settings = {name: v["value"] for name, v in plan_json["variables"].items()}
    version = call["version_constraint"]

    allow = deploy_requirements(plan, region, settings)
    write_json(f"{out}/policies/deploy-role-policy.json", deploy_role_policy(allow))
    write_check_list(allow, f"{work}/deploy-check.tsv")
    review = review_points(plan, settings)
    lines = header(region, settings, version, plan)
    lines += allow_section(allow)
    lines += review_section(review)
    lines += roles_section(plan, out)
    lines += policies_section(plan, out)
    lines += resource_policies_section(plan, out)
    lines += other_resources_section(plan)
    all_actions = plan.all_actions()
    lines += actions_section(all_actions)
    open(f"{out}/summary.md", "w").write("\n".join(lines) + "\n")

    print_outcome(plan, region, all_actions, allow, review)


class Plan:
    """The resources the plan would create, and how they point at each other."""

    def __init__(self, plan, module, masks):
        self.masks = masks
        self.creates = [c for c in plan["resource_changes"] if c["change"]["actions"] == ["create"]]
        self.reads = {key(c["address"]): c for c in plan["resource_changes"] if c["change"]["actions"] == ["read"]}
        self.config = {r["address"]: r for r in module["resources"]}
        self.roles = {key(c["address"]): c for c in self.of_type("aws_iam_role")}
        policies = {key(c["address"]): c for c in self.of_type("aws_iam_policy")}
        # Which role each attachment and inline policy belongs to, read from the config's
        # references ("aws_iam_role.clumio_iam_role"), never guessed from names.
        self.managed_of = {r: [] for r in self.roles}
        for c in self.of_type("aws_iam_role_policy_attachment"):
            self.managed_of[self.points_to(c, "role")].append(policies[self.points_to(c, "policy_arn")])
        self.inline_of = {r: [] for r in self.roles}
        for c in self.of_type("aws_iam_role_policy"):
            self.inline_of[self.points_to(c, "role")].append(c)

    def of_type(self, resource_type):
        return [c for c in self.creates if c["type"] == resource_type]

    def points_to(self, change, expression):
        ref = self.config[key(change["address"])]["expressions"][expression]["references"][-1]
        return ".".join(strip_index(ref).split(".")[:2])

    def mask(self, text):
        for real, placeholder in self.masks.items():
            text = text.replace(real, placeholder)
        return text

    def document(self, change):
        """A policy document. A few name ARNs created in the same run, so the plan can't print
        them whole: those are rebuilt from their aws_iam_policy_document statements, with only
        the new ARNs as placeholders."""
        if after(change).get("policy"):
            return json.loads(self.mask(after(change)["policy"]))
        ref = strip_index(self.config[key(change["address"])]["expressions"]["policy"]["references"][-1])
        source = self.reads[".".join(ref.split(".")[:3])]["change"]
        known, unknown = source["after"]["statement"], source["after_unknown"].get("statement", [])
        if len(unknown) not in (0, len(known)):
            sys.exit(f"FAIL: {change['address']}: plan statement lists differ in length; refusing a partial policy")
        statements = [statement_from_source(s, unknown[i] if unknown else {}) for i, s in enumerate(known)]
        return json.loads(self.mask(json.dumps({"Version": "2012-10-17", "Statement": statements})))

    def all_actions(self):
        return sorted({a for t in POLICY_TYPES for c in self.of_type(t) for a in actions(self.document(c))})


HANDLED_FIELDS = {"sid", "effect", "actions", "resources", "condition", "principals"}


def statement_from_source(st, unknown):
    other = [k for k, v in st.items() if v not in (None, [], "", {}) and k not in HANDLED_FIELDS]
    if other:   # not_actions, not_resources, not_principals: rebuilding without them would misstate the policy
        sys.exit(f"FAIL: a policy statement uses {other}, which this tool does not render; read the module's policy directly")
    res_unknown = unknown.get("resources", [])
    if res_unknown is True:
        resources = [NEW_ARN]
    else:
        resources = [NEW_ARN if (i < len(res_unknown) and res_unknown[i]) else r
                     for i, r in enumerate(st.get("resources") or [])]
    out = {"Sid": st.get("sid") or None, "Effect": st["effect"], "Action": st["actions"], "Resource": resources}
    if st.get("principals"):
        out["Principal"] = {}
        for pr in st["principals"]:
            out["Principal"].setdefault(pr["type"], []).extend(pr["identifiers"])
    if st.get("condition"):
        out["Condition"] = {}
        for cnd in st["condition"]:
            out["Condition"].setdefault(cnd["test"], {})[cnd["variable"]] = cnd["values"]
    return {k: v for k, v in out.items() if v is not None}


# --- What to allow, what to review: computed from the plan ----------------------

ROLE_PURPOSE = {  # what each Clumio role is for, by its resource name in Clumio's module
    "aws_iam_role.clumio_iam_role": "Clumio's main role: find, back up and restore your data",
    "aws_iam_role.clumio_support_role": "Clumio support: open and read AWS Support cases",
    "aws_iam_role.clumio_s3_continuous_backup_event_bridge_role": "EventBridge: send S3 change events to Clumio",
}


# What Terraform calls, per resource type, across create, update and destroy: taken from
# CloudTrail during live runs (module 0.41.0), not assumed. Plus tagging (the module tags its
# roles; CreateRole with tags is denied without iam:TagRole, proven live) and boundary actions.
ROLE_MANAGE = ["iam:TagRole", "iam:UntagRole", "iam:ListRoleTags", "iam:GetRole", "iam:DeleteRole",
               "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
               "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
               "iam:UpdateAssumeRolePolicy", "iam:UpdateRole"]          # the last two: module upgrades
ROLE_CREATE = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
ROLE_ATTACH = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
ROLE_UNBOUND = ["iam:DeleteRolePermissionsBoundary"]                    # only when no boundary is required
POLICY_ACTIONS = ["iam:CreatePolicy", "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions",
                  "iam:CreatePolicyVersion", "iam:DeletePolicyVersion", "iam:DeletePolicy"]
TOPIC_ACTIONS = ["sns:CreateTopic", "sns:GetTopicAttributes", "sns:SetTopicAttributes",
                 "sns:ListTagsForResource", "sns:DeleteTopic"]
RULE_ACTIONS = ["events:PutRule", "events:DescribeRule", "events:ListTagsForResource", "events:PutTargets",
                "events:ListTargetsByRule", "events:RemoveTargets", "events:DeleteRule"]
# modules/profile reads each database's PITR window at plan time, to stop a plan that would shorten
# one. Taken from Terraform's debug log on a live read (spike S6, 2026-10-28): tags come inside these
# answers, so no rds:ListTagsForResource. Each action is granted, and checked, on its own resource type.
DATABASE_READS = [("ReadRdsInstances", "Read RDS instances' PITR windows (the shorter-window guard)", "rds:DescribeDBInstances", "db"),
                  ("ReadAuroraClusters", "Read Aurora clusters' PITR windows (the shorter-window guard)", "rds:DescribeDBClusters", "cluster")]

# One statement of the deploy role's policy (grants: a list of resource patterns), and how to
# check it with the IAM simulator (checks: one (real ARN, extra context) pair per call to test).
Row = namedtuple("Row", "sid label actions grants condition call_region checks")


def context_entry(key, values, kind="string"):
    return {"ContextKeyName": key, "ContextKeyValues": listify(values), "ContextKeyType": kind}


def deploy_requirements(plan, region, settings):
    """The deploy role's statements. Grants are built from the common start of the real names
    (never assumed); attachments are limited to Clumio's own policies, and role creation to
    your permissions boundary when you set one, so the role can't grant itself more."""
    def pattern(changes):
        start = os.path.commonprefix([plan.mask(after(c)["name"]) for c in changes]).split("<")[0]
        if "Clumio" not in start:   # never widen to e.g. role/*: every role in the account
            sys.exit(f"FAIL: names share no Clumio prefix ({start!r}); refusing a broad grant")
        return start + "*"
    def arns(base, changes):
        return [base + plan.mask(after(c)["name"]) for c in changes]
    # IAM ARNs come from each entity's OWN path: Clumio's module doesn't apply iam_path to every
    # one (module 0.41.0 creates ClumioS3EbPolicy at /), so one path for all would grant the wrong ARN.
    def iam_arn(kind, change):
        return f"arn:aws:iam::<ACCOUNT_ID>:{kind}{after(change)['path']}{plan.mask(after(change)['name'])}"
    def iam_grants(kind, changes):   # one pattern per distinct path
        by_path = {}
        for c in changes:
            by_path.setdefault(after(c)["path"], []).append(c)
        return [f"arn:aws:iam::<ACCOUNT_ID>:{kind}{path}{pattern(group)}" for path, group in sorted(by_path.items())]
    boundary = settings.get("permissions_boundary_arn") or ""
    tags = {"Vendor": "Clumio", **(settings.get("role_tags") or {})}
    tag_context = [context_entry(f"aws:RequestTag/{k}", v) for k, v in tags.items()]
    tag_context.append(context_entry("aws:TagKeys", sorted(tags), "stringList"))
    rows = []
    roles, policies = plan.of_type("aws_iam_role"), plan.of_type("aws_iam_policy")
    topics, rules = plan.of_type("aws_sns_topic"), plan.of_type("aws_cloudwatch_event_rule")
    if roles:
        role_grants = iam_grants("role", roles)
        boundary_context = [context_entry("iam:PermissionsBoundary", boundary)] if boundary else []
        rows.append(Row("ClumioRoles", "Manage roles and their inline policies",
                        ROLE_MANAGE + ([] if boundary else ROLE_UNBOUND), role_grants, None, "us-east-1",
                        [(iam_arn("role", r), tag_context) for r in roles]))
        rows.append(Row("ClumioRoleCreate", "Create roles" + (" (only with your permissions boundary)" if boundary else ""),
                        ROLE_CREATE, role_grants, {"StringEquals": {"iam:PermissionsBoundary": plan.mask(boundary)}} if boundary else None,
                        "us-east-1", [(iam_arn("role", r), tag_context + boundary_context) for r in roles]))
    if roles and policies:
        # One check per real attachment, each with that policy's own ARN as iam:PolicyARN.
        attachments = [(iam_arn("role", plan.roles[role]), [context_entry("iam:PolicyARN", iam_arn("policy", p))])
                       for role, attached in plan.managed_of.items() for p in attached]
        rows.append(Row("ClumioPolicyAttachments", "Attach Clumio-named policies to those roles",
                        ROLE_ATTACH, role_grants, {"ArnLike": {"iam:PolicyARN": one_or_list(iam_grants("policy", policies))}},
                        "us-east-1", attachments))
    if policies:
        rows.append(Row("ClumioManagedPolicies", "Managed policies", POLICY_ACTIONS, iam_grants("policy", policies),
                        None, "us-east-1", [(iam_arn("policy", p), []) for p in policies]))
    if topics:
        base = f"arn:aws:sns:{region}:<ACCOUNT_ID>:"
        rows.append(Row("ClumioSnsTopic", "SNS topic", TOPIC_ACTIONS, [base + pattern(topics)], None,
                        region, [(arn, []) for arn in arns(base, topics)]))
    if rules:
        base = f"arn:aws:events:{region}:<ACCOUNT_ID>:rule/"
        rows.append(Row("ClumioEventBridgeRules", "EventBridge rules and targets", RULE_ACTIONS, [base + pattern(rules)],
                        None, region, [(arn, []) for arn in arns(base, rules)]))
    if "rds" in (settings.get("workloads") or []):   # a profile with databases needs "rds" in workloads
        for sid, label, action, kind in DATABASE_READS:
            grant = f"arn:aws:rds:{region}:<ACCOUNT_ID>:{kind}:*"
            rows.append(Row(sid, label, [action], [grant], None, region, [(grant, [])]))
    return rows


def deploy_role_policy(rows):
    """An IAM policy for the identity that runs Terraform: exactly the rows, nothing more."""
    return {"Version": "2012-10-17", "Statement": [
        {"Sid": r.sid, "Effect": "Allow", "Action": r.actions, "Resource": one_or_list(r.grants), **({"Condition": r.condition} if r.condition else {})}
        for r in rows]}


def write_check_list(rows, path):
    """One line per action set and real ARN: what preview.sh asks the IAM simulator, with the
    request context an SCP may test (Region; tags, boundary and policy ARN where they apply)."""
    with open(path, "w") as f:
        for r in rows:
            for arn, extra in r.checks:
                context = json.dumps([context_entry("aws:RequestedRegion", r.call_region)] + extra)
                f.write(f"{' '.join(r.actions)}\t{arn}\t{context}\n")


def review_points(plan, settings):
    """Broad permissions worth a security review, found by reading the policy documents."""
    every = [st for t in POLICY_TYPES for c in plan.of_type(t) for st in plan.document(c)["Statement"]]
    statements = [st for st in every if st.get("Effect") == "Allow"]   # what Clumio may do
    denied_roles = sorted({r for st in every if st.get("Effect") == "Deny" and "iam:PassRole" in listify(st.get("Action"))
                           for r in listify(st.get("Resource"))})
    def has(action, resource_test=lambda r: True, condition_test=lambda cond: True):
        return any(action in listify(st.get("Action")) and any(resource_test(r) for r in listify(st.get("Resource")))
                   and condition_test(st.get("Condition", {})) for st in statements)
    def resource_account(cond):
        return {v for block in cond.values() for k, vals in block.items() if k == "s3:ResourceAccount" for v in listify(vals)}
    all_s3 = lambda r: r == "arn:aws:s3:::*"
    checks = [
        (has("kms:Decrypt", lambda r: r.endswith(":*:*:key/*")),
         "KMS: can use ANY key whose key policy lets IAM grant access (needed for encrypted data)"),
        (has("s3:GetObject", all_s3, lambda c: not resource_account(c)),
         "S3 read: objects in any bucket it can reach, including other accounts' buckets whose bucket policy allows it"),
        (has("s3:DeleteObject", all_s3, lambda c: resource_account(c) == {"<ACCOUNT_ID>"}),
         "S3 write + delete: objects in every bucket in this account (restores)"),
        (has("s3:DeleteObject", all_s3, lambda c: resource_account(c) != {"<ACCOUNT_ID>"}),
         "S3 write + delete: objects in every bucket, NOT limited to this account"),
        (has("s3:PutBucketNotification"),
         "S3: can change a bucket's event notifications and inventory configuration"),
        (has("s3:PutObject", lambda r: "clumio-s3-backup" in r, lambda c: "*" in resource_account(c)),
         "S3 copy out: to clumio-s3-backup* buckets in ANY AWS account (Clumio's data_plane_account_id not set)"),
        (has("s3:PutObject", lambda r: "clumio-s3-backup" in r, lambda c: resource_account(c) == {"<CLUMIO_DATA_PLANE_ACCOUNT_ID>"}),
         "S3 copy out: only to clumio-s3-backup* buckets in Clumio's data plane account"),
        (has("events:PutRule", lambda r: "clumio-s3-event-rule" in r),
         "At runtime: creates EventBridge rules clumio-s3-event-rule-* in this account"),
        (has("s3:PutStorageLensConfiguration"),
         "At runtime: creates S3 Storage Lens configurations clumio-storage-lens-*"),
        (has("events:PutEvents") or has("sqs:SendMessage"),
         "Sends events and messages to Clumio's event bus and queues"),
        (has("iam:PassRole", lambda r: r == NEW_ARN),
         "IAM PassRole: to a role this setup creates"),
        (has("rds:ModifyDBCluster", lambda r: r.endswith(":cluster:*")) or has("rds:ModifyDBInstance", lambda r: r.endswith(":db:*")),
         "RDS: can change settings of every database in this region, not only tagged ones (it sets backup retention); "
         "creates, copies, deletes snapshots. The same IAM serves DocumentDB and Neptune"),
        (has("ec2:RunInstances"),
         "EC2: can launch instances (restores)"),
        (has("ec2:TerminateInstances", condition_test=lambda c: "aws:ResourceTag/clumio.restore.tag" in str(c)),
         "EC2: can terminate only instances it restored (tag clumio.restore.tag)"),
        (has("ec2:TerminateInstances", condition_test=lambda c: "clumio.restore.tag" not in str(c)),
         "EC2: can terminate instances NOT limited to ones it restored - check it"),
        (has("ec2:DeleteSnapshot", condition_test=lambda c: "aws:ResourceTag/Vendor" in str(c)),
         "EC2: can delete only snapshots tagged Vendor=Clumio"),
        (has("support:CreateCase"),
         "Support: can open, read and update AWS Support cases in this account"
         + (", and read Trusted Advisor results" if any(a.startswith("support:DescribeTrustedAdvisor") for st in statements
                                                        for a in listify(st.get("Action"))) else "")),
    ]
    points = [text for found, text in checks if found]
    # Entities the module creates outside iam_path: a naming rule or SCP on paths must allow them.
    for change in plan.of_type("aws_iam_role") + plan.of_type("aws_iam_policy"):
        if after(change)["path"] != settings["iam_path"]:
            points.insert(0, f"IAM path: `{plan.mask(after(change)['name'])}` is created at `{after(change)['path']}`, not at iam_path "
                             f"`{settings['iam_path']}` (Clumio's module doesn't apply iam_path to it). A path rule needs an exception")
    # PassRole on roles this setup doesn't create: say exactly which roles and to which service.
    for st in statements:
        if "iam:PassRole" in listify(st.get("Action")) and any(r != NEW_ARN for r in listify(st.get("Resource"))):
            services = sorted({v for block in st.get("Condition", {}).values()
                               for k, vals in block.items() if k == "iam:PassedToService" for v in listify(vals)})
            points.append(f"IAM PassRole: on {', '.join(listify(st['Resource']))}, only to {', '.join(services) or 'ANY service'}"
                          + (" (restores re-attach a database's own roles)" if services == ["rds.amazonaws.com"] else "")
                          + (" (restored instances get their instance role)" if services == ["ec2.amazonaws.com*"] else ""))
    if denied_roles:
        points.append(f"IAM PassRole: explicitly DENIED on {', '.join(denied_roles)} (your pass_role_deny_list)")
    points += resource_policy_points(plan)
    return points


def resource_policy_points(plan):
    """What the SNS topic's resource policy lets other principals do."""
    points = []
    for change in plan.of_type("aws_sns_topic_policy"):
        for st in plan.document(change)["Statement"]:
            who = ", ".join("any principal" if p == "*" else p for v in st["Principal"].values() for p in listify(v))
            cond = "; ".join(f"only if {k} = {', '.join(listify(v))}" for block in st.get("Condition", {}).values() for k, v in block.items())
            points.append(f"SNS topic policy: {', '.join(listify(st['Action']))} by {who}" + (f", {cond}" if cond else ""))
    return points


def allow_section(rows):
    lines = ["## What the deploy role needs\n",
             "The identity that runs Terraform needs all of these: create, read, update and destroy (from CloudTrail on"
             " live runs), plus tagging and boundary actions. The policy is `policies/deploy-role-policy.json`.\n",
             "> **Before attaching it,** replace `<ACCOUNT_ID>` with your account ID: "
             "`sed 's/<ACCOUNT_ID>/123456789012/g' policies/deploy-role-policy.json`\n",
             "| What | Actions | Resource | Condition |\n| --- | --- | --- | --- |"]
    lines += [f"| {r.label} | `{', '.join(r.actions)}` | `{', '.join(r.grants)}` | {('`' + json.dumps(r.condition) + '`') if r.condition else 'none'} |"
              for r in rows]
    return lines


def review_section(points):
    return (["\n## Review before approving\n", "Highlights found in the policies below. Read every file in `policies/` before approving.\n"]
            + [f"- {p}" for p in points] + [""])


def print_outcome(plan, region, all_actions, allow, review):
    services = sorted({a.split(":")[0] for a in all_actions})
    managed, inline = len(plan.of_type("aws_iam_policy")), len(plan.of_type("aws_iam_role_policy"))
    other = len(plan.of_type("aws_sns_topic")) + len(plan.of_type("aws_cloudwatch_event_rule"))
    print(f"\nClumio would create in {region} (nothing was created):")
    for role, change in sorted(plan.roles.items(), key=lambda kv: after(kv[1])["name"]):
        print(f"  role  {plan.mask(after(change)['name'])}")
        print(f"        {ROLE_PURPOSE.get(role, '')}")
    print(f"  + {managed} managed and {inline} inline policies, {other} SNS/EventBridge resources")
    print(f"  = {len(all_actions)} permissions across {len(services)} AWS services ({', '.join(services)})")
    print("\nThe deploy role needs (policies/deploy-role-policy.json; replace <ACCOUNT_ID> first):")
    for r in allow:
        print(f"  {len(r.actions):2} actions  {r.label:<50} on {', '.join(r.grants)}")
    print("\nReview before approving (highlights; read every file in policies/):")
    for point in review:
        print(f"  - {point}")


# --- Sections of summary.md --------------------------------------------------

def header(region, settings, version, plan):
    tags = {"Vendor": "Clumio", **(settings.get("role_tags") or {})}
    return [
        f"# Clumio IAM preview: {region}\n",
        f"What Clumio's Terraform module `aws-template` v{version} creates in account `<ACCOUNT_ID>`, "
        f"rendered by `terraform plan` (nothing was created).\n",
        f"Settings: prefix `{settings['iam_prefix'] or '(Clumio default names)'}`, IAM path `{settings['iam_path']}`, "
        f"workloads `{','.join(settings['workloads'])}`.\n",
        f"Role tags `{tags}`; permissions boundary `{plan.mask(settings.get('permissions_boundary_arn') or 'none')}`; "
        f"pass-role deny list: {len(settings.get('pass_role_deny_list') or [])} role(s).\n",
        "`<CLUMIO_TOKEN>`, `<EXTERNAL_ID>`, `<CLUMIO_AWS_ACCOUNT_ID>`, `<CLUMIO_DATA_PLANE_ACCOUNT_ID>` are issued by Clumio when you connect.\n",
    ]


def roles_section(plan, out):
    lines = ["## Roles\n\n| Role | Path | Who can assume it | Managed policies | Inline policies |\n| --- | --- | --- | --- | --- |"]
    for role, change in sorted(plan.roles.items(), key=lambda kv: after(kv[1])["name"]):
        a = after(change)
        trust = json.loads(plan.mask(a["assume_role_policy"]))
        write_json(f"{out}/policies/{file_name('trust--' + plan.mask(a['name']))}.json", trust)
        managed = ", ".join(f"`{plan.mask(after(p)['name'])}`" for p in plan.managed_of[role]) or "none"
        inline = ", ".join(f"`{plan.mask(after(p)['name'])}`" for p in plan.inline_of[role]) or "none"
        lines.append(f"| `{plan.mask(a['name'])}` | `{a['path']}` | {who_can_assume(trust)} | {managed} | {inline} |")
    return lines


def policies_section(plan, out):
    lines = ["\n## Policies\n\n| Policy | Kind | Path | Actions | Broad resource (`*`, all S3, any KMS key) | File |\n| --- | --- | --- | --- | --- | --- |"]
    for change in plan.creates:
        if change["type"] not in POLICY_TYPES:
            continue
        doc = plan.document(change)
        name = plan.mask(after(change)["name"])
        kind = "managed" if change["type"] == "aws_iam_policy" else "inline"
        path = f"policies/{file_name(f'{kind}--{name}')}.json"
        write_json(f"{out}/{path}", doc)
        iam_path = f"`{after(change)['path']}`" if kind == "managed" else "-"
        lines.append(f"| `{name}` | {kind} | {iam_path} | {len(actions(doc))} | {'yes' if is_broad(doc) else 'no'} | `{path}` |")
    return lines


def resource_policies_section(plan, out):
    lines = ["\n## Resource policies\n\n| Resource | File |\n| --- | --- |"]
    for change in plan.of_type("aws_sns_topic_policy"):
        topic = next((after(t)["name"] for t in plan.of_type("aws_sns_topic")), "sns-topic")
        path = f"policies/{file_name('resource--' + plan.mask(topic))}.json"
        write_json(f"{out}/{path}", plan.document(change))
        lines.append(f"| SNS topic `{plan.mask(topic)}` | `{path}` |")
    return lines


def other_resources_section(plan):
    lines = ["\n## Other resources\n\n| Type | Name |\n| --- | --- |"]
    for change in plan.creates:
        if change["type"] in ("aws_sns_topic", "aws_cloudwatch_event_rule", "aws_iam_instance_profile"):
            name = after(change).get("name") or short(change["address"])
            lines.append(f"| `{change['type']}` | `{plan.mask(name)}` |")
    return lines


def actions_section(all_actions):
    lines = ["\n## All actions, by service\n"]
    for service in sorted({a.split(":")[0] for a in all_actions}):
        lines.append(f"- **{service}**: " + ", ".join(a.split(":")[1] for a in all_actions if a.startswith(service + ":")))
    return lines


# --- Small helpers -----------------------------------------------------------

def after(change):
    return change["change"]["after"]


def template_call(module):
    """Clumio's aws-template call, wherever it sits: at the top of the plan, or inside modules/connection/iam."""
    for call in module.get("module_calls", {}).values():
        if call.get("source") == "clumio-code/aws-template/clumio":
            return call
        found = template_call(call.get("module", {}))
        if found:
            return found
    return None


def short(address):
    return re.sub(r"^(module\.[^.]+\.)+", "", address)  # the template has no modules of its own


def strip_index(address):
    return re.sub(r"\[.*?\]", "", address)


def key(address):
    return strip_index(short(address))          # e.g. "aws_iam_role.clumio_iam_role"


def one_or_list(values):
    return values[0] if len(values) == 1 else values   # IAM takes either; one stays a plain string


def listify(value):
    return [value] if isinstance(value, str) else (value or [])


def actions(doc):
    return sorted({a for st in doc["Statement"] for a in listify(st.get("Action"))})


def is_broad(doc):
    return any(r in ("*", "arn:aws:s3:::*") or r.endswith(":*:*:key/*")
               for st in doc["Statement"] for r in listify(st.get("Resource")))


def who_can_assume(trust):
    parts = []
    for st in trust["Statement"]:
        principals = sorted({p for v in st["Principal"].values() for p in listify(v)})
        conditions = sorted({k for block in st.get("Condition", {}).values() for k in block})
        parts.append(", ".join(principals) + (f" + {', '.join(conditions)}" if conditions else ""))
    return "; ".join(parts)


def file_name(text):
    return re.sub(r"[<>]", "", text)             # placeholders without shell-hostile < >


def write_json(file_path, doc):
    with open(file_path, "w") as f:
        json.dump(doc, f, indent=2)


if __name__ == "__main__":
    main()
