"""
Tests for engine/recipe_validator.py's validate_row_1_against_foundation()
-- Phase 4A's row-1-only comparison between the stored foundation
formula and what row_1's own instructions actually account for.

Fixtures are loaded from the real example files (contracts/examples/)
via copy, or built as small hand-constructed recipes for cases the real
examples don't exercise (multiple stitch-post types, bare CH/SKIP/
same_stitch behavior) -- per the project's established convention
(tests/test_foundation.py, tests/test_recipe_schema_v2.py do the same).
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.recipe_validator import RecipeMathError, validate_row_1_against_foundation

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRUCTURAL_EXAMPLE_PATH = os.path.join(REPO_ROOT, "contracts", "examples", "stitch_recipe_v2_structural_example.json")
KNOWN_BAD_EXAMPLE_PATH = os.path.join(REPO_ROOT, "contracts", "examples", "stitch_recipe_v2_known_bad_ai_example.json")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def structural_recipe():
    return load_json(STRUCTURAL_EXAMPLE_PATH)


def known_bad_recipe():
    return load_json(KNOWN_BAD_EXAMPLE_PATH)


def minimal_recipe(row_1_setup=None, row_1_repeat=None, repeat_multiple=1, additional_chains=0,
                    expected_stitch_posts=None, expected_chain_spaces=None):
    """A small, hand-built, schema-valid recipe for row_1 edge cases the
    real example files don't exercise. Callers plug in whatever row_1
    structure they're testing."""
    if row_1_setup is None:
        row_1_setup = []
    if row_1_repeat is None:
        row_1_repeat = [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}]
    return {
        "pattern_id": "test_pattern",
        "name": "Test Stitch",
        "aliases": [],
        "terminology": "US",
        "foundation_formula": {"repeat_multiple": repeat_multiple, "additional_chains": additional_chains},
        "row_1": {"setup": row_1_setup, "repeat": row_1_repeat},
        "later_rows": {
            "setup": [{"stitch": "CH", "count": 1, "placement": "turning_chain"}],
            "repeat": [{"stitch": "DC", "count": 1, "placement": "next_stitch"}],
        },
        "expected_swatch_structure": {
            "expected_stitch_posts_per_repeat": expected_stitch_posts,
            "expected_chain_spaces_per_repeat": expected_chain_spaces,
        },
        "verification": {"status": "AI_PROPOSED", "confirmations": []},
    }


# ---------------------------------------------------------------------------
# 1-9: the structural example, fully traced
# ---------------------------------------------------------------------------

