"""
Tests for engine/later_row_validator.py's validate_recipe_rows() -- Phase
5's row-by-row, TYPED validation of later_rows against what the row
before them actually produced (never a flat total).

Fixtures are small, hand-built recipes (per the project's established
convention -- see tests/test_recipe_validator.py). Every test explains
the crochet math it's checking in a short comment. Row 1's foundation
formula is always chosen so row 1 itself is exactly valid (consumed ==
foundation_count) unless the test is specifically about a row-1 failure,
so that any later-row failure under test is unambiguously about later
rows, not a row-1 artifact.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.later_row_validator import validate_recipe_rows
from engine.recipe_validator import RecipeMathError


def recipe(row_1_repeat, later_setup, later_repeat, repeat_multiple,
           row_1_setup=None, additional_chains=0):
    """A small, hand-built, schema-valid v2 recipe for later-row edge
    cases. row_1 is deliberately minimal; callers plug in whatever
    later_rows structure they're testing."""
    if row_1_setup is None:
        row_1_setup = []
    return {
        "pattern_id": "test_pattern",
        "name": "Test Stitch",
        "aliases": [],
        "terminology": "US",
        "foundation_formula": {"repeat_multiple": repeat_multiple, "additional_chains": additional_chains},
        "row_1": {"setup": row_1_setup, "repeat": row_1_repeat},
        "later_rows": {"setup": later_setup, "repeat": later_repeat},
        "expected_swatch_structure": {"expected_stitch_posts_per_repeat": None, "expected_chain_spaces_per_repeat": None},
        "verification": {"status": "AI_PROPOSED", "confirmations": []},
    }


DC_NEXT_FOUNDATION = [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}]
PLAIN_TURNING_CHAIN = [{"stitch": "CH", "count": 1, "placement": "turning_chain"}]
DC_NEXT_DC = [{"stitch": "DC", "count": 1, "placement": "next_dc"}]


# ---------------------------------------------------------------------------
# 1: a valid row 1 feeding a valid row 2
# ---------------------------------------------------------------------------

class ValidRow1FeedsRow2Tests(unittest.TestCase):
    def test_row_1_dc_repeat_feeds_row_2_next_dc_repeat(self):
        # Row 1: "DC in next foundation chain" x3 -> 3 DC posts, 0 chain
        # spaces (foundation_formula repeat_multiple=1 matches exactly).
        # Row 2: "ch 1 (turn), DC in next dc" x3 -- one later-row DC per
        # row-1 DC, so all 3 literal DC posts are used with none left
        # over and none demanded that don't exist.
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=1)

        self.assertTrue(result["row_1"]["valid"])
        self.assertTrue(result["valid"])
        self.assertIsNone(result["first_failing_row"])
        row2 = result["later_rows"][0]
        self.assertEqual(row2["row_number"], 2)
        self.assertTrue(row2["valid"])
        self.assertEqual(row2["repeat_execution_count"], 3)
        self.assertEqual(row2["output_structure"]["stitch_posts"], {"DC": 3})
        self.assertEqual(row2["output_structure"]["chain_spaces"], 1)  # the turning chain's own edge space


# ---------------------------------------------------------------------------
# 2: a valid three-row chain, each row fed the previous row's ACTUAL output
# ---------------------------------------------------------------------------

class ValidThreeRowChainTests(unittest.TestCase):
    def test_three_rows_of_dc_next_dc_each_use_the_actual_previous_output(self):
        # Row 1: 3 DC (as above). Row 2: turning chain (1 edge chain
        # space, no counts_as) + "DC in next dc" x3, consuming exactly
        # row 1's 3 literal DC -> row 2 outputs {DC:3, chain_spaces:1}.
        # Row 3 receives THAT exact structure (not row 1's, and not a
        # guessed number) and does the same thing again: its "DC in next
        # dc" x3 must consume row 2's 3 DC (leaving row 2's 1 chain space
        # untouched, which is fine -- see IMPORTANT PRINCIPLE test below).
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=2)

        self.assertTrue(result["valid"])
        self.assertIsNone(result["first_failing_row"])
        row2, row3 = result["later_rows"]
        self.assertEqual(row2["output_structure"], {"stitch_posts": {"DC": 3}, "chain_spaces": 1, "total_workable_positions": 4})
        # Row 3's INPUT must be row 2's actual output, not row 1's again.
        self.assertEqual(row3["input_structure"], row2["output_structure"])
        self.assertEqual(row3["repeat_execution_count"], 3)
        self.assertTrue(row3["valid"])


# ---------------------------------------------------------------------------
# 3: row 2 requesting more stitch posts than row 1 produced (overdraw)
# ---------------------------------------------------------------------------

class RequestsMoreStitchPostsThanAvailableTests(unittest.TestCase):
    def test_setup_wants_5_dc_but_only_2_are_available(self):
        # Row 1: "DC 2 in next foundation chain" x1 (repeat_multiple=2
        # matches: consumes 2, matches foundation_count=2*1+0) -> 2 DC.
        # Row 2's setup asks for 5 DC via next_dc, but only 2 exist --
        # a plain, unambiguous overdraw (real DC posts, just not enough).
        r = recipe([{"stitch": "DC", "count": 2, "placement": "next_foundation_chain"}],
                   [{"stitch": "DC", "count": 5, "placement": "next_dc"}],
                   DC_NEXT_DC, repeat_multiple=2)
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)

        self.assertFalse(result["valid"])
        self.assertEqual(result["first_failing_row"], 2)
        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "stitch_posts", "code": "DC", "needed": 5, "available": 2})


