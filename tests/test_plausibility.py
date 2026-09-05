"""
Tests for engine/plausibility.py -- the general sanity checks that
catch an obviously wrong AI proposal the first time a stitch is ever
seen, with no confirmed_patterns.json history involved at all.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.plausibility import (
    check_repeat_not_degenerate,
    check_setup_not_oversized,
    run_plausibility_checks,
)


class CheckSetupNotOversizedTests(unittest.TestCase):

    def test_oversized_setup_is_flagged(self):
        # The exact shape of the "chain 40" discrepancy logged in
        # data/concierge_log.csv: a lone CH 40 setup step.
        warning = check_setup_not_oversized([{"stitch": "CH", "count": 40}])
        self.assertIsNotNone(warning)
        self.assertIn("40", warning)

    def test_normal_small_turning_chain_is_not_flagged(self):
        self.assertIsNone(check_setup_not_oversized([{"stitch": "CH", "count": 3}]))

    def test_empty_setup_is_not_flagged(self):
        self.assertIsNone(check_setup_not_oversized([]))

    def test_a_setup_that_only_consumes_and_produces_little_is_not_flagged(self):
        # The real halter mesh row 1 setup: SKIP 5, DC 1 -- produces
        # only 1 new stitch.
        setup = [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
        self.assertIsNone(check_setup_not_oversized(setup))


class CheckRepeatNotDegenerateTests(unittest.TestCase):

    def test_empty_repeat_is_flagged(self):
        self.assertIsNotNone(check_repeat_not_degenerate([]))

    def test_zero_consumption_repeat_is_flagged(self):
        # CH consumes 0 -- a repeat made only of CH steps never uses
        # anything up and would repeat forever.
        warning = check_repeat_not_degenerate([{"stitch": "CH", "count": 1}])
        self.assertIsNotNone(warning)

    def test_normal_repeat_is_not_flagged(self):
        self.assertIsNone(check_repeat_not_degenerate([{"stitch": "DC", "count": 1}]))

    def test_normal_multi_step_repeat_is_not_flagged(self):
        repeat = [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]
        self.assertIsNone(check_repeat_not_degenerate(repeat))


class RunPlausibilityChecksTests(unittest.TestCase):
    """
    run_plausibility_checks() never imports or touches
    engine/confirmed_patterns.py or data/confirmed_stitch_patterns.json
    -- these are integration-style tests (hand-built fixtures, no real
    API call) proving a warning fires purely from the row's own shape,
    with no confirmation history involved at all.
    """

    def test_chain_40_style_row_triggers_a_warning_with_no_confirmed_history_at_all(self):
        row = {
            "setup": [{"stitch": "CH", "count": 40}],
            "repeat": [{"stitch": "DC", "count": 1}, {"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}],
            "repeat_count": 6,
        }
        warnings = run_plausibility_checks(row)
        self.assertTrue(any("40" in w for w in warnings), f"expected a warning mentioning 40, got {warnings}")

    def test_normal_row_has_no_warnings(self):
        row = {
            "setup": [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}],
            "repeat": [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}],
            "repeat_count": 7,
        }
        self.assertEqual(run_plausibility_checks(row), [])

    def test_row_can_fail_both_checks_at_once(self):
        row = {"setup": [{"stitch": "CH", "count": 50}], "repeat": [], "repeat_count": 1}
        warnings = run_plausibility_checks(row)
        self.assertEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
