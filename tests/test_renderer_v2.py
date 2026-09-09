"""
Tests for engine/renderer_v2.py -- Phase 7's v2 swatch-plan renderer.

render_swatch_plan() accepts only an already-built structured plan (see
engine/swatch_planner_v2.py's _build_swatch_plan()); these tests build
small hand-checked plan dicts directly, matching the project's existing
convention of small, self-contained fixtures per module.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.renderer_v2 import _render_step, render_swatch_plan

US_TERMS = {
    "CH": "chain", "SC": "single crochet", "HDC": "half double crochet",
    "DC": "double crochet", "SLST": "slip stitch", "SKIP": "skip",
    "INC": "increase", "DEC": "decrease",
}


def minimal_plan(terminology="US", row_1_setup=None, row_1_repeat=None,
                  later_row_setup=None, later_row_repeat=None, later_rows=None,
                  warnings=None):
    if later_rows is None:
        later_rows = [{"row_number": 2, "repeat_execution_count": 3, "valid": True}]
    return {
        "ready_for_rendering": True,
        "pattern_id": "test_pattern",
        "name": "Test Stitch",
        "terminology": terminology,
        "trust": {"verification_status": "CONFIRMED", "provenance": "library"},
        "requested_repeat_count": 3,
        "total_rows": 1 + len(later_rows),
        "foundation_chain_count": 3,
        "foundation_formula": {"repeat_multiple": 1, "requested_repeat_count": 3,
                                "repeated_chains": 3, "additional_chains": 0, "foundation_count": 3},
        "row_1_setup": row_1_setup if row_1_setup is not None else [],
        "row_1_repeat": row_1_repeat if row_1_repeat is not None else
            [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
        "row_1_repeat_execution_count": 3,
        "later_row_setup": later_row_setup if later_row_setup is not None else
            [{"stitch": "CH", "count": 1, "placement": "turning_chain"}],
        "later_row_repeat": later_row_repeat if later_row_repeat is not None else
            [{"stitch": "DC", "count": 1, "placement": "next_dc"}],
        "later_rows": later_rows,
        "validation_evidence": {"row_1_valid": True, "row_1_consumed_foundation_positions": 3,
                                 "later_rows_valid": True, "overall_valid": True},
        "warnings": warnings if warnings is not None else [],
    }


# ---------------------------------------------------------------------------
# Stitch terminology mapping
# ---------------------------------------------------------------------------

class StitchTerminologyTests(unittest.TestCase):
    def test_ch_working_loop_renders_as_chain_n(self):
        step = {"stitch": "CH", "count": 3, "placement": "working_loop"}
        self.assertEqual(_render_step(step, US_TERMS), "chain 3")

    def test_dc_1_renders_singular(self):
        step = {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}
        self.assertEqual(_render_step(step, US_TERMS), "make 1 double crochet in the next foundation chain")

    def test_dc_3_renders_plural(self):
        step = {"stitch": "DC", "count": 3, "placement": "next_foundation_chain"}
        self.assertEqual(_render_step(step, US_TERMS), "make 3 double crochets in the next 3 foundation chains")

    def test_sc_hdc_slst_map_correctly(self):
        for code, name in (("SC", "single crochet"), ("HDC", "half double crochet"), ("SLST", "slip stitch")):
            step = {"stitch": code, "count": 1, "placement": "next_stitch"}
            self.assertEqual(_render_step(step, US_TERMS), f"make 1 {name} in the next stitch")

    def test_skip_renders_without_make_verb(self):
        step = {"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"}
        self.assertEqual(_render_step(step, US_TERMS), "skip the next foundation chain")

    def test_increase_and_decrease_word_correctly(self):
        inc = {"stitch": "INC", "count": 1, "placement": "next_stitch"}
        dec = {"stitch": "DEC", "count": 1, "placement": "next_stitch"}
        self.assertEqual(_render_step(inc, US_TERMS), "make 1 increase in the next stitch")
        self.assertEqual(_render_step(dec, US_TERMS), "make 1 decrease in the next 2 stitches")


# ---------------------------------------------------------------------------
# Placement language
# ---------------------------------------------------------------------------

class PlacementLanguageTests(unittest.TestCase):
    def test_next_foundation_chain(self):
        step = {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}
        self.assertIn("in the next foundation chain", _render_step(step, US_TERMS))

    def test_same_stitch_uses_generic_phrase_always(self):
        # Neither Phase 4A's nor Phase 5's report tracks the KIND of the
        # most recently established target -- only whether one exists --
        # so this must always be the generic phrase, never a guess at
        # "stitch" vs "chain space".
        step = {"stitch": "SC", "count": 2, "placement": "same_stitch"}
        self.assertEqual(_render_step(step, US_TERMS), "make 2 single crochets in the same stitch or space")

    def test_next_stitch(self):
        step = {"stitch": "SC", "count": 1, "placement": "next_stitch"}
        self.assertEqual(_render_step(step, US_TERMS), "make 1 single crochet in the next stitch")

    def test_next_dc(self):
        step = {"stitch": "DC", "count": 1, "placement": "next_dc"}
        self.assertEqual(_render_step(step, US_TERMS), "make 1 double crochet in the next double crochet")

    def test_next_chain_space(self):
        step = {"stitch": "SC", "count": 3, "placement": "next_chain_space"}
        self.assertEqual(_render_step(step, US_TERMS), "make 3 single crochets in the next 3 chain spaces")

    def test_turning_chain_without_counts_as(self):
        step = {"stitch": "CH", "count": 1, "placement": "turning_chain"}
        self.assertEqual(_render_step(step, US_TERMS), "turn and chain 1")

    def test_turning_chain_with_counts_as_appends_a_plain_language_note(self):
        step = {"stitch": "CH", "count": 4, "placement": "turning_chain",
                "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 1}}
        rendered = _render_step(step, US_TERMS)
        self.assertTrue(rendered.startswith("turn and chain 4"))
        self.assertIn("counts as 1 double crochet", rendered)
        self.assertIn("forms 1 chain space", rendered)

    def test_no_internal_implementation_terms_leak_into_rendered_text(self):
        steps = [
            {"stitch": "DC", "count": 1, "placement": "next_dc"},
            {"stitch": "SC", "count": 1, "placement": "same_stitch"},
            {"stitch": "CH", "count": 4, "placement": "turning_chain",
             "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 1}},
        ]
        forbidden = ["target_established", "ordered_output", "cursor", "produced_structure", "counts_as pool"]
        for step in steps:
            rendered = _render_step(step, US_TERMS)
            for term in forbidden:
                self.assertNotIn(term, rendered)


# ---------------------------------------------------------------------------
# DEC/INC pluralization uses consumed positions, not raw count
# ---------------------------------------------------------------------------

class PluralizationTests(unittest.TestCase):
    def test_dec_pluralizes_by_positions_consumed_not_step_count(self):
        # DEC consumes 2 stitches per unit -- DEC count=2 spans 4 stitches.
        step = {"stitch": "DEC", "count": 2, "placement": "next_stitch"}
        self.assertEqual(_render_step(step, US_TERMS), "make 2 decreases in the next 4 stitches")


# ---------------------------------------------------------------------------
# Terminology support
# ---------------------------------------------------------------------------

class TerminologySupportTests(unittest.TestCase):
    def test_unsupported_terminology_returns_safe_result_not_a_guess(self):
        plan = minimal_plan(terminology="UK")
        result = render_swatch_plan(plan)
        self.assertEqual(result["status"], "unsupported_terminology")
        self.assertIsNone(result["text"])
        self.assertTrue(len(result["errors"]) > 0)

    def test_us_terminology_renders_successfully(self):
        plan = minimal_plan(terminology="US")
        result = render_swatch_plan(plan)
        self.assertEqual(result["status"], "rendered")
        self.assertIsInstance(result["text"], str)


# ---------------------------------------------------------------------------
# Full plan rendering
# ---------------------------------------------------------------------------

class RenderSwatchPlanTests(unittest.TestCase):
    def test_full_plan_renders_foundation_row_1_and_later_rows(self):
        plan = minimal_plan()
        result = render_swatch_plan(plan)
        text = result["text"]
        self.assertIn("Foundation: Chain 3.", text)
        self.assertIn("Row 1:", text)
        self.assertIn("Row 2:", text)
        self.assertIn("Then repeat 3 times:", text)

    def test_warnings_are_included_as_notes(self):
        plan = minimal_plan(warnings=["This is a test warning."])
        result = render_swatch_plan(plan)
        self.assertIn("Notes:", result["text"])
        self.assertIn("This is a test warning.", result["text"])

    def test_multiple_later_rows_each_use_their_own_derived_repeat_count(self):
        plan = minimal_plan(later_rows=[
            {"row_number": 2, "repeat_execution_count": 3, "valid": True},
            {"row_number": 3, "repeat_execution_count": 2, "valid": True},
        ])
        result = render_swatch_plan(plan)
        self.assertIn("Row 2: ", result["text"])
        self.assertIn("Row 3: ", result["text"])
        self.assertIn("Then repeat 2 times:", result["text"])

    def test_does_not_mutate_the_plan(self):
        plan = minimal_plan()
        import copy
        before = copy.deepcopy(plan)
        render_swatch_plan(plan)
        self.assertEqual(plan, before)


# ---------------------------------------------------------------------------
# Plan validation: render_swatch_plan() must validate its own argument
# before reading any field from it, and must never raise for a
# malformed plan -- always a structured {"status": "invalid_plan", ...}
# result instead.
# ---------------------------------------------------------------------------

class InvalidPlanTests(unittest.TestCase):
    def _assert_invalid_plan(self, plan):
        result = render_swatch_plan(plan)
        self.assertEqual(result["status"], "invalid_plan")
        self.assertIsNone(result["text"])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(len(result["errors"]) > 0)
        return result

    def test_none_is_rejected_without_raising(self):
        self._assert_invalid_plan(None)

    def test_empty_list_is_rejected_without_raising(self):
        self._assert_invalid_plan([])

    def test_empty_dict_is_rejected_without_raising(self):
        result = self._assert_invalid_plan({})
        self.assertTrue(any("ready_for_rendering" in e for e in result["errors"]))

    def test_dict_with_only_terminology_is_rejected_not_treated_as_unsupported(self):
        # This plan HAS a recognized terminology value, but it is still
        # missing ready_for_rendering and every other required field --
        # it must be reported as invalid_plan, not unsupported_terminology.
        result = self._assert_invalid_plan({"terminology": "US"})
        self.assertTrue(any("ready_for_rendering" in e for e in result["errors"]))

    def test_non_dict_plan_types_are_all_rejected(self):
        for bad in (42, "a string", 3.14, True, (1, 2)):
            with self.subTest(bad=bad):
                self._assert_invalid_plan(bad)

    def test_missing_ready_for_rendering_is_rejected(self):
        plan = minimal_plan()
        del plan["ready_for_rendering"]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("ready_for_rendering" in e and "missing" in e for e in result["errors"]))

    def test_ready_for_rendering_false_is_rejected(self):
        plan = minimal_plan()
        plan["ready_for_rendering"] = False
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("ready_for_rendering" in e for e in result["errors"]))

    def test_ready_for_rendering_truthy_but_not_true_is_rejected(self):
        # Exactly True is required -- 1 is truthy but not the same
        # object/value this module treats as an authorized plan.
        plan = minimal_plan()
        plan["ready_for_rendering"] = 1
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("ready_for_rendering" in e for e in result["errors"]))

    def test_missing_required_field_is_rejected(self):
        for field in ("pattern_id", "name", "terminology", "trust", "requested_repeat_count",
                      "total_rows", "foundation_chain_count", "foundation_formula",
                      "row_1_setup", "row_1_repeat", "row_1_repeat_execution_count",
                      "later_row_setup", "later_row_repeat", "later_rows",
                      "validation_evidence", "warnings"):
            with self.subTest(field=field):
                plan = minimal_plan()
                del plan[field]
                result = self._assert_invalid_plan(plan)
                self.assertTrue(any(field in e and "missing" in e for e in result["errors"]))

    def test_malformed_trust_non_dict_is_rejected(self):
        plan = minimal_plan()
        plan["trust"] = "library"
        self._assert_invalid_plan(plan)

    def test_malformed_trust_missing_provenance_is_rejected(self):
        plan = minimal_plan()
        plan["trust"] = {"verification_status": "CONFIRMED"}
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("trust.provenance" in e for e in result["errors"]))

    def test_malformed_foundation_count_non_integer_is_rejected(self):
        plan = minimal_plan()
        plan["foundation_chain_count"] = "eighteen"
        self._assert_invalid_plan(plan)

    def test_malformed_foundation_count_negative_is_rejected(self):
        plan = minimal_plan()
        plan["foundation_chain_count"] = -1
        self._assert_invalid_plan(plan)

    def test_malformed_foundation_formula_non_dict_is_rejected(self):
        plan = minimal_plan()
        plan["foundation_formula"] = "not a dict"
        self._assert_invalid_plan(plan)

    def test_malformed_step_list_non_list_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat"] = "not a list"
        self._assert_invalid_plan(plan)

    def test_malformed_step_non_dict_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat"] = ["not a step"]
        self._assert_invalid_plan(plan)

    def test_malformed_step_missing_count_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat"] = [{"stitch": "DC", "placement": "next_foundation_chain"}]
        self._assert_invalid_plan(plan)

    def test_malformed_step_zero_count_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat"] = [{"stitch": "DC", "count": 0, "placement": "next_foundation_chain"}]
        self._assert_invalid_plan(plan)

    def test_unknown_stitch_code_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat"] = [{"stitch": "TRC", "count": 1, "placement": "next_foundation_chain"}]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("unknown stitch code" in e for e in result["errors"]))

    def test_unknown_placement_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat"] = [{"stitch": "DC", "count": 1, "placement": "somewhere_else"}]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("unknown placement" in e for e in result["errors"]))

    def test_unknown_stitch_in_later_row_repeat_is_rejected(self):
        plan = minimal_plan()
        plan["later_row_repeat"] = [{"stitch": "NOPE", "count": 1, "placement": "next_dc"}]
        self._assert_invalid_plan(plan)

    def test_malformed_later_row_summary_non_dict_is_rejected(self):
        plan = minimal_plan()
        plan["later_rows"] = ["not a summary"]
        self._assert_invalid_plan(plan)

    def test_malformed_later_row_summary_missing_row_number_is_rejected(self):
        plan = minimal_plan()
        plan["later_rows"] = [{"repeat_execution_count": 3, "valid": True}]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("row_number" in e for e in result["errors"]))

    def test_malformed_later_row_summary_invalid_repeat_count_is_rejected(self):
        plan = minimal_plan()
        plan["later_rows"] = [{"row_number": 2, "repeat_execution_count": -1, "valid": True}]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("repeat_execution_count" in e for e in result["errors"]))

    def test_invalid_requested_repeat_count_is_rejected(self):
        plan = minimal_plan()
        plan["requested_repeat_count"] = 0
        self._assert_invalid_plan(plan)

    def test_invalid_row_1_repeat_execution_count_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat_execution_count"] = -5
        self._assert_invalid_plan(plan)

    def test_all_problems_are_reported_together_not_just_the_first(self):
        plan = {"terminology": 42, "row_1_repeat": "not a list"}
        result = render_swatch_plan(plan)
        self.assertEqual(result["status"], "invalid_plan")
        self.assertTrue(any("ready_for_rendering" in e for e in result["errors"]))
        self.assertTrue(any("terminology" in e for e in result["errors"]))
        self.assertTrue(any("row_1_repeat" in e for e in result["errors"]))

    def test_valid_ready_plan_with_unsupported_terminology_is_not_invalid_plan(self):
        # A structurally valid, ready_for_rendering=True plan whose
        # terminology just isn't implemented must still be reported as
        # "unsupported_terminology," never "invalid_plan" -- the plan
        # itself is fine; only the terminology isn't supported.
        plan = minimal_plan(terminology="UK")
        result = render_swatch_plan(plan)
        self.assertEqual(result["status"], "unsupported_terminology")
        self.assertIsNone(result["text"])


# ---------------------------------------------------------------------------
# Internal readiness contract: ready_for_rendering=True alone is NOT
# enough. trust.provenance must be exactly "library", trust
# .verification_status must be exactly "CONFIRMED", validation_evidence's
# three fields and every later-row's "valid" must each be exactly True,
# and the plan's own fields must agree with each other (total_rows,
# repeat counts, row numbering, foundation count). A forged or
# inconsistent plan must never reach rendered text.
# ---------------------------------------------------------------------------

class ForgedOrInconsistentPlanTests(unittest.TestCase):
    def _assert_invalid_plan(self, plan):
        result = render_swatch_plan(plan)
        self.assertEqual(result["status"], "invalid_plan")
        self.assertIsNone(result["text"])
        self.assertTrue(len(result["errors"]) > 0)
        return result

    def test_provenance_ai_is_rejected(self):
        plan = minimal_plan()
        plan["trust"]["provenance"] = "ai"
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("provenance" in e for e in result["errors"]))

    def test_provenance_arbitrary_string_is_rejected(self):
        plan = minimal_plan()
        plan["trust"]["provenance"] = "some_other_source"
        self._assert_invalid_plan(plan)

    def test_verification_status_ai_proposed_is_rejected(self):
        plan = minimal_plan()
        plan["trust"]["verification_status"] = "AI_PROPOSED"
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("verification_status" in e for e in result["errors"]))

    def test_missing_verification_status_is_rejected(self):
        plan = minimal_plan()
        del plan["trust"]["verification_status"]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("verification_status" in e for e in result["errors"]))

    def test_overall_valid_false_is_rejected(self):
        plan = minimal_plan()
        plan["validation_evidence"]["overall_valid"] = False
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("overall_valid" in e for e in result["errors"]))

    def test_overall_valid_truthy_non_bool_is_rejected(self):
        # 1 is truthy but must not be accepted as a substitute for the
        # literal bool True.
        plan = minimal_plan()
        plan["validation_evidence"]["overall_valid"] = 1
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("overall_valid" in e for e in result["errors"]))

    def test_missing_validation_evidence_fields_are_rejected(self):
        for field in ("row_1_valid", "later_rows_valid", "overall_valid"):
            with self.subTest(field=field):
                plan = minimal_plan()
                del plan["validation_evidence"][field]
                result = self._assert_invalid_plan(plan)
                self.assertTrue(any(field in e for e in result["errors"]))

    def test_empty_validation_evidence_is_rejected(self):
        plan = minimal_plan()
        plan["validation_evidence"] = {}
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("row_1_valid" in e for e in result["errors"]))
        self.assertTrue(any("later_rows_valid" in e for e in result["errors"]))
        self.assertTrue(any("overall_valid" in e for e in result["errors"]))

    def test_later_row_with_valid_false_is_rejected(self):
        plan = minimal_plan(later_rows=[{"row_number": 2, "repeat_execution_count": 3, "valid": False}])
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("later_rows[0].valid" in e for e in result["errors"]))

    def test_inconsistent_total_rows_is_rejected(self):
        plan = minimal_plan()
        plan["total_rows"] = 99
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("total_rows" in e for e in result["errors"]))

    def test_nonconsecutive_later_row_numbers_are_rejected(self):
        plan = minimal_plan(later_rows=[
            {"row_number": 2, "repeat_execution_count": 3, "valid": True},
            {"row_number": 4, "repeat_execution_count": 3, "valid": True},
        ])
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("row_number" in e and "consecutive" in e for e in result["errors"]))

    def test_foundation_count_mismatch_is_rejected(self):
        plan = minimal_plan()
        plan["foundation_formula"]["foundation_count"] = 999
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("foundation_chain_count" in e for e in result["errors"]))

    def test_non_string_warning_is_rejected(self):
        plan = minimal_plan()
        plan["warnings"] = [123]
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("warnings[0]" in e for e in result["errors"]))

    def test_row_1_repeat_execution_count_mismatch_is_rejected(self):
        plan = minimal_plan()
        plan["row_1_repeat_execution_count"] = 999
        result = self._assert_invalid_plan(plan)
        self.assertTrue(any("row_1_repeat_execution_count" in e for e in result["errors"]))

    def test_forged_minimal_readiness_claim_is_rejected(self):
        # Exactly the forged shape from the correction request: claims
        # ready_for_rendering True, but with provenance "ai" and an
        # empty validation_evidence -- must be rejected on BOTH grounds,
        # never rendered.
        forged = {
            "ready_for_rendering": True,
            "trust": {"provenance": "ai"},
            "validation_evidence": {},
        }
        result = self._assert_invalid_plan(forged)
        self.assertTrue(any("provenance" in e for e in result["errors"]))
        self.assertTrue(any("row_1_valid" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