# ---------------------------------------------------------------------------
# 4: row 2 requesting a chain space when none exists (overdraw)
# ---------------------------------------------------------------------------

class RequestsChainSpaceWhenNoneExistTests(unittest.TestCase):
    def test_setup_wants_a_chain_space_but_row_1_made_none(self):
        # Row 1: pure DC repeat -- 0 chain spaces produced at all. Row
        # 2's setup asks for a chain space via next_chain_space: none
        # exist, plain overdraw (not "unused," genuinely absent).
        r = recipe(DC_NEXT_FOUNDATION,
                   [{"stitch": "SC", "count": 1, "placement": "next_chain_space"}],
                   DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)

        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "chain_spaces", "code": None, "needed": 1, "available": 0})


# ---------------------------------------------------------------------------
# 5: next_dc refusing an SC, HDC, or chain space
# ---------------------------------------------------------------------------

class NextDcRefusesWrongTypesTests(unittest.TestCase):
    def test_next_dc_does_not_accept_sc_posts(self):
        # Row 1 produces SC only (no DC anywhere). Row 2's setup asks
        # for a DC via next_dc: 0 DC exist, even though SC posts do --
        # SC must never be silently treated as DC.
        r = recipe([{"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}],
                   DC_NEXT_DC, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "stitch_posts", "code": "DC", "needed": 1, "available": 0})

    def test_next_dc_does_not_accept_hdc_posts(self):
        # Same idea with HDC instead of SC.
        r = recipe([{"stitch": "HDC", "count": 1, "placement": "next_foundation_chain"}],
                   DC_NEXT_DC, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"]["code"], "DC")
        self.assertEqual(row2["attempted_overdraw"]["available"], 0)

    def test_next_dc_does_not_accept_a_chain_space(self):
        # Row 1 produces chain spaces only (SKIP + CH working_loop each
        # repeat: SKIP consumes the foundation position but places
        # nothing, CH produces a floating chain space) -- 0 stitch posts
        # of any kind. Row 2's setup asks for a DC via next_dc: the
        # chain space must not be treated as a DC.
        r = recipe([{"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"},
                    {"stitch": "CH", "count": 1, "placement": "working_loop"}],
                   DC_NEXT_DC, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "stitch_posts", "code": "DC", "needed": 1, "available": 0})


# ---------------------------------------------------------------------------
# 6: next_stitch not silently consuming a chain space
# ---------------------------------------------------------------------------

class NextStitchRefusesChainSpaceTests(unittest.TestCase):
    def test_next_stitch_does_not_draw_from_chain_spaces(self):
        # Row 1 (as above) produces chain spaces only, 0 stitch posts of
        # any type. Row 2's setup asks for a generic stitch post via
        # next_stitch: must fail, not silently grab a chain space.
        r = recipe([{"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"},
                    {"stitch": "CH", "count": 1, "placement": "working_loop"}],
                   [{"stitch": "SC", "count": 1, "placement": "next_stitch"}],
                   DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "stitch_posts", "code": None, "needed": 1, "available": 0})


# ---------------------------------------------------------------------------
# 7/8: next_chain_space, and a same_stitch cluster worked into it
# ---------------------------------------------------------------------------

class ChainSpaceClusterTests(unittest.TestCase):
    def test_next_chain_space_targets_an_actual_chain_space_and_same_stitch_clusters_into_it(self):
        # Row 1: "SC in next foundation chain, ch 1" x2 -> 2 SC posts, 2
        # chain spaces (foundation_formula repeat_multiple=1 matches:
        # SC consumes 1, CH consumes 0 -> 1 per repeat).
        # Row 2's repeat: "1 SC in next chain space, 2 more SC in the
        # SAME chain space" (a 3-SC shell) -- one next_chain_space step
        # establishes the target, then same_stitch reuses it twice more
        # WITHOUT drawing a second chain space. Each pass therefore
        # consumes exactly 1 chain space and produces 3 SC.
        r = recipe([{"stitch": "SC", "count": 1, "placement": "next_foundation_chain"},
                    {"stitch": "CH", "count": 1, "placement": "working_loop"}],
                   PLAIN_TURNING_CHAIN,
                   [{"stitch": "SC", "count": 1, "placement": "next_chain_space"},
                    {"stitch": "SC", "count": 2, "placement": "same_stitch"}],
                   repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)

        self.assertTrue(result["valid"])
        row2 = result["later_rows"][0]
        # 2 chain spaces available -> exactly 2 passes, 1 chain space each.
        self.assertEqual(row2["repeat_execution_count"], 2)
        self.assertEqual(row2["repeat_result"]["consumed"], {"stitch_posts": {}, "chain_spaces": 2})
        # 3 SC per pass x2 passes = 6 SC produced by the repeat alone.
        self.assertEqual(row2["repeat_result"]["produced_structure"]["stitch_posts"], {"SC": 6})
        # Row 1's ordered_output (production order) is [SC, CH, SC, CH].
        # Flat crochet turns at the end of the row, so row 2's cursor
        # actually walks the REVERSE of that: [CH, SC, CH, SC].
        # next_chain_space searches FORWARD from the cursor: pass 1 finds
        # the chain space immediately (index 0). Pass 2 must pass over
        # the SC at index 1 to reach the chain space at index 2 -- that
        # SC is now behind the cursor and gone. The cursor ends at index
        # 3, one position short of the end, so the trailing SC (index 3)
        # is the only thing that remains -- not the 2 SC posts an
        # unordered pool model would have (wrongly) reported as
        # untouched leftover, and not the SAME leftover an un-turned
        # (bug) implementation would have computed either.
        self.assertEqual(row2["ordered_input"][0]["kind"], "chain_space")
        self.assertEqual(
            row2["remaining_unused_input_targets"],
            {"stitch_posts": {"SC": 1}, "chain_spaces": 0, "total_workable_positions": 1},
        )


