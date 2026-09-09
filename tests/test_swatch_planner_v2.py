"""
Tests for engine/swatch_planner_v2.py -- Phase 7's trusted swatch
planner: Phase 6 resolution -> Phase 5 simulation -> structured plan ->
rendered instructions, with an explicit, never-collapsed-to-one status
for every way that pipeline can stop short of a usable result.

Every test builds a small, hand-checked in-memory library and AI
proposal (per the project's established convention -- see
tests/test_recipe_library.py) and passes the library directly to
plan_trusted_swatch(); none of this reads or writes the real production
data/confirmed_stitch_recipes_v2.json or the unrelated v1
data/confirmed_stitch_patterns.json.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.swatch_planner_v2 import (
    STATUS_AMBIGUOUS_RECIPE,
    STATUS_INVALID_AI_PROPOSAL,
    STATUS_INVALID_LIBRARY,
    STATUS_INVALID_REQUEST,
    STATUS_NO_TRUSTED_RECIPE,
    STATUS_READY,
    STATUS_RENDER_UNSUPPORTED,
    STATUS_SIMULATION_FAILED,
    STATUS_SIMULATION_UNSUPPORTED,
    plan_trusted_swatch,
)


def make_recipe(pattern_id, name, aliases=None, status="AI_PROPOSED", terminology="US",
                 repeat_multiple=1, additional_chains=0,
                 row_1_repeat=None, later_setup=None, later_repeat=None):
    aliases = aliases or []
    row_1_repeat = row_1_repeat if row_1_repeat is not None else \
        [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}]
    later_setup = later_setup if later_setup is not None else \
        [{"stitch": "CH", "count": 1, "placement": "turning_chain"}]
    later_repeat = later_repeat if later_repeat is not None else \
        [{"stitch": "DC", "count": 1, "placement": "next_dc"}]

    verification = {"status": status, "confirmations": []}
    if status in ("CONFIRMED", "SWATCH_TESTED"):
        verification["confirmations"] = [{"photo": "a.jpg", "date": "2026-01-01", "note": "hand swatched"}]
    if status == "REJECTED":
        verification["reason"] = "did not match the target construction"

    return {
        "pattern_id": pattern_id,
        "name": name,
        "aliases": aliases,
        "terminology": terminology,
        "foundation_formula": {"repeat_multiple": repeat_multiple, "additional_chains": additional_chains},
        "row_1": {"setup": [], "repeat": row_1_repeat},
        "later_rows": {"setup": later_setup, "repeat": later_repeat},
        "expected_swatch_structure": {"expected_stitch_posts_per_repeat": None, "expected_chain_spaces_per_repeat": None},
        "verification": verification,
    }


def library_of(*recipes):
    return {"schema_version": "2.0.0", "recipes": list(recipes)}


TRUSTED_RECIPE = make_recipe("filet_mesh_v1", "Filet Mesh", aliases=["open filet mesh"], status="CONFIRMED")


# ---------------------------------------------------------------------------
# The ready path: trusted match overrides a differing AI proposal
# ---------------------------------------------------------------------------

class ReadyPathTests(unittest.TestCase):
    def test_ready_plan_uses_the_trusted_recipe_not_the_ai_proposal(self):
        library = library_of(TRUSTED_RECIPE)
        # The AI's own math is wrong (repeat_multiple=2 vs the trusted
        # recipe's 1) -- if the planner ever used the AI's numbers, the
        # rendered instructions would reflect that; they must not.
        ai_proposal = make_recipe("ai_guess", "filet mesh", status="AI_PROPOSED", repeat_multiple=2)

        result = plan_trusted_swatch(ai_proposal, requested_repeat_count=4, later_row_count=2, library=library)

        self.assertEqual(result["status"], STATUS_READY)
        self.assertTrue(result["ready_for_user_instructions"])
        self.assertEqual(result["provenance"], "library")
        self.assertIs(result["selected_recipe"], TRUSTED_RECIPE)
        self.assertEqual(result["foundation"]["repeat_multiple"], 1)  # the TRUSTED recipe's formula, not 2
        self.assertIn("Filet Mesh", result["rendered_instructions"])
        # ai_proposal preserved only for comparison, never used as content.
        self.assertIsNot(result["resolution"]["ai_proposal"], ai_proposal)
        self.assertNotEqual(result["resolution"]["comparison"]["differences"], [])

    def test_ready_plan_never_mutates_ai_proposal_library_or_itself(self):
        library = library_of(TRUSTED_RECIPE)
        library_before = copy.deepcopy(library)
        ai_proposal = make_recipe("ai_guess", "filet mesh", status="AI_PROPOSED", repeat_multiple=2)
        ai_before = copy.deepcopy(ai_proposal)

        result = plan_trusted_swatch(ai_proposal, requested_repeat_count=3, later_row_count=1, library=library)

        self.assertEqual(library, library_before)
        self.assertEqual(ai_proposal, ai_before)

        # Mutating the returned plan's embedded step lists must never
        # reach back into the trusted library recipe.
        result["swatch_plan"]["row_1_setup"].append({"stitch": "SKIP", "count": 99, "placement": "next_foundation_chain"})
        self.assertEqual(library["recipes"][0]["row_1"]["setup"], [])


# ---------------------------------------------------------------------------
# invalid_request
# ---------------------------------------------------------------------------

class InvalidRequestTests(unittest.TestCase):
    def test_zero_or_negative_requested_repeat_count_is_invalid_request(self):
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_x", "filet mesh")
        for bad in (0, -1):
            with self.subTest(bad=bad):
                result = plan_trusted_swatch(ai_proposal, bad, 1, library)
                self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
                self.assertFalse(result["ready_for_user_instructions"])
                self.assertIsNone(result["rendered_instructions"])
                self.assertIsNone(result["resolution"])

    def test_negative_later_row_count_is_invalid_request(self):
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_x", "filet mesh")
        result = plan_trusted_swatch(ai_proposal, 3, -1, library)
        self.assertEqual(result["status"], STATUS_INVALID_REQUEST)

    def test_non_integer_counts_are_invalid_request(self):
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_x", "filet mesh")
        for bad in (True, False, "3", 3.0, None):
            with self.subTest(bad=bad):
                result = plan_trusted_swatch(ai_proposal, bad, 1, library)
                self.assertEqual(result["status"], STATUS_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# invalid_ai_proposal
# ---------------------------------------------------------------------------

class InvalidAiProposalTests(unittest.TestCase):
    def test_structurally_broken_ai_proposal(self):
        library = library_of(TRUSTED_RECIPE)
        result = plan_trusted_swatch({"pattern_id": "incomplete"}, 3, 1, library)
        self.assertEqual(result["status"], STATUS_INVALID_AI_PROPOSAL)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertTrue(len(result["errors"]) > 0)


# ---------------------------------------------------------------------------
# no_trusted_recipe -- both no_match and untrusted_match collapse here
# ---------------------------------------------------------------------------

class NoTrustedRecipeTests(unittest.TestCase):
    def test_no_library_match(self):
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_unknown", "popcorn stitch", status="AI_PROPOSED")
        result = plan_trusted_swatch(ai_proposal, 3, 1, library)
        self.assertEqual(result["status"], STATUS_NO_TRUSTED_RECIPE)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertEqual(result["resolution"]["status"], "no_match")

    def test_matched_but_unconfirmed_recipe_is_not_trusted(self):
        unconfirmed = make_recipe("waffle_v1", "Waffle Stitch", status="SIMULATION_VALID")
        library = library_of(unconfirmed)
        ai_proposal = make_recipe("ai_waffle", "waffle stitch", status="AI_PROPOSED")
        result = plan_trusted_swatch(ai_proposal, 3, 1, library)
        self.assertEqual(result["status"], STATUS_NO_TRUSTED_RECIPE)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertEqual(result["resolution"]["status"], "untrusted_match")

    def test_rejected_recipe_is_never_selected(self):
        rejected = make_recipe("bad_v1", "Bad Stitch", status="REJECTED")
        library = library_of(rejected)
        ai_proposal = make_recipe("ai_bad", "bad stitch", status="AI_PROPOSED")
        result = plan_trusted_swatch(ai_proposal, 3, 1, library)
        self.assertEqual(result["status"], STATUS_NO_TRUSTED_RECIPE)
        self.assertIsNone(result["selected_recipe"])


# ---------------------------------------------------------------------------
# ambiguous_recipe
# ---------------------------------------------------------------------------

class AmbiguousRecipeTests(unittest.TestCase):
    def test_ambiguous_match_lists_conflicts_and_produces_nothing(self):
        recipe_a = make_recipe("dup_a", "Stitch A", status="CONFIRMED")
        recipe_b = make_recipe("dup_b", "Stitch B", status="CONFIRMED")
        library = library_of(recipe_a, recipe_b)
        ai_proposal = make_recipe("ai_shared", "Stitch A", aliases=["Stitch B"], status="AI_PROPOSED")

        result = plan_trusted_swatch(ai_proposal, 3, 1, library)

        self.assertEqual(result["status"], STATUS_AMBIGUOUS_RECIPE)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertIn("dup_a", result["errors"][0])
        self.assertIn("dup_b", result["errors"][0])


# ---------------------------------------------------------------------------
# invalid_library
# ---------------------------------------------------------------------------

class InvalidLibraryTests(unittest.TestCase):
    def test_malformed_directly_supplied_library(self):
        ai_proposal = make_recipe("ai_x", "Stitch")
        result = plan_trusted_swatch(ai_proposal, 3, 1, {"recipes": "not a list"})
        self.assertEqual(result["status"], STATUS_INVALID_LIBRARY)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertIsNone(result["resolution"])

    def test_confirmed_recipe_in_a_malformed_library_is_never_selected(self):
        # A library that would (if searched naively) hand back a
        # "CONFIRMED" recipe, but the library itself is invalid (a
        # duplicate pattern_id) -- must never reach selection.
        trusted_first = make_recipe("dup_id", "Stitch A", status="CONFIRMED")
        untrusted_second = make_recipe("dup_id", "Stitch A", status="AI_PROPOSED")
        library = library_of(trusted_first, untrusted_second)
        ai_proposal = make_recipe("ai_x", "Stitch A", status="AI_PROPOSED")

        result = plan_trusted_swatch(ai_proposal, 3, 1, library)

        self.assertEqual(result["status"], STATUS_INVALID_LIBRARY)
        self.assertIsNone(result["selected_recipe"])


# ---------------------------------------------------------------------------
# simulation_unsupported -- a RecipeMathError "refuses to guess" case
# ---------------------------------------------------------------------------

class SimulationUnsupportedTests(unittest.TestCase):
    def test_same_stitch_with_no_established_target_is_unsupported_not_a_crash(self):
        bad_sim = make_recipe(
            "p_bad_sim", "Bad Sim Stitch", status="CONFIRMED",
            later_setup=[{"stitch": "CH", "count": 1, "placement": "turning_chain"}],
            later_repeat=[{"stitch": "SC", "count": 1, "placement": "same_stitch"}],
        )
        library = library_of(bad_sim)
        ai_proposal = make_recipe("ai_x", "Bad Sim Stitch", status="AI_PROPOSED")

        result = plan_trusted_swatch(ai_proposal, 3, 1, library)

        self.assertEqual(result["status"], STATUS_SIMULATION_UNSUPPORTED)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertTrue(len(result["errors"]) > 0)


# ---------------------------------------------------------------------------
# simulation_failed -- an ordinary math mismatch, reported not raised
# ---------------------------------------------------------------------------

class SimulationFailedTests(unittest.TestCase):
    def test_foundation_mismatch_in_the_trusted_recipe_itself(self):
        bad_math = make_recipe("p_bad_math", "Bad Math Stitch", status="CONFIRMED",
                                repeat_multiple=1, additional_chains=5)
        library = library_of(bad_math)
        ai_proposal = make_recipe("ai_x", "Bad Math Stitch", status="AI_PROPOSED")

        result = plan_trusted_swatch(ai_proposal, 3, 1, library)

        self.assertEqual(result["status"], STATUS_SIMULATION_FAILED)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        self.assertIsNotNone(result["row_validation"])
        self.assertEqual(result["row_validation"]["first_failing_row"], 1)


# ---------------------------------------------------------------------------
# render_unsupported -- everything passed except the terminology
# ---------------------------------------------------------------------------

class RenderUnsupportedTests(unittest.TestCase):
    def test_uk_terminology_is_not_silently_rendered_as_us(self):
        uk_recipe = make_recipe("p_uk", "UK Stitch", status="CONFIRMED", terminology="UK")
        library = library_of(uk_recipe)
        ai_proposal = make_recipe("ai_x", "UK Stitch", status="AI_PROPOSED", terminology="UK")

        result = plan_trusted_swatch(ai_proposal, 3, 1, library)

        self.assertEqual(result["status"], STATUS_RENDER_UNSUPPORTED)
        self.assertFalse(result["ready_for_user_instructions"])
        self.assertIsNone(result["rendered_instructions"])
        # Simulation DID succeed -- the structured plan still exists,
        # only the rendered text does not.
        self.assertIsNotNone(result["swatch_plan"])
        self.assertTrue(len(result["errors"]) > 0)


# ---------------------------------------------------------------------------
# Structured swatch plan contents (PART 4's checklist)
# ---------------------------------------------------------------------------

class StructuredSwatchPlanTests(unittest.TestCase):
    def test_plan_contains_the_required_fields_from_the_trusted_recipe(self):
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_guess", "filet mesh", status="AI_PROPOSED", repeat_multiple=99)
        result = plan_trusted_swatch(ai_proposal, requested_repeat_count=5, later_row_count=2, library=library)
        plan = result["swatch_plan"]

        self.assertEqual(plan["pattern_id"], "filet_mesh_v1")
        self.assertEqual(plan["name"], "Filet Mesh")
        self.assertEqual(plan["terminology"], "US")
        self.assertEqual(plan["trust"]["provenance"], "library")
        self.assertEqual(plan["trust"]["verification_status"], "CONFIRMED")
        self.assertEqual(plan["requested_repeat_count"], 5)
        self.assertEqual(plan["total_rows"], 3)
        self.assertEqual(plan["foundation_chain_count"], plan["foundation_formula"]["foundation_count"])
        self.assertEqual(plan["foundation_formula"]["repeat_multiple"], 1)  # TRUSTED recipe's, not 99
        self.assertEqual(plan["row_1_setup"], TRUSTED_RECIPE["row_1"]["setup"])
        self.assertEqual(plan["row_1_repeat"], TRUSTED_RECIPE["row_1"]["repeat"])
        self.assertEqual(plan["row_1_repeat_execution_count"], 5)
        self.assertEqual(plan["later_row_setup"], TRUSTED_RECIPE["later_rows"]["setup"])
        self.assertEqual(plan["later_row_repeat"], TRUSTED_RECIPE["later_rows"]["repeat"])
        self.assertEqual(len(plan["later_rows"]), 2)
        self.assertIn("row_1_valid", plan["validation_evidence"])
        self.assertTrue(any("four inches" in w or "gauge" in w for w in plan["warnings"]))

    def test_plan_does_not_claim_a_physical_measurement(self):
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_x", "filet mesh")
        result = plan_trusted_swatch(ai_proposal, 3, 1, library)
        self.assertNotIn("four inches", result["rendered_instructions"].replace("does not claim any physical measurement (e.g. \"four inches\")", ""))
        # (The warning text itself is allowed to mention "four inches" as
        # the thing NOT being claimed; the instructions body must not
        # assert it as fact.)
        body = result["rendered_instructions"].split("Notes:")[0]
        self.assertNotIn("4 inches", body)
        self.assertNotIn("four inches", body)


# ---------------------------------------------------------------------------
# Existing test suite (Phase 1-6) unaffected
# ---------------------------------------------------------------------------

class RegressionSpotChecksTests(unittest.TestCase):
    def test_v1_renderer_and_swatch_module_are_untouched(self):
        from engine.renderer import render_row
        from engine.swatch import build_test_foundation
        row = {"setup": [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}],
               "repeat": [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]}
        self.assertIn("double crochet", render_row(row, repeat_count=6))
        self.assertEqual(build_test_foundation(row["setup"], row["repeat"], test_repeat_count=6), 18)

    def test_recipe_library_still_works_standalone(self):
        from engine.recipe_library import resolve_stitch_recipe
        library = library_of(TRUSTED_RECIPE)
        ai_proposal = make_recipe("ai_x", "filet mesh")
        result = resolve_stitch_recipe(ai_proposal, library)
        self.assertEqual(result["status"], "trusted_match")


if __name__ == "__main__":
    unittest.main()
