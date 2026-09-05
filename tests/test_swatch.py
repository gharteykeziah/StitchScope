"""
Regression tests for engine/swatch.py's multi-row swatch validator,
built from hand-computed fixtures (no real API call) -- the same spirit
as tests/golden/*.json for single-row validation, but for the new
row-to-row behavior: does row 2's claimed stitch count actually hold up
against what row 1 really produces?
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.swatch import build_test_foundation, simulate_swatch


class BuildTestFoundationTests(unittest.TestCase):

    def test_foundation_from_setup_and_repeat(self):
        # setup: SKIP 5, DC 1 -> consumes 5 + 1 = 6, once
        # repeat: DC 1 -> consumes 1, worked 6 times (our test count) = 6
        # foundation = 6 + 6 = 12
        setup_steps = [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
        repeat_steps = [{"stitch": "DC", "count": 1}]
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6), 12)

    def test_default_test_repeat_count_is_6(self):
        setup_steps = []
        repeat_steps = [{"stitch": "DC", "count": 1}]
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps), 6)

    def test_ignores_any_repeat_count_the_row_itself_might_carry(self):
        # build_test_foundation only ever takes raw setup/repeat steps, not
        # a full row dict with its own "repeat_count" -- there's nothing
        # for a caller to accidentally pass through here that would make
        # this circular. DC consumes 1 stitch per count, so the result
        # scales directly with whatever test_repeat_count we choose.
        setup_steps = []
        repeat_steps = [{"stitch": "DC", "count": 1}]
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=3), 3)
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=100), 100)


class SimulateSwatchTests(unittest.TestCase):

    def test_all_rows_hold_up(self):
        # Row 1: DC 1 x5 -> consumes 5, produces 5. Foundation is exactly 5.
        # Row 2: DC 1 x5 -> needs 5, row 1 produced 5. Holds up.
        rows = [
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 5},
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 5},
        ]
        result = simulate_swatch(rows, foundation_length=5)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["trail"]), 2)
        self.assertEqual(result["trail"][0]["produced"], 5)
        self.assertEqual(result["trail"][1]["produced"], 5)
        self.assertTrue(all(entry["valid"] for entry in result["trail"]))

    def test_row_2_needs_more_stitches_than_row_1_actually_produced(self):
        # Row 1: DC 1 x5 -> consumes 5, produces 5 (foundation is exactly 5).
        # Row 2: DC 1 x8 -> needs 8, but row 1 only produced 5. Must fail
        # at row 2, not row 1 -- this is the core new behavior: a later
        # row's claim gets checked against what the engine actually
        # computed the prior row produces, not against anything the AI
        # itself asserted.
        rows = [
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 5},
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 8},
        ]
        result = simulate_swatch(rows, foundation_length=5)

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_at_row"], 2)
        self.assertEqual(result["needed"], 8)
        self.assertEqual(result["available"], 5)

        # Row 1 still shows up in the trail as valid -- only row 2 failed.
        self.assertEqual(len(result["trail"]), 2)
        self.assertTrue(result["trail"][0]["valid"])
        self.assertFalse(result["trail"][1]["valid"])

    def test_stops_at_first_failure_and_does_not_run_later_rows(self):
        rows = [
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 5},
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 8},  # fails here
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 1},  # never reached
        ]
        result = simulate_swatch(rows, foundation_length=5)

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_at_row"], 2)
        self.assertEqual(len(result["trail"]), 2, "row 3 should never have been simulated")


if __name__ == "__main__":
    unittest.main()