# ---------------------------------------------------------------------------
# Order matters: identical aggregate totals, different physical order,
# different traversal results. This is the whole reason ordered_output +
# a cursor replaced the earlier unordered stitch_posts/chain_spaces pool.
# ---------------------------------------------------------------------------

class OrderMattersTests(unittest.TestCase):
    def test_dc_ch_sc_vs_sc_ch_dc_same_totals_different_results(self):
        # Both row 1 repeats produce the exact same aggregate structure --
        # {"DC": 1, "SC": 1} stitch posts + 1 chain space -- but in
        # opposite PRODUCTION order. Row 2's repeat is just "1 DC in next
        # dc," and row 2's cursor walks the TURNED (reversed) form of
        # each row 1's output:
        #   recipe A produces [DC, CH, SC]  -> row 2 walks [SC, CH, DC]
        #   recipe B produces [SC, CH, DC]  -> row 2 walks [DC, CH, SC]
        # Recipe A's DC ends up LAST in traversal order, so reaching it
        # means passing over (and permanently losing) the SC and the
        # chain space first -- row 2 ends with NOTHING left. Recipe B's
        # DC ends up FIRST in traversal order, found immediately, so the
        # chain space and SC survive behind it. Same row-1 totals,
        # opposite row-2 outcomes -- an unordered pool model, or a model
        # that forgot to turn between rows, could not distinguish these.
        dc_first = [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
                    {"stitch": "CH", "count": 1, "placement": "working_loop"},
                    {"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}]
        sc_first = [{"stitch": "SC", "count": 1, "placement": "next_foundation_chain"},
                    {"stitch": "CH", "count": 1, "placement": "working_loop"},
                    {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}]

        recipe_a = recipe(dc_first, [], DC_NEXT_DC, repeat_multiple=2)
        recipe_b = recipe(sc_first, [], DC_NEXT_DC, repeat_multiple=2)

        result_a = validate_recipe_rows(recipe_a, requested_repeat_count=1, later_row_count=1)
        result_b = validate_recipe_rows(recipe_b, requested_repeat_count=1, later_row_count=1)

        # Both row 1s have identical aggregate totals -- the premise of
        # the test (same totals, only order differs).
        self.assertEqual(
            result_a["row_1"]["row_1"]["produced_structure"],
            result_b["row_1"]["row_1"]["produced_structure"],
        )
        self.assertNotEqual(
            result_a["row_1"]["row_1"]["ordered_output"],
            result_b["row_1"]["row_1"]["ordered_output"],
        )

        row2_a = result_a["later_rows"][0]
        row2_b = result_b["later_rows"][0]
        # Row 2's ordered_input is the TURNED (reversed) form of row 1's
        # ordered_output, not the same order.
        self.assertEqual(row2_a["ordered_input"][0]["stitch"], "SC")
        self.assertEqual(row2_b["ordered_input"][0]["stitch"], "DC")

        self.assertTrue(row2_a["valid"])
        self.assertTrue(row2_b["valid"])
        # Recipe A: DC is last in traversal order -> reaching it passes
        # over (and loses) the SC and the chain space.
        self.assertEqual(row2_a["remaining_unused_input_targets"]["stitch_posts"], {})
        self.assertEqual(row2_a["remaining_unused_input_targets"]["chain_spaces"], 0)
        # Recipe B: DC is first in traversal order -> the SC and the
        # chain space survive behind it.
        self.assertEqual(row2_b["remaining_unused_input_targets"]["stitch_posts"], {"SC": 1})
        self.assertEqual(row2_b["remaining_unused_input_targets"]["chain_spaces"], 1)


# ---------------------------------------------------------------------------
# next_dc moves past intervening SC posts and chain spaces to reach the
# next literal DC -- it never stops early just because something else
# is in the way, and whatever it passes is gone afterward.
# ---------------------------------------------------------------------------

class NextDcMovesPastInterveningPositionsTests(unittest.TestCase):
    def test_next_dc_passes_over_an_sc_and_a_chain_space_to_reach_the_dc(self):
        # Row 1's ordered_output (production order) is [DC, chain_space,
        # SC]. After turning at the end of the row, row 2's cursor
        # actually walks the REVERSE: [SC, chain_space, DC]. Row 2's
        # next_dc must walk past the SC and the chain space (neither
        # eligible) to reach the DC two positions later, and both must
        # be gone afterward -- not available to any later step.
        r = recipe(
            [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "CH", "count": 1, "placement": "working_loop"},
             {"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}],
            [], DC_NEXT_DC, repeat_multiple=2,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(
            [e["kind"] for e in row2["ordered_input"]],
            ["stitch_post", "chain_space", "stitch_post"],
        )
        self.assertEqual(row2["ordered_input"][0]["stitch"], "SC")
        self.assertEqual(row2["ordered_input"][2]["stitch"], "DC")
        self.assertTrue(row2["valid"])
        self.assertEqual(row2["repeat_execution_count"], 1)
        self.assertEqual(row2["repeat_result"]["consumed"], {"stitch_posts": {"DC": 1}, "chain_spaces": 0})
        self.assertEqual(
            row2["remaining_unused_input_targets"],
            {"stitch_posts": {}, "chain_spaces": 0, "total_workable_positions": 0},
        )


# ---------------------------------------------------------------------------
# A later instruction cannot move the cursor backward to re-target a
# position an earlier instruction already passed.
# ---------------------------------------------------------------------------

class CannotMoveBackwardTests(unittest.TestCase):
    def test_next_dc_cannot_retarget_a_dc_next_stitch_already_consumed(self):
        # Row 1's ordered_output (production order) is [SC, DC]; after
        # turning, row 2's cursor walks the reverse: [DC, SC]. Row 2's
        # repeat first does "SC in next stitch" (generic -- takes
        # whatever is positionally first, the DC, moving the cursor past
        # it), THEN "DC in next dc." The DC existed in row 1's aggregate
        # totals, but the cursor already moved past it -- next_dc cannot
        # go back for it, so this must fail, not succeed by "finding"
        # the same DC twice.
        r = recipe(
            [{"stitch": "SC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
            [],
            [{"stitch": "SC", "count": 1, "placement": "next_stitch"},
             {"stitch": "DC", "count": 1, "placement": "next_dc"}],
            repeat_multiple=2,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(row2["ordered_input"][0]["stitch"], "DC")
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "stitch_posts", "code": "DC", "needed": 1, "available": 0})


# ---------------------------------------------------------------------------
# next_chain_space respects order: whether it succeeds depends on WHERE
# the chain space sits relative to what a later step in the same pass
# also needs -- not just whether one exists somewhere in the row.
# ---------------------------------------------------------------------------

class NextChainSpaceRespectsOrderTests(unittest.TestCase):
    def test_chain_space_after_the_dc_in_traversal_order_forces_the_dc_to_be_lost(self):
        # Row 1's ordered_output (production order) is [chain_space, DC]
        # -- but flat crochet turns at the end of the row, so row 2's
        # cursor actually walks the REVERSE: [DC, chain_space]. Row 2's
        # repeat asks for "SC in next chain space" FIRST, then "DC in
        # next dc." Reaching the chain space (which is now AFTER the DC
        # in traversal order) means passing over -- and losing -- the DC
        # first, so the later next_dc step has nothing left. This must
        # fail even though a literal DC obviously exists in row 1.
        r = recipe(
            [{"stitch": "CH", "count": 1, "placement": "working_loop"},
             {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
            [],
            [{"stitch": "SC", "count": 1, "placement": "next_chain_space"},
             {"stitch": "DC", "count": 1, "placement": "next_dc"}],
            repeat_multiple=1,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(row2["ordered_input"][0]["stitch"], "DC")
        self.assertFalse(row2["valid"])
        self.assertEqual(row2["attempted_overdraw"], {"pool": "stitch_posts", "code": "DC", "needed": 1, "available": 0})

    def test_chain_space_before_the_dc_in_traversal_order_lets_both_succeed(self):
        # Row 1's production order is reversed from the case above --
        # [DC, chain_space] -- so after turning, row 2's cursor walks
        # [chain_space, DC]: next_chain_space finds its target
        # immediately, and next_dc finds its own DC right after -- both
        # succeed, proving the earlier failure was about TRAVERSAL
        # ORDER (post-turn), not about missing content.
        r = recipe(
            [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "CH", "count": 1, "placement": "working_loop"}],
            [],
            [{"stitch": "SC", "count": 1, "placement": "next_chain_space"},
             {"stitch": "DC", "count": 1, "placement": "next_dc"}],
            repeat_multiple=1,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(row2["ordered_input"][0]["kind"], "chain_space")
        self.assertTrue(row2["valid"])
        self.assertEqual(row2["repeat_execution_count"], 1)


# ---------------------------------------------------------------------------
# next_stitch picks the POSITIONALLY next stitch post, never the
# alphabetically-first one -- the bug this whole redesign fixes.
# ---------------------------------------------------------------------------

class NextStitchNeverSelectsAlphabeticallyTests(unittest.TestCase):
    def test_next_stitch_takes_the_positionally_first_post_not_dc(self):
        # Row 1's ordered_output (production order) is [DC, SC]; after
        # turning, row 2's cursor actually walks [SC, DC] -- SC comes
        # first in TRAVERSAL order, even though "DC" sorts before "SC"
        # alphabetically. A single next_stitch step must consume the SC
        # (position 0 of the turned input), never the DC, no matter what
        # string-sorting a bygone implementation might have preferred.
        r = recipe(
            [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}],
            [],
            [{"stitch": "HDC", "count": 1, "placement": "next_stitch"}],
            repeat_multiple=2,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(row2["ordered_input"][0]["stitch"], "SC")
        # The FIRST pass's own consumption is what proves the point --
        # the overall repeat_execution_count may go on to consume the
        # DC too on a second pass (next_stitch is generic and the DC is
        # also an eligible target), which is correct and unrelated to
        # this test's claim.
        self.assertEqual(row2["repeat_once_consumed"], {"stitch_posts": {"SC": 1}, "chain_spaces": 0})


# ---------------------------------------------------------------------------
# same_stitch reuses the current target without moving the cursor --
# proven by the NEXT step still being able to reach a position that
# would otherwise have been passed over.
# ---------------------------------------------------------------------------

class SameStitchDoesNotMoveCursorTests(unittest.TestCase):
    def test_same_stitch_leaves_the_second_dc_reachable_by_the_next_pass(self):
        # Row 1 produces 2 DC posts (no chain spaces). Each repeat pass
        # is "DC in next dc, then 3 more SC in the SAME stitch." If
        # same_stitch secretly advanced the cursor, the second pass
        # would find nothing left after just one DC; since it doesn't,
        # BOTH DC posts get their own pass, each with 3 extra SC.
        r = recipe(
            [{"stitch": "DC", "count": 2, "placement": "next_foundation_chain"}],
            [],
            [{"stitch": "DC", "count": 1, "placement": "next_dc"},
             {"stitch": "SC", "count": 3, "placement": "same_stitch"}],
            repeat_multiple=2,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertTrue(row2["valid"])
        self.assertEqual(row2["repeat_execution_count"], 2)
        self.assertEqual(row2["repeat_result"]["produced_structure"]["stitch_posts"], {"DC": 2, "SC": 6})
        self.assertEqual(
            row2["remaining_unused_input_targets"],
            {"stitch_posts": {}, "chain_spaces": 0, "total_workable_positions": 0},
        )


# ---------------------------------------------------------------------------
# Ordered output is passed correctly row 1 -> row 2 -> row 3, and the
# aggregate reports built from it remain internally consistent.
# ---------------------------------------------------------------------------

class OrderedOutputThreadingTests(unittest.TestCase):
    def test_ordered_output_is_reversed_turning_the_row_before_becoming_the_next_rows_input(self):
        # Flat crochet turns at the end of every row: the next row's
        # cursor walks the previous row's production in REVERSE, not
        # unchanged. Row 1 here produces 3 DC (all identical, but this
        # still proves the relationship holds structurally at every
        # hand-off): row 2's ordered_input must be the reverse of row
        # 1's ordered_output, and row 3's ordered_input must be the
        # reverse of row 2's own ordered_output -- never the same order,
        # and never row 1's output reused a second time for row 3.
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=2)
        row2, row3 = result["later_rows"]

        row1_ordered_output = result["row_1"]["row_1"]["ordered_output"]
        self.assertEqual(row2["ordered_input"], list(reversed(row1_ordered_output)))
        self.assertEqual(row3["ordered_input"], list(reversed(row2["ordered_output"])))
        # Each row's OWN ordered_output stays in that row's own
        # production order in its report -- never reversed in place.
        self.assertNotEqual(row2["ordered_output"], row2["ordered_input"])

    def test_row_1_output_dc_chain_space_sc_becomes_row_2_input_sc_chain_space_dc(self):
        # The exact example from this correction: row 1 produces
        # [DC, chain_space, SC] in that order; row 2 must receive
        # [SC, chain_space, DC] -- the reverse, not the same order.
        r = recipe(
            [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "CH", "count": 1, "placement": "working_loop"},
             {"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}],
            [], [{"stitch": "SC", "count": 1, "placement": "next_stitch"}],
            repeat_multiple=2,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        row1_ordered = result["row_1"]["row_1"]["ordered_output"]
        row2 = result["later_rows"][0]

        self.assertEqual(
            [e["kind"] if e["kind"] == "chain_space" else e["stitch"] for e in row1_ordered],
            ["DC", "chain_space", "SC"],
        )
        self.assertEqual(
            [e["kind"] if e["kind"] == "chain_space" else e["stitch"] for e in row2["ordered_input"]],
            ["SC", "chain_space", "DC"],
        )
        # And a next_stitch in row 2 must select the SC (positionally
        # first in the turned input), never the DC.
        self.assertEqual(row2["repeat_once_consumed"], {"stitch_posts": {"SC": 1}, "chain_spaces": 0})

    def test_aggregate_produced_structure_is_a_correct_summary_of_ordered_output(self):
        r = recipe(
            [{"stitch": "SC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "CH", "count": 1, "placement": "working_loop"}],
            PLAIN_TURNING_CHAIN,
            [{"stitch": "SC", "count": 1, "placement": "next_chain_space"},
             {"stitch": "SC", "count": 2, "placement": "same_stitch"}],
            repeat_multiple=1,
        )
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        row2 = result["later_rows"][0]
        ordered = row2["ordered_output"]
        manual_stitch_posts = {}
        manual_chain_spaces = 0
        for entry in ordered:
            if entry["kind"] == "chain_space":
                manual_chain_spaces += 1
            else:
                manual_stitch_posts[entry["stitch"]] = manual_stitch_posts.get(entry["stitch"], 0) + 1
        self.assertEqual(row2["output_structure"]["stitch_posts"], manual_stitch_posts)
        self.assertEqual(row2["output_structure"]["chain_spaces"], manual_chain_spaces)
        self.assertEqual(
            row2["output_structure"]["total_workable_positions"],
            len(ordered),
        )


# ---------------------------------------------------------------------------
# 9: working_loop preserving the most recent target (in a later row)
# ---------------------------------------------------------------------------

class WorkingLoopPreservesTargetInLaterRowTests(unittest.TestCase):
    def test_dc_next_dc_then_ch_working_loop_then_dc_same_stitch(self):
        # Row 1: 2 DC (repeat_multiple=1, requested_repeat_count=2).
        # Row 2's repeat: "DC in next dc, ch 1, DC in same stitch" --
        # the CH working_loop in between must NOT clear the target the
        # first DC established, so the final DC validly refers back to
        # the SAME DC post the first one targeted (this row's own code
        # path, independent of Phase 4A's row-1 fix for the same rule).
        r = recipe(DC_NEXT_FOUNDATION,
                   PLAIN_TURNING_CHAIN,
                   [{"stitch": "DC", "count": 1, "placement": "next_dc"},
                    {"stitch": "CH", "count": 1, "placement": "working_loop"},
                    {"stitch": "DC", "count": 1, "placement": "same_stitch"}],
                   repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)

        self.assertTrue(result["valid"])
        row2 = result["later_rows"][0]
        # Each pass consumes exactly 1 DC (the same_stitch consumes none
        # additional) -> 2 DC available means exactly 2 passes.
        self.assertEqual(row2["repeat_execution_count"], 2)
        self.assertEqual(row2["repeat_result"]["consumed"], {"stitch_posts": {"DC": 2}, "chain_spaces": 0})
        # Each pass produces 2 DC posts + 1 chain space -> x2 passes.
        self.assertEqual(row2["repeat_result"]["produced_structure"]["stitch_posts"], {"DC": 4})
        self.assertEqual(row2["repeat_result"]["produced_structure"]["chain_spaces"], 2)


# ---------------------------------------------------------------------------
# 10: same_stitch without a target failing clearly
# ---------------------------------------------------------------------------

class SameStitchWithoutTargetTests(unittest.TestCase):
    def test_same_stitch_as_first_repeat_step_with_no_target_raises(self):
        # Row 2's setup is a plain turning chain with NO counts_as, so it
        # establishes no target at all. The repeat's first step is
        # same_stitch, which therefore has nothing to refer back to.
        r = recipe([{"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}],
                   PLAIN_TURNING_CHAIN,
                   [{"stitch": "SC", "count": 1, "placement": "same_stitch"}],
                   repeat_multiple=1)
        with self.assertRaises(RecipeMathError):
            validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)

    def test_skip_with_same_stitch_remains_invalid(self):
        # Even with a target established by the first step, SKIP with
        # same_stitch must still raise -- skipping doesn't work into a
        # stitch, so "the same stitch as a skip" has no referent.
        r = recipe(DC_NEXT_FOUNDATION,
                   PLAIN_TURNING_CHAIN,
                   [{"stitch": "DC", "count": 1, "placement": "next_dc"},
                    {"stitch": "SKIP", "count": 1, "placement": "same_stitch"}],
                   repeat_multiple=1)
        with self.assertRaises(RecipeMathError):
            validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)


# ---------------------------------------------------------------------------
# 11/12: turning_chain with and without counts_as
# ---------------------------------------------------------------------------

class TurningChainProductionTests(unittest.TestCase):
    def test_turning_chain_with_no_counts_as_produces_only_a_chain_space(self):
        # A bare "ch 1" turning chain (no counts_as) contributes exactly
        # 1 chain space and NO stitch-post credit -- and does not
        # establish a target (nothing here is "a stitch" same_stitch
        # could mean).
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(row2["setup_result"]["produced_structure"], {"stitch_posts": {}, "chain_spaces": 1, "total_workable_positions": 1})
        self.assertEqual(row2["setup_result"]["counts_as_stitch_posts"], {})

    def test_turning_chain_with_counts_as_replaces_raw_production(self):
        # "ch 4 (counts as 1 DC + 1 chain space)" must be credited with
        # EXACTLY {"DC": 1, "chain_spaces": 1} -- not the raw CH
        # production of 4 chain spaces on top. Section 5's rule is that
        # counts_as changes what this step is credited with producing,
        # not adds to it.
        r = recipe(DC_NEXT_FOUNDATION,
                   [{"stitch": "CH", "count": 4, "placement": "turning_chain",
                     "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 1}}],
                   DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        row2 = result["later_rows"][0]
        self.assertEqual(
            row2["setup_result"]["produced_structure"],
            {"stitch_posts": {"DC": 1}, "chain_spaces": 1, "total_workable_positions": 2},
        )
        self.assertEqual(row2["setup_result"]["counts_as_stitch_posts"], {"DC": 1})


# ---------------------------------------------------------------------------
# 13: a row 2 failure stopping row 3
# ---------------------------------------------------------------------------

class Row2FailureStopsRow3Tests(unittest.TestCase):
    def test_row_3_is_never_evaluated_once_row_2_fails(self):
        # Row 2's setup demands 5 DC but row 1 only made 2 -- a clean
        # overdraw. later_row_count=2 asks for rows 2 AND 3, but
        # processing must stop at row 2's failure: later_rows must have
        # exactly one entry (row 2), and row 3 must never appear.
        r = recipe([{"stitch": "DC", "count": 2, "placement": "next_foundation_chain"}],
                   [{"stitch": "DC", "count": 5, "placement": "next_dc"}],
                   DC_NEXT_DC, repeat_multiple=2)
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=2)

        self.assertFalse(result["valid"])
        self.assertEqual(result["first_failing_row"], 2)
        self.assertEqual(len(result["later_rows"]), 1)
        self.assertEqual(result["later_rows"][0]["row_number"], 2)

    def test_row_1_failure_prevents_any_later_row_from_being_evaluated(self):
        # A row 1 that doesn't account for its own foundation (setup
        # consumes 1, but the formula provides 2) is invalid at the
        # Phase 4A layer -- no later row should ever be attempted.
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC,
                   repeat_multiple=1, additional_chains=1)
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=2)

        self.assertFalse(result["row_1"]["valid"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["first_failing_row"], 1)
        self.assertEqual(result["later_rows"], [])


# ---------------------------------------------------------------------------
# Ambiguous repeat count: later_rows.repeat that never touches the pool
# ---------------------------------------------------------------------------

class AmbiguousRepeatCountTests(unittest.TestCase):
    def test_repeat_of_only_working_loop_cannot_derive_a_count(self):
        # later_rows.repeat is just "ch 1" (working_loop) -- it never
        # draws a single stitch post or chain space from the previous
        # row, so nothing in the recipe constrains how many times it
        # could run. This must be reported as undecidable, not guessed
        # (e.g. defaulting to requested_repeat_count).
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN,
                   [{"stitch": "CH", "count": 1, "placement": "working_loop"}],
                   repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=1)

        self.assertFalse(result["valid"])
        row2 = result["later_rows"][0]
        self.assertFalse(row2["valid"])
        self.assertFalse(row2["repeat_count_derivable"])
        self.assertIsNone(row2["repeat_execution_count"])
        self.assertTrue(len(row2["errors"]) >= 1)


# ---------------------------------------------------------------------------
# next_dc refusing to guess whether a counts_as-derived DC is eligible
# (docs/recipe_model_v2.md section 11, open question 4)
# ---------------------------------------------------------------------------

class NextDcCountsAsAmbiguityTests(unittest.TestCase):
    def test_next_dc_raises_rather_than_consuming_a_counts_as_derived_dc(self):
        # Row 1: 2 DC. Row 2's turning chain counts as 1 DC + 1 chain
        # space; its repeat consumes exactly row 1's 2 literal DC via
        # next_dc, leaving row 2's OWN output as {DC: 3 (2 literal +
        # 1 counts_as), chain_spaces: 1}. Row 3 receives that pool and
        # tries to consume ALL 3 DC via next_dc -- the first 2 passes
        # are unambiguous (literal DC), but the 3rd would have to target
        # the DC that exists only because of row 2's counts_as credit.
        # This module refuses to guess whether that's legal (open
        # question 4) and must raise, not silently allow or forbid it.
        turning_chain_counts_as_dc = [
            {"stitch": "CH", "count": 4, "placement": "turning_chain",
             "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 1}}
        ]
        r = recipe(DC_NEXT_FOUNDATION, turning_chain_counts_as_dc, DC_NEXT_DC, repeat_multiple=1)
        with self.assertRaises(RecipeMathError) as ctx:
            validate_recipe_rows(r, requested_repeat_count=2, later_row_count=2)
        self.assertIn("counts_as", str(ctx.exception))
        self.assertIn("question 4", str(ctx.exception))

    def test_next_dc_succeeds_when_literal_dc_alone_is_sufficient(self):
        # Same setup, but row 3's repeat only asks for 2 DC (matching
        # row 2's 2 LITERAL DC exactly) -- never touching the 1
        # counts_as-derived DC, so no ambiguity arises and this must
        # succeed normally.
        turning_chain_counts_as_dc = [
            {"stitch": "CH", "count": 4, "placement": "turning_chain",
             "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 1}}
        ]
        r = recipe(DC_NEXT_FOUNDATION, turning_chain_counts_as_dc, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)
        self.assertTrue(result["valid"])
        row2 = result["later_rows"][0]
        self.assertEqual(row2["repeat_execution_count"], 2)
        self.assertEqual(row2["output_counts_as_stitch_posts"], {"DC": 1})


# ---------------------------------------------------------------------------
# 14: input recipes and reports are not mutated
# ---------------------------------------------------------------------------

class NoMutationTests(unittest.TestCase):
    def test_recipe_is_not_mutated(self):
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        before = copy.deepcopy(r)
        validate_recipe_rows(r, requested_repeat_count=3, later_row_count=2)
        self.assertEqual(r, before)

    def test_verification_status_is_not_changed_by_a_passing_result(self):
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=2)
        self.assertTrue(result["valid"])
        self.assertEqual(r["verification"]["status"], "AI_PROPOSED")

    def test_verification_status_is_not_changed_by_a_failing_result(self):
        r = recipe([{"stitch": "DC", "count": 2, "placement": "next_foundation_chain"}],
                   [{"stitch": "DC", "count": 5, "placement": "next_dc"}],
                   DC_NEXT_DC, repeat_multiple=2)
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)
        self.assertFalse(result["valid"])
        self.assertEqual(r["verification"]["status"], "AI_PROPOSED")

    def test_repeated_calls_are_deterministic_and_do_not_share_mutable_state(self):
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        first = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=2)
        second = validate_recipe_rows(r, requested_repeat_count=3, later_row_count=2)
        self.assertEqual(first, second)

    def test_turning_a_rows_output_does_not_mutate_the_stored_report(self):
        # Uses a mixed-type row (DC, chain space, SC) rather than an
        # all-DC one -- an in-place reversal bug would be invisible on a
        # symmetric list but immediately visible here.
        r = recipe(
            [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
             {"stitch": "CH", "count": 1, "placement": "working_loop"},
             {"stitch": "SC", "count": 1, "placement": "next_foundation_chain"}],
            [], [{"stitch": "SC", "count": 1, "placement": "next_stitch"}],
            repeat_multiple=2,
        )
        result = validate_recipe_rows(r, requested_repeat_count=1, later_row_count=1)

        row1_ordered_before = copy.deepcopy(result["row_1"]["row_1"]["ordered_output"])
        row2_ordered_output_before = copy.deepcopy(result["later_rows"][0]["ordered_output"])
        row2_ordered_input_before = copy.deepcopy(result["later_rows"][0]["ordered_input"])

        # Building row 2's turned input (and, had there been a row 3,
        # its turned input from row 2's output) must never reverse
        # row 1's or row 2's stored lists in place.
        self.assertEqual(result["row_1"]["row_1"]["ordered_output"], row1_ordered_before)
        self.assertEqual(result["later_rows"][0]["ordered_output"], row2_ordered_output_before)
        self.assertEqual(result["later_rows"][0]["ordered_input"], row2_ordered_input_before)
        # And row 2's own ordered_output (production order) must still
        # differ from its ordered_input (the turned form it received).
        self.assertNotEqual(
            result["later_rows"][0]["ordered_output"],
            result["later_rows"][0]["ordered_input"],
        )


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------

class MalformedInputTests(unittest.TestCase):
    def test_invalid_later_row_count_raises(self):
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        for bad in (-1, None, "2", 2.0, True, False):
            with self.subTest(bad=bad):
                with self.assertRaises(RecipeMathError):
                    validate_recipe_rows(r, requested_repeat_count=2, later_row_count=bad)

    def test_zero_later_row_count_only_checks_row_1(self):
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_recipe_rows(r, requested_repeat_count=2, later_row_count=0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["later_rows"], [])
        self.assertIsNone(result["first_failing_row"])

    def test_invalid_requested_repeat_count_raises(self):
        # Delegated to validate_row_1_against_foundation() -- confirms
        # that delegation actually happens rather than being bypassed.
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        with self.assertRaises(RecipeMathError):
            validate_recipe_rows(r, requested_repeat_count=0, later_row_count=1)

    def test_schema_invalid_recipe_raises(self):
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        del r["pattern_id"]
        with self.assertRaises(RecipeMathError):
            validate_recipe_rows(r, requested_repeat_count=2, later_row_count=1)


# ---------------------------------------------------------------------------
# 15: existing Phase 1-4 behavior remains correct (lightweight spot checks;
# the full suite run is the authoritative check -- see VERIFICATION section)
# ---------------------------------------------------------------------------

class RegressionSpotChecksTests(unittest.TestCase):
    def test_phase_4a_row_1_validator_still_works_standalone(self):
        from engine.recipe_validator import validate_row_1_against_foundation
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        result = validate_row_1_against_foundation(r, 3)
        self.assertTrue(result["valid"])

    def test_calculate_foundation_still_works(self):
        from engine.foundation import calculate_foundation
        r = recipe(DC_NEXT_FOUNDATION, PLAIN_TURNING_CHAIN, DC_NEXT_DC, repeat_multiple=1)
        self.assertEqual(calculate_foundation(r, 3)["foundation_count"], 3)

    def test_validate_recipe_v2_still_accepts_the_structural_and_known_bad_examples(self):
        import json
        from engine.schema import validate_recipe_v2
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("stitch_recipe_v2_structural_example.json", "stitch_recipe_v2_known_bad_ai_example.json"):
            with open(os.path.join(repo_root, "contracts", "examples", name)) as f:
                self.assertEqual(validate_recipe_v2(json.load(f)), [])


if __name__ == "__main__":
    unittest.main()
