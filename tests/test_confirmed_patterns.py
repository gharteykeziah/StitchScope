"""
Tests for engine/confirmed_patterns.py -- the comparison logic that
checks a fresh AI proposal against a human-confirmed ground truth, once
one exists.

Every test redirects the module's on-disk patterns file to a scratch
temp file for its duration (see ConfirmedPatternsTestCase), so running
this suite never reads or writes the real
data/confirmed_stitch_patterns.json.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.confirmed_patterns as cp

MESH_SETUP = [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
MESH_REPEAT = [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]


class ConfirmedPatternsTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._tmp_path = os.path.join(self._tmp_dir, "confirmed_stitch_patterns.json")
        with open(self._tmp_path, "w") as f:
            f.write("{}")
        self._original_path = cp._PATTERNS_PATH
        cp._PATTERNS_PATH = self._tmp_path

    def tearDown(self):
        cp._PATTERNS_PATH = self._original_path
        shutil.rmtree(self._tmp_dir)


class NormalizeStitchFamilyTests(unittest.TestCase):

    def test_normalizes_case_and_whitespace(self):
        self.assertEqual(cp.normalize_stitch_family("  Filet   Mesh "), "filet mesh")


class CheckAgainstConfirmedTests(ConfirmedPatternsTestCase):

    def test_no_confirmed_entry_when_stitch_family_never_seen(self):
        result = cp.check_against_confirmed("filet mesh", MESH_SETUP, MESH_REPEAT, 6)
        self.assertEqual(result["status"], cp.NO_CONFIRMED_ENTRY)
        self.assertIsNone(result["confirmed_entry"])
        self.assertEqual(result["disagreements"], [])

    def test_last_ai_proposal_recorded_even_with_no_confirmed_entry(self):
        cp.check_against_confirmed("filet mesh", MESH_SETUP, MESH_REPEAT, 6)
        data = cp.load_patterns()
        self.assertEqual(data["filet mesh"]["last_ai_proposal"]["turning_chain"], 6)
        self.assertEqual(data["filet mesh"]["last_ai_proposal"]["setup"], MESH_SETUP)
        # Still not confirmed -- an entry existing isn't the same as confirmed.
        self.assertEqual(data["filet mesh"]["confirmations"], [])

    def test_matches_confirmed(self):
        cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                            photo_filename="a.jpg", note="hand swatched")

        result = cp.check_against_confirmed("filet mesh", MESH_SETUP, MESH_REPEAT, 6)
        self.assertEqual(result["status"], cp.MATCHES_CONFIRMED)
        self.assertEqual(result["disagreements"], [])
        self.assertIsNotNone(result["confirmed_entry"])

    def test_conflicts_with_confirmed_names_which_parts_disagree(self):
        cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                            photo_filename="a.jpg", note="hand swatched")

        wrong_repeat = [{"stitch": "DC", "count": 5}]
        result = cp.check_against_confirmed("filet mesh", MESH_SETUP, wrong_repeat, proposed_turning_chain=9)

        self.assertEqual(result["status"], cp.CONFLICTS_WITH_CONFIRMED)
        self.assertEqual(len(result["disagreements"]), 2)
        self.assertTrue(any("repeat differs" in d for d in result["disagreements"]))
        self.assertTrue(any("turning_chain differs" in d for d in result["disagreements"]))
        # setup matched -- only the two mismatched parts are named.
        self.assertFalse(any("setup differs" in d for d in result["disagreements"]))

    def test_last_ai_proposal_updates_even_on_conflict(self):
        cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                            photo_filename="a.jpg", note="hand swatched")
        wrong_repeat = [{"stitch": "DC", "count": 5}]
        cp.check_against_confirmed("filet mesh", MESH_SETUP, wrong_repeat, proposed_turning_chain=9)

        data = cp.load_patterns()
        self.assertEqual(data["filet mesh"]["last_ai_proposal"]["repeat"], wrong_repeat)
        # Confirmed ground truth itself is untouched.
        self.assertEqual(data["filet mesh"]["repeat"], MESH_REPEAT)


class ConfirmPatternTests(ConfirmedPatternsTestCase):

    def test_confirming_a_new_stitch_family_creates_it(self):
        entry = cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                                    photo_filename="a.jpg", note="first confirmation")
        self.assertEqual(entry["setup"], MESH_SETUP)
        self.assertEqual(entry["repeat"], MESH_REPEAT)
        self.assertEqual(entry["turning_chain"], 6)
        self.assertEqual(len(entry["confirmations"]), 1)
        self.assertEqual(entry["confirmations"][0]["photo"], "a.jpg")
        self.assertEqual(entry["confirmations"][0]["note"], "first confirmation")

    def test_second_matching_confirmation_appends_without_conflict(self):
        cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                            photo_filename="a.jpg", note="first")
        entry = cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                                    photo_filename="b.jpg", note="second, matches")
        self.assertEqual(len(entry["confirmations"]), 2)

    def test_second_confirmation_conflicting_with_existing_raises_and_does_not_overwrite(self):
        cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                            photo_filename="a.jpg", note="first")

        conflicting_repeat = [{"stitch": "DC", "count": 5}]
        with self.assertRaises(cp.ConfirmationConflictError):
            cp.confirm_pattern("filet mesh", MESH_SETUP, conflicting_repeat, turning_chain=6,
                                photo_filename="b.jpg", note="second, wrong")

        # Established ground truth from the first confirmation is untouched.
        data = cp.load_patterns()
        self.assertEqual(data["filet mesh"]["repeat"], MESH_REPEAT)
        self.assertEqual(len(data["filet mesh"]["confirmations"]), 1)

    def test_confirming_a_previously_only_proposed_family_fills_it_in(self):
        # Seen via check_against_confirmed (e.g. from a real photo run)
        # but never confirmed -- confirm_pattern() should fill it in,
        # not treat it as a conflict.
        cp.check_against_confirmed("filet mesh", MESH_SETUP, MESH_REPEAT, 6)
        entry = cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=6,
                                    photo_filename="a.jpg", note="confirmed now")
        self.assertEqual(entry["setup"], MESH_SETUP)
        self.assertEqual(len(entry["confirmations"]), 1)


if __name__ == "__main__":
    unittest.main()
