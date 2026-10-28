"""Tests for status.py's coverage (status) and --teardown. Fakes stand in for AWS and
Clumio; each fake answer has the shape of a real one read on 2026-10-28, and the fake Clumio filters
the way the real API does, so a wrong filter in status.py fails here. Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

ACCOUNT, REGION = "123456789012", "us-west-2"
UNIT = "11111111-2222-3333-4444-555555555555"
RULE, GROUP = "rule-gold", "pg-gold"
# One policy per workload, named <profile>-<workload>-<account>-<region>, as modules/protect makes them.
# gold has all five 2-protect- folders applied; dbonly has rds and aurora only.
POLICY = {w: f"pol-gold-{w}" for w in ("s3", "rds", "aurora", "ec2", "ebs")}
POLICIES = ([{"id": POLICY[w], "name": f"gold-{w}-{ACCOUNT}-{REGION}"} for w in POLICY]
            + [{"id": f"pol-dbonly-{w}", "name": f"dbonly-{w}-{ACCOUNT}-{REGION}"} for w in ("rds", "aurora")]
            + [{"id": "pol-theirs", "name": "gold-prod"}, {"id": "pol-elsewhere", "name": f"gold-rds-{ACCOUNT}-eu-west-1"}])
GROUPS = [{"id": GROUP, "name": f"gold-s3-{ACCOUNT}-{REGION}"}, {"id": "pg-theirs", "name": "someone-elses-group"}]

KIT = {"account_id": ACCOUNT, "region": REGION, "organizational_unit_id": UNIT}


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
            "/policies/definitions": [dict(p) for p in POLICIES],
            "/datasources/protection-groups": [dict(g) for g in GROUPS],
        }
        self.single = {f"/connections/aws/{ACCOUNT}_{REGION}": (200, {"organizational_unit_id": UNIT}),
                       "/policies/rules/rule-other": (200, {"id": "rule-other", "name": "CEG Demo"})}
        self.broken = set()
        self.page_size = {}  # path -> items per page; Clumio pages by cursor, a _links._next href (read live, 2026-10-28)
        self.endless = set()  # paths whose every page links to another

    def get(self, path, unit=None):
        bare, _, query = path.partition("?")
        if bare in self.broken:
            return 500, {}
        # Live, 2026-10-28: a rule in a unit is found only in that unit's context; without it, 404.
        if bare.startswith("/policies/rules/") and unit != UNIT:
            return 404, {}
        if bare in self.single:
            return self.single[bare]
        if bare not in self.lists:
            return 404, {}
        found = self.lists[bare]
        params = urllib.parse.parse_qs(query)
        if "filter" in params:
            for field, test in json.loads(params["filter"][0]).items():
                found = [item for item in found if matches(lookup(item, field), test)]
        size = self.page_size.get(bare, len(found) or 1)
        start = int(params.get("start", ["0"])[0])
        body = {"_embedded": {"items": found[start:start + size]}, "start": str(start)}
        if bare in self.endless or start + size < len(found):
            following = urllib.parse.urlencode({key: value[0] for key, value in params.items() if key != "start"})
            body["_links"] = {"_next": {"href": f"{bare}?{following}&start={start + size}"}}
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
        self.live_instances = set()  # instance IDs AWS describes as not terminated
        self.settings_path = self.settings("trial")
        self.kit = dict(KIT)
        self.applied = []  # the 1-connect and 2-protect- folders whose state still holds resources

    def settings(self, mode):
        """A 1-connect/terraform.tfvars with this mode, as the person wrote it."""
        handle, path = tempfile.mkstemp(suffix=".tfvars")
        with os.fdopen(handle, "w") as out:
            out.write(f'account_id = "{ACCOUNT}"\nregion = "{REGION}"\norganizational_unit = "{UNIT}"\nmode = "{mode}"\n')
        self.addCleanup(os.remove, path)
        return path

    def world(self):
        return status.World(
            settings_path=self.settings_path, terraform_version=lambda: "1.15.5", aws_cli_found=lambda: True,
            signed_in_account=lambda: ACCOUNT, clumio_credentials_set=lambda: True, clumio_get=self.clumio.get,
            kit=lambda: self.kit,
            tagged_resources=lambda region: self.resources, databases=lambda region: self.dbs,
            volumes=lambda region: self.vols, instances=lambda region: self.live_instances,
            applied_folders=lambda: self.applied)

    def add_db(self, name, policy=None, rule=RULE, backup=None, kind="db", pitr=7, cluster=None):
        policy = policy or POLICY["aurora" if kind == "cluster" else "rds"]
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
                 "protection_info": {"policy_id": POLICY["s3"]}, "last_backup_timestamp": backup})

    def add_instance(self, instance_id, policy=POLICY["ec2"], backup=None, value="gold"):
        self.resources.append(instance(instance_id, value))
        self.live_instances.add(instance_id)
        self.clumio.lists["/datasources/aws/ec2-instances"].append(
            {"id": f"id-{instance_id}", "instance_native_id": instance_id, "account_native_id": ACCOUNT, "aws_region": REGION,
             "is_deleted": False, "protection_info": {"policy_id": policy, "rule_id": RULE}, "last_backup_timestamp": backup})

    def add_volume(self, volume_id, attached_to=None, key="clumio-volume-profile", policy=POLICY["ebs"], backup=None):
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
        # Cold review, 2026-10-28: the fix (rule_before_id) needs the rule's ID, so the line carries both.
        self.assertIn("rule-other", records[0]["detail"])
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

    # The kit's policies are found by name in Clumio; another team's, or another Region's, never count.
    def test_only_policies_named_for_this_account_and_region_are_the_kits(self):
        profiles = status.kit_profiles(self.world(), self.kit)
        self.assertEqual(sorted(profiles), ["dbonly", "gold"])
        self.assertEqual(profiles["gold"]["rds"], POLICY["rds"])
        self.assertEqual(profiles["gold"]["s3_group"], GROUP)
        self.assertNotIn("s3", profiles["dbonly"])

    def test_a_database_held_by_this_profiles_rds_policy_is_ours_not_the_aurora_one(self):
        self.add_db("orders-db", policy=POLICY["aurora"], backup="2026-10-28T05:00:00Z")
        states, _, _ = self.states()
        self.assertEqual(states["orders-db"], "OTHER")

    # Live, 2026-10-28: the shared tenant had 84 policies, near the 100 on one page, and the list says
    # nothing about pages but a _next link. Every page is read: one missed would turn ours into BAD_VALUE.
    def test_policies_on_a_later_page_are_still_found(self):
        self.add_db("orders-db", backup="2026-10-28T05:00:00Z")
        self.clumio.page_size["/policies/definitions"] = 1  # gold's RDS policy is the second: page two
        states, _, _ = self.states()
        self.assertEqual(states["orders-db"], "OURS")

    def test_a_list_that_never_ends_is_unknown_never_a_guess(self):
        self.add_db("orders-db")
        self.clumio.page_size["/policies/definitions"] = 1
        self.clumio.endless.add("/policies/definitions")
        with self.assertRaises(status.ClumioUnavailable):
            status.coverage(self.world())

    def test_a_tag_for_a_workload_whose_folder_isnt_applied_is_off_and_names_the_folder(self):
        self.add_instance("i-0abc", value="dbonly")
        states, records, _ = self.states()
        self.assertEqual(states["i-0abc"], "OFF")
        self.assertIn("2-protect-ec2", records[0]["detail"])

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

    # --- Fixes from the cold review ---

    def test_teardown_waits_while_a_backup_is_aborting(self):
        self.add_db("orders-db")
        self.clumio.lists["/tasks"].append({"id": "4060", "status": "aborting", "primary_entity": {"id": "id-orders-db"}})
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "BLOCKED")

    def test_teardown_sees_a_running_task_on_a_later_page(self):
        self.add_db("orders-db")
        self.clumio.page_size["/tasks"] = 1
        self.clumio.lists["/tasks"] += [{"id": "4040", "status": "completed", "primary_entity": {"id": "id-orders-db"}},
                                        {"id": "4041", "status": "in_progress", "primary_entity": {"id": "id-orders-db"}}]
        state, lines = status.teardown(self.world())
        self.assertEqual(state, "BLOCKED")
        self.assertTrue(any("4041" in line for line in lines))

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

    # Read live on 2026-10-28: for each tagged Aurora cluster, AWS's tagging API also returns an ARN
    # named by the cluster's resource ID (cluster:cluster-<id>, lowercase). It's the same cluster.
    def test_a_clusters_resource_id_arn_is_the_same_cluster_not_another(self):
        self.add_db("orders-cluster", kind="cluster")
        self.resources.append(database("cluster-brutmag4u7oebrgdzwkgfjyhxu", kind="cluster"))
        records, _ = status.coverage(self.world())
        self.assertEqual([r["name"] for r in records], ["orders-cluster"])

    # Live, 2026-10-28: an hour after a teardown, AWS's tagging API still listed the lab's terminated
    # instances and deleted volumes, and status showed them as NOT_YET and OFF. Only what AWS describes
    # as existing is checked.
    def test_what_the_tagging_api_lists_but_aws_says_is_gone_is_left_out(self):
        self.resources = [instance("i-gone"), volume("vol-gone"), database("old-db")]
        records, _ = status.coverage(self.world())
        self.assertEqual(records, [])

    # --- --teardown ---

    # The check reads the mode from the settings file, as the person set it. Live, 2026-10-28: reading
    # the applied mode made retiring production need an extra apply just to record "trial".
    def test_teardown_is_refused_while_the_settings_say_production(self):
        self.settings_path = self.settings("production")
        state, lines = status.teardown(self.world())
        self.assertEqual(state, "REFUSED")
        self.assertIn("mode is production", lines[0])

    # Cold review, 2026-10-28: a missing settings file let the check say READY in production.
    def test_teardown_without_settings_is_unknown_never_ready(self):
        self.settings_path = os.path.join(tempfile.gettempdir(), "no-such-settings.tfvars")
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "UNKNOWN")

    def test_teardown_names_the_folders_still_applied_protect_first(self):
        self.applied = ["1-connect", "2-protect-rds", "2-protect-s3"]
        state, lines = status.teardown(self.world())
        self.assertEqual(state, "READY")
        self.assertTrue(any("2-protect-rds" in line and "2-protect-s3" in line and "1-connect last" in line for line in lines))

    def test_teardown_goes_ahead_once_the_settings_say_trial(self):
        self.settings_path = self.settings("trial")
        state, _ = status.teardown(self.world())
        self.assertEqual(state, "READY")

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

    # Cold review, 2026-10-28: the database lookup read one page; another database with a name that
    # contains this one could push it to page two.
    def test_a_database_on_a_later_page_is_found(self):
        self.clumio.lists["/datasources/aws/rds-resources"].append(
            {"id": "id-orders-db-old", "name": "orders-db-old", "account_native_id": ACCOUNT, "aws_region": REGION, "is_deleted": False})
        self.add_db("orders-db", backup="2026-10-28T05:00:00Z")
        self.clumio.page_size["/datasources/aws/rds-resources"] = 1
        states, _, _ = self.states()
        self.assertEqual(states["orders-db"], "OURS")


if __name__ == "__main__":
    unittest.main()
