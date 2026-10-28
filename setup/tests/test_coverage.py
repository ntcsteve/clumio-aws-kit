"""Tests for status.py's coverage (make status), --preview and --teardown. Fakes stand in for AWS and
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
                          "protection_group_id": GROUP, "workloads": {"s3": True, "databases": True}},
                 "dbonly": {"tag": {"key": "clumio-profile", "value": "dbonly"}, "policy_id": "pol-db", "rule_id": "rule-db",
                            "protection_group_id": None, "workloads": {"s3": False, "databases": True}}},
}


def tagged(arn, value):
    return {"ResourceARN": arn, "Tags": [{"Key": "clumio-profile", "Value": value}]}


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
            "/tasks": [],
        }
        self.single = {f"/connections/aws/{ACCOUNT}_{REGION}": (200, {"organizational_unit_id": UNIT}),
                       "/policies/rules/rule-other": (200, {"id": "rule-other", "name": "CEG Demo"})}
        self.broken = set()

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
        return 200, {"_embedded": {"items": found}}


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
        self.kit = dict(KIT)
        self.plan = None

    def world(self):
        return status.World(
            settings_path="unused", terraform_version=lambda: "1.15.5", aws_cli_found=lambda: True,
            signed_in_account=lambda: ACCOUNT, clumio_credentials_set=lambda: True, clumio_get=self.clumio.get,
            kit=lambda: self.kit, saved_plan=lambda: self.plan,
            tagged_resources=lambda region: self.resources, databases=lambda region: self.dbs)

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

    def states(self):
        records, unit_result = status.coverage(self.world())
        return {r["name"]: r["state"] for r in records}, records, unit_result

    # --- make status ---

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

    # --- make plan: --preview ---

    def plan_with(self, **profiles):
        return {"variables": {"account_id": {"value": ACCOUNT}, "region": {"value": REGION},
                              "profiles": {"value": profiles}}}

    def test_preview_shows_each_databases_pitr_window_now_and_after(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3})
        self.resources = [database("orders-db")]
        self.dbs = {"orders-db": {"pitr": 7, "cluster": None}}
        lines = status.preview(self.world())
        self.assertEqual(lines[0]["state"], "WILL_PROTECT")
        self.assertIn("7 days now, 3 days after: SHORTER", lines[0]["detail"])

    def test_preview_flags_a_bad_tag_before_anything_is_applied(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3})
        self.resources = [bucket("docs", "gld")]
        lines = status.preview(self.world())
        self.assertEqual(lines[0]["state"], "BAD_VALUE")

    def test_preview_with_nothing_tagged_says_what_to_tag(self):
        self.plan = self.plan_with(gold={"s3": True, "databases": True, "pitr_retention_days": 3})
        self.assertEqual(status.preview(self.world()), [])

    # --- make teardown: --teardown ---

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
