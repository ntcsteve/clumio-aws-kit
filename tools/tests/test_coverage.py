"""Tests for status.py's coverage (status), --preview and --teardown. Fakes stand in for AWS and
Clumio; each fake answer has the shape of a real one read on 2026-10-28, and the fake Clumio filters
the way the real API does, so a wrong filter in status.py fails here. Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

ACCOUNT, REGION = "123456789012", "us-west-2"
UNIT = "11111111-2222-3333-4444-555555555555"
POLICY, RULE, GROUP = "pol-gold", "rule-gold", "pg-gold"

KIT = {
    "account_id": ACCOUNT, "region": REGION, "organizational_unit_id": UNIT, "mode": "trial",
    "profiles": {"gold": {"tag": {"key": "clumio-profile", "value": "gold"}, "policy_id": POLICY, "rule_id": RULE,
                          "volume_tag": {"key": "clumio-volume-profile", "value": "gold"}, "volume_rule_id": "rule-gold-volumes",
                          "protection_group_id": GROUP, "workloads": {"s3": True, "databases": True, "ec2": True, "ebs_volumes": True}},
                 "dbonly": {"tag": {"key": "clumio-profile", "value": "dbonly"}, "policy_id": "pol-db", "rule_id": "rule-db",
                            "volume_tag": {"key": "clumio-volume-profile", "value": "dbonly"}, "volume_rule_id": None,
                            "protection_group_id": None, "workloads": {"s3": False, "databases": True, "ec2": False, "ebs_volumes": False}}},
}


def tagged(arn, value, key="clumio-profile"):
    return {"ResourceARN": arn, "Tags": [{"Key": key, "Value": value}]}


def instance(instance_id, value="gold"):
    return tagged(f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{instance_id}", value)


def volume(volume_id, value="gold", key="clumio-volume-profile"):
    return tagged(f"arn:aws:ec2:{REGION}:{ACCOUNT}:volume/{volume_id}", value, key)


def bucket(name, value="gold"):
    return tagged(f"arn:aws:s3:::{name}", value)


def database(name, value="gold", kind="db"):
    return tagged(f"arn:aws:rds:{REGION}:{ACCOUNT}:{kind}:{name}", value)


class FakeClumio:
    """Lists items per path and applies the request's filter as Clumio does ($eq, $contains, $in)."""

    def __init__(self):
        self.lists = {
            "/datasources/aws/rds-resources": [],
            "/backups/aws/rds-resources": [],
            "/datasources/protection-groups/s3-assets": [],
            "/datasources/aws/ec2-instances": [],
            "/datasources/aws/ebs-volumes": [],
            "/tasks": [],
        }
        self.single = {f"/connections/aws/{ACCOUNT}_{REGION}": (200, {"organizational_unit_id": UNIT}),
                       "/policies/rules/rule-other": (200, {"id": "rule-other", "name": "CEG Demo"})}
        self.broken = set()
        self.more_pages = set()  # paths whose answer says another page follows

    def get(self, path, unit=None):
        bare, _, query = path.partition("?")
        if bare in self.broken:
            return 500, {}
        if bare in self.single:
            return self.single[bare]
        if bare not in self.lists:
            return 404, {}
        found = self.lists[bare]
        params = urllib.parse.parse_qs(query)
        if "filter" in params:
            for field, test in json.loads(params["filter"][0]).items():
                found = [item for item in found if matches(lookup(item, field), test)]
        body = {"_embedded": {"items": found}}
        if bare in self.more_pages:
            body["total_pages_count"] = 2
        return 200, body


def lookup(item, dotted):
    for part in dotted.split("."):
        item = (item or {}).get(part)
    return item


def matches(value, test):
    (op, expected), = test.items()
    return {"$eq": value == expected, "$contains": isinstance(value, str) and expected in value,
            "$in": value in expected}[op]


