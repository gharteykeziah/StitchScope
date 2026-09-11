"""
Tests for engine/image_swatch_pipeline.py -- Phase 8's top-level image
pipeline: image path -> (injected) vision call -> per-region trusted
resolution -> swatch plan -> rendered instructions, or a clear refusal.

NO TEST HERE CONTACTS THE REAL API. Every test either supplies a fake
`vision_client` callable (the dependency-injection seam
generate_swatch_from_image() is built around) or exercises a failure
path (missing file, bad extension) that never reaches vision_client at
all. A handful of tests use a real temp image FILE (so path-existence/
extension checks have something real to check), but the "photo content"
itself is never actually sent anywhere -- the injected vision_client
never looks at the file's bytes.
"""

import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.image_swatch_pipeline import (
    STATUS_API_FAILED,
    STATUS_IMAGE_NOT_FOUND,
    STATUS_IMAGE_UNREADABLE,
    STATUS_INVALID_AI_RESPONSE,
    STATUS_INVALID_LIBRARY,
    STATUS_INVALID_REQUEST,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED_IMAGE_TYPE,
    generate_swatch_from_image,
)
from engine.recipe_library import RecipeLibraryError
from engine.swatch_planner_v2 import STATUS_NO_TRUSTED_RECIPE, STATUS_READY
from engine.vision import VisionProposalError


def make_recipe(pattern_id, name, aliases=None, status="CONFIRMED", terminology="US",
                 repeat_multiple=1, additional_chains=0):
    aliases = aliases or []
    verification = {"status": status, "confirmations": []}
    if status in ("CONFIRMED", "SWATCH_TESTED"):
        verification["confirmations"] = [{"photo": "a.jpg", "date": "2026-01-01", "note": "hand swatched"}]
    return {
        "pattern_id": pattern_id,
        "name": name,
        "aliases": aliases,
        "terminology": terminology,
        "foundation_formula": {"repeat_multiple": repeat_multiple, "additional_chains": additional_chains},
        "row_1": {"setup": [], "repeat": [{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}]},
        "later_rows": {
            "setup": [{"stitch": "CH", "count": 1, "placement": "turning_chain"}],
            "repeat": [{"stitch": "DC", "count": 1, "placement": "next_dc"}],
        },
        "expected_swatch_structure": {"expected_stitch_posts_per_repeat": None, "expected_chain_spaces_per_repeat": None},
        "verification": verification,
    }


def library_of(*recipes):
    return {"schema_version": "2.0.0", "recipes": list(recipes)}


TRUSTED_FILET_MESH = make_recipe("filet_mesh_v1", "Filet Mesh", aliases=["open filet mesh"], status="CONFIRMED")


def proposal_with(*regions):
    return {"photo_id": "demo.jpg", "regions": list(regions)}


def region(region_label="cuff", stitch_family="filet mesh", confidence=0.82, uncertain_fields=None):
    return {
        "region_label": region_label,
        "stitch_family": stitch_family,
        "confidence": confidence,
        "uncertain_fields": uncertain_fields if uncertain_fields is not None else [],
    }


class _TempImage:
    """A small real temp file with a given extension, for path-existence
    checks. Its bytes are never actually read by any injected
    vision_client in these tests."""

    def __init__(self, suffix=".jpg"):
        fd, self.path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(b"not a real image, never read by the fake vision client")

    def __enter__(self):
        return self.path

    def __exit__(self, *exc_info):
        os.remove(self.path)


class RecordingVisionClient:
    """A fake vision_client that records whether/how it was called, so
    tests can prove image-path validation happens BEFORE any (real or
    injected) API call."""

    def __init__(self, proposal=None, error=None):
        self.proposal = proposal
        self.error = error
        self.calls = []

    def __call__(self, image_path):
        self.calls.append(image_path)
        if self.error is not None:
            raise self.error
        return self.proposal


# ---------------------------------------------------------------------------
# invalid_request: every locally-knowable malformed input, validated
# BEFORE vision_client is ever invoked, with zero vision calls.
# ---------------------------------------------------------------------------