class StructuralExampleTests(unittest.TestCase):

    def setUp(self):
        self.result = validate_row_1_against_foundation(structural_recipe(), 6)

    def test_is_valid(self):
        self.assertTrue(self.result["valid"])

    def test_foundation_count_is_18(self):
        self.assertEqual(self.result["foundation"]["foundation_count"], 18)

    def test_setup_consumes_6(self):
        self.assertEqual(self.result["setup"]["consumed_foundation_positions"], 6)

    def test_repeat_once_consumes_2(self):
        self.assertEqual(self.result["repeat_once"]["consumed_foundation_positions"], 2)

    def test_repeat_total_consumes_12(self):
        self.assertEqual(self.result["repeat_total"]["consumed_foundation_positions"], 12)

    def test_row_1_consumes_18(self):
        self.assertEqual(self.result["row_1"]["consumed_foundation_positions"], 18)

    def test_row_1_produces_7_dc_6_chain_spaces_13_total(self):
        produced = self.result["row_1"]["produced_structure"]
        self.assertEqual(produced["stitch_posts"], {"DC": 7})
        self.assertEqual(produced["chain_spaces"], 6)
        self.assertEqual(produced["total_workable_positions"], 13)

    def test_unused_and_overdrawn_are_both_zero(self):
        self.assertEqual(self.result["row_1"]["unused_foundation_positions"], 0)
        self.assertEqual(self.result["row_1"]["overdrawn_foundation_positions"], 0)

    def test_expected_repeat_structure_matches(self):
        expected = self.result["expected_repeat_structure"]
        self.assertTrue(expected["stitch_posts_match"])
        self.assertTrue(expected["chain_spaces_match"])
        self.assertEqual(expected["actual_stitch_posts_per_repeat"], 1)
        self.assertEqual(expected["actual_chain_spaces_per_repeat"], 1)

    def test_no_errors(self):
        self.assertEqual(self.result["errors"], [])

    def test_ordered_output_matches_the_row_s_actual_left_to_right_production(self):
        # setup: SKIP 5 (produces nothing) then DC 1 -> just [DC].
        # repeat, once: CH 1 (a chain space), SKIP 1 (nothing), DC 1 ->
        # [chain_space, DC]. Six passes concatenate in order.
        DC = {"kind": "stitch_post", "stitch": "DC", "source": "literal"}
        CS = {"kind": "chain_space", "stitch": None, "source": "literal"}
        self.assertEqual(self.result["setup"]["ordered_output"], [DC])
        self.assertEqual(self.result["repeat_once"]["ordered_output"], [CS, DC])
        self.assertEqual(self.result["repeat_total"]["ordered_output"], [CS, DC] * 6)
        self.assertEqual(self.result["row_1"]["ordered_output"], [DC] + [CS, DC] * 6)
        # The aggregate produced_structure must always be a summary of
        # ordered_output, never an independent fact.
        ordered = self.result["row_1"]["ordered_output"]
        self.assertEqual(sum(1 for e in ordered if e["kind"] == "stitch_post" and e["stitch"] == "DC"), 7)
        self.assertEqual(sum(1 for e in ordered if e["kind"] == "chain_space"), 6)


# ---------------------------------------------------------------------------
# 10-13: the known-bad example, caught by exact accounting
# ---------------------------------------------------------------------------

class KnownBadExampleTests(unittest.TestCase):

    def setUp(self):
        self.recipe = known_bad_recipe()
        self.result = validate_row_1_against_foundation(self.recipe, 6)

    def test_is_invalid(self):
        self.assertFalse(self.result["valid"])

    def test_foundation_count_is_9(self):
        self.assertEqual(self.result["foundation"]["foundation_count"], 9)

    def test_row_1_accounts_for_7(self):
        self.assertEqual(self.result["row_1"]["consumed_foundation_positions"], 7)

    def test_reports_2_unexplained_positions(self):
        self.assertEqual(self.result["row_1"]["unused_foundation_positions"], 2)
        self.assertEqual(self.result["row_1"]["overdrawn_foundation_positions"], 0)
        self.assertIn(
            "Row 1 accounts for 7 of 9 foundation positions; 2 positions are unexplained.",
            self.result["errors"],
        )

    def test_recipe_remains_rejected(self):
        self.assertEqual(self.recipe["verification"]["status"], "REJECTED")


# ---------------------------------------------------------------------------
# 14/15: modified formulas -- overdraw and unused
# ---------------------------------------------------------------------------

class ModifiedFormulaMismatchTests(unittest.TestCase):

    def test_formula_too_short_reports_overdraw(self):
        recipe = structural_recipe()
        recipe["foundation_formula"]["additional_chains"] = 0  # foundation = 2*6+0 = 12, row_1 needs 18
        result = validate_row_1_against_foundation(recipe, 6)
        self.assertFalse(result["valid"])
        self.assertEqual(result["foundation"]["foundation_count"], 12)
        self.assertEqual(result["row_1"]["consumed_foundation_positions"], 18)
        self.assertEqual(result["row_1"]["overdrawn_foundation_positions"], 6)
        self.assertEqual(result["row_1"]["unused_foundation_positions"], 0)
        self.assertIn(
            "Row 1 requires 18 foundation positions, but the formula provides 12; short by 6.",
            result["errors"],
        )

    def test_formula_too_long_reports_unused(self):
        recipe = structural_recipe()
        recipe["foundation_formula"]["additional_chains"] = 20  # foundation = 2*6+20 = 32, row_1 needs 18
        result = validate_row_1_against_foundation(recipe, 6)
        self.assertFalse(result["valid"])
        self.assertEqual(result["foundation"]["foundation_count"], 32)
        self.assertEqual(result["row_1"]["consumed_foundation_positions"], 18)
        self.assertEqual(result["row_1"]["unused_foundation_positions"], 14)
        self.assertEqual(result["row_1"]["overdrawn_foundation_positions"], 0)
        self.assertIn(
            "Row 1 accounts for 18 of 32 foundation positions; 14 positions are unexplained.",
            result["errors"],
        )


