"""
Tests for engine/recipe_library.py -- Phase 6's trusted v2 recipe
library, name/alias normalization and lookup, the is_recipe_trusted()
policy, structural AI-vs-library comparison, and safe resolution of an
AI-proposed recipe against the library.

Every test uses a hand-built library dict passed explicitly as the
`library` argument, or a temp file for load_recipe_library() -- none of
this ever reads or writes the real production
data/confirmed_stitch_recipes_v2.json, and none of it touches the
older, unrelated data/confirmed_stitch_patterns.json at all.
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.recipe_library import (
    RecipeLibraryError,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_INVALID_AI_PROPOSAL,
    STATUS_NO_MATCH,
    STATUS_TRUSTED_MATCH,
    STATUS_UNTRUSTED_MATCH,
    compare_recipe_proposal,
    find_recipe_by_name,
    find_recipe_by_pattern_id,
    is_recipe_trusted,
    load_recipe_library,
    normalize_stitch_name,
    resolve_stitch_recipe,
    validate_recipe_library,
)


def make_recipe(pattern_id, name, aliases=None, status="AI_PROPOSED",
                 repeat_multiple=1, dc_count=1, row_1_setup=None,
                 later_setup=None, reason=None):
    """A small, hand-built, schema-valid v2 recipe for library/resolution
    tests -- per the project's established convention (see
    tests/test_recipe_validator.py, tests/test_later_row_validator.py)."""
    if aliases is None:
        aliases = []
    if row_1_setup is None:
        row_1_setup = []
    if later_setup is None:
        later_setup = [{"stitch": "CH", "count": 1, "placement": "turning_chain"}]

    verification = {"status": status, "confirmations": []}
    if status in ("CONFIRMED", "SWATCH_TESTED"):
        verification["confirmations"] = [{"photo": "a.jpg", "date": "2026-01-01", "note": "hand swatched"}]
    if status == "REJECTED":
        verification["reason"] = reason or "did not match the target construction"

    return {
        "pattern_id": pattern_id,
        "name": name,
        "aliases": aliases,
        "terminology": "US",
        "foundation_formula": {"repeat_multiple": repeat_multiple, "additional_chains": 0},
        "row_1": {
            "setup": row_1_setup,
            "repeat": [{"stitch": "DC", "count": dc_count, "placement": "next_foundation_chain"}],
        },
        "later_rows": {
            "setup": later_setup,
            "repeat": [{"stitch": "DC", "count": 1, "placement": "next_dc"}],
        },
        "expected_swatch_structure": {
            "expected_stitch_posts_per_repeat": None,
            "expected_chain_spaces_per_repeat": None,
        },
        "verification": verification,
    }


def library_of(*recipes):
    return {"schema_version": "2.0.0", "recipes": list(recipes)}


class TempLibraryFile:
    """Writes a library dict to a scratch temp file for load_recipe_library()
    tests, cleaned up automatically."""

    def __init__(self, library_dict_or_raw_text):
        self._dir = tempfile.mkdtemp()
        self.path = os.path.join(self._dir, "library.json")
        with open(self.path, "w") as f:
            if isinstance(library_dict_or_raw_text, str):
                f.write(library_dict_or_raw_text)
            else:
                json.dump(library_dict_or_raw_text, f)

    def __enter__(self):
        return self.path

    def __exit__(self, *exc_info):
        import shutil
        shutil.rmtree(self._dir)


# ---------------------------------------------------------------------------
# 1/2/3: loading -- empty library, malformed top-level, malformed recipe
# ---------------------------------------------------------------------------

class LoadRecipeLibraryTests(unittest.TestCase):
    def test_empty_library_loads_successfully(self):
        with TempLibraryFile(library_of()) as path:
            library = load_recipe_library(path)
        self.assertEqual(library["recipes"], [])

    def test_malformed_top_level_fails_clearly(self):
        with TempLibraryFile({"recipes": "not a list"}) as path:
            with self.assertRaises(RecipeLibraryError) as ctx:
                load_recipe_library(path)
        self.assertIn("recipes", str(ctx.exception))

    def test_missing_recipes_key_fails_clearly(self):
        with TempLibraryFile({"schema_version": "2.0.0"}) as path:
            with self.assertRaises(RecipeLibraryError):
                load_recipe_library(path)

    def test_invalid_json_fails_clearly(self):
        with TempLibraryFile("{not valid json") as path:
            with self.assertRaises(RecipeLibraryError):
                load_recipe_library(path)

    def test_missing_file_fails_clearly(self):
        with self.assertRaises(RecipeLibraryError):
            load_recipe_library("/nonexistent/path/to/library.json")

    def test_malformed_recipe_is_not_silently_skipped(self):
        good = make_recipe("good_one", "Good Stitch")
        broken = {"pattern_id": "broken_one"}  # missing everything else
        with TempLibraryFile(library_of(good, broken)) as path:
            with self.assertRaises(RecipeLibraryError) as ctx:
                load_recipe_library(path)
        self.assertIn("broken_one", str(ctx.exception))

    def test_the_real_production_library_loads_and_is_currently_empty(self):
        # No physically confirmed v2 recipe has been supplied yet -- an
        # empty library here is correct, not a bug to work around.
        library = load_recipe_library()
        self.assertEqual(library["recipes"], [])


# ---------------------------------------------------------------------------
# Top-level library contract: schema_version, notes, unexpected fields
# ---------------------------------------------------------------------------

class LibraryTopLevelContractTests(unittest.TestCase):
    def test_missing_schema_version_is_rejected(self):
        errors = validate_recipe_library({"recipes": []})
        self.assertTrue(any("schema_version" in e and "missing" in e for e in errors))

    def test_wrong_schema_version_is_rejected(self):
        errors = validate_recipe_library({"schema_version": "1.0.0", "recipes": []})
        self.assertTrue(any("unsupported version" in e for e in errors))

    def test_non_string_schema_version_is_rejected(self):
        errors = validate_recipe_library({"schema_version": 2.0, "recipes": []})
        self.assertTrue(any("schema_version" in e and "must be a string" in e for e in errors))

    def test_malformed_notes_empty_string_is_rejected(self):
        errors = validate_recipe_library({"schema_version": "2.0.0", "recipes": [], "notes": ""})
        self.assertTrue(any("notes" in e for e in errors))

    def test_malformed_notes_non_string_is_rejected(self):
        errors = validate_recipe_library({"schema_version": "2.0.0", "recipes": [], "notes": 123})
        self.assertTrue(any("notes" in e for e in errors))

    def test_unexpected_top_level_field_is_rejected(self):
        # Unexpected top-level fields are rejected, mirroring the closed
        # -shape (additionalProperties: false) discipline
        # contracts/stitch_recipe_schema_v2.json already applies to
        # every object inside a v2 recipe.
        errors = validate_recipe_library({"schema_version": "2.0.0", "recipes": [], "mystery_field": True})
        self.assertTrue(any("mystery_field" in e and "unexpected top-level" in e for e in errors))

    def test_valid_top_level_shape_with_notes_has_no_errors(self):
        errors = validate_recipe_library({"schema_version": "2.0.0", "recipes": [], "notes": "a note"})
        self.assertEqual(errors, [])

    def test_all_top_level_problems_are_reported_together(self):
        errors = validate_recipe_library({"schema_version": 1, "notes": "", "mystery": True})
        self.assertTrue(any("schema_version" in e for e in errors))
        self.assertTrue(any("notes" in e for e in errors))
        self.assertTrue(any("mystery" in e for e in errors))
        self.assertTrue(any("recipes" in e for e in errors))


# ---------------------------------------------------------------------------
# 4/5/6: duplicate pattern_id, duplicate name, ambiguous alias
# ---------------------------------------------------------------------------

class ValidateRecipeLibraryDuplicateTests(unittest.TestCase):
    def test_duplicate_pattern_ids_are_rejected(self):
        a = make_recipe("same_id", "Stitch A")
        b = make_recipe("same_id", "Stitch B")
        errors = validate_recipe_library(library_of(a, b))
        self.assertTrue(any("same_id" in e and "unique" in e for e in errors))

    def test_duplicate_normalized_names_are_rejected(self):
        a = make_recipe("pattern_a", "Filet Mesh")
        b = make_recipe("pattern_b", "filet mesh")
        errors = validate_recipe_library(library_of(a, b))
        self.assertTrue(any("filet mesh" in e and "ambiguous" in e for e in errors))

    def test_ambiguous_shared_alias_is_rejected(self):
        a = make_recipe("pattern_a", "Stitch A", aliases=["mesh variant"])
        b = make_recipe("pattern_b", "Stitch B", aliases=["mesh variant"])
        errors = validate_recipe_library(library_of(a, b))
        self.assertTrue(any("mesh variant" in e and "ambiguous" in e for e in errors))
        self.assertTrue(any("pattern_a" in e and "pattern_b" in e for e in errors))

    def test_same_recipe_reusing_its_own_name_as_an_alias_is_not_ambiguous(self):
        a = make_recipe("pattern_a", "Filet Mesh", aliases=["Filet Mesh", "open filet mesh"])
        errors = validate_recipe_library(library_of(a))
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# 7/8/9: normalization -- case/whitespace, hyphen/underscore, no fuzzy guessing
# ---------------------------------------------------------------------------

class NormalizeStitchNameTests(unittest.TestCase):
    def test_case_and_whitespace_normalize_identically(self):
        forms = ["Filet Mesh", "filet mesh", " FILET   MESH ", "filet-mesh", "filet_mesh"]
        normalized = {normalize_stitch_name(f) for f in forms}
        self.assertEqual(normalized, {"filet mesh"})

    def test_hyphen_and_underscore_runs_collapse_like_whitespace(self):
        self.assertEqual(normalize_stitch_name("open--filet__mesh"), "open filet mesh")
        self.assertEqual(normalize_stitch_name("-leading and trailing-"), "leading and trailing")

    def test_undeclared_similar_terms_do_not_match(self):
        # "mesh" is not automatically the same as "filet mesh" or "open
        # mesh" -- only explicit aliases make two terms equivalent.
        library = library_of(make_recipe("filet_mesh_v1", "Filet Mesh", aliases=["open filet mesh"]))
        self.assertEqual(find_recipe_by_name("mesh", library), [])
        self.assertEqual(find_recipe_by_name("open mesh", library), [])
        self.assertEqual(len(find_recipe_by_name("open filet mesh", library)), 1)


# ---------------------------------------------------------------------------
# 10: exact pattern_id lookup
# ---------------------------------------------------------------------------

class FindByPatternIdTests(unittest.TestCase):
    def test_exact_pattern_id_lookup(self):
        target = make_recipe("filet_mesh_v1", "Filet Mesh")
        other = make_recipe("waffle_v1", "Waffle Stitch")
        library = library_of(target, other)
        self.assertIs(find_recipe_by_pattern_id("filet_mesh_v1", library), target)
        self.assertIsNone(find_recipe_by_pattern_id("nonexistent_id", library))


# ---------------------------------------------------------------------------
# 11/12/13: trust policy -- CONFIRMED only
# ---------------------------------------------------------------------------

class IsRecipeTrustedTests(unittest.TestCase):
    def test_confirmed_recipe_is_trusted(self):
        self.assertTrue(is_recipe_trusted(make_recipe("p", "n", status="CONFIRMED")))

    def test_ai_proposed_is_not_trusted(self):
        self.assertFalse(is_recipe_trusted(make_recipe("p", "n", status="AI_PROPOSED")))

    def test_structure_valid_is_not_trusted(self):
        self.assertFalse(is_recipe_trusted(make_recipe("p", "n", status="STRUCTURE_VALID")))

    def test_math_valid_is_not_trusted(self):
        self.assertFalse(is_recipe_trusted(make_recipe("p", "n", status="MATH_VALID")))

    def test_simulation_valid_is_not_trusted(self):
        self.assertFalse(is_recipe_trusted(make_recipe("p", "n", status="SIMULATION_VALID")))

    def test_swatch_tested_is_not_trusted(self):
        # A physical attempt happened, but that alone doesn't mean it
        # matched what was intended -- CONFIRMED is the only status
        # that also carries the human-verified-it-matches judgment.
        self.assertFalse(is_recipe_trusted(make_recipe("p", "n", status="SWATCH_TESTED")))

    def test_rejected_is_not_trusted(self):
        self.assertFalse(is_recipe_trusted(make_recipe("p", "n", status="REJECTED")))


# ---------------------------------------------------------------------------
# 14/15/16: resolution outcomes -- trusted, untrusted, no-match, ambiguous, invalid
# ---------------------------------------------------------------------------

class ResolveStitchRecipeTests(unittest.TestCase):
    def test_trusted_match_overrides_differing_ai_instructions(self):
        trusted = make_recipe("filet_mesh_v1", "Filet Mesh", status="CONFIRMED", repeat_multiple=1)
        library = library_of(trusted)
        ai_proposal = make_recipe("ai_proposed", "filet mesh", status="AI_PROPOSED", repeat_multiple=2)

        result = resolve_stitch_recipe(ai_proposal, library)

        self.assertEqual(result["status"], STATUS_TRUSTED_MATCH)
        self.assertTrue(result["trusted"])
        self.assertIs(result["selected_recipe"], trusted)
        self.assertEqual(result["provenance"], "library")
        self.assertFalse(result["ai_proposal_usable_for_user_instructions"])
        self.assertTrue(
            any(d["path"] == "foundation_formula.repeat_multiple" for d in result["comparison"]["differences"])
        )

    def test_schema_valid_but_unconfirmed_match_is_not_trusted(self):
        unconfirmed = make_recipe("waffle_v1", "Waffle Stitch", status="SIMULATION_VALID")
        library = library_of(unconfirmed)
        ai_proposal = make_recipe("ai_waffle", "waffle stitch", status="AI_PROPOSED")

        result = resolve_stitch_recipe(ai_proposal, library)

        self.assertEqual(result["status"], STATUS_UNTRUSTED_MATCH)
        self.assertFalse(result["trusted"])
        self.assertIsNone(result["selected_recipe"])
        self.assertIsNone(result["provenance"])
        self.assertIs(result["matched_recipe"], unconfirmed)

    def test_rejected_recipe_is_never_selected_for_user_instructions(self):
        rejected = make_recipe("bad_v1", "Bad Stitch", status="REJECTED")
        library = library_of(rejected)
        ai_proposal = make_recipe("ai_bad", "bad stitch", status="AI_PROPOSED")

        result = resolve_stitch_recipe(ai_proposal, library)

        self.assertEqual(result["status"], STATUS_UNTRUSTED_MATCH)
        self.assertIsNone(result["selected_recipe"])
        self.assertFalse(result["trusted"])

    def test_no_library_match_leaves_ai_proposal_unverified(self):
        library = library_of(make_recipe("filet_mesh_v1", "Filet Mesh", status="CONFIRMED"))
        ai_proposal = make_recipe("ai_unknown", "popcorn stitch", status="AI_PROPOSED")

        result = resolve_stitch_recipe(ai_proposal, library)

        self.assertEqual(result["status"], STATUS_NO_MATCH)
        self.assertIsNone(result["selected_recipe"])
        self.assertIsNone(result["matched_recipe"])
        self.assertFalse(result["ai_proposal_usable_for_user_instructions"])
        self.assertEqual(result["ai_proposal"]["pattern_id"], "ai_unknown")

    def test_ambiguous_match_lists_conflicting_pattern_ids_and_picks_none(self):
        # The library itself is perfectly valid -- no shared pattern_id,
        # no shared alias between recipe_a and recipe_b. The ambiguity
        # comes entirely from the AI PROPOSAL's own name and alias each
        # independently matching a DIFFERENT, individually unambiguous
        # library recipe (the only way ambiguous_match can still arise
        # now that a library-internal ambiguity is rejected outright at
        # validation time -- see resolve_stitch_recipe()'s docstring).
        recipe_a = make_recipe("dup_a", "Stitch A", status="CONFIRMED")
        recipe_b = make_recipe("dup_b", "Stitch B", status="CONFIRMED")
        library = library_of(recipe_a, recipe_b)
        ai_proposal = make_recipe("ai_shared", "Stitch A", aliases=["Stitch B"], status="AI_PROPOSED")

        result = resolve_stitch_recipe(ai_proposal, library)

        self.assertEqual(result["status"], STATUS_AMBIGUOUS_MATCH)
        self.assertIsNone(result["selected_recipe"])
        self.assertEqual(sorted(result["conflicting_pattern_ids"]), ["dup_a", "dup_b"])

    def test_invalid_ai_proposal_produces_invalid_ai_proposal_status(self):
        library = library_of()
        broken_proposal = {"pattern_id": "incomplete"}

        result = resolve_stitch_recipe(broken_proposal, library)

        self.assertEqual(result["status"], STATUS_INVALID_AI_PROPOSAL)
        self.assertIsNone(result["selected_recipe"])
        self.assertTrue(len(result["errors"]) > 0)
        self.assertEqual(result["ai_proposal"], broken_proposal)

    def test_lookup_terms_record_pattern_id_name_and_every_alias(self):
        library = library_of()
        ai_proposal = make_recipe("ai_x", "Some Stitch", aliases=["alt one", "alt two"])
        result = resolve_stitch_recipe(ai_proposal, library)
        kinds = [t["kind"] for t in result["lookup_terms"]]
        self.assertEqual(kinds, ["pattern_id", "name", "alias", "alias"])


# ---------------------------------------------------------------------------
# Trust boundary: a directly-supplied library must be validated before
# anything is searched, matched, or selected from it -- for
# resolve_stitch_recipe() AND for the public lookup helpers.
# ---------------------------------------------------------------------------

class TrustBoundaryTests(unittest.TestCase):
    def test_directly_supplied_malformed_library_cannot_be_resolved(self):
        malformed_library = {"recipes": "not a list"}  # also missing schema_version
        ai_proposal = make_recipe("ai_x", "Some Stitch", status="AI_PROPOSED")
        with self.assertRaises(RecipeLibraryError):
            resolve_stitch_recipe(ai_proposal, malformed_library)

    def test_directly_supplied_malformed_confirmed_recipe_cannot_be_selected(self):
        # Claims CONFIRMED, but is missing every other required v2
        # field -- validate_recipe_v2() must catch this, and
        # resolve_stitch_recipe() must never reach is_recipe_trusted()
        # on it at all.
        fake_confirmed = {
            "pattern_id": "fake_trusted",
            "name": "Fake Stitch",
            "verification": {
                "status": "CONFIRMED",
                "confirmations": [{"photo": "a.jpg", "date": "2026-01-01", "note": "not real"}],
            },
        }
        library = {"schema_version": "2.0.0", "recipes": [fake_confirmed]}
        ai_proposal = make_recipe("ai_fake", "Fake Stitch", status="AI_PROPOSED")

        with self.assertRaises(RecipeLibraryError) as ctx:
            resolve_stitch_recipe(ai_proposal, library)
        self.assertIn("fake_trusted", str(ctx.exception))

    def test_duplicate_pattern_id_in_directly_supplied_library_raises_not_first_match(self):
        # Two recipes share a pattern_id -- one CONFIRMED, one not. A
        # naive "return the first match" implementation could silently
        # hand back the CONFIRMED one (or the wrong one); this must
        # instead refuse to search the library at all.
        trusted_first = make_recipe("dup_id", "Stitch A", status="CONFIRMED")
        untrusted_second = make_recipe("dup_id", "Stitch A", status="AI_PROPOSED")
        library = library_of(trusted_first, untrusted_second)
        ai_proposal = make_recipe("ai_x", "Stitch A", status="AI_PROPOSED")

        with self.assertRaises(RecipeLibraryError) as ctx:
            resolve_stitch_recipe(ai_proposal, library)
        self.assertIn("dup_id", str(ctx.exception))

    def test_ambiguous_shared_alias_in_directly_supplied_library_raises_not_silent_pick(self):
        dup_a = make_recipe("dup_a", "Stitch A", aliases=["shared term"], status="CONFIRMED")
        dup_b = make_recipe("dup_b", "Stitch B", aliases=["shared term"], status="CONFIRMED")
        library = {"schema_version": "2.0.0", "recipes": [dup_a, dup_b]}
        ai_proposal = make_recipe("ai_shared", "shared term", status="AI_PROPOSED")

        with self.assertRaises(RecipeLibraryError) as ctx:
            resolve_stitch_recipe(ai_proposal, library)
        self.assertIn("shared term", str(ctx.exception))
        self.assertIn("ambiguous", str(ctx.exception))

    def test_find_recipe_by_pattern_id_rejects_an_unvalidated_library(self):
        malformed = {"schema_version": "2.0.0", "recipes": [{"pattern_id": "x"}]}
        with self.assertRaises(RecipeLibraryError):
            find_recipe_by_pattern_id("x", malformed)

    def test_find_recipe_by_name_rejects_an_unvalidated_library(self):
        malformed = {"schema_version": "2.0.0", "recipes": [{"pattern_id": "x"}]}
        with self.assertRaises(RecipeLibraryError):
            find_recipe_by_name("x", malformed)

    def test_valid_directly_supplied_library_continues_to_work(self):
        trusted = make_recipe("filet_mesh_v1", "Filet Mesh", status="CONFIRMED")
        library = library_of(trusted)

        self.assertIs(find_recipe_by_pattern_id("filet_mesh_v1", library), trusted)
        self.assertEqual(find_recipe_by_name("filet mesh", library), [trusted])

        ai_proposal = make_recipe("ai_x", "filet mesh", status="AI_PROPOSED")
        result = resolve_stitch_recipe(ai_proposal, library)
        self.assertEqual(result["status"], STATUS_TRUSTED_MATCH)
        self.assertIs(result["selected_recipe"], trusted)


# ---------------------------------------------------------------------------
# 17/18/19/20: structural comparison
# ---------------------------------------------------------------------------

class CompareRecipeProposalTests(unittest.TestCase):
    def test_identical_recipes_report_no_differences(self):
        recipe = make_recipe("p", "Stitch")
        result = compare_recipe_proposal(recipe, copy.deepcopy(recipe))
        self.assertTrue(result["matches"])
        self.assertEqual(result["differences"], [])

    def test_detects_a_foundation_difference(self):
        a = make_recipe("p", "Stitch", repeat_multiple=1)
        b = make_recipe("p", "Stitch", repeat_multiple=2)
        result = compare_recipe_proposal(a, b)
        self.assertFalse(result["matches"])
        self.assertIn(
            {"path": "foundation_formula.repeat_multiple", "ai_value": 1, "library_value": 2},
            result["differences"],
        )

    def test_detects_reordered_steps_not_just_different_totals(self):
        # Same steps, same aggregate totals, different ORDER.
        a = make_recipe("p", "Stitch", row_1_setup=[
            {"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"},
            {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
        ])
        b = make_recipe("p", "Stitch", row_1_setup=[
            {"stitch": "DC", "count": 1, "placement": "next_foundation_chain"},
            {"stitch": "SKIP", "count": 1, "placement": "next_foundation_chain"},
        ])
        result = compare_recipe_proposal(a, b)
        self.assertFalse(result["matches"])
        paths = {d["path"] for d in result["differences"]}
        self.assertIn("row_1.setup[0].stitch", paths)
        self.assertIn("row_1.setup[1].stitch", paths)

    def test_detects_a_placement_difference(self):
        a = make_recipe("p", "Stitch", row_1_setup=[{"stitch": "DC", "count": 1, "placement": "next_foundation_chain"}])
        b = make_recipe("p", "Stitch", row_1_setup=[{"stitch": "DC", "count": 1, "placement": "same_stitch"}])
        result = compare_recipe_proposal(a, b)
        self.assertIn(
            {"path": "row_1.setup[0].placement", "ai_value": "next_foundation_chain", "library_value": "same_stitch"},
            result["differences"],
        )

    def test_detects_a_counts_as_difference(self):
        a = make_recipe("p", "Stitch", later_setup=[{"stitch": "CH", "count": 4, "placement": "turning_chain"}])
        b = make_recipe("p", "Stitch", later_setup=[
            {"stitch": "CH", "count": 4, "placement": "turning_chain",
             "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 1}},
        ])
        result = compare_recipe_proposal(a, b)
        matching = [d for d in result["differences"] if d["path"] == "later_rows.setup[0].counts_as"]
        self.assertEqual(len(matching), 1)
        self.assertIsNone(matching[0]["ai_value"])
        self.assertEqual(matching[0]["library_value"], {"stitch_posts": {"DC": 1}, "chain_spaces": 1})

    def test_case_only_name_difference_is_not_reported(self):
        a = make_recipe("p", "Filet Mesh")
        b = make_recipe("p", "filet mesh")
        result = compare_recipe_proposal(a, b)
        self.assertEqual(result["differences"], [])

    def test_does_not_decide_which_recipe_is_correct(self):
        a = make_recipe("p", "Stitch", repeat_multiple=1)
        b = make_recipe("p", "Stitch", repeat_multiple=2)
        result = compare_recipe_proposal(a, b)
        self.assertNotIn("valid", result)
        self.assertNotIn("correct", result)


# ---------------------------------------------------------------------------
# 21: no mutation
# ---------------------------------------------------------------------------

class NoMutationTests(unittest.TestCase):
    def test_resolve_does_not_mutate_ai_proposal_or_library(self):
        trusted = make_recipe("filet_mesh_v1", "Filet Mesh", status="CONFIRMED")
        library = library_of(trusted)
        library_before = copy.deepcopy(library)
        ai_proposal = make_recipe("ai_proposed", "filet mesh", status="AI_PROPOSED", repeat_multiple=2)
        ai_before = copy.deepcopy(ai_proposal)

        result = resolve_stitch_recipe(ai_proposal, library)

        self.assertEqual(ai_proposal, ai_before)
        self.assertEqual(library, library_before)
        # The returned ai_proposal is an independent copy, not the same object.
        self.assertIsNot(result["ai_proposal"], ai_proposal)
        result["ai_proposal"]["pattern_id"] = "mutated"
        self.assertEqual(ai_proposal["pattern_id"], "ai_proposed")

    def test_compare_recipe_proposal_does_not_mutate_either_input(self):
        a = make_recipe("p", "Stitch")
        b = make_recipe("p", "Stitch", repeat_multiple=2)
        a_before, b_before = copy.deepcopy(a), copy.deepcopy(b)
        compare_recipe_proposal(a, b)
        self.assertEqual(a, a_before)
        self.assertEqual(b, b_before)

    def test_find_recipe_by_name_does_not_mutate_the_library(self):
        library = library_of(make_recipe("p", "Filet Mesh", aliases=["mesh variant"]))
        before = copy.deepcopy(library)
        find_recipe_by_name("filet mesh", library)
        find_recipe_by_name("mesh variant", library)
        find_recipe_by_name("nonexistent", library)
        self.assertEqual(library, before)


# ---------------------------------------------------------------------------
# 22: existing test suite (Phase 1-5) unaffected -- lightweight spot checks;
# the full suite run is the authoritative check (see VERIFICATION section).
# ---------------------------------------------------------------------------

class RegressionSpotChecksTests(unittest.TestCase):
    def test_validate_recipe_v2_still_works_standalone(self):
        from engine.schema import validate_recipe_v2
        self.assertEqual(validate_recipe_v2(make_recipe("p", "Stitch")), [])

    def test_phase_4a_and_phase_5_validators_still_work(self):
        from engine.recipe_validator import validate_row_1_against_foundation
        from engine.later_row_validator import validate_recipe_rows
        recipe = make_recipe("p", "Stitch", repeat_multiple=1)
        row1_result = validate_row_1_against_foundation(recipe, 3)
        self.assertTrue(row1_result["valid"])
        rows_result = validate_recipe_rows(recipe, 3, 1)
        self.assertTrue(rows_result["valid"])

    def test_v1_confirmed_patterns_module_and_its_data_file_are_untouched(self):
        # This module never imports or references engine.confirmed_patterns
        # or data/confirmed_stitch_patterns.json at all -- confirmed here
        # by checking the real v1 file still parses and still has its
        # pre-existing (unrelated) content, not anything this phase wrote.
        import engine.confirmed_patterns as cp
        data = cp.load_patterns()
        self.assertIn("filet mesh", data)


if __name__ == "__main__":
    unittest.main()
