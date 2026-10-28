"""Tests for status.py --preflight. Fakes stand in for AWS and Clumio; each fake answer has the shape
of a real answer read on 2026-10-28. Run: python3 -m unittest discover -s tests, in tools/."""
import os
import sys
import tempfile
import unittest

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
    def run_preflight(self, settings=GOOD_SETTINGS, signed_in=ACCOUNT, clumio=None, terraform="1.15.5", env=True):
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

    def test_a_full_unit_fails(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/policies/rules": (200, rules(25))}))
        self.assertEqual(self.states(results)["rule slots"], "FAIL")

    def test_rules_of_other_units_are_not_counted(self):
        results = self.run_preflight(clumio=FakeClumio(**{"/policies/rules": (200, rules(25, GLOBAL))}))
        self.assertEqual(self.states(results)["rule slots"], "PASS")

    def test_an_existing_connection_is_a_note_not_a_failure(self):
        results = self.run_preflight(clumio=FakeClumio(**{f"/connections/aws/{ACCOUNT}_us-west-2": (200, {"organizational_unit_id": UNIT})}))
        self.assertEqual(self.states(results)["connection"], "NOTE")
        self.assertEqual(status.exit_code(results), 0)

    def test_checks_that_need_settings_are_skipped_when_settings_fail(self):
        results = self.run_preflight(settings=None)
        self.assertEqual(self.states(results)["AWS sign-in"], "SKIP")


if __name__ == "__main__":
    unittest.main()