# ---------------------------------------------------------------------------
# 16-18: expected_swatch_structure comparison
# ---------------------------------------------------------------------------

class ExpectedRepeatStructureTests(unittest.TestCase):

    def test_null_expected_values_do_not_cause_failure(self):
        recipe = structural_recipe()
        recipe["expected_swatch_structure"]["expected_stitch_posts_per_repeat"] = None
        recipe["expected_swatch_structure"]["expected_chain_spaces_per_repeat"] = None
        result = validate_row_1_against_foundation(recipe, 6)
        self.assertTrue(result["valid"])
        expected = result["expected_repeat_structure"]
        self.assertIsNone(expected["stitch_posts_match"])
        self.assertIsNone(expected["chain_spaces_match"])
        self.assertEqual(expected["actual_stitch_posts_per_repeat"], 1)
        self.assertEqual(expected["actual_chain_spaces_per_repeat"], 1)

    def test_incorrect_expected_stitch_posts_causes_failure(self):
        recipe = structural_recipe()
        recipe["expected_swatch_structure"]["expected_stitch_posts_per_repeat"] = 99
        result = validate_row_1_against_foundation(recipe, 6)
        self.assertFalse(result["valid"])
        self.assertFalse(result["expected_repeat_structure"]["stitch_posts_match"])
        self.assertIn(
            "Expected 99 stitch post(s) per repeat, but row_1.repeat produces 1.",
            result["errors"],
        )

    def test_incorrect_expected_chain_spaces_causes_failure(self):
        recipe = structural_recipe()
        recipe["expected_swatch_structure"]["expected_chain_spaces_per_repeat"] = 99
        result = validate_row_1_against_foundation(recipe, 6)
        self.assertFalse(result["valid"])
        self.assertFalse(result["expected_repeat_structure"]["chain_spaces_match"])
        self.assertIn(
            "Expected 99 chain space(s) per repeat, but row_1.repeat produces 1.",
            result["errors"],
        )


# ---------------------------------------------------------------------------
# 19: multiple stitch-post types totaled correctly
# ---------------------------------------------------------------------------

class MultipleStitchPostTypesTests(unittest.TestCase):

    def test_different_stitch_types_are_tracked_separately_and_totaled(self):
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[
                {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
                {"stitch": "SC", "count": 1, "placement": "next_foundation_chain"},
            ],
            repeat_multiple=2,
            additional_chains=0,
        )
        result = validate_row_1_against_foundation(recipe, 1)
        produced = result["repeat_once"]["produced_structure"]
        self.assertEqual(produced["stitch_posts"], {"DC": 1, "SC": 1})
        self.assertEqual(produced["total_workable_positions"], 2)
        self.assertEqual(result["expected_repeat_structure"]["actual_stitch_posts_per_repeat"], 2)


# ---------------------------------------------------------------------------
# 20/21: bare CH / SKIP behavior
# ---------------------------------------------------------------------------

class BareStepBehaviorTests(unittest.TestCase):

    def test_ch_working_loop_produces_chain_spaces_consumes_nothing(self):
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[{"stitch": "CH", "count": 3, "placement": "working_loop"}],
        )
        result = validate_row_1_against_foundation(recipe, 1)
        self.assertEqual(result["repeat_once"]["consumed_foundation_positions"], 0)
        self.assertEqual(result["repeat_once"]["produced_structure"]["chain_spaces"], 3)
        self.assertEqual(result["repeat_once"]["produced_structure"]["stitch_posts"], {})

    def test_skip_consumes_foundation_produces_nothing(self):
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[{"stitch": "SKIP", "count": 4, "placement": "next_foundation_chain"}],
        )
        result = validate_row_1_against_foundation(recipe, 1)
        self.assertEqual(result["repeat_once"]["consumed_foundation_positions"], 4)
        self.assertEqual(result["repeat_once"]["produced_structure"]["stitch_posts"], {})
        self.assertEqual(result["repeat_once"]["produced_structure"]["chain_spaces"], 0)


