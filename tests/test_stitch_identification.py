"""
Tests for engine/stitch_identification.py -- Phase 8's small, validated
IDENTIFICATION contract (region_label/stitch_name/aliases/confidence/
uncertainty) and the adapter from engine/vision.py's proposal-region
shape (region_label/stitch_family/confidence/uncertain_fields) into it.

No test here contacts the real API or reads/writes any file -- every
identification is a small, hand-built in-memory dict.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.stitch_identification import (
    identification_from_vision_region,
    validate_identification,
)


def make_identification(region_label="cuff", stitch_name="filet mesh", aliases=None,
                         confidence=0.82, uncertainty=None):
    identification = {
        "region_label": region_label,
        "stitch_name": stitch_name,
        "aliases": aliases if aliases is not None else [],
        "confidence": confidence,
    }
    if uncertainty is not None:
        identification["uncertainty"] = uncertainty
    return identification


class ValidIdentificationTests(unittest.TestCase):
    def test_well_formed_identification_has_no_errors(self):
        self.assertEqual(validate_identification(make_identification()), [])

    def test_uncertainty_may_be_a_non_empty_string(self):
        identification = make_identification(uncertainty="unsure whether this is filet mesh or open mesh")
        self.assertEqual(validate_identification(identification), [])

    def test_uncertainty_may_be_explicitly_null(self):
        identification = make_identification()
        identification["uncertainty"] = None
        self.assertEqual(validate_identification(identification), [])

    def test_uncertainty_may_be_omitted_entirely(self):
        identification = make_identification()  # no "uncertainty" key at all
        self.assertNotIn("uncertainty", identification)
        self.assertEqual(validate_identification(identification), [])

    def test_aliases_may_be_a_nonempty_list_of_strings(self):
        identification = make_identification(aliases=["open filet mesh", "filet net"])
        self.assertEqual(validate_identification(identification), [])

    def test_aliases_may_be_empty_list(self):
        identification = make_identification(aliases=[])
        self.assertEqual(validate_identification(identification), [])

    def test_confidence_boundary_values_zero_and_one_are_valid(self):
        for value in (0, 0.0, 1, 1.0):
            with self.subTest(value=value):
                identification = make_identification(confidence=value)
                self.assertEqual(validate_identification(identification), [])


class ShapeTests(unittest.TestCase):
    def test_non_dict_identification_is_rejected(self):
        for bad in (None, "filet mesh", 42, [], ["region_label"]):
            with self.subTest(bad=bad):
                errors = validate_identification(bad)
                self.assertTrue(errors)

    def test_unexpected_field_is_rejected(self):
        identification = make_identification()
        identification["row_1"] = {"setup": [], "repeat": []}  # a smuggled instruction field
        errors = validate_identification(identification)
        self.assertTrue(any("row_1" in e for e in errors))

    def test_multiple_unexpected_fields_are_all_reported(self):
        identification = make_identification()
        identification["setup"] = []
        identification["repeat"] = []
        errors = validate_identification(identification)
        self.assertTrue(any("setup" in e for e in errors))
        self.assertTrue(any("repeat" in e for e in errors))


class RequiredFieldTests(unittest.TestCase):
    def test_missing_region_label_is_rejected(self):
        identification = make_identification()
        del identification["region_label"]
        errors = validate_identification(identification)
        self.assertTrue(any("region_label" in e for e in errors))

    def test_missing_stitch_name_is_rejected(self):
        identification = make_identification()
        del identification["stitch_name"]
        errors = validate_identification(identification)
        self.assertTrue(any("stitch_name" in e for e in errors))

    def test_missing_confidence_is_rejected(self):
        identification = make_identification()
        del identification["confidence"]
        errors = validate_identification(identification)
        self.assertTrue(any("confidence" in e for e in errors))

    def test_empty_string_region_label_is_rejected(self):
        identification = make_identification(region_label="   ")
        errors = validate_identification(identification)
        self.assertTrue(any("region_label" in e for e in errors))

    def test_empty_string_stitch_name_is_rejected(self):
        identification = make_identification(stitch_name="")
        errors = validate_identification(identification)
        self.assertTrue(any("stitch_name" in e for e in errors))

    def test_non_string_region_label_is_rejected(self):
        identification = make_identification()
        identification["region_label"] = 5
        errors = validate_identification(identification)
        self.assertTrue(any("region_label" in e for e in errors))

    def test_non_string_stitch_name_is_rejected(self):
        identification = make_identification()
        identification["stitch_name"] = ["filet mesh"]
        errors = validate_identification(identification)
        self.assertTrue(any("stitch_name" in e for e in errors))


class AliasesTests(unittest.TestCase):
    def test_aliases_must_be_a_list(self):
        identification = make_identification(aliases="open filet mesh")
        errors = validate_identification(identification)
        self.assertTrue(any("aliases" in e for e in errors))

    def test_aliases_list_with_non_string_entry_is_rejected(self):
        identification = make_identification(aliases=["ok", 5])
        errors = validate_identification(identification)
        self.assertTrue(any("aliases" in e for e in errors))

    def test_aliases_list_with_empty_string_entry_is_rejected(self):
        identification = make_identification(aliases=["ok", ""])
        errors = validate_identification(identification)
        self.assertTrue(any("aliases" in e for e in errors))


class ConfidenceTests(unittest.TestCase):
    def test_confidence_out_of_range_is_rejected(self):
        for bad in (-0.01, 1.01, -5, 5):
            with self.subTest(bad=bad):
                identification = make_identification(confidence=bad)
                errors = validate_identification(identification)
                self.assertTrue(any("confidence" in e for e in errors))

    def test_confidence_as_string_is_rejected(self):
        identification = make_identification(confidence="0.9")
        errors = validate_identification(identification)
        self.assertTrue(any("confidence" in e for e in errors))

    def test_confidence_bool_is_rejected_even_though_bool_is_an_int_subclass(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                identification = make_identification(confidence=bad)
                errors = validate_identification(identification)
                self.assertTrue(any("confidence" in e for e in errors))


class UncertaintyTests(unittest.TestCase):
    def test_uncertainty_empty_string_is_rejected(self):
        identification = make_identification()
        identification["uncertainty"] = "   "
        errors = validate_identification(identification)
        self.assertTrue(any("uncertainty" in e for e in errors))

    def test_uncertainty_non_string_non_null_is_rejected(self):
        identification = make_identification()
        identification["uncertainty"] = 5
        errors = validate_identification(identification)
        self.assertTrue(any("uncertainty" in e for e in errors))


class AdapterTests(unittest.TestCase):
    def test_adapts_a_confident_region_with_no_uncertain_fields(self):
        region = {
            "region_label": "cuff",
            "stitch_family": "filet mesh",
            "confidence": 0.82,
            "uncertain_fields": [],
        }
        identification = identification_from_vision_region(region)
        self.assertEqual(identification["region_label"], "cuff")
        self.assertEqual(identification["stitch_name"], "filet mesh")
        self.assertEqual(identification["aliases"], [])
        self.assertEqual(identification["confidence"], 0.82)
        self.assertIsNone(identification["uncertainty"])
        self.assertEqual(validate_identification(identification), [])

    def test_adapts_an_uncertain_region_into_a_readable_uncertainty_string(self):
        region = {
            "region_label": "body",
            "stitch_family": "single crochet",
            "confidence": 0.4,
            "uncertain_fields": ["stitch_family"],
        }
        identification = identification_from_vision_region(region)
        self.assertIn("stitch_family", identification["uncertainty"])
        self.assertEqual(validate_identification(identification), [])

    def test_adapter_output_always_validates(self):
        # A well-formed proposal-shape region should always adapt into a
        # validation-clean identification -- the adapter's whole job is
        # to produce something validate_identification() accepts.
        for region in (
            {"region_label": "hem", "stitch_family": "double crochet", "confidence": 1.0, "uncertain_fields": []},
            {"region_label": "yoke", "stitch_family": "granny square", "confidence": 0.0, "uncertain_fields": ["region_label", "stitch_family"]},
        ):
            with self.subTest(region=region):
                identification = identification_from_vision_region(region)
                self.assertEqual(validate_identification(identification), [])

    def test_adapter_never_mutates_the_input_region(self):
        region = {
            "region_label": "cuff",
            "stitch_family": "filet mesh",
            "confidence": 0.82,
            "uncertain_fields": ["stitch_family"],
        }
        region_before = dict(region)
        identification_from_vision_region(region)
        self.assertEqual(region, region_before)

    def test_adapter_never_produces_row_instruction_fields(self):
        region = {
            "region_label": "cuff",
            "stitch_family": "filet mesh",
            "confidence": 0.82,
            "uncertain_fields": [],
        }
        identification = identification_from_vision_region(region)
        for forbidden in ("setup", "repeat", "turning_chain", "row_1", "later_rows"):
            self.assertNotIn(forbidden, identification)


if __name__ == "__main__":
    unittest.main()
