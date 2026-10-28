"""Tests for record_fixtures.py: a recording keeps nothing that isn't this kit's. Run: python3 -m
unittest discover -s tests, in tools/."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import record_fixtures  # noqa: E402
import status  # noqa: E402

OURS = "12345" "6789012"
THEIRS = "98765" "4321098"  # Built at run time, so this file holds no real-looking account number.
KIT = {"account_id": OURS, "region": "us-west-2", "organizational_unit_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}


class Recording(unittest.TestCase):
    # Live, 2026-10-28: the first stage 2f recording saved Clumio's whole policy and protection-group
    # lists, with other teams' accounts, bucket rules and tags. check.sh's account scan caught it.
    def test_tenant_wide_lists_keep_only_the_kits_items(self):
        lists = {"/policies/definitions": [{"id": "p1", "name": f"gold-rds-{OURS}-us-west-2"}, {"id": "p2", "name": "their-policy"}],
                 "/datasources/protection-groups": [{"id": "g1", "name": f"gold-s3-{OURS}-us-west-2"},
                                                    {"id": "g2", "name": "their-group", "bucket_rule": f'{{"aws_account_native_id": "{THEIRS}"}}'}]}
        world = status.World(None, None, None, None, None,
                             lambda path, unit=None: (200, {"_embedded": {"items": lists[path.split("?")[0]]}}),
                             kit=lambda: KIT)
        recording, answers = record_fixtures.record(world)
        recording.kit()
        for path in lists:
            recording.clumio_get(f"{path}?limit=100", unit=KIT["organizational_unit_id"])
        saved = str(answers["clumio"])
        self.assertNotIn("their", saved)
        self.assertNotIn(THEIRS, saved)
        self.assertIn(f"gold-rds-{OURS}-us-west-2", saved)
        self.assertIn(f"gold-s3-{OURS}-us-west-2", saved)



class OtherRules(unittest.TestCase):
    # Cold review, 2026-10-28: OTHER looks up the winning rule, and the recorder saved it whole.
    def test_another_teams_rule_is_saved_as_its_id_only(self):
        rule = {"id": "r-9", "name": "team-b payroll rule", "condition": '{"aws_tag": "payroll"}'}
        world = status.World(None, None, None, None, None, lambda path, unit=None: (200, rule), kit=lambda: KIT)
        recording, answers = record_fixtures.record(world)
        recording.kit()
        recording.clumio_get("/policies/rules/r-9", unit=KIT["organizational_unit_id"])
        saved = str(answers["clumio"])
        self.assertNotIn("payroll", saved)
        self.assertIn("r-9", saved)

if __name__ == "__main__":
    unittest.main()
