"""Tests for the masks every saved answer goes through (record_fixtures.py, proof/capture.py): no real
account or unit ID may reach a file the public repo ships. Run: python3 -m unittest discover -s tests, in tools/."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import status  # noqa: E402

# Built at run time, so this file holds no real-looking account number.
OURS, CLUMIO, DATA_PLANE = "98765" "4321098", "87654" "3210987", "76543" "2109876"
UNIT = "11111111-2222-3333-4444-555555555555"
KIT = {"account_id": OURS, "region": "us-west-2", "organizational_unit_id": UNIT}


def world(status_code, connection):
    return status.World(None, None, None, None, None, lambda path, unit=None: (status_code, connection))


class Masks(unittest.TestCase):
    # Live, 2026-10-28: the first stage 2d fixture kept Clumio's own two AWS accounts, from the
    # connection's answer, and check.sh refused it. Masks cover them too.
    def test_masks_cover_this_account_the_unit_and_clumios_two_accounts(self):
        masks = status.masks(world(200, {"clumio_aws_account_id": CLUMIO, "data_plane_account_id": DATA_PLANE}), KIT)
        text = status.mask(f'{{"a": "{OURS}", "u": "{UNIT}", "c": "{CLUMIO}", "d": "arn:aws:iam::{DATA_PLANE}:root"}}', masks)
        for real in (OURS, UNIT, CLUMIO, DATA_PLANE):
            self.assertNotIn(real, text)
        for stand_in in ("123456789012", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "111111111111", "222222222222"):
            self.assertIn(stand_in, text)

    def test_no_masks_when_clumio_does_not_answer(self):
        # Without the connection, Clumio's accounts are unknown: saving anyway could leak them.
        self.assertIsNone(status.masks(world(503, {}), KIT))


if __name__ == "__main__":
    unittest.main()
