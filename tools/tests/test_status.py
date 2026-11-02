"""Tests for status.py --preflight. Fakes stand in for AWS and Clumio; each fake answer has the shape
of a real answer read on 2026-10-28. Run: python3 -m unittest discover -s tests, in tools/."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

ACCOUNT = "123456789012"
UNIT = "11111111-2222-3333-4444-555555555555"
GLOBAL = "00000000-0000-0000-0000-000000000000"

GOOD_SETTINGS = f'''account_id          = "{ACCOUNT}" # a comment
region              = "us-west-2"
organizational_unit = "{UNIT}"
mode                = "trial"
iam_prefix = ""
'''

REGIONS = {"_embedded": {"items": [
    {"id": "us-west-2", "name": "US West (Oregon)", "is_data_plane_region": True},
    {"id": "ap-northeast-1", "name": "Asia Pacific (Tokyo)", "is_data_plane_region": False},
]}}


def rules(count, unit=UNIT):
    return {"_embedded": {"items": [{"id": f"r{n}", "name": f"rule {n}", "organizational_unit_id": unit} for n in range(count)]}}


class FakeClumio:
    """Answers GETs from a table: path -> (HTTP status, body). Records the unit context of each call."""

    def __init__(self, **overrides):
        self.answers = {
            "/connections/aws/regions": (200, REGIONS),
            f"/organizational-units/{UNIT}": (200, {"id": UNIT, "name": "cvlt-cloudnatives"}),
            "/policies/rules": (200, rules(3)),
            f"/connections/aws/{ACCOUNT}_us-west-2": (404, {}),
            "/organizational-units": (200, {"_embedded": {"items": [
                {"id": GLOBAL, "name": "Global organizational unit", "descendant_ids": [UNIT]}]}}),
        }
        self.answers.update(overrides)
        self.contexts = {}

    def get(self, path, unit=None):
        bare = path.split("?")[0]
        self.contexts[bare] = unit
        return self.answers.get(bare, (404, {}))


class Preflight(unittest.TestCase):
    def run_preflight(self, settings=GOOD_SETTINGS, signed_in=ACCOUNT, clumio=None, terraform="1.15.5", env=True, pending=(), applied=(), connect_unreadable=False):
        folder = tempfile.mkdtemp()
        if settings is not None:
            with open(os.path.join(folder, "terraform.tfvars"), "w") as f:
                f.write(settings)
        self.clumio = clumio or FakeClumio()
        world = status.World(
            settings_path=os.path.join(folder, "terraform.tfvars"),
            terraform_version=lambda: terraform,
            aws_cli_found=lambda: True,
            signed_in_account=lambda: signed_in,
            clumio_credentials_set=lambda: env,
            clumio_get=self.clumio.get,
            pending_rule_folders=lambda: list(pending),
            applied_folders=lambda: list(applied),
            connect_resources=lambda: None if connect_unreadable else (["a resource"] if "1-connect" in applied else []),
        )
        return status.preflight(world)

    def states(self, results):
        return {check: state for state, check, _ in results}

    def detail(self, results, check):
        return next(d for _, c, d in results if c == check)

    def test_everything_ready_passes(self):
        results = self.run_preflight()
        self.assertTrue(all(state == "PASS" for state, _, _ in results), results)
        self.assertEqual(status.exit_code(results), 0)

    def test_rules_are_counted_inside_the_unit(self):
        self.run_preflight()
        self.assertEqual(self.clumio.contexts["/policies/rules"], UNIT)

    def test_old_terraform_fails(self):
        results = self.run_preflight(terraform="1.9.8")
        self.assertEqual(self.states(results)["tools"], "FAIL")
        self.assertEqual(status.exit_code(results), 1)

    def test_missing_settings_file_fails_and_says_how_to_make_it(self):
        results = self.run_preflight(settings=None)
        self.assertEqual(self.states(results)["settings"], "FAIL")
        self.assertIn("cp settings.example terraform.tfvars", self.detail(results, "settings"))

    def test_a_placeholder_fails_and_names_the_setting(self):
        results = self.run_preflight(settings=GOOD_SETTINGS.replace(f'"{ACCOUNT}"', '"ACCOUNT-ID-REPLACE-THIS"'))
        self.assertEqual(self.states(results)["settings"], "FAIL")
        self.assertIn("account_id", self.detail(results, "settings"))

    def test_signed_in_to_another_account_fails(self):
        results = self.run_preflight(signed_in="111111111111")
        self.assertEqual(self.states(results)["AWS sign-in"], "FAIL")
        self.assertIn("111111111111", self.detail(results, "AWS sign-in"))

    def test_not_signed_in_fails(self):
        results = self.run_preflight(signed_in=None)
        self.assertEqual(self.states(results)["AWS sign-in"], "FAIL")

    def test_missing_clumio_credentials_fail(self):
        results = self.run_preflight(env=False)
        self.assertEqual(self.states(results)["Clumio token"], "FAIL")
        self.assertIn("CLUMIO_API_TOKEN", self.detail(results, "Clumio token"))

    def test_a_rejected_token_fails(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/connections/aws/regions": (401, {})}))
        self.assertEqual(self.states(results)["Clumio token"], "FAIL")

    def test_clumio_unreachable_fails_without_guessing(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/connections/aws/regions": (None, {})}))
        self.assertEqual(self.states(results)["Clumio token"], "FAIL")
        self.assertIn("reach", self.detail(results, "Clumio token"))

    def test_an_unknown_unit_fails(self):
        results = self.run_preflight(clumio=FakeClumio(**{f"/organizational-units/{UNIT}": (404, {})}))
        self.assertEqual(self.states(results)["unit"], "FAIL")

    def test_global_needs_no_lookup_and_counts_global_rules(self):
        results = self.run_preflight(settings=GOOD_SETTINGS.replace(f'"{UNIT}"', '"global"'),
                                     clumio=FakeClumio(**{"/policies/rules": (200, rules(3, GLOBAL))}))
        self.assertEqual(self.states(results)["unit"], "PASS")
        self.assertEqual(self.clumio.contexts["/policies/rules"], GLOBAL)

    def test_an_unset_unit_lists_the_units_to_choose_from(self):
        results = self.run_preflight(settings=GOOD_SETTINGS.replace(f'"{UNIT}"', '"UNIT-REPLACE-THIS"'))
        self.assertEqual(self.states(results)["unit"], "FAIL")
        self.assertIn(f"cvlt-cloudnatives  {UNIT}", self.detail(results, "unit"))
        self.assertIn("global", self.detail(results, "unit"))

    def test_an_unsupported_region_fails(self):
        results = self.run_preflight(settings=GOOD_SETTINGS.replace("us-west-2", "eu-north-1"),
                                     clumio=FakeClumio(**{f"/connections/aws/{ACCOUNT}_eu-north-1": (404, {})}))
        self.assertEqual(self.states(results)["Region"], "FAIL")

    def test_a_full_unit_with_nothing_pending_is_a_note(self):
        # Full can be fine: the person's own folders may have filled it. Say what it means for the next one.
        results = self.run_preflight(clumio=FakeClumio(**{"/policies/rules": (200, rules(5))}))
        self.assertEqual(self.states(results)["rule slots"], "NOTE")
        self.assertIn("refused", self.detail(results, "rule slots"))

    # Live, 2026-10-28: a child unit refused a sixth rule ("Number of rules is limited to 5"), while
    # Global's limit is 25. Clumio shows no limit before you hit it, so preflight counts what the
    # 2-protect- folders still need against the limit seen for that kind of unit.
    def test_folders_that_need_more_rules_than_the_unit_has_left_fail_and_are_named(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/policies/rules": (200, rules(3))}),
                                     pending=["2-protect-ec2", "2-protect-ebs", "2-protect-rds"])
        self.assertEqual(self.states(results)["rule slots"], "FAIL")
        detail = self.detail(results, "rule slots")
        self.assertIn("2-protect-ebs", detail)
        self.assertIn("3 of 5", detail)

    def test_folders_that_fit_pass(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/policies/rules": (200, rules(3))}),
                                     pending=["2-protect-rds", "2-protect-aurora"])
        self.assertEqual(self.states(results)["rule slots"], "PASS")

    def test_global_counts_against_its_own_limit(self):
        results = self.run_preflight(settings=GOOD_SETTINGS.replace(f'"{UNIT}"', '"global"'),
                                     clumio=FakeClumio(**{"/policies/rules": (200, rules(20, GLOBAL))}),
                                     pending=["2-protect-ec2", "2-protect-ebs"])
        self.assertEqual(self.states(results)["rule slots"], "PASS")

    def test_rules_of_other_units_are_not_counted(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/policies/rules": (200, rules(25, GLOBAL))}))
        self.assertEqual(self.states(results)["rule slots"], "PASS")

    # The connection line decides for itself: one word, one meaning. It was a NOTE for both "yours" and
    # "stop, not yours", so an expected NOTE needed exceptions in the docs (cold agent walk, 2026-11-01).
    def connected_in(self, unit, status="connected"):
        return FakeClumio(**{f"/connections/aws/{ACCOUNT}_us-west-2": (200, {"organizational_unit_id": unit, "connection_status": status})})

    def test_the_connection_1_connect_made_in_this_unit_passes(self):
        results = self.run_preflight(clumio=self.connected_in(UNIT), applied=["1-connect"])
        self.assertEqual(self.states(results)["connection"], "PASS")
        self.assertEqual(status.exit_code(results), 0)

    def test_a_connection_1_connect_made_in_global_passes(self):
        # Clumio names Global with the all-zero ID, and the setting says "global": these are one unit.
        results = self.run_preflight(settings=GOOD_SETTINGS.replace(f'"{UNIT}"', '"global"'), clumio=self.connected_in(GLOBAL), applied=["1-connect"])
        self.assertEqual(self.states(results)["connection"], "PASS")

    def test_a_connection_1_connect_didnt_make_fails_and_says_stop(self):
        results = self.run_preflight(clumio=self.connected_in(UNIT))
        self.assertEqual(self.states(results)["connection"], "FAIL")
        self.assertEqual(status.exit_code(results), 1)
        self.assertIn("Stop", self.detail(results, "connection"))
        self.assertIn("docs/operate.md", self.detail(results, "connection"))

    def test_a_folder_applied_elsewhere_doesnt_make_it_ours(self):
        results = self.run_preflight(clumio=self.connected_in(UNIT), applied=["2-protect-s3"])
        self.assertEqual(self.states(results)["connection"], "FAIL")

    def test_a_connection_in_another_unit_fails_and_names_both(self):
        results = self.run_preflight(clumio=self.connected_in("99999999-2222-3333-4444-555555555555"), applied=["1-connect"])
        self.assertEqual(self.states(results)["connection"], "FAIL")
        self.assertIn("99999999-2222-3333-4444-555555555555", self.detail(results, "connection"))
        self.assertIn(UNIT, self.detail(results, "connection"))

    # HTTP 200 only says the record exists: it isn't "connected".
    def test_a_connection_clumio_doesnt_call_connected_fails_and_names_what_it_read(self):
        results = self.run_preflight(clumio=self.connected_in(UNIT, status="disconnected"), applied=["1-connect"])
        self.assertEqual(self.states(results)["connection"], "FAIL")
        self.assertIn("disconnected", self.detail(results, "connection"))
        self.assertIn("docs/operate.md", self.detail(results, "connection"))

    # S3 denied, a network failure, a stale backend: not knowing whose it is must never read as ours.
    def test_a_connection_whose_state_cant_be_read_fails_and_doesnt_claim_it(self):
        results = self.run_preflight(clumio=self.connected_in(UNIT), connect_unreadable=True)
        self.assertEqual(self.states(results)["connection"], "FAIL")
        self.assertIn("state bucket", self.detail(results, "connection"))

    def test_a_connection_with_no_status_fails(self):
        results = self.run_preflight(clumio=self.connected_in(UNIT, status=None), applied=["1-connect"])
        self.assertEqual(self.states(results)["connection"], "FAIL")

    def test_checks_that_need_settings_are_skipped_when_settings_fail(self):
        results = self.run_preflight(settings=None)
        self.assertEqual(self.states(results)["AWS sign-in"], "SKIP")



class PagedRules(FakeClumio):
    """Rules over pages, as Clumio pages by cursor: this unit's rules only on page two."""

    def get(self, path, unit=None):
        if path.startswith("/policies/rules"):
            if "start=2" in path:
                return 200, rules(5)
            return 200, {"_embedded": {"items": rules(2, GLOBAL)["_embedded"]["items"]},
                         "_links": {"_next": {"href": "/policies/rules?limit=100&start=2"}}}
        return super().get(path, unit)


