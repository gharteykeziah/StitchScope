"""
Tests for engine/schema.py's validate_recipe_v2() -- the Phase 2 plain-
Python validator for the recipe-model-v2 shape designed in
docs/recipe_model_v2.md, and for contracts/stitch_recipe_schema_v2.json
(the language-agnostic reference; not read by any code here, but its
enums/required fields are cross-checked against the Python constants
below so the two can't silently drift apart).

This is a completely separate validation path from v1's validate_recipe()
and v3's validate_proposal() -- both are re-exercised here too (a subset
of their own test files' coverage) purely to confirm this Phase 2
addition didn't change their behavior; the authoritative tests for those
remain tests/test_golden_examples.py and tests/test_stitch_recipe.py.
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.schema import (
    LATER_REPEAT_PLACEMENTS,
    LATER_SETUP_PLACEMENTS,
    ROW1_PLACEMENTS,
    V2_KNOWN_STITCHES,
    V2_PLACEMENTS,
    V2_VERIFICATION_STATUSES,
    validate_proposal,
    validate_recipe,
    validate_recipe_v2,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRUCTURAL_EXAMPLE_PATH = os.path.join(REPO_ROOT, "contracts", "examples", "stitch_recipe_v2_structural_example.json")
KNOWN_BAD_EXAMPLE_PATH = os.path.join(REPO_ROOT, "contracts", "examples", "stitch_recipe_v2_known_bad_ai_example.json")
SCHEMA_V2_PATH = os.path.join(REPO_ROOT, "contracts", "stitch_recipe_schema_v2.json")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def minimal_valid_recipe():
    """A hand-built, minimal recipe that satisfies every v2 rule -- the
    base fixture negative tests mutate via copy.deepcopy."""
    return {
        "pattern_id": "test_pattern",
        "name": "Test Stitch",
        "aliases": [],
        "terminology": "US",
        "foundation_formula": {"repeat_multiple": 1, "additional_chains": 0},
        "row_1": {
            "setup": [],
            "repeat": [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}],
        },
        "later_rows": {
            "setup": [{"stitch": "CH", "count": 1, "placement": "turning_chain"}],
            "repeat": [{"stitch": "DC", "count": 1, "placement": "next_stitch"}],
        },
        "expected_swatch_structure": {
            "expected_stitch_posts_per_repeat": 1,
            "expected_chain_spaces_per_repeat": 0,
        },
        "verification": {"status": "AI_PROPOSED", "confirmations": []},
    }


def assert_has_error_containing(test_case, errors, substring):
    test_case.assertTrue(
        any(substring in e for e in errors),
        f"expected an error containing {substring!r}, got: {errors}",
    )


# ---------------------------------------------------------------------------
# 1/2: the two real example files
# ---------------------------------------------------------------------------

class ExampleFilesLoadAsValidJSONTests(unittest.TestCase):

    def test_structural_example_is_valid_json(self):
        load_json(STRUCTURAL_EXAMPLE_PATH)  # raises if not valid JSON

    def test_known_bad_example_is_valid_json(self):
        load_json(KNOWN_BAD_EXAMPLE_PATH)


class ExampleFilesPassStructuralValidationTests(unittest.TestCase):

    def test_structural_example_passes_validate_recipe_v2(self):
        recipe = load_json(STRUCTURAL_EXAMPLE_PATH)
        errors = validate_recipe_v2(recipe)
        self.assertEqual(errors, [], f"structural example should be schema-valid, got: {errors}")
        self.assertEqual(recipe["verification"]["status"], "AI_PROPOSED", "must remain unconfirmed")

    def test_known_bad_example_passes_structural_validation_despite_being_rejected(self):
        # The important distinction: REJECTED records that the crochet
        # construction was determined wrong -- schema validation must
        # not reject the recipe merely because it's semantically bad.
        recipe = load_json(KNOWN_BAD_EXAMPLE_PATH)
        errors = validate_recipe_v2(recipe)
        self.assertEqual(errors, [], f"known-bad example should still be schema-valid, got: {errors}")
        self.assertEqual(recipe["verification"]["status"], "REJECTED")
        self.assertTrue(recipe["verification"].get("reason"), "REJECTED must carry a non-empty reason")
        self.assertEqual(recipe["verification"]["confirmations"], [], "rejected via structural evidence, not a physical swatch")


# ---------------------------------------------------------------------------
# 3: non-dict input
# ---------------------------------------------------------------------------

class NonDictInputTests(unittest.TestCase):

    def test_non_dict_recipe_is_rejected(self):
        for bad in (None, "a string", 42, ["a", "list"]):
            with self.subTest(bad=bad):
                errors = validate_recipe_v2(bad)
                self.assertTrue(len(errors) > 0)


# ---------------------------------------------------------------------------
# 4/5/6: top-level required fields, empty pattern_id, invalid terminology
# ---------------------------------------------------------------------------

class TopLevelRequiredFieldsTests(unittest.TestCase):

    REQUIRED_FIELDS = (
        "pattern_id", "name", "aliases", "terminology",
        "foundation_formula", "row_1", "later_rows",
        "expected_swatch_structure", "verification",
    )

    def test_every_required_top_level_field_is_enforced(self):
        for field in self.REQUIRED_FIELDS:
            with self.subTest(field=field):
                recipe = minimal_valid_recipe()
                del recipe[field]
                errors = validate_recipe_v2(recipe)
                assert_has_error_containing(self, errors, f"missing required field '{field}'")

    def test_empty_pattern_id_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["pattern_id"] = ""
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.pattern_id")

    def test_invalid_terminology_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["terminology"] = "CA"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.terminology")

    def test_valid_terminology_values_are_accepted(self):
        for value in ("US", "UK"):
            recipe = minimal_valid_recipe()
            recipe["terminology"] = value
            self.assertEqual(validate_recipe_v2(recipe), [])


# ---------------------------------------------------------------------------
# 7/8/9: foundation_formula numeric rules, including booleans
# ---------------------------------------------------------------------------

class FoundationFormulaTests(unittest.TestCase):

    def test_repeat_multiple_zero_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["foundation_formula"]["repeat_multiple"] = 0
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.foundation_formula.repeat_multiple")

    def test_additional_chains_negative_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["foundation_formula"]["additional_chains"] = -1
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.foundation_formula.additional_chains")

    def test_boolean_repeat_multiple_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["foundation_formula"]["repeat_multiple"] = True
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.foundation_formula.repeat_multiple")

    def test_boolean_additional_chains_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["foundation_formula"]["additional_chains"] = False
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.foundation_formula.additional_chains")

    def test_additional_chains_zero_is_accepted(self):
        recipe = minimal_valid_recipe()
        recipe["foundation_formula"]["additional_chains"] = 0
        self.assertEqual(validate_recipe_v2(recipe), [])


# ---------------------------------------------------------------------------
# 10/11: empty repeat lists
# ---------------------------------------------------------------------------

class EmptyRepeatTests(unittest.TestCase):

    def test_empty_row_1_repeat_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"] = []
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat")

    def test_empty_later_rows_repeat_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["repeat"] = []
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.later_rows.repeat")

    def test_empty_row_1_setup_is_accepted(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["setup"] = []
        self.assertEqual(validate_recipe_v2(recipe), [])


# ---------------------------------------------------------------------------
# 12-16: step-level rules
# ---------------------------------------------------------------------------

class StepLevelTests(unittest.TestCase):

    def test_missing_stitch_is_rejected(self):
        recipe = minimal_valid_recipe()
        del recipe["row_1"]["repeat"][0]["stitch"]
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0]: missing required field 'stitch'")

    def test_unknown_stitch_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["stitch"] = "TRC"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0].stitch")

    def test_zero_step_count_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["count"] = 0
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0].count")

    def test_boolean_step_count_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["count"] = True
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0].count")

    def test_missing_placement_is_rejected(self):
        recipe = minimal_valid_recipe()
        del recipe["row_1"]["repeat"][0]["placement"]
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0]: missing required field 'placement'")

    def test_unknown_placement_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["placement"] = "next_galaxy"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0].placement")

    def test_non_dict_step_does_not_crash(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0] = "not a step"
        errors = validate_recipe_v2(recipe)  # must not raise
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0]")


# ---------------------------------------------------------------------------
# 17/18: placement context rules
# ---------------------------------------------------------------------------

class PlacementContextTests(unittest.TestCase):

    def test_row_1_next_chain_space_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["placement"] = "next_chain_space"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "not valid for row_1")

    def test_later_rows_setup_next_foundation_chain_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0] = {"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "not valid for later_rows.setup")

    def test_later_rows_repeat_next_foundation_chain_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["repeat"][0]["placement"] = "next_foundation_chain"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "not valid for later_rows.repeat")

    def test_later_rows_repeat_turning_chain_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["repeat"][0]["stitch"] = "CH"
        recipe["later_rows"]["repeat"][0]["placement"] = "turning_chain"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "not valid for later_rows.repeat")

    def test_all_row1_allowed_placements_accepted_for_non_ch(self):
        for placement in ("next_foundation_chain", "same_stitch"):
            recipe = minimal_valid_recipe()
            recipe["row_1"]["repeat"][0]["placement"] = placement
            self.assertEqual(validate_recipe_v2(recipe), [], f"placement {placement} should be valid on row_1")


# ---------------------------------------------------------------------------
# 19-24: stitch/placement compatibility and counts_as
# ---------------------------------------------------------------------------

class StitchPlacementCompatibilityTests(unittest.TestCase):

    def test_ch_with_incompatible_placement_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["repeat"][0] = {"stitch": "CH", "count": 1, "placement": "next_stitch"}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "stitch CH must use placement")

    def test_non_ch_with_working_loop_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["placement"] = "working_loop"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "must not use placement 'working_loop'")

    def test_non_ch_with_turning_chain_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["repeat"][0]["placement"] = "turning_chain"
        errors = validate_recipe_v2(recipe)
        # Rejected on two independent grounds: not a valid later_rows.repeat
        # placement, AND non-CH can't use turning_chain either way.
        assert_has_error_containing(self, errors, "not valid for later_rows.repeat")

    def test_counts_as_on_non_turning_chain_step_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0] = {
            "stitch": "CH", "count": 1, "placement": "working_loop",
            "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 0},
        }
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "counts_as: only allowed on a CH step whose placement is turning_chain")

    def test_invalid_counts_as_stitch_key_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {"TRC": 1}, "chain_spaces": 0}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "stitch_posts.TRC")

    def test_negative_counts_as_values_are_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {"DC": -1}, "chain_spaces": -2}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "stitch_posts.DC")
        assert_has_error_containing(self, errors, "chain_spaces")

    def test_boolean_counts_as_values_are_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {"DC": True}, "chain_spaces": 0}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "stitch_posts.DC")

    def test_all_zero_counts_as_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {"DC": 0}, "chain_spaces": 0}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "has no effect")

    def test_all_zero_counts_as_with_empty_stitch_posts_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {}, "chain_spaces": 0}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "has no effect")

    def test_non_zero_counts_as_is_accepted(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {"DC": 1}, "chain_spaces": 1}
        self.assertEqual(validate_recipe_v2(recipe), [])


# ---------------------------------------------------------------------------
# 25/26: expected_swatch_structure
# ---------------------------------------------------------------------------

class ExpectedSwatchStructureTests(unittest.TestCase):

    def test_null_expected_values_are_accepted(self):
        recipe = minimal_valid_recipe()
        recipe["expected_swatch_structure"]["expected_stitch_posts_per_repeat"] = None
        recipe["expected_swatch_structure"]["expected_chain_spaces_per_repeat"] = None
        self.assertEqual(validate_recipe_v2(recipe), [])

    def test_negative_expected_values_are_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["expected_swatch_structure"]["expected_stitch_posts_per_repeat"] = -1
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.expected_swatch_structure.expected_stitch_posts_per_repeat")

    def test_boolean_expected_value_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["expected_swatch_structure"]["expected_chain_spaces_per_repeat"] = True
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.expected_swatch_structure.expected_chain_spaces_per_repeat")


# ---------------------------------------------------------------------------
# 27/28/29: verification status/confirmation/reason consistency
# ---------------------------------------------------------------------------

class VerificationConsistencyTests(unittest.TestCase):

    def test_confirmed_with_no_confirmations_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["verification"] = {"status": "CONFIRMED", "confirmations": []}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "CONFIRMED requires at least one confirmation")

    def test_swatch_tested_with_no_confirmations_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["verification"] = {"status": "SWATCH_TESTED", "confirmations": []}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "SWATCH_TESTED requires at least one confirmation")

    def test_rejected_without_reason_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["verification"] = {"status": "REJECTED", "confirmations": []}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "REJECTED requires a non-empty 'reason'")

    def test_confirmed_with_one_confirmation_is_accepted(self):
        recipe = minimal_valid_recipe()
        recipe["verification"] = {
            "status": "CONFIRMED",
            "confirmations": [{"photo": "a.jpg", "date": "2026-09-06", "note": "matched exactly"}],
        }
        self.assertEqual(validate_recipe_v2(recipe), [])

    def test_rejected_with_reason_is_accepted(self):
        recipe = minimal_valid_recipe()
        recipe["verification"] = {"status": "REJECTED", "confirmations": [], "reason": "does not match target construction"}
        self.assertEqual(validate_recipe_v2(recipe), [])

    def test_confirmation_record_precise_path(self):
        recipe = minimal_valid_recipe()
        recipe["verification"] = {
            "status": "CONFIRMED",
            "confirmations": [{"photo": "a.jpg", "date": "", "note": "x"}],
        }
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.verification.confirmations[0].date")


# ---------------------------------------------------------------------------
# 30: multiple errors collected with precise paths
# ---------------------------------------------------------------------------

class MultipleErrorsTests(unittest.TestCase):

    def test_multiple_independent_errors_are_all_collected(self):
        recipe = minimal_valid_recipe()
        recipe["pattern_id"] = ""
        recipe["foundation_formula"]["repeat_multiple"] = 0
        recipe["row_1"]["repeat"][1:] = []  # still non-empty (1 item), skip
        recipe["row_1"]["repeat"][0]["placement"] = "next_chain_space"
        recipe["later_rows"]["repeat"] = []
        recipe["verification"] = {"status": "REJECTED", "confirmations": []}

        errors = validate_recipe_v2(recipe)

        assert_has_error_containing(self, errors, "recipe.pattern_id")
        assert_has_error_containing(self, errors, "recipe.foundation_formula.repeat_multiple")
        assert_has_error_containing(self, errors, "not valid for row_1")
        assert_has_error_containing(self, errors, "recipe.later_rows.repeat: must be a non-empty list")
        assert_has_error_containing(self, errors, "REJECTED requires a non-empty 'reason'")
        self.assertGreaterEqual(len(errors), 5)

    def test_precise_path_examples_from_the_spec(self):
        # The exact path shapes called out in the task description.
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"].append({"stitch": "DC", "count": 1, "placement": "bogus"})
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[1].placement")


# ---------------------------------------------------------------------------
# 31: unexpected properties rejected at multiple object levels
# ---------------------------------------------------------------------------

class UnexpectedPropertiesTests(unittest.TestCase):

    def test_unexpected_top_level_property_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["mystery_field"] = "surprise"
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe: unexpected property 'mystery_field'")

    def test_unexpected_step_property_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["row_1"]["repeat"][0]["extra"] = 1
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.row_1.repeat[0]: unexpected property 'extra'")

    def test_unexpected_counts_as_property_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["later_rows"]["setup"][0]["counts_as"] = {"stitch_posts": {"DC": 1}, "chain_spaces": 1, "extra": True}
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "unexpected property 'extra'")

    def test_unexpected_verification_property_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["verification"]["extra"] = 1
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.verification: unexpected property 'extra'")

    def test_unexpected_foundation_formula_property_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["foundation_formula"]["extra"] = 1
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.foundation_formula: unexpected property 'extra'")

    def test_notes_and_known_issues_are_permitted_at_top_level(self):
        recipe = minimal_valid_recipe()
        recipe["notes"] = "some documentation"
        recipe["known_issues"] = ["something to watch"]
        self.assertEqual(validate_recipe_v2(recipe), [])

    def test_empty_notes_string_is_rejected(self):
        recipe = minimal_valid_recipe()
        recipe["notes"] = ""
        errors = validate_recipe_v2(recipe)
        assert_has_error_containing(self, errors, "recipe.notes")


# ---------------------------------------------------------------------------
# 32/33: existing v1 recipe / v3 proposal validation still work
# ---------------------------------------------------------------------------

class ExistingValidatorsUnaffectedTests(unittest.TestCase):

    def test_v1_validate_recipe_still_accepts_a_valid_v1_shape(self):
        v1_recipe = {
            "setup": [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}],
            "repeat": [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}],
            "turning_chain": [{"stitch": "CH", "count": 3}],
        }
        self.assertEqual(validate_recipe(v1_recipe), [])

    def test_v1_validate_recipe_still_rejects_missing_repeat(self):
        v1_recipe = {"setup": [], "turning_chain": []}
        errors = validate_recipe(v1_recipe)
        self.assertTrue(len(errors) > 0)

    def test_v3_validate_proposal_still_accepts_a_valid_identification(self):
        proposal = {
            "regions": [
                {"region_label": "center panel", "stitch_family": "filet mesh", "confidence": 0.8, "uncertain_fields": []}
            ]
        }
        self.assertEqual(validate_proposal(proposal), [])

    def test_v3_validate_proposal_still_rejects_missing_regions(self):
        errors = validate_proposal({"photo_id": "x.jpg"})
        self.assertTrue(len(errors) > 0)


# ---------------------------------------------------------------------------
# JSON contract <-> Python validator consistency (no jsonschema dependency --
# just comparing the plain data both sides already load/define)
# ---------------------------------------------------------------------------

class SchemaContractConsistencyTests(unittest.TestCase):
    """
    Manually cross-checks contracts/stitch_recipe_schema_v2.json's enums
    and required-field lists against engine/schema.py's constants, so the
    two can't silently drift apart. No JSON Schema library involved --
    this just reads the same plain dict structure both a human and
    validate_recipe_v2() would.
    """

    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(SCHEMA_V2_PATH)

    def test_top_level_required_fields_match(self):
        self.assertEqual(
            set(self.schema["required"]),
            set(TopLevelRequiredFieldsTests.REQUIRED_FIELDS),
        )

    def test_stitch_enum_matches(self):
        schema_stitches = set(self.schema["definitions"]["stitch_code"]["enum"])
        self.assertEqual(schema_stitches, set(V2_KNOWN_STITCHES))

    def test_full_placement_enum_matches(self):
        row1_enum = set(self.schema["definitions"]["row1_step"]["properties"]["placement"]["enum"])
        later_setup_enum = set(self.schema["definitions"]["later_setup_step"]["properties"]["placement"]["enum"])
        later_repeat_enum = set(self.schema["definitions"]["later_repeat_step"]["properties"]["placement"]["enum"])

        self.assertEqual(row1_enum, set(ROW1_PLACEMENTS))
        self.assertEqual(later_setup_enum, set(LATER_SETUP_PLACEMENTS))
        self.assertEqual(later_repeat_enum, set(LATER_REPEAT_PLACEMENTS))
        self.assertEqual(row1_enum | later_setup_enum | later_repeat_enum, set(V2_PLACEMENTS))

    def test_verification_status_enum_matches(self):
        schema_statuses = set(self.schema["definitions"]["verification"]["properties"]["status"]["enum"])
        self.assertEqual(schema_statuses, set(V2_VERIFICATION_STATUSES))

    def test_schema_version_matches_python_constant(self):
        from engine.schema import RECIPE_V2_SCHEMA_VERSION
        self.assertEqual(self.schema["schemaVersion"], RECIPE_V2_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