class Coverage(unittest.TestCase):
    def setUp(self):
        self.clumio = FakeClumio()
        self.resources = []
        self.dbs = {}  # name -> {"pitr": days, "cluster": cluster name or None}
        self.vols = {}  # volume ID -> {"instance": the instance it's attached to, or None}
        self.kit = dict(KIT)
        self.plan = None

    def world(self):
        return status.World(
            settings_path="unused", terraform_version=lambda: "1.15.5", aws_cli_found=lambda: True,
            signed_in_account=lambda: ACCOUNT, clumio_credentials_set=lambda: True, clumio_get=self.clumio.get,
            kit=lambda: self.kit, saved_plan=lambda: self.plan,
            tagged_resources=lambda region: self.resources, databases=lambda region: self.dbs,
            volumes=lambda region: self.vols)

    def add_db(self, name, policy=POLICY, rule=RULE, backup=None, kind="db", pitr=7, cluster=None):
        self.resources.append(database(name, kind=kind))
        self.dbs[name] = {"pitr": pitr, "cluster": cluster}
        if policy is not None or kind != "member":
            asset = {"id": f"id-{name}", "name": name, "account_native_id": ACCOUNT, "aws_region": REGION, "is_deleted": False,
                     "protection_info": {"policy_id": policy, "rule_id": rule} if policy else None}
            self.clumio.lists["/datasources/aws/rds-resources"].append(asset)
        if backup:
            self.clumio.lists["/backups/aws/rds-resources"].append({"resource_id": f"id-{name}", "start_timestamp": backup})

    def add_bucket(self, name, in_group=True, backup=None, value="gold"):
        self.resources.append(bucket(name, value))
        if in_group:
            self.clumio.lists["/datasources/protection-groups/s3-assets"].append(
                {"id": f"asset-{name}", "bucket_name": name, "group_id": GROUP, "is_deleted": False,
                 "protection_info": {"policy_id": POLICY}, "last_backup_timestamp": backup})

    def add_instance(self, instance_id, policy=POLICY, backup=None, value="gold"):
        self.resources.append(instance(instance_id, value))
        self.clumio.lists["/datasources/aws/ec2-instances"].append(
            {"id": f"id-{instance_id}", "instance_native_id": instance_id, "account_native_id": ACCOUNT, "aws_region": REGION,
             "is_deleted": False, "protection_info": {"policy_id": policy, "rule_id": RULE}, "last_backup_timestamp": backup})

    def add_volume(self, volume_id, attached_to=None, key="clumio-volume-profile", policy=POLICY, backup=None):
        self.resources.append(volume(volume_id, key=key))
        self.vols[volume_id] = {"instance": attached_to}
        self.clumio.lists["/datasources/aws/ebs-volumes"].append(
            {"id": f"id-{volume_id}", "volume_native_id": volume_id, "account_native_id": ACCOUNT, "aws_region": REGION,
             "is_deleted": False, "protection_info": {"policy_id": policy, "rule_id": "rule-gold-volumes"}, "last_backup_timestamp": backup})

    def states(self):
        records, unit_result = status.coverage(self.world())
        return {r["name"]: r["state"] for r in records}, records, unit_result

    # --- status ---

    def test_a_database_with_our_policy_and_a_backup_is_ours(self):
        self.add_db("orders-db", backup="2026-10-28T05:00:00Z")
        states, records, unit = self.states()
        self.assertEqual(states["orders-db"], "OURS")
        self.assertIn("2026-10-28 05:00 UTC", records[0]["last_backup"])
        self.assertEqual(status.coverage_exit_code(records, unit), 0)

    def test_our_database_without_a_backup_is_waiting_and_not_a_failure(self):
        self.add_db("orders-db")
        states, records, unit = self.states()
        self.assertEqual(states["orders-db"], "WAITING")
        self.assertEqual(status.coverage_exit_code(records, unit), 0)

    def test_another_rule_winning_names_that_rule(self):
        self.add_db("orders-db", policy="pol-theirs", rule="rule-other")
        states, records, unit = self.states()
        self.assertEqual(states["orders-db"], "OTHER")
        self.assertIn("CEG Demo", records[0]["detail"])
        self.assertEqual(status.coverage_exit_code(records, unit), 1)

    def test_a_database_clumio_has_not_found_is_not_yet(self):
        self.resources.append(database("new-db"))
        self.dbs["new-db"] = {"pitr": 1, "cluster": None}
        states, _, _ = self.states()
        self.assertEqual(states["new-db"], "NOT_YET")

    def test_a_database_of_the_same_name_in_another_region_does_not_count(self):
        self.add_db("orders-db", backup="2026-10-28T05:00:00Z")
        self.clumio.lists["/datasources/aws/rds-resources"][0]["aws_region"] = "eu-west-1"
        states, _, _ = self.states()
        self.assertEqual(states["orders-db"], "NOT_YET")

    def test_an_aurora_cluster_is_checked_and_its_member_instances_are_not(self):
        self.add_db("orders-cluster", kind="cluster", backup="2026-10-28T05:00:00Z")
        self.resources.append(database("orders-cluster-1"))
        self.dbs["orders-cluster-1"] = {"pitr": 7, "cluster": "orders-cluster"}
        states, _, _ = self.states()
        self.assertEqual(states, {"orders-cluster": "OURS"})

    def test_a_bucket_in_our_group_with_a_backup_is_ours(self):
        self.add_bucket("orders-docs", backup="2026-10-28T06:00:00Z")
        states, _, _ = self.states()
        self.assertEqual(states["orders-docs"], "OURS")

    def test_a_bucket_not_yet_in_our_group_is_not_yet(self):
        self.add_bucket("orders-docs", in_group=False)
        states, _, _ = self.states()
        self.assertEqual(states["orders-docs"], "NOT_YET")

    def test_a_tag_naming_no_profile_is_a_bad_value(self):
        self.add_bucket("orders-docs", in_group=False, value="gld")
        states, records, unit = self.states()
        self.assertEqual(states["orders-docs"], "BAD_VALUE")
        self.assertIn("gold", records[0]["detail"])
        self.assertEqual(status.coverage_exit_code(records, unit), 1)

    def test_a_bucket_in_a_profile_without_s3_is_off(self):
        self.add_bucket("orders-docs", in_group=False, value="dbonly")
        states, records, unit = self.states()
        self.assertEqual(states["orders-docs"], "OFF")
        self.assertEqual(status.coverage_exit_code(records, unit), 1)

    def test_clumio_failing_is_unknown_never_a_guess(self):
        self.add_db("orders-db")
        self.clumio.broken.add("/datasources/aws/rds-resources")
        states, records, unit = self.states()
        self.assertEqual(states["orders-db"], "UNKNOWN")
        self.assertEqual(status.coverage_exit_code(records, unit), 2)

    def test_a_connection_in_another_unit_fails(self):
        self.clumio.single[f"/connections/aws/{ACCOUNT}_{REGION}"] = (200, {"organizational_unit_id": "another-unit"})
        _, records, unit = self.states()
        self.assertEqual(unit[0], "FAIL")
        self.assertEqual(status.coverage_exit_code(records, unit), 1)

    def test_nothing_applied_says_so(self):
        self.kit = None
        with self.assertRaises(status.NothingApplied):
            status.coverage(self.world())

    def test_json_lines_carry_every_field(self):
        self.add_db("orders-db", backup="2026-10-28T05:00:00Z")
        _, records, _ = self.states()
        self.assertEqual(set(records[0]), {"kind", "name", "profile", "state", "detail", "last_backup"})

    # --- EC2 and EBS ---

    def test_an_instance_with_our_policy_and_a_backup_is_ours(self):
        self.add_instance("i-0abc", backup="2026-10-28T07:00:00Z")
        states, _, _ = self.states()
        self.assertEqual(states["i-0abc"], "OURS")

    def test_an_instance_in_a_profile_without_ec2_is_off(self):
        self.add_instance("i-0abc", value="dbonly")
        states, _, _ = self.states()
        self.assertEqual(states["i-0abc"], "OFF")

    def test_a_volume_tagged_on_its_own_with_a_backup_is_ours(self):
        self.add_volume("vol-0aaa", backup="2026-10-28T07:00:00Z")
        states, _, _ = self.states()
        self.assertEqual(states["vol-0aaa"], "OURS")

    def test_a_volume_tagged_on_its_own_on_a_protected_instance_is_double(self):
        self.add_instance("i-0abc", backup="2026-10-28T07:00:00Z")
        self.add_volume("vol-0bbb", attached_to="i-0abc")
        states, records, unit = self.states()
        self.assertEqual(states["vol-0bbb"], "DOUBLE")
        self.assertIn("i-0abc", next(r["detail"] for r in records if r["name"] == "vol-0bbb"))
        self.assertEqual(status.coverage_exit_code(records, unit), 1)

    def test_a_volume_carrying_the_instance_tag_on_a_protected_instance_is_not_listed(self):
        self.add_instance("i-0abc", backup="2026-10-28T07:00:00Z")
        self.add_volume("vol-0ccc", attached_to="i-0abc", key="clumio-profile")
        states, _, _ = self.states()
        self.assertEqual(states, {"i-0abc": "OURS"})

    def test_an_unattached_volume_with_the_instance_tag_is_off_and_says_which_tag(self):
        self.add_volume("vol-0ddd", key="clumio-profile")
        states, records, _ = self.states()
        self.assertEqual(states["vol-0ddd"], "OFF")
        self.assertIn("clumio-volume-profile", records[0]["detail"])

    def test_teardown_waits_while_an_instance_backup_runs(self):
        self.add_instance("i-0abc")
        self.clumio.lists["/tasks"].append({"id": "4050", "status": "in_progress", "primary_entity": {"id": "id-i-0abc"}})
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "BLOCKED")

    def test_preview_flags_a_double_volume_before_anything_is_applied(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "ec2": True, "ebs_volumes": True, "pitr_retention_days": 3})
        self.resources = [instance("i-0abc"), volume("vol-0bbb")]
        self.vols = {"vol-0bbb": {"instance": "i-0abc"}}
        states = {line["name"]: line["state"] for line in status.preview(self.world())}
        self.assertEqual(states, {"i-0abc": "WILL_PROTECT", "vol-0bbb": "DOUBLE"})

    # --- Fixes from the cold review ---

    def test_teardown_waits_while_a_backup_is_aborting(self):
        self.add_db("orders-db")
        self.clumio.lists["/tasks"].append({"id": "4060", "status": "aborting", "primary_entity": {"id": "id-orders-db"}})
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "BLOCKED")

    def test_teardown_with_more_tasks_than_one_page_is_unknown_never_ready(self):
        self.add_db("orders-db")
        self.clumio.more_pages.add("/tasks")
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "UNKNOWN")

    def test_a_tagged_aurora_instance_on_an_untagged_cluster_is_off_and_names_the_cluster(self):
        self.resources.append(database("orders-cluster-1"))
        self.dbs = {"orders-cluster-1": {"pitr": 7, "cluster": "orders-cluster", "engine": "aurora-mysql"},
                    "orders-cluster": {"pitr": 7, "cluster": None, "engine": "aurora-mysql"}}
        states, records, _ = self.states()
        self.assertEqual(states["orders-cluster-1"], "OFF")
        self.assertIn("orders-cluster", records[0]["detail"])

    def test_documentdb_and_neptune_are_off_as_not_supported(self):
        self.resources.append(database("docs-cluster", kind="cluster"))
        self.dbs = {"docs-cluster": {"pitr": 7, "cluster": None, "engine": "docdb"}}
        states, records, _ = self.states()
        self.assertEqual(states["docs-cluster"], "OFF")
        self.assertIn("not supported", records[0]["detail"])

    # --- --preview, after terraform plan -out=tfplan ---

    def plan_with(self, **profiles):
        return {"variables": {"account_id": {"value": ACCOUNT}, "region": {"value": REGION},
                              "profiles": {"value": profiles}}}

    # The profile module stops a plan that shortens a window without allow_shorter_pitr, so a saved
    # plan has already passed that guard. The preview only shows each window, now and after.
    def test_preview_shows_a_shorter_window_and_leaves_the_judging_to_the_module(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3, "allow_shorter_pitr": True})
        self.resources = [database("orders-db")]
        self.dbs = {"orders-db": {"pitr": 7, "cluster": None}}
        lines = status.preview(self.world())
        self.assertEqual(lines[0]["state"], "WILL_PROTECT")
        self.assertIn("7 days now, 3 days after: shorter", lines[0]["detail"])

    # Taking a trial down saves its destroy plan as deploy/tfplan too. Previewing it as protection
    # would show every resource as WILL_PROTECT for a plan that removes all of it.
    def test_a_plan_that_only_removes_is_not_previewed_as_protection(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3})
        self.plan["resource_changes"] = [{"address": "module.profile[\"gold\"].clumio_policy.this", "change": {"actions": ["delete"]}},
                                         {"address": "module.connection.clumio_aws_connection.this", "change": {"actions": ["delete"]}}]
        self.resources = [database("orders-db")]
        with self.assertRaises(status.RemovalPlan):
            status.preview(self.world())

    def test_a_plan_that_creates_is_previewed(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 14})
        self.plan["resource_changes"] = [{"address": "module.profile[\"gold\"].clumio_policy.this", "change": {"actions": ["create"]}}]
        self.resources = [database("orders-db")]
        self.dbs = {"orders-db": {"pitr": 7, "cluster": None}}
        self.assertEqual(status.preview(self.world())[0]["state"], "WILL_PROTECT")

    def test_preview_of_a_longer_window(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 14})
        self.resources = [database("orders-db")]
        self.dbs = {"orders-db": {"pitr": 7, "cluster": None}}
        lines = status.preview(self.world())
        self.assertEqual(lines[0]["state"], "WILL_PROTECT")
        self.assertIn("7 days now, 14 days after: longer", lines[0]["detail"])

    def test_preview_flags_a_bad_tag_before_anything_is_applied(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3})
        self.resources = [bucket("docs", "gld")]
        lines = status.preview(self.world())
        self.assertEqual(lines[0]["state"], "BAD_VALUE")

    def test_preview_with_nothing_tagged_says_what_to_tag(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3})
        self.assertEqual(status.preview(self.world()), [])

    # --- --teardown ---

    def test_teardown_is_refused_in_production(self):
        self.kit = dict(KIT, mode="production")
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "REFUSED")

    def test_teardown_waits_while_a_backup_runs(self):
        self.add_db("orders-db")
        self.clumio.lists["/tasks"].append({"id": "4043", "status": "in_progress", "type": "aws_rds_resource_rolling_backup",
                                            "primary_entity": {"id": "id-orders-db"}})
        state, lines = status.teardown(self.world())
        self.assertEqual(state, "BLOCKED")
        self.assertTrue(any("4043" in line for line in lines))

    def test_teardown_waits_while_a_bucket_group_backup_runs(self):
        self.add_bucket("orders-docs")
        self.clumio.lists["/tasks"].append({"id": "4044", "status": "queued", "primary_entity": {"id": GROUP}})
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "BLOCKED")

    def test_teardown_is_ready_when_nothing_runs_and_lists_the_pitr_windows_left_behind(self):
        self.add_db("orders-db", pitr=14)
        self.clumio.lists["/tasks"].append({"id": "4040", "status": "completed", "primary_entity": {"id": "id-orders-db"}})
        state, lines = status.teardown(self.world())
        self.assertEqual(state, "READY")
        self.assertTrue(any("orders-db" in line and "14 days" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