class RuleSlotPages(unittest.TestCase):
    # Cold review, 2026-10-28: the rule list holds every unit's rules, so this unit's can fall past page one.
    def test_a_unit_full_on_page_two_is_seen(self):
        results = Preflight.run_preflight(self, clumio=PagedRules(), pending=["2-protect-ec2"])
        self.assertEqual({c: s for s, c, _ in results}["rule slots"], "FAIL")


class Flags(unittest.TestCase):
    # Cold review, 2026-10-28: a partial set crashed, and --teardown ignored the flags and checked
    # 1-connect's account instead.
    def test_flags_need_all_three(self):
        self.assertIn("--account, --region and --unit", status.flag_problem(account="123456789012", region=None, unit=None, mode_flag=False))

    def test_flags_work_only_for_status(self):
        self.assertIn("status and --json", status.flag_problem(account="123456789012", region="us-west-2", unit="global", mode_flag=True))

    def test_a_full_set_for_status_is_fine(self):
        self.assertIsNone(status.flag_problem(account="123456789012", region="us-west-2", unit="global", mode_flag=False))

    def test_no_flags_is_fine(self):
        self.assertIsNone(status.flag_problem(account=None, region=None, unit=None, mode_flag=True))

class FolderStateTests(unittest.TestCase):
    """Which folders hold something, read through real Terraform, so it works for any backend."""

    # Built here, so no state-shaped text ships in this file.
    STATE = {'version': 4, 'terraform_version': '1.15.5', 'serial': 1, 'lineage': 'test', 'outputs': {}}
    RULE = {'mode': 'managed', 'type': 'clumio_policy_rule', 'name': 'tagged', 'provider': 'provider["registry.terraform.io/clumio-code/clumio"]', 'instances': []}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        patcher = mock.patch.object(status, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def folder(self, name, initialized=False, resources=None, state_text=None, settings=False):
        """A step folder as a clone holds it. It calls a local module, as every step folder does: before
        terraform init, `terraform state pull` fails with "Module not installed"."""
        path = os.path.join(self.root, name)
        os.makedirs(os.path.join(path, "m"))
        with open(os.path.join(path, "main.tf"), "w") as out:
            out.write('module "m" {\n  source = "./m"\n}\n' if not initialized else "")
        if initialized:
            os.makedirs(os.path.join(path, ".terraform"))
        if settings:
            open(os.path.join(path, "terraform.tfvars"), "w").close()
        if resources is not None:
            state_text = json.dumps(dict(self.STATE, resources=resources))
        if state_text is not None:
            with open(os.path.join(path, "terraform.tfstate"), "w") as out:
                out.write(state_text)

    def test_a_fresh_clone_has_nothing_applied(self):
        self.folder("1-connect")
        self.folder("2-protect-rds")
        self.assertEqual(status.applied_folders(), [])

    def test_a_folder_with_resources_is_applied(self):
        self.folder("1-connect", initialized=True, resources=[self.RULE])
        self.assertEqual(status.applied_folders(), ["1-connect"])

    def test_a_folder_with_an_emptied_state_isnt_applied(self):
        self.folder("1-connect", initialized=True, resources=[])
        self.assertEqual(status.applied_folders(), [])

    def test_a_state_terraform_cant_read_is_never_taken_as_empty(self):
        self.folder("1-connect", initialized=True, state_text="not a state")
        self.assertEqual(status.applied_folders(), ["1-connect"])

    def test_a_local_state_in_a_folder_not_initialized_is_never_taken_as_empty(self):
        self.folder("1-connect", resources=[self.RULE])
        self.assertEqual(status.applied_folders(), ["1-connect"])

    def state_kept_elsewhere(self, name, resources):
        """A real non-default backend, offline: the state isn't terraform.tfstate, as with S3."""
        self.folder(name, settings=True)
        path = os.path.join(self.root, name)
        with open(os.path.join(path, "main.tf"), "w") as out:
            out.write('terraform {\n  backend "local" {\n    path = "elsewhere/state"\n  }\n}\n')
        os.makedirs(os.path.join(path, "elsewhere"))
        with open(os.path.join(path, "elsewhere", "state"), "w") as out:
            json.dump(dict(self.STATE, resources=resources), out)
        subprocess.run(["terraform", "init", "-input=false"], cwd=path, capture_output=True, check=True)

    def test_state_kept_elsewhere_counts_as_applied(self):
        self.state_kept_elsewhere("1-connect", [self.RULE])
        self.assertEqual(status.applied_folders(), ["1-connect"])

    def test_a_rule_in_state_kept_elsewhere_counts(self):
        self.state_kept_elsewhere("2-protect-rds", [self.RULE])
        self.assertEqual(status.pending_rule_folders(), [])

    # A clone on a new machine: the state exists in S3, but this folder hasn't been initialized yet.
    def test_a_backend_not_initialized_is_never_taken_as_empty(self):
        self.folder("2-protect-rds")
        open(os.path.join(self.root, "2-protect-rds", "backend.tf"), "w").close()
        self.assertIsNone(status.folder_resources("2-protect-rds"))
        self.assertEqual(status.applied_folders(), ["2-protect-rds"])

    def test_other_folders_are_left_out(self):
        self.folder("proof", initialized=True, resources=[self.RULE])
        self.assertEqual(status.applied_folders(), [])

    def test_a_folder_with_settings_and_no_rule_will_add_one(self):
        self.folder("2-protect-rds", settings=True)
        self.assertEqual(status.pending_rule_folders(), ["2-protect-rds"])

    def test_a_folder_whose_rule_exists_adds_none(self):
        self.folder("2-protect-rds", settings=True, initialized=True, resources=[self.RULE])
        self.assertEqual(status.pending_rule_folders(), [])

    def test_a_folder_it_cant_read_counts_as_needing_a_rule(self):
        self.folder("2-protect-rds", settings=True, initialized=True, state_text="not a state")
        self.assertEqual(status.pending_rule_folders(), ["2-protect-rds"])

    def test_s3_adds_no_rule(self):
        self.folder("2-protect-s3", settings=True)
        self.assertEqual(status.pending_rule_folders(), [])


if __name__ == "__main__":
    unittest.main()