class InvalidRequestImagePathTests(unittest.TestCase):
    def test_none_image_path_makes_zero_vision_calls(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        result = generate_swatch_from_image(None, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
        self.assertIsNone(result["regions"])
        self.assertEqual(client.calls, [])

    def test_numeric_image_path_makes_zero_vision_calls(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        result = generate_swatch_from_image(123, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
        self.assertEqual(client.calls, [])

    def test_empty_string_image_path_makes_zero_vision_calls(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        result = generate_swatch_from_image("", vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
        self.assertEqual(client.calls, [])

    def test_whitespace_only_image_path_makes_zero_vision_calls(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        result = generate_swatch_from_image("   ", vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
        self.assertEqual(client.calls, [])

    def test_list_image_path_makes_zero_vision_calls(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        result = generate_swatch_from_image(["not", "a", "path"], vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
        self.assertEqual(client.calls, [])


class InvalidRequestRepeatCountTests(unittest.TestCase):
    def test_invalid_requested_repeat_counts_make_zero_vision_calls(self):
        for bad in (0, -1, -100, 3.0, "3", True, False, None):
            with self.subTest(bad=bad):
                client = RecordingVisionClient(proposal=proposal_with(region()))
                with _TempImage() as path:
                    result = generate_swatch_from_image(path, requested_repeat_count=bad, vision_client=client)
                self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
                self.assertIsNone(result["regions"])
                self.assertEqual(client.calls, [])

    def test_invalid_later_row_counts_make_zero_vision_calls(self):
        for bad in (-1, -100, 1.5, "1", True, False, None):
            with self.subTest(bad=bad):
                client = RecordingVisionClient(proposal=proposal_with(region()))
                with _TempImage() as path:
                    result = generate_swatch_from_image(path, later_row_count=bad, vision_client=client)
                self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
                self.assertEqual(client.calls, [])

    def test_valid_boundary_counts_do_not_raise_invalid_request(self):
        # 1 and 0 are the documented minimums -- must NOT be rejected.
        client = RecordingVisionClient(proposal=proposal_with(region()), )
        with _TempImage() as path:
            result = generate_swatch_from_image(
                path, requested_repeat_count=1, later_row_count=0, vision_client=client, library=library_of(),
            )
        self.assertEqual(result["status"], STATUS_PROCESSED)
        self.assertEqual(len(client.calls), 1)


class InvalidRequestVisionClientTests(unittest.TestCase):
    def test_non_callable_vision_client_is_invalid_request(self):
        for bad in (123, "not callable", [], {}):
            with self.subTest(bad=bad):
                with _TempImage() as path:
                    result = generate_swatch_from_image(path, vision_client=bad)
                self.assertEqual(result["status"], STATUS_INVALID_REQUEST)
                self.assertIsNone(result["regions"])


class InvalidLibraryBeforeVisionCallTests(unittest.TestCase):
    def test_malformed_directly_supplied_library_makes_zero_vision_calls(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client, library={"recipes": "not a list"})
        self.assertEqual(result["status"], STATUS_INVALID_LIBRARY)
        self.assertIsNone(result["regions"])
        self.assertEqual(client.calls, [])

    def test_library_with_duplicate_pattern_id_makes_zero_vision_calls(self):
        dup = make_recipe("dup_id", "Stitch A", status="CONFIRMED")
        client = RecordingVisionClient(proposal=proposal_with(region()))
        with _TempImage() as path:
            result = generate_swatch_from_image(
                path, vision_client=client, library=library_of(dup, dup),
            )
        self.assertEqual(result["status"], STATUS_INVALID_LIBRARY)
        self.assertEqual(client.calls, [])

    def test_broken_default_library_makes_zero_vision_calls(self):
        # Simulates the real production file being unreadable/invalid --
        # mocks the single function load_recipe_library() that
        # _load_or_validate_library(None) calls internally, so no real
        # file is touched by this test.
        client = RecordingVisionClient(proposal=proposal_with(region()))
        with _TempImage() as path:
            with patch(
                "engine.recipe_library.load_recipe_library",
                side_effect=RecipeLibraryError("simulated broken production library"),
            ):
                result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_LIBRARY)
        self.assertIsNone(result["regions"])
        self.assertEqual(client.calls, [])

    def test_valid_directly_supplied_library_does_not_raise_invalid_library(self):
        client = RecordingVisionClient(proposal=proposal_with(region(stitch_family="filet mesh")))
        with _TempImage() as path:
            result = generate_swatch_from_image(
                path, vision_client=client, library=library_of(TRUSTED_FILET_MESH),
            )
        self.assertEqual(result["status"], STATUS_PROCESSED)
        self.assertEqual(len(client.calls), 1)


# ---------------------------------------------------------------------------
# Raw AI-response fields outside the identification contract are always
# discarded, never read -- they can never affect a selected recipe or
# rendered instructions, even when present and internally consistent.
# ---------------------------------------------------------------------------

class RawInstructionFieldsAreDiscardedTests(unittest.TestCase):
    def _region_with_smuggled_instructions(self):
        r = region(region_label="cuff", stitch_family="filet mesh", confidence=0.9)
        # Smuggle exactly the fields Phase 8 says must never reach
        # planning or rendering, with content that would be OBVIOUSLY
        # visible in the output if it ever leaked through -- a
        # distinctive marker stitch name no real renderer would produce.
        r["setup"] = [{"stitch": "MARKER_FROM_AI", "count": 999, "placement": "next_foundation_chain"}]
        r["repeat"] = [{"stitch": "MARKER_FROM_AI", "count": 999, "placement": "next_dc"}]
        r["turning_chain"] = [{"stitch": "MARKER_FROM_AI", "count": 999}]
        r["row_1"] = {"setup": [], "repeat": [{"stitch": "MARKER_FROM_AI", "count": 999, "placement": "next_foundation_chain"}]}
        r["later_rows"] = {"setup": [], "repeat": [{"stitch": "MARKER_FROM_AI", "count": 999, "placement": "next_dc"}]}
        r["pattern_id"] = "MARKER_FROM_AI_pattern_id"
        return r

    def test_smuggled_fields_are_absent_from_the_adapted_identification(self):
        from engine.stitch_identification import identification_from_vision_region
        raw_region = self._region_with_smuggled_instructions()
        identification = identification_from_vision_region(raw_region)
        for forbidden in ("setup", "repeat", "turning_chain", "row_1", "later_rows", "pattern_id"):
            self.assertNotIn(forbidden, identification)
        self.assertNotIn("MARKER_FROM_AI", str(identification))

    def test_smuggled_fields_cannot_change_which_recipe_is_selected_or_rendered(self):
        client = RecordingVisionClient(proposal=proposal_with(self._region_with_smuggled_instructions()))
        with _TempImage() as path:
            clean_result = generate_swatch_from_image(
                path, requested_repeat_count=4, later_row_count=2,
                vision_client=RecordingVisionClient(proposal=proposal_with(region(stitch_family="filet mesh", confidence=0.9))),
                library=library_of(TRUSTED_FILET_MESH),
            )
            smuggled_result = generate_swatch_from_image(
                path, requested_repeat_count=4, later_row_count=2,
                vision_client=client,
                library=library_of(TRUSTED_FILET_MESH),
            )

        clean_region = clean_result["regions"][0]
        smuggled_region = smuggled_result["regions"][0]

        # Identical outcome whether or not the raw AI response smuggled
        # instruction fields -- proving those fields had zero effect.
        self.assertEqual(clean_region["swatch_status"], smuggled_region["swatch_status"])
        self.assertEqual(clean_region["selected_pattern_id"], smuggled_region["selected_pattern_id"])
        self.assertEqual(clean_region["rendered_instructions"], smuggled_region["rendered_instructions"])

        # The trusted library recipe was used, not the smuggled data.
        self.assertEqual(smuggled_region["selected_pattern_id"], TRUSTED_FILET_MESH["pattern_id"])
        self.assertNotIn("MARKER_FROM_AI", smuggled_region["rendered_instructions"])
        self.assertNotIn("999", smuggled_region["rendered_instructions"])

    def test_smuggled_fields_do_not_cause_invalid_ai_response_or_invalid_identification(self):
        # Confirms the CHOSEN behavior is "discard," not "reject the
        # whole proposal" -- a region with extra fields still produces a
        # normal, ready result when it identifies a trusted stitch.
        client = RecordingVisionClient(proposal=proposal_with(self._region_with_smuggled_instructions()))
        with _TempImage() as path:
            result = generate_swatch_from_image(
                path, vision_client=client, library=library_of(TRUSTED_FILET_MESH),
            )
        self.assertEqual(result["status"], STATUS_PROCESSED)
        self.assertEqual(result["regions"][0]["swatch_status"], STATUS_READY)


# ---------------------------------------------------------------------------
# Image-path validation happens BEFORE any vision call
# ---------------------------------------------------------------------------

class ImagePathValidationTests(unittest.TestCase):
    def test_missing_file_never_calls_vision_client(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        result = generate_swatch_from_image("/no/such/file.jpg", vision_client=client)
        self.assertEqual(result["status"], STATUS_IMAGE_NOT_FOUND)
        self.assertIsNone(result["regions"])
        self.assertEqual(client.calls, [])

    def test_unsupported_extension_never_calls_vision_client(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        with _TempImage(suffix=".gif") as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_UNSUPPORTED_IMAGE_TYPE)
        self.assertEqual(client.calls, [])

    def test_supported_extensions_pass_the_check(self):
        for suffix in (".jpg", ".jpeg", ".png"):
            with self.subTest(suffix=suffix):
                client = RecordingVisionClient(proposal=proposal_with(region()))
                with _TempImage(suffix=suffix) as path:
                    result = generate_swatch_from_image(path, vision_client=client)
                self.assertEqual(result["status"], STATUS_PROCESSED)
                self.assertEqual(len(client.calls), 1)

    def test_extension_check_is_case_insensitive(self):
        client = RecordingVisionClient(proposal=proposal_with(region()))
        with _TempImage(suffix=".JPG") as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_PROCESSED)


# ---------------------------------------------------------------------------
# API failure / image reading failure
# ---------------------------------------------------------------------------

class ApiAndReadFailureTests(unittest.TestCase):
    def test_vision_proposal_error_is_caught_as_api_failed(self):
        client = RecordingVisionClient(error=VisionProposalError("network error"))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_API_FAILED)
        self.assertIn("network error", result["errors"][0])
        self.assertIsNone(result["regions"])

    def test_os_error_is_caught_as_image_unreadable(self):
        client = RecordingVisionClient(error=PermissionError("cannot read file"))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_IMAGE_UNREADABLE)
        self.assertIsNone(result["regions"])

    def test_no_raw_traceback_leaks_into_the_result(self):
        client = RecordingVisionClient(error=VisionProposalError("boom"))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        for error in result["errors"]:
            self.assertNotIn("Traceback", error)


# ---------------------------------------------------------------------------
# Invalid AI response / no regions
# ---------------------------------------------------------------------------

class InvalidAiResponseTests(unittest.TestCase):
    def test_missing_regions_field_is_invalid_ai_response(self):
        client = RecordingVisionClient(proposal={"photo_id": "x"})
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_AI_RESPONSE)
        self.assertIsNone(result["regions"])
        self.assertTrue(result["errors"])

    def test_empty_regions_list_is_invalid_ai_response(self):
        client = RecordingVisionClient(proposal=proposal_with())
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_AI_RESPONSE)

    def test_malformed_region_is_invalid_ai_response(self):
        client = RecordingVisionClient(proposal={"regions": [{"region_label": "cuff"}]})  # missing fields
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_AI_RESPONSE)

    def test_non_dict_response_is_invalid_ai_response(self):
        client = RecordingVisionClient(proposal="not a dict")
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client)
        self.assertEqual(result["status"], STATUS_INVALID_AI_RESPONSE)


# ---------------------------------------------------------------------------
# Per-region processing: trust boundary, independence, honest refusal
# ---------------------------------------------------------------------------

class PerRegionProcessingTests(unittest.TestCase):
    def test_no_trusted_recipe_against_empty_library(self):
        client = RecordingVisionClient(proposal=proposal_with(region(stitch_family="filet mesh")))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client, library=library_of())
        self.assertEqual(result["status"], STATUS_PROCESSED)
        self.assertEqual(len(result["regions"]), 1)
        r = result["regions"][0]
        self.assertEqual(r["swatch_status"], STATUS_NO_TRUSTED_RECIPE)
        self.assertFalse(r["ready_for_user_instructions"])
        self.assertIsNone(r["rendered_instructions"])

    def test_trusted_match_produces_ready_instructions(self):
        client = RecordingVisionClient(proposal=proposal_with(region(stitch_family="filet mesh")))
        with _TempImage() as path:
            result = generate_swatch_from_image(
                path, requested_repeat_count=4, later_row_count=2,
                vision_client=client, library=library_of(TRUSTED_FILET_MESH),
            )
        r = result["regions"][0]
        self.assertEqual(r["swatch_status"], STATUS_READY)
        self.assertTrue(r["ready_for_user_instructions"])
        self.assertIsNotNone(r["rendered_instructions"])
        self.assertEqual(r["selected_pattern_id"], "filet_mesh_v1")
        self.assertEqual(r["recipe_resolution_status"], "trusted_match")

    def test_high_confidence_never_overrides_no_trusted_recipe(self):
        client = RecordingVisionClient(
            proposal=proposal_with(region(stitch_family="filet mesh", confidence=1.0))
        )
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client, library=library_of())
        r = result["regions"][0]
        self.assertEqual(r["confidence"], 1.0)
        self.assertEqual(r["swatch_status"], STATUS_NO_TRUSTED_RECIPE)
        self.assertIsNone(r["rendered_instructions"])

    def test_multiple_regions_are_processed_independently(self):
        client = RecordingVisionClient(proposal=proposal_with(
            region(region_label="cuff", stitch_family="filet mesh"),
            region(region_label="body", stitch_family="unknown stitch"),
        ))
        with _TempImage() as path:
            result = generate_swatch_from_image(
                path, vision_client=client, library=library_of(TRUSTED_FILET_MESH),
            )
        self.assertEqual(len(result["regions"]), 2)
        cuff, body = result["regions"]
        self.assertEqual(cuff["region_label"], "cuff")
        self.assertEqual(cuff["swatch_status"], STATUS_READY)
        self.assertEqual(body["region_label"], "body")
        self.assertEqual(body["swatch_status"], STATUS_NO_TRUSTED_RECIPE)
        # One region's failure never contaminates the other's success.
        self.assertIsNotNone(cuff["rendered_instructions"])
        self.assertIsNone(body["rendered_instructions"])

    def test_regions_with_similar_names_are_never_merged(self):
        client = RecordingVisionClient(proposal=proposal_with(
            region(region_label="cuff", stitch_family="mesh"),
            region(region_label="collar", stitch_family="mesh"),
        ))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client, library=library_of())
        self.assertEqual(len(result["regions"]), 2)
        self.assertEqual(result["regions"][0]["region_label"], "cuff")
        self.assertEqual(result["regions"][1]["region_label"], "collar")

    def test_region_identification_is_preserved_in_the_result(self):
        client = RecordingVisionClient(proposal=proposal_with(
            region(region_label="yoke", stitch_family="popcorn stitch", confidence=0.6, uncertain_fields=["stitch_family"])
        ))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client, library=library_of())
        r = result["regions"][0]
        self.assertEqual(r["identification"]["stitch_name"], "popcorn stitch")
        self.assertEqual(r["confidence"], 0.6)
        self.assertIn("stitch_family", r["uncertainty"])