# ---------------------------------------------------------------------------
# 22/23: same_stitch behavior and its limits
# ---------------------------------------------------------------------------

class SameStitchTests(unittest.TestCase):

    def test_same_stitch_does_not_consume_another_foundation_position(self):
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[
                {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
                {"stitch": "DC", "count": 2, "placement": "same_stitch"},
            ],
        )
        result = validate_row_1_against_foundation(recipe, 1)
        self.assertEqual(result["repeat_once"]["consumed_foundation_positions"], 1)
        self.assertEqual(result["repeat_once"]["produced_structure"]["stitch_posts"], {"DC": 3})

    def test_same_stitch_with_no_prior_target_raises(self):
        recipe = minimal_recipe(
            row_1_setup=[{"stitch": "DC", "count": 1, "placement": "same_stitch"}],
            row_1_repeat=[{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
        )
        with self.assertRaises(RecipeMathError):
            validate_row_1_against_foundation(recipe, 1)

    def test_same_stitch_on_skip_raises(self):
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[
                {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
                {"stitch": "SKIP", "count": 1, "placement": "same_stitch"},
            ],
        )
        with self.assertRaises(RecipeMathError):
            validate_row_1_against_foundation(recipe, 1)

    def test_same_stitch_established_across_setup_repeat_boundary(self):
        # setup establishes a target; repeat's same_stitch (as its FIRST
        # step) must be able to refer back to it -- proving the boundary
        # is handled, not just same_stitch within one list.
        recipe = minimal_recipe(
            row_1_setup=[{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
            row_1_repeat=[{"stitch": "DC", "count": 1, "placement": "same_stitch"}],
        )
        result = validate_row_1_against_foundation(recipe, 1)
        self.assertEqual(result["repeat_once"]["consumed_foundation_positions"], 0)
        self.assertEqual(result["repeat_once"]["produced_structure"]["stitch_posts"], {"DC": 1})


# ---------------------------------------------------------------------------
# 22a-22d: working_loop preserves (does not clear) the previous target
# ---------------------------------------------------------------------------

class WorkingLoopPreservesTargetTests(unittest.TestCase):
    """
    DC next_foundation_chain -> CH working_loop -> DC same_stitch: the
    final DC must be able to refer back to the SAME foundation chain the
    first DC targeted, because a floating working-loop chain in between
    doesn't touch the foundation and so has no reason to erase the most
    recently targeted position.
    """

    def setUp(self):
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[
                {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
                {"stitch": "CH", "count": 1, "placement": "working_loop"},
                {"stitch": "DC", "count": 1, "placement": "same_stitch"},
            ],
            repeat_multiple=1,
            additional_chains=0,
        )
        self.result = validate_row_1_against_foundation(recipe, 1)

    def test_is_valid(self):
        self.assertTrue(self.result["valid"])

    def test_consumes_exactly_1_foundation_position(self):
        self.assertEqual(self.result["repeat_once"]["consumed_foundation_positions"], 1)
        self.assertEqual(self.result["row_1"]["consumed_foundation_positions"], 1)

    def test_produces_2_dc_posts_1_chain_space_3_total(self):
        produced = self.result["repeat_once"]["produced_structure"]
        self.assertEqual(produced["stitch_posts"], {"DC": 2})
        self.assertEqual(produced["chain_spaces"], 1)
        self.assertEqual(produced["total_workable_positions"], 3)

    def test_row_1_totals_match(self):
        produced = self.result["row_1"]["produced_structure"]
        self.assertEqual(produced["stitch_posts"], {"DC": 2})
        self.assertEqual(produced["chain_spaces"], 1)
        self.assertEqual(produced["total_workable_positions"], 3)

    def test_ordered_output_is_dc_then_chain_space_then_dc(self):
        # Order matters here specifically: this is DC, chain space, DC --
        # not DC, DC, chain space or any other arrangement that would
        # happen to have the same {"DC": 2, "chain_spaces": 1} totals.
        DC = {"kind": "stitch_post", "stitch": "DC", "source": "literal"}
        CS = {"kind": "chain_space", "stitch": None, "source": "literal"}
        self.assertEqual(self.result["row_1"]["ordered_output"], [DC, CS, DC])

    def test_working_loop_alone_does_not_clear_a_target_established_before_it(self):
        # Isolates the mechanism: DC establishes a target, CH working_loop
        # comes next, and same_stitch afterward must still see it.
        recipe = minimal_recipe(
            row_1_setup=[{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
            row_1_repeat=[
                {"stitch": "CH", "count": 2, "placement": "working_loop"},
                {"stitch": "SC", "count": 1, "placement": "same_stitch"},
            ],
        )
        result = validate_row_1_against_foundation(recipe, 1)
        self.assertEqual(result["repeat_once"]["produced_structure"]["stitch_posts"], {"SC": 1})
        self.assertEqual(result["repeat_once"]["produced_structure"]["chain_spaces"], 2)


# ---------------------------------------------------------------------------
# 22e: repeats execute sequentially, carrying target state across the
# repeat-iteration boundary (not just the setup-to-repeat boundary)
# ---------------------------------------------------------------------------

class SequentialRepeatExecutionTests(unittest.TestCase):

    def test_target_cleared_by_one_pass_is_not_available_to_the_next(self):
        # setup establishes a target; each repeat pass is [SC same_stitch,
        # SKIP next_foundation_chain]. Pass 1 sees the target set by
        # setup (True) and succeeds, but its own SKIP clears the target
        # by the time the pass ends. Pass 2's same_stitch must see THAT
        # cleared state, not the value left behind by setup -- so it must
        # raise. An implementation that analyzes repeat once (seeded from
        # setup's target) and multiplies the result would never re-check
        # this and would incorrectly report success no matter how many
        # repeats are requested.
        recipe = minimal_recipe(
            row_1_setup=[{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
            row_1_repeat=[
                {"stitch": "SC", "count": 1, "placement": "same_stitch"},
                {"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"},
            ],
            repeat_multiple=1,
            additional_chains=1,
        )
        # A single pass only ever sees setup's target -- valid.
        result_one_repeat = validate_row_1_against_foundation(recipe, 1)
        self.assertTrue(result_one_repeat["valid"])

        # A second pass must see pass 1's cleared target -- invalid.
        with self.assertRaises(RecipeMathError):
            validate_row_1_against_foundation(recipe, 2)

    def test_target_carries_from_one_repeat_pass_into_the_next(self):
        # Each repeat pass: DC next_foundation_chain (establishes target),
        # then CH working_loop (must NOT clear it) -- a positive-path
        # sanity check that consumption/production accumulate correctly
        # pass by pass.
        recipe = minimal_recipe(
            row_1_setup=[],
            row_1_repeat=[
                {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
                {"stitch": "CH", "count": 1, "placement": "working_loop"},
            ],
            repeat_multiple=1,
            additional_chains=0,
        )
        result = validate_row_1_against_foundation(recipe, 3)
        self.assertTrue(result["valid"])
        self.assertEqual(result["repeat_total"]["consumed_foundation_positions"], 3)
        produced = result["repeat_total"]["produced_structure"]
        self.assertEqual(produced["stitch_posts"], {"DC": 3})
        self.assertEqual(produced["chain_spaces"], 3)

    def test_first_pass_result_is_carried_from_setup_not_from_a_later_pass(self):
        # repeat_once must reflect the pass whose target came from setup
        # (the first pass), confirming sequential execution starts the
        # chain correctly rather than, say, reporting some other pass.
        # (foundation_count is deliberately left mismatched here -- this
        # test is only about repeat_once/repeat_total's per-pass content,
        # not overall validity.)
        recipe = minimal_recipe(
            row_1_setup=[{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
            row_1_repeat=[{"stitch": "SC", "count": 1, "placement": "same_stitch"}],
        )
        result = validate_row_1_against_foundation(recipe, 5)
        self.assertEqual(result["repeat_once"]["consumed_foundation_positions"], 0)
        self.assertEqual(result["repeat_once"]["produced_structure"]["stitch_posts"], {"SC": 1})
        self.assertEqual(
            result["repeat_total"]["produced_structure"]["stitch_posts"], {"SC": 5}
        )


# ---------------------------------------------------------------------------
# 24-26: malformed input
# ---------------------------------------------------------------------------

class MalformedInputTests(unittest.TestCase):

    def test_non_dict_recipe_raises(self):
        for bad in (None, "a string", 42, ["a", "list"]):
            with self.subTest(bad=bad):
                with self.assertRaises(RecipeMathError):
                    validate_row_1_against_foundation(bad, 6)

    def test_malformed_recipe_raises(self):
        recipe = structural_recipe()
        del recipe["pattern_id"]
        with self.assertRaises(RecipeMathError) as ctx:
            validate_row_1_against_foundation(recipe, 6)
        self.assertIn("pattern_id", str(ctx.exception))

    def test_invalid_repeat_count_raises(self):
        for bad in (0, -1, None, "6", 6.0):
            with self.subTest(bad=bad):
                with self.assertRaises(RecipeMathError):
                    validate_row_1_against_foundation(structural_recipe(), bad)

    def test_boolean_repeat_counts_are_rejected(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                with self.assertRaises(RecipeMathError):
                    validate_row_1_against_foundation(structural_recipe(), bad)


# ---------------------------------------------------------------------------
# 27/28: no mutation, no status change
# ---------------------------------------------------------------------------

class NoMutationTests(unittest.TestCase):

    def test_recipe_is_not_mutated(self):
        recipe = structural_recipe()
        before = copy.deepcopy(recipe)
        validate_row_1_against_foundation(recipe, 6)
        self.assertEqual(recipe, before)

    def test_recipe_is_not_mutated_on_a_failing_report(self):
        recipe = known_bad_recipe()
        before = copy.deepcopy(recipe)
        validate_row_1_against_foundation(recipe, 6)
        self.assertEqual(recipe, before)

    def test_verification_status_is_not_changed(self):
        recipe = known_bad_recipe()
        validate_row_1_against_foundation(recipe, 6)
        self.assertEqual(recipe["verification"]["status"], "REJECTED")
        recipe2 = structural_recipe()
        validate_row_1_against_foundation(recipe2, 6)
        self.assertEqual(recipe2["verification"]["status"], "AI_PROPOSED")


# ---------------------------------------------------------------------------
# 29-31: nothing else regressed
# ---------------------------------------------------------------------------

class RegressionSpotChecksTests(unittest.TestCase):
    """
    Lightweight in-file spot checks that Phase 3's calculate_foundation(),
    Phase 2's validate_recipe_v2(), and the v1 validator/swatch pathway
    all still behave exactly as before -- complementing (not replacing)
    the full suite run: python3 -m unittest discover -s tests.
    """

    def test_calculate_foundation_still_works(self):
        from engine.foundation import calculate_foundation
        self.assertEqual(calculate_foundation(structural_recipe(), 6)["foundation_count"], 18)

    def test_validate_recipe_v2_still_accepts_both_examples(self):
        from engine.schema import validate_recipe_v2
        self.assertEqual(validate_recipe_v2(structural_recipe()), [])
        self.assertEqual(validate_recipe_v2(known_bad_recipe()), [])

    def test_v1_validator_and_swatch_are_untouched(self):
        from engine.validator import check_full_row
        from engine.swatch import build_test_foundation
        setup_steps = [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
        repeat_steps = [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6), 18)
        full_row = {"setup": setup_steps, "repeat": repeat_steps}
        result = check_full_row(full_row, repeat_count=7, stitches_available=20)
        self.assertEqual(result["consumed"], 20)
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
