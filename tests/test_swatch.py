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

    def test_setups_own_chain_steps_extend_the_foundation(self):
        # This is the real filet-mesh case that exposed the bug: setup
        # is "chain 2, skip 1" (a lead-in before a DC-based repeat), and
        # repeat is "DC 1, chain 1" worked 6 times.
        #
        # consumed = setup's SKIP 1 (1) + repeat's DC 1 x6 (6) = 7
        # setup's own CH 2 adds 2 brand-new chain links on top of that,
        # since nothing has been worked into the foundation yet when
        # that CH runs -- those links must be physically chained too.
        # Correct foundation = 7 + 2 = 9, not 7.
        setup_steps = [{"stitch": "CH", "count": 2}, {"stitch": "SKIP", "count": 1}]
        repeat_steps = [{"stitch": "DC", "count": 1}, {"stitch": "CH", "count": 1}]
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6), 9)

    def test_repeats_own_chain_steps_do_not_extend_the_foundation(self):
        # A CH inside the REPEAT (not setup) is a floating chain-space
        # hung off a stitch that's already been worked into the
        # foundation -- it must NOT get the same treatment as a CH in
        # setup. This is the "chain 1" after each DC in the mesh repeat:
        # it should never inflate the foundation length.
        setup_steps = []
        repeat_steps = [{"stitch": "DC", "count": 1}, {"stitch": "CH", "count": 1}]
        # consumed = DC 1 x6 = 6; no setup CH steps to add.
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6), 6)

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
    """
    Every row in one simulate_swatch() call is worked the SAME
    test_repeat_count -- a row's own "repeat_count" field is never read
    (see simulate_swatch()'s docstring for why). So these fixtures drive
    pass/fail through each row's repeat *structure* (how many stitches
    its repeat unit consumes per repetition), not through differing
    repeat_count claims -- that's what a real AI proposal actually gives
    us to distrust: the stitch pattern, not a number we'd simulate as-is
    anyway.
    """

    def test_all_rows_hold_up(self):
        # Row 1: repeat is DC 1 (1 stitch/rep) x5 test repeats -> produces 5.
        # Foundation is exactly 5.
        # Row 2: repeat is also DC 1 (1 stitch/rep) x5 -> needs 5, row 1
        # produced 5. Holds up.
        rows = [
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 999},
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 1},
        ]
        result = simulate_swatch(rows, foundation_length=5, test_repeat_count=5)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["trail"]), 2)
        self.assertEqual(result["trail"][0]["produced"], 5)
        self.assertEqual(result["trail"][1]["produced"], 5)
        self.assertTrue(all(entry["valid"] for entry in result["trail"]))

    def test_row_2_needs_more_stitches_than_row_1_actually_produced(self):
        # Row 1: repeat is DC 1 -> consumes 1/rep x5 test repeats = 5
        # consumed, 5 produced (foundation is exactly 5).
        # Row 2: repeat is DC 2 (2 DC stitches per rep) -> consumes 2/rep
        # x5 test repeats = 10 needed, but row 1 only produced 5. Must
        # fail at row 2, not row 1 -- this is the core new behavior: a
        # later row's proposed stitch STRUCTURE gets checked against what
        # the engine actually computed the prior row produces, at a test
        # repeat count that's the same for every row and never read from
        # anything the AI itself asserted.
        rows = [
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 1},
            {"setup": [], "repeat": [{"stitch": "DC", "count": 2}], "repeat_count": 1},
        ]
        result = simulate_swatch(rows, foundation_length=5, test_repeat_count=5)

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_at_row"], 2)
        self.assertEqual(result["needed"], 10)
        self.assertEqual(result["available"], 5)

        # Row 1 still shows up in the trail as valid -- only row 2 failed.
        self.assertEqual(len(result["trail"]), 2)
        self.assertTrue(result["trail"][0]["valid"])
        self.assertFalse(result["trail"][1]["valid"])

    def test_stops_at_first_failure_and_does_not_run_later_rows(self):
        rows = [
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 1},
            {"setup": [], "repeat": [{"stitch": "DC", "count": 2}], "repeat_count": 1},  # fails here
            {"setup": [], "repeat": [{"stitch": "DC", "count": 1}], "repeat_count": 1},  # never reached
        ]
        result = simulate_swatch(rows, foundation_length=5, test_repeat_count=5)

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_at_row"], 2)
        self.assertEqual(len(result["trail"]), 2, "row 3 should never have been simulated")


class Row1AgainstItsOwnFoundationTests(unittest.TestCase):
    """
    The trivial-but-necessary sanity check that was missing, which is
    why this bug shipped: row 1, simulated at the SAME test_repeat_count
    used to build the foundation from its own structure, must always
    pass -- by construction. If this ever fails, the bug is that row 1's
    simulation is pulling repeat_count from somewhere else (e.g. the
    AI's own proposed value) instead of the fixed test_repeat_count
    actually used to build the foundation.
    """

    def test_row_1_passes_against_a_foundation_built_from_its_own_structure(self):
        setup_steps = []
        repeat_steps = [{"stitch": "DC", "count": 1}]  # 1 stitch consumed/produced per rep
        test_repeat_count = 6

        foundation = build_test_foundation(setup_steps, repeat_steps, test_repeat_count)

        # Row 1's own proposed repeat_count is deliberately something
        # else entirely (99) -- a stand-in for whatever number an AI
        # might have put there. It must be ignored by simulate_swatch();
        # only test_repeat_count should ever be simulated.
        row_1 = {"setup": setup_steps, "repeat": repeat_steps, "repeat_count": 99}

        result = simulate_swatch([row_1], foundation, test_repeat_count=test_repeat_count)

        self.assertTrue(
            result["success"],
            f"row 1 must pass against a foundation built from its own structure at "
            f"the same test_repeat_count, regardless of its own claimed repeat_count "
            f"-- got {result}",
        )
        self.assertEqual(result["trail"][0]["consumed"], foundation)
        self.assertEqual(result["trail"][0]["produced"], foundation)


if __name__ == "__main__":
    unittest.main()
