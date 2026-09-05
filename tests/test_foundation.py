"""
Tests for engine/foundation.py's calculate_foundation() -- the one
authoritative Phase 3 calculation:

    foundation_count = repeat_multiple * requested_repeat_count + additional_chains

Fixtures are loaded from the real example files (contracts/examples/)
rather than duplicated as literal dicts, per the project's established
convention (tests/test_recipe_schema_v2.py does the same).
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.foundation import FoundationCalculationError, calculate_foundation

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


# ---------------------------------------------------------------------------
# 1/2/3: the documented calculations for the structural example
# ---------------------------------------------------------------------------

class StructuralExampleCalculationTests(unittest.TestCase):

    def test_six_repeats_returns_18(self):
        result = calculate_foundation(structural_recipe(), 6)
        self.assertEqual(result["foundation_count"], 18)

    def test_seven_repeats_returns_20(self):
        result = calculate_foundation(structural_recipe(), 7)
        self.assertEqual(result["foundation_count"], 20)

    def test_three_repeats_returns_12(self):
        result = calculate_foundation(structural_recipe(), 3)
        self.assertEqual(result["foundation_count"], 12)


# ---------------------------------------------------------------------------
# 4: full breakdown shape
# ---------------------------------------------------------------------------

class BreakdownShapeTests(unittest.TestCase):

    def test_breakdown_contains_all_five_keys(self):
        result = calculate_foundation(structural_recipe(), 6)
        self.assertEqual(
            set(result.keys()),
            {"repeat_multiple", "requested_repeat_count", "repeated_chains", "additional_chains", "foundation_count"},
        )

    def test_breakdown_values_are_internally_consistent(self):
        result = calculate_foundation(structural_recipe(), 6)
        self.assertEqual(result["repeat_multiple"], 2)
        self.assertEqual(result["requested_repeat_count"], 6)
        self.assertEqual(result["repeated_chains"], 12)
        self.assertEqual(result["additional_chains"], 6)
        self.assertEqual(result["repeated_chains"] + result["additional_chains"], result["foundation_count"])


# ---------------------------------------------------------------------------
# 5: the known-bad example -- calculated honestly, still REJECTED
# ---------------------------------------------------------------------------

class KnownBadExampleCalculationTests(unittest.TestCase):

    def test_six_repeats_returns_9_while_recipe_remains_rejected(self):
        recipe = known_bad_recipe()
        result = calculate_foundation(recipe, 6)
        self.assertEqual(result["foundation_count"], 9)
        self.assertEqual(result["repeat_multiple"], 1)
        self.assertEqual(result["additional_chains"], 3)
        # The calculation does not touch, read, or care about verification --
        # confirmed by checking the ORIGINAL dict is still exactly REJECTED.
        self.assertEqual(recipe["verification"]["status"], "REJECTED")
        self.assertTrue(recipe["verification"]["reason"])

    def test_rejected_status_does_not_block_calculation(self):
        # Explicit, separate assertion of the core trust distinction: a
        # structurally valid REJECTED recipe still calculates. No special
        # casing on verification.status exists anywhere in
        # calculate_foundation() -- this proves it by observation.
        recipe = known_bad_recipe()
        self.assertEqual(recipe["verification"]["status"], "REJECTED")
        result = calculate_foundation(recipe, 1)
        self.assertEqual(result["foundation_count"], 1 * 1 + 3)


# ---------------------------------------------------------------------------
# 6: repeat count 1
# ---------------------------------------------------------------------------

class RepeatCountOneTests(unittest.TestCase):

    def test_repeat_count_one_works(self):
        result = calculate_foundation(structural_recipe(), 1)
        self.assertEqual(result["foundation_count"], 2 * 1 + 6)


# ---------------------------------------------------------------------------
# 7-13: rejected requested_repeat_count values, no coercion
# ---------------------------------------------------------------------------

class RequestedRepeatCountValidationTests(unittest.TestCase):

    def test_zero_is_rejected(self):
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), 0)

    def test_negative_is_rejected(self):
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), -3)

    def test_true_is_rejected(self):
        # bool is a subclass of int in Python -- True must not be
        # silently treated as 1.
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), True)

    def test_false_is_rejected(self):
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), False)

    def test_decimal_is_rejected(self):
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), 6.0)

    def test_string_is_rejected(self):
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), "6")

    def test_none_is_rejected(self):
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(structural_recipe(), None)

    def test_no_silent_coercion_of_decimal_that_equals_an_int(self):
        # 6.0 == 6 in Python -- must still be rejected, not coerced.
        recipe = structural_recipe()
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(recipe, 6.0)
        # A real int 6 must still work fine, proving the rejection above
        # was about type, not value.
        self.assertEqual(calculate_foundation(recipe, 6)["foundation_count"], 18)


# ---------------------------------------------------------------------------
# 14/15: malformed recipe input
# ---------------------------------------------------------------------------

class MalformedRecipeTests(unittest.TestCase):

    def test_non_dict_recipe_is_rejected(self):
        for bad in (None, "a string", 42, ["a", "list"]):
            with self.subTest(bad=bad):
                with self.assertRaises(FoundationCalculationError):
                    calculate_foundation(bad, 6)

    def test_malformed_recipe_is_rejected_with_schema_details(self):
        recipe = structural_recipe()
        del recipe["pattern_id"]
        with self.assertRaises(FoundationCalculationError) as ctx:
            calculate_foundation(recipe, 6)
        self.assertIn("pattern_id", str(ctx.exception))

    def test_recipe_with_invalid_foundation_formula_is_rejected(self):
        recipe = structural_recipe()
        recipe["foundation_formula"]["repeat_multiple"] = 0
        with self.assertRaises(FoundationCalculationError) as ctx:
            calculate_foundation(recipe, 6)
        self.assertIn("repeat_multiple", str(ctx.exception))

    def test_does_not_calculate_from_malformed_data(self):
        # Confirms no partial/garbage result is ever returned -- only the
        # exception, never a dict, when validation fails.
        recipe = structural_recipe()
        del recipe["verification"]
        try:
            calculate_foundation(recipe, 6)
            self.fail("expected FoundationCalculationError")
        except FoundationCalculationError:
            pass


# ---------------------------------------------------------------------------
# 16: no mutation of the supplied recipe
# ---------------------------------------------------------------------------

class NoMutationTests(unittest.TestCase):

    def test_recipe_is_not_mutated_by_a_successful_call(self):
        recipe = structural_recipe()
        before = copy.deepcopy(recipe)
        calculate_foundation(recipe, 6)
        self.assertEqual(recipe, before)

    def test_recipe_is_not_mutated_by_a_failed_call(self):
        recipe = structural_recipe()
        recipe["foundation_formula"]["additional_chains"] = -1
        before = copy.deepcopy(recipe)
        with self.assertRaises(FoundationCalculationError):
            calculate_foundation(recipe, 6)
        self.assertEqual(recipe, before)


# ---------------------------------------------------------------------------
# 17: large but reasonable repeat counts
# ---------------------------------------------------------------------------

class LargeRepeatCountTests(unittest.TestCase):

    def test_large_repeat_count_calculates_deterministically(self):
        recipe = structural_recipe()
        result_a = calculate_foundation(recipe, 10_000)
        result_b = calculate_foundation(recipe, 10_000)
        expected = 2 * 10_000 + 6
        self.assertEqual(result_a["foundation_count"], expected)
        self.assertEqual(result_a, result_b)


# ---------------------------------------------------------------------------
# 18/19: nothing else regressed
# ---------------------------------------------------------------------------

class RegressionSpotChecksTests(unittest.TestCase):
    """
    Lightweight, in-file spot checks that Phase 1/2 validation and the
    v1 swatch/foundation pathway still behave exactly as before --
    complementing (not replacing) the full suite run, which is the real
    proof: python3 -m unittest discover -s tests.
    """

    def test_v2_examples_still_pass_validate_recipe_v2_unchanged(self):
        from engine.schema import validate_recipe_v2
        self.assertEqual(validate_recipe_v2(structural_recipe()), [])
        self.assertEqual(validate_recipe_v2(known_bad_recipe()), [])

    def test_v1_build_test_foundation_is_untouched(self):
        from engine.swatch import build_test_foundation
        setup_steps = [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
        repeat_steps = [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]
        # Same fixture/expected value as tests/test_swatch.py's own
        # build_test_foundation coverage -- 2*6+6=18 by the v1 formula's
        # own (different) accounting, reusing check_full_row + new_chain_links.
        self.assertEqual(build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6), 18)


if __name__ == "__main__":
    unittest.main()