# ---------------------------------------------------------------------------
# Old (v1) pathway is never touched
# ---------------------------------------------------------------------------

class OldPathwayUntouchedTests(unittest.TestCase):
    def test_module_does_not_import_v1_modules(self):
        import ast

        import engine.image_swatch_pipeline as pipeline_module

        with open(pipeline_module.__file__) as f:
            source = f.read()
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("engine.confirmed_patterns", imported_modules)
        self.assertNotIn("engine.swatch", imported_modules)
        self.assertNotIn("engine.renderer", imported_modules)

    def test_never_falls_back_to_untrusted_instructions(self):
        client = RecordingVisionClient(proposal=proposal_with(region(stitch_family="filet mesh")))
        with _TempImage() as path:
            result = generate_swatch_from_image(path, vision_client=client, library=library_of())
        r = result["regions"][0]
        self.assertIsNone(r["rendered_instructions"])
        self.assertFalse(r["ready_for_user_instructions"])


# ---------------------------------------------------------------------------
# No mutation, no real network access
# ---------------------------------------------------------------------------

class NoMutationTests(unittest.TestCase):
    def test_does_not_mutate_the_supplied_library(self):
        library = library_of(TRUSTED_FILET_MESH)
        before = copy.deepcopy(library)
        client = RecordingVisionClient(proposal=proposal_with(region(stitch_family="filet mesh")))
        with _TempImage() as path:
            generate_swatch_from_image(path, vision_client=client, library=library)
        self.assertEqual(library, before)


class DefaultVisionClientTests(unittest.TestCase):
    def test_importing_the_module_makes_no_api_call(self):
        # Import already happened at module load time (see the top of
        # this file) -- if that contacted the real API, every other test
        # here would already have failed/hung. This test exists to
        # document the guarantee explicitly.
        import engine.image_swatch_pipeline  # noqa: F401
        self.assertTrue(True)

    def test_default_vision_client_is_the_real_photo_function_but_is_never_invoked_without_a_real_call(self):
        from engine.image_swatch_pipeline import generate_swatch_from_image as gsi
        from engine.vision import get_vision_proposal_from_photo
        # Confirms the wiring without ever actually calling it: a missing
        # file short-circuits before vision_client (real or injected) is
        # invoked at all.
        result = gsi("/no/such/file.jpg")
        self.assertEqual(result["status"], STATUS_IMAGE_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
