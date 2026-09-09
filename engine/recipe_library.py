"""
Phase 6: the trusted v2 recipe library, and safe resolution of an
AI-proposed stitch (name + untrusted instructions) against it.

WHY THIS MODULE EXISTS

The AI pipeline can correctly IDENTIFY a stitch ("this looks like filet
mesh") while proposing INCORRECT instructions for it. Those are two
separate claims with two separate trust levels:

  1. AI identification            -- "this looks like filet mesh"
  2. AI-proposed instructions     -- untrusted, no matter how the recipe
                                      got here (schema-valid, math-valid,
                                      simulation-valid -- none of that is
                                      physical confirmation)
  3. A stored, trusted recipe     -- instructions a human has previously
                                      reviewed AND physically confirmed

When a trusted recipe already exists for the identified stitch, this
module's job is to make sure the TRUSTED recipe is what gets used for
real output -- never the fresh AI proposal, no matter how plausible
that proposal looks on paper.

MATHEMATICAL VALIDITY IS NOT PHYSICAL CONFIRMATION

Nothing in this module ever promotes a recipe's verification.status.
Passing validate_recipe_v2() (schema), calculate_foundation() (math),
validate_row_1_against_foundation() (Phase 4A), or
validate_recipe_rows() (Phase 5) are all still just computer-checkable
layers -- see docs/recipe_model_v2.md section 6. A recipe that passes
every one of them can still be crochet-wrong; only a status of exactly
"CONFIRMED" (see is_recipe_trusted() below) means a person actually
made the stitch AND a human verified it matches. This module reads that
status; it never sets it, computes it, or infers it from anything else.

THIS LIBRARY IS GENERIC -- NOT HARD-CODED FOR ANY ONE STITCH

Every function here operates on the v2 recipe shape and a name/alias
lookup that any stitch family can use. Nothing about filet mesh (or any
other specific stitch) is baked into this module; the structural
example and known-bad example in contracts/examples/ are illustrative
fixtures, not entries this module trusts by name.

RELATIONSHIP TO THE EXISTING (v1) CONFIRMED-PATTERN SYSTEM

engine/confirmed_patterns.py and data/confirmed_stitch_patterns.json
are a DIFFERENT, older system this module does not touch, extend, or
migrate:
  - v1 keys a flat dict by one normalized "stitch family" string and
    stores three bare step lists (setup/repeat/turning_chain) with no
    placement, no counts_as, no pattern_id/aliases, and a binary
    confirmed-or-not distinction (confirmations non-empty or not).
  - v2 (this module) stores complete, schema-valid recipe objects (with
    placement, counts_as, a foundation formula, row_1 vs later_rows,
    and the graduated 7-value verification.status from
    docs/recipe_model_v2.md section 7) in a list, looked up by
    pattern_id or by normalized name/alias, with an explicit trust
    predicate (is_recipe_trusted()) rather than a bare non-empty check.
  - v1's data/confirmed_stitch_patterns.json currently has two entries,
    "filet mesh" and "single crochet," and NEITHER is actually
    confirmed (both have empty "confirmations" lists) -- there is
    nothing there for this module to migrate even if it wanted to.
This module reads and writes only data/confirmed_stitch_recipes_v2.json
(see _LIBRARY_PATH) -- data/confirmed_stitch_patterns.json is never
opened, read, written, or referenced by any function below.

EVERY PUBLIC LOOKUP VALIDATES A DIRECTLY-SUPPLIED LIBRARY FIRST

load_recipe_library() always validates (it reads a file, parses it, and
raises RecipeLibraryError on any problem before returning). But
find_recipe_by_pattern_id(), find_recipe_by_name(), and
resolve_stitch_recipe() all also accept a `library` argument directly,
bypassing disk entirely -- and a directly-supplied dict is NOT
guaranteed to have gone through validate_recipe_library() first. A
malformed dict handed to these functions could claim
verification.status == "CONFIRMED" without ever having passed
validate_recipe_v2(), or could contain a duplicate pattern_id, or an
ambiguous shared alias -- none of which is_recipe_trusted() or a plain
list-scan would catch on its own.

To close that trust boundary, EVERY public function below that accepts
a `library` argument runs it through the shared internal
_load_or_validate_library() helper before doing anything else:
`library=None` loads and validates the real file (via
load_recipe_library()); a directly-supplied library is validated with
validate_recipe_library() on the spot, and RecipeLibraryError is raised
immediately if it fails -- consistently, the same way and the same
exception type regardless of where the library came from. No lookup,
comparison, or selection ever runs against an unvalidated library.
resolve_stitch_recipe() validates the library exactly ONCE per call
(not once per lookup term) and then uses small private, `_..._in()`
helpers internally that assume that already-validated library --
find_recipe_by_pattern_id() and find_recipe_by_name() remain the safe,
independently-validating PUBLIC entry points for any other caller.

SIMULATION EVIDENCE IS DELIBERATELY OUT OF SCOPE HERE

resolve_stitch_recipe() does not call calculate_foundation(),
validate_row_1_against_foundation(), or validate_recipe_rows() -- it
only calls validate_recipe_v2() to reject a structurally broken AI
proposal outright. Attaching foundation/row/later-row simulation
evidence would require deciding a requested_repeat_count and
later_row_count the caller hasn't supplied at this layer, and would
duplicate validator logic this module doesn't own. That attachment is
Phase 7's job, once a caller actually has a swatch-testing request to
run those validators against; this module only decides WHICH recipe
(library or AI) should be used, not whether it mathematically checks
out.
"""

import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

from engine.schema import validate_recipe_v2

_LIBRARY_PATH = Path(__file__).resolve().parent.parent / "data" / "confirmed_stitch_recipes_v2.json"

LIBRARY_SCHEMA_VERSION = "2.0.0"
_ALLOWED_LIBRARY_TOP_LEVEL_FIELDS = frozenset({"schema_version", "recipes", "notes"})

TRUSTED_VERIFICATION_STATUS = "CONFIRMED"

STATUS_TRUSTED_MATCH = "trusted_match"
STATUS_UNTRUSTED_MATCH = "untrusted_match"
STATUS_NO_MATCH = "no_match"
STATUS_AMBIGUOUS_MATCH = "ambiguous_match"
STATUS_INVALID_AI_PROPOSAL = "invalid_ai_proposal"

_STEP_LIST_PATHS = (
    ("row_1", "setup", "row_1.setup"),
    ("row_1", "repeat", "row_1.repeat"),
    ("later_rows", "setup", "later_rows.setup"),
    ("later_rows", "repeat", "later_rows.repeat"),
)
_STEP_FIELDS = ("stitch", "count", "placement", "counts_as")
_FOUNDATION_FIELDS = ("repeat_multiple", "additional_chains")
_EXPECTED_STRUCTURE_FIELDS = ("expected_stitch_posts_per_repeat", "expected_chain_spaces_per_repeat")


class RecipeLibraryError(ValueError):
    """
    Raised when a v2 recipe library cannot be trusted as a whole: the
    file isn't valid JSON, the top-level shape is wrong (an unexpected
    field, a missing/non-string/unsupported "schema_version", a
    malformed "notes"), any stored recipe fails validate_recipe_v2(),
    two recipes share a pattern_id, or two recipes' normalized
    name/alias sets overlap ambiguously.

    Raised consistently by load_recipe_library() (loading from disk)
    AND by every other public function in this module that accepts a
    `library` argument directly (find_recipe_by_pattern_id(),
    find_recipe_by_name(), resolve_stitch_recipe()) -- a directly
    -supplied library is validated the same way, with the same
    exception, as one loaded from the real file; see this module's
    docstring, "EVERY PUBLIC LOOKUP VALIDATES A DIRECTLY-SUPPLIED
    LIBRARY FIRST".

    Never raised merely because the library is EMPTY -- an empty,
    well-shaped library ({"schema_version": "2.0.0", "recipes": []}) is
    valid and distinct from a broken one; see load_recipe_library()'s
    docstring.
    """


def normalize_stitch_name(name):
    """
    Deterministic normalization used for every name/alias lookup in
    this module. Given a candidate name or alias string, returns:

      1. leading/trailing whitespace trimmed
      2. casefolded (broader than .lower() -- consistent across
         locales/unicode for this kind of ASCII-mostly matching)
      3. every run of hyphens and/or underscores replaced with a single
         space (so "filet-mesh" and "filet_mesh" normalize the same as
         "filet mesh")
      4. every run of remaining whitespace collapsed to one space
      5. trimmed again (step 3 can introduce a leading/trailing space,
         e.g. "-filet mesh-")

    "Filet Mesh", "filet mesh", " FILET   MESH ", "filet-mesh", and
    "filet_mesh" all normalize to "filet mesh".

    This is EXACT, deterministic string normalization only -- never
    fuzzy matching, stemming, or plural handling, and it never decides
    that two semantically-similar-looking names ("mesh," "open mesh,"
    "filet mesh") refer to the same stitch. If two names are meant to
    match, they must be declared as the same recipe's name/aliases;
    this function only makes exact-term lookup insensitive to case,
    surrounding whitespace, internal whitespace runs, and hyphen-vs-
    underscore-vs-space, nothing more.

    Raises TypeError if name is not a string -- callers pass user/AI-
    supplied strings, and a non-string here is a caller bug, not a
    "no match" outcome to silently absorb.
    """
    if not isinstance(name, str):
        raise TypeError(f"normalize_stitch_name() requires a string, got {type(name).__name__}")
    normalized = name.strip().casefold()
    normalized = re.sub(r"[-_]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def is_recipe_trusted(recipe):
    """
    True only when recipe["verification"]["status"] is exactly
    "CONFIRMED" -- the sole status in the v2 vocabulary
    (contracts/stitch_recipe_schema_v2.json, engine/schema.py,
    docs/recipe_model_v2.md section 7) representing actual, completed
    physical confirmation: a person physically crocheted the exact
    candidate AND a human verified the result matches the intended
    stitch variation.

    Every other status returns False, deliberately including
    SWATCH_TESTED: that status means a physical attempt happened, but
    NOT that it matched what was intended (see section 7 -- "whether
    the attempt succeeded or failed"). AI_PROPOSED, STRUCTURE_VALID,
    MATH_VALID, and SIMULATION_VALID are all purely computer-checkable
    layers with no human or physical object involved at all. REJECTED
    means a determination was already made that the recipe is wrong.
    None of these authorize trusted, user-facing output.

    Does not itself validate the recipe's shape or schema -- callers
    are expected to already know it's a schema-valid v2 recipe (e.g.
    because it came from load_recipe_library(), which already runs
    validate_recipe_v2() on every stored entry). Returns False (rather
    than raising) for a recipe missing or malformed verification data,
    since "not demonstrably trusted" is the correct read of that case.
    """
    verification = recipe.get("verification") if isinstance(recipe, dict) else None
    if not isinstance(verification, dict):
        return False
    return verification.get("status") == TRUSTED_VERIFICATION_STATUS


def validate_recipe_library(library):
    """
    Validates a v2 recipe library's shape without touching disk --
    usable standalone (e.g. on a hand-built dict in a test) or as the
    check load_recipe_library() and every other public function in this
    module runs before trusting a `library` argument (see this module's
    docstring, "EVERY PUBLIC LOOKUP VALIDATES A DIRECTLY-SUPPLIED
    LIBRARY FIRST").

    Checks, in order, never stopping early except where a check literally
    cannot proceed without the thing it's checking (every problem that
    CAN be reported alongside others is reported, not just the first):
      1. library is a dict.
      2. No top-level field other than "schema_version", "recipes", and
         the optional "notes" is present -- an unexpected top-level
         field is rejected, the same closed-shape discipline
         contracts/stitch_recipe_schema_v2.json already applies to
         every object in a v2 recipe (additionalProperties: false).
      3. "schema_version" is required, must be a string, and must equal
         exactly LIBRARY_SCHEMA_VERSION ("2.0.0") -- a missing,
         non-string, or different value is rejected; this module never
         guesses how to read a library format it wasn't written for.
      4. "notes", if present, must be a non-empty string (same rule
         v2 recipes already use for their own optional "notes" fields).
      5. "recipes" is required and must be a list -- this function
         cannot proceed to checks 6-8 without it, so it returns early
         only at this specific point.
      6. Every entry in "recipes" passes validate_recipe_v2() -- a
         malformed entry is reported with its index and (if readable)
         pattern_id, never silently skipped or excluded from the rest
         of this function's checks.
      7. No two entries share a pattern_id.
      8. No normalized name or alias is shared by two different
         pattern_ids (an "ambiguous duplicate" -- see
         normalize_stitch_name()). A recipe listing the same term as
         both its own name and its own alias, or twice in its own
         aliases, is not an error (nothing is ambiguous about a term
         only ever pointing at one pattern_id).

    Returns a list of readable error strings -- an empty list means the
    library (structurally) checks out, including a library whose
    "recipes" list is simply empty. Never raises; mirrors
    validate_recipe_v2()'s own contract exactly.
    """
    errors = []

    if not isinstance(library, dict):
        return [f"library must be an object, got {type(library).__name__}"]

    for key in library:
        if key not in _ALLOWED_LIBRARY_TOP_LEVEL_FIELDS:
            errors.append(f"library: unexpected top-level field {key!r}")

    if "schema_version" not in library:
        errors.append("library: missing required field 'schema_version'")
    else:
        version = library["schema_version"]
        if not isinstance(version, str):
            errors.append(f"library.schema_version: must be a string, got {type(version).__name__}")
        elif version != LIBRARY_SCHEMA_VERSION:
            errors.append(
                f"library.schema_version: unsupported version {version!r} -- this module only "
                f"supports {LIBRARY_SCHEMA_VERSION!r}"
            )

    if "notes" in library:
        notes = library["notes"]
        if not isinstance(notes, str) or len(notes) == 0:
            errors.append(f"library.notes: must be a non-empty string, got {notes!r}")

    if "recipes" not in library:
        errors.append("library: missing required field 'recipes'")
        return errors

    recipes = library["recipes"]
    if not isinstance(recipes, list):
        errors.append(f"library.recipes: must be a list, got {type(recipes).__name__}")
        return errors

    pattern_id_counts = Counter()
    term_to_pattern_ids = {}

    for index, recipe in enumerate(recipes):
        recipe_errors = validate_recipe_v2(recipe)
        if recipe_errors:
            label = recipe.get("pattern_id") if isinstance(recipe, dict) else None
            prefix = f"library.recipes[{index}]" + (f" (pattern_id={label!r})" if label else "")
            for e in recipe_errors:
                errors.append(f"{prefix}: {e}")
            continue

        pattern_id = recipe["pattern_id"]
        pattern_id_counts[pattern_id] += 1

        terms = [recipe["name"]] + list(recipe["aliases"])
        for term in terms:
            normalized = normalize_stitch_name(term)
            term_to_pattern_ids.setdefault(normalized, set()).add(pattern_id)

    for pattern_id, count in pattern_id_counts.items():
        if count > 1:
            errors.append(f"library.recipes: pattern_id {pattern_id!r} appears {count} times -- must be unique")

    for term, pattern_ids in term_to_pattern_ids.items():
        if len(pattern_ids) > 1:
            errors.append(
                f"library.recipes: normalized name/alias {term!r} is ambiguous -- claimed by "
                f"pattern_ids {sorted(pattern_ids)}"
            )

    return errors


def load_recipe_library(path=None):
    """
    Reads, parses, and fully validates a v2 recipe library from disk.

    path defaults to data/confirmed_stitch_recipes_v2.json (this
    module's own library, entirely separate from the older v1
    data/confirmed_stitch_patterns.json -- see this module's
    docstring). Pass an explicit path (e.g. a temp file) in tests
    rather than monkeypatching _LIBRARY_PATH, though both work.

    Raises RecipeLibraryError -- never returns a broken library -- when:
      - the file doesn't exist or can't be read,
      - the file isn't valid JSON,
      - validate_recipe_library() reports any error at all (bad
        top-level shape, a malformed recipe, a duplicate pattern_id, or
        an ambiguous duplicate name/alias).

    Returns the parsed library dict unchanged otherwise -- including a
    library whose "recipes" list is empty, which is a valid, normal
    result (see this module's docstring: an empty production v2 library
    is expected until a recipe is actually physically confirmed), never
    conflated with a broken library that fails to load at all.

    Never mutates anything -- this is a pure read. Callers must treat
    the returned dict and every recipe in it as read-only; nothing in
    this module copies recipes defensively on load (find_recipe_by_*()
    and resolve_stitch_recipe() are documented individually on what
    they do and don't copy).
    """
    target_path = Path(path) if path is not None else _LIBRARY_PATH

    try:
        with open(target_path) as f:
            raw = f.read()
    except OSError as e:
        raise RecipeLibraryError(f"could not read recipe library at {target_path}: {e}")

    try:
        library = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RecipeLibraryError(f"recipe library at {target_path} is not valid JSON: {e}")

    errors = validate_recipe_library(library)
    if errors:
        raise RecipeLibraryError(
            f"recipe library at {target_path} failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return library


def _load_or_validate_library(library):
    """
    The one shared trust-boundary gate every public function in this
    module that accepts a `library` argument runs through before doing
    anything else with it (see this module's docstring, "EVERY PUBLIC
    LOOKUP VALIDATES A DIRECTLY-SUPPLIED LIBRARY FIRST").

    library=None loads and validates the real file, exactly like
    calling load_recipe_library() directly. A directly-supplied library
    is validated on the spot with validate_recipe_library(); if that
    reports any error at all, raises RecipeLibraryError immediately --
    the same exception, the same message format, as a broken library
    loaded from disk -- and the caller never proceeds to search it.

    Returns the (now known-valid) library dict, read-only from this
    point on.
    """
    if library is None:
        return load_recipe_library()
    errors = validate_recipe_library(library)
    if errors:
        raise RecipeLibraryError(
            "supplied library failed validation:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return library


def _find_recipe_by_pattern_id_in(pattern_id, library):
    """Unchecked lookup against a library ALREADY KNOWN to be valid --
    never call with a library that hasn't gone through
    _load_or_validate_library() or validate_recipe_library() first.
    Exists so resolve_stitch_recipe() can validate its library once per
    call instead of once per lookup term; see find_recipe_by_pattern_id()
    for the safe, independently-validating public version."""
    for recipe in library.get("recipes", []):
        if isinstance(recipe, dict) and recipe.get("pattern_id") == pattern_id:
            return recipe
    return None


def _find_recipe_by_name_in(name, library):
    """Unchecked lookup against a library ALREADY KNOWN to be valid --
    see _find_recipe_by_pattern_id_in()'s docstring; find_recipe_by_name()
    is the safe, independently-validating public version."""
    normalized_target = normalize_stitch_name(name)
    matches = []
    for recipe in library.get("recipes", []):
        if not isinstance(recipe, dict):
            continue
        terms = [recipe.get("name", "")] + list(recipe.get("aliases") or [])
        for term in terms:
            if not isinstance(term, str):
                continue
            if normalize_stitch_name(term) == normalized_target:
                matches.append(recipe)
                break
    return matches


def find_recipe_by_pattern_id(pattern_id, library=None):
    """
    Returns the recipe whose pattern_id exactly equals pattern_id, or
    None if no recipe in the library has that pattern_id.

    library defaults to load_recipe_library() (the real production
    library) if not supplied; a directly-supplied library is validated
    with validate_recipe_library() before it is ever searched, raising
    RecipeLibraryError immediately if it fails (see
    _load_or_validate_library()) -- this function never selects from,
    or even scans, an unvalidated library. pattern_id is compared
    exactly (it is an identifier, not a display name) -- never
    normalized.

    A library that passed validation cannot contain two recipes with
    the same pattern_id (validate_recipe_library() rejects that), so
    this never needs to consider ambiguity the way find_recipe_by_name()
    does.
    """
    library = _load_or_validate_library(library)
    return _find_recipe_by_pattern_id_in(pattern_id, library)


def find_recipe_by_name(name, library=None):
    """
    Returns a LIST of every recipe in the library whose own name, or
    any one of its declared aliases, normalizes (see
    normalize_stitch_name()) to the same value as `name`.

    library defaults to load_recipe_library() (the real production
    library) if not supplied; a directly-supplied library is validated
    with validate_recipe_library() before it is ever searched, raising
    RecipeLibraryError immediately if it fails (see
    _load_or_validate_library()) -- this function never selects from,
    or even scans, an unvalidated library.

    Deliberately returns a list rather than a single recipe-or-None:
    an empty list means no match; a list of exactly one means an
    unambiguous match; a list of more than one means this specific
    term is ambiguous in the library that was searched. This function
    NEVER picks one match over another when there is more than one --
    "do not guess when two recipes match" -- so it always hands back
    everything that matched and leaves the decision (report ambiguity,
    refuse to proceed) to the caller (resolve_stitch_recipe() reports
    this as an ambiguous_match result). Because this function's library
    is now always validated first, and validate_recipe_library()
    rejects an ambiguous normalized term outright, this can only ever
    return more than one entry in practice if the SAME term matches two
    recipes through different fields in a way validate_recipe_library()
    doesn't already forbid -- it never happens for a well-formed
    library, but this function still refuses to guess if it somehow did.
    """
    library = _load_or_validate_library(library)
    return _find_recipe_by_name_in(name, library)


def _compare_step_lists(path_label, ai_steps, library_steps, differences):
    ai_steps = ai_steps if isinstance(ai_steps, list) else []
    library_steps = library_steps if isinstance(library_steps, list) else []

    if len(ai_steps) != len(library_steps):
        differences.append({
            "path": f"{path_label}.length",
            "ai_value": len(ai_steps),
            "library_value": len(library_steps),
        })

    for i in range(min(len(ai_steps), len(library_steps))):
        ai_step = ai_steps[i] if isinstance(ai_steps[i], dict) else {}
        library_step = library_steps[i] if isinstance(library_steps[i], dict) else {}
        for field in _STEP_FIELDS:
            ai_value = ai_step.get(field)
            library_value = library_step.get(field)
            if ai_value != library_value:
                differences.append({
                    "path": f"{path_label}[{i}].{field}",
                    "ai_value": ai_value,
                    "library_value": library_value,
                })


def compare_recipe_proposal(ai_recipe, library_recipe):
    """
    Structural, deterministic, field-by-field comparison of two v2
    recipes -- an AI proposal and a library recipe (trusted or not; this
    function doesn't check or care). Reports agreement and
    disagreement only; it never decides which recipe (if either) is
    physically correct.

    Compares, with exact field paths in every reported difference:
      - pattern_id
      - name and aliases, as NORMALIZED SETS (see normalize_stitch_name()
        -- "Filet Mesh" vs "filet mesh" is not reported as a difference,
        but a genuinely different or missing alias is)
      - foundation_formula.repeat_multiple, foundation_formula.additional_chains
      - row_1.setup, row_1.repeat, later_rows.setup, later_rows.repeat
        -- each step list compared INDEX BY INDEX (a length mismatch is
        reported as "<path>.length" in addition to comparing every
        index the two lists have in common, so a reordering or a
        different step count is never hidden behind matching totals),
        each step's stitch/count/placement/counts_as compared
        individually (e.g. "row_1.repeat[1].placement",
        "later_rows.setup[0].counts_as")
      - expected_swatch_structure.expected_stitch_posts_per_repeat,
        expected_swatch_structure.expected_chain_spaces_per_repeat

    Never compares only totals -- two recipes with equal aggregate
    stitch counts but different step order or placement are reported
    as differing at the specific index/field where they diverge.

    Returns:
      {"matches": bool,           # True only if no differences at all
       "differences": [{"path": str, "ai_value": ..., "library_value": ...}, ...]}

    Both inputs are read only -- never mutated, never assumed to already
    be schema-valid (missing/malformed fields are treated as absent
    rather than raising, so this can be called even on a
    invalid_ai_proposal's ai_recipe for diagnostic purposes).
    """
    differences = []

    ai_recipe = ai_recipe if isinstance(ai_recipe, dict) else {}
    library_recipe = library_recipe if isinstance(library_recipe, dict) else {}

    if ai_recipe.get("pattern_id") != library_recipe.get("pattern_id"):
        differences.append({
            "path": "pattern_id",
            "ai_value": ai_recipe.get("pattern_id"),
            "library_value": library_recipe.get("pattern_id"),
        })

    ai_name = ai_recipe.get("name")
    library_name = library_recipe.get("name")
    ai_name_norm = normalize_stitch_name(ai_name) if isinstance(ai_name, str) else None
    library_name_norm = normalize_stitch_name(library_name) if isinstance(library_name, str) else None
    if ai_name_norm != library_name_norm:
        differences.append({"path": "name", "ai_value": ai_name, "library_value": library_name})

    ai_aliases = [a for a in (ai_recipe.get("aliases") or []) if isinstance(a, str)]
    library_aliases = [a for a in (library_recipe.get("aliases") or []) if isinstance(a, str)]
    ai_aliases_norm = {normalize_stitch_name(a) for a in ai_aliases}
    library_aliases_norm = {normalize_stitch_name(a) for a in library_aliases}
    if ai_aliases_norm != library_aliases_norm:
        differences.append({
            "path": "aliases",
            "ai_value": sorted(ai_aliases_norm),
            "library_value": sorted(library_aliases_norm),
        })

    ai_formula = ai_recipe.get("foundation_formula") if isinstance(ai_recipe.get("foundation_formula"), dict) else {}
    library_formula = library_recipe.get("foundation_formula") if isinstance(library_recipe.get("foundation_formula"), dict) else {}
    for field in _FOUNDATION_FIELDS:
        ai_value = ai_formula.get(field)
        library_value = library_formula.get(field)
        if ai_value != library_value:
            differences.append({
                "path": f"foundation_formula.{field}",
                "ai_value": ai_value,
                "library_value": library_value,
            })

    for section, key, path_label in _STEP_LIST_PATHS:
        ai_section = ai_recipe.get(section) if isinstance(ai_recipe.get(section), dict) else {}
        library_section = library_recipe.get(section) if isinstance(library_recipe.get(section), dict) else {}
        _compare_step_lists(path_label, ai_section.get(key), library_section.get(key), differences)

    ai_expected = ai_recipe.get("expected_swatch_structure") if isinstance(ai_recipe.get("expected_swatch_structure"), dict) else {}
    library_expected = library_recipe.get("expected_swatch_structure") if isinstance(library_recipe.get("expected_swatch_structure"), dict) else {}
    for field in _EXPECTED_STRUCTURE_FIELDS:
        ai_value = ai_expected.get(field)
        library_value = library_expected.get(field)
        if ai_value != library_value:
            differences.append({
                "path": f"expected_swatch_structure.{field}",
                "ai_value": ai_value,
                "library_value": library_value,
            })

    return {"matches": len(differences) == 0, "differences": differences}


def _lookup_term(kind, raw, normalized=None):
    return {"kind": kind, "raw": raw, "normalized": normalized}


def resolve_stitch_recipe(ai_proposal, library=None):
    """
    Resolves an AI-proposed v2 recipe against the trusted recipe
    library, deciding which recipe (if any) is safe to use for real,
    user-facing output.

    library defaults to load_recipe_library() (the real production
    library) if not supplied.

    TRUST BOUNDARY: the library is validated BEFORE anything is
    searched, every time, regardless of where it came from. Raises
    RecipeLibraryError immediately -- the exact same exception
    load_recipe_library() raises for a broken file -- if a
    directly-supplied `library` fails validate_recipe_library() (bad
    top-level shape, an unsupported schema_version, any malformed
    recipe, a duplicate pattern_id, or an ambiguous shared alias). This
    is deliberate and unconditional: a hand-built or externally-supplied
    library dict claiming a recipe is verification.status == "CONFIRMED"
    is NEVER searched, matched, or selected unless it has actually
    passed validate_recipe_v2() as part of a library that as a whole
    passed validate_recipe_library() -- there is no path through this
    function that reaches is_recipe_trusted() on a recipe from an
    unvalidated library. (See this module's docstring, "EVERY PUBLIC
    LOOKUP VALIDATES A DIRECTLY-SUPPLIED LIBRARY FIRST".)

    Process:
      1. Validates the library (see TRUST BOUNDARY above) -- raises
         before touching ai_proposal at all if the library itself is
         broken.
      2. Validates ai_proposal with validate_recipe_v2(). A
         structurally invalid proposal short-circuits immediately as
         invalid_ai_proposal -- nothing is looked up, since pattern_id/
         name/aliases can't be trusted to even mean what they claim.
      3. Searches the (now known-valid) library deterministically, in
         this fixed order: pattern_id first (the most specific,
         guaranteed-unique identifier), then name, then every declared
         alias. Every attempted term is recorded in "lookup_terms"
         regardless of whether it matched.
      4. Every recipe matched by ANY of those terms is collected
         (deduplicated by pattern_id). Zero matches -> no_match. More
         than one DISTINCT recipe matched -> ambiguous_match, naming
         every conflicting pattern_id -- this function never guesses
         which one the AI "must have meant." Because the library is
         now always valid by this point (no duplicate pattern_id, no
         ambiguous shared alias within it), this can only happen when
         the AI PROPOSAL's own name and one of its own aliases
         independently match two DIFFERENT, individually unambiguous
         library recipes -- not from any defect in the library itself.
      5. Exactly one matched recipe -> trusted_match if
         is_recipe_trusted() is True for it, otherwise untrusted_match.

    Returns a dict:
      {"status": one of STATUS_TRUSTED_MATCH / STATUS_UNTRUSTED_MATCH /
                 STATUS_NO_MATCH / STATUS_AMBIGUOUS_MATCH /
                 STATUS_INVALID_AI_PROPOSAL,
       "lookup_terms": [{"kind": "pattern_id"|"name"|"alias",
                          "raw": str, "normalized": str|None}, ...],
       "matched_recipe": <recipe dict> | None,
           # the single library recipe that matched, regardless of
           # trust -- present for trusted_match and untrusted_match,
           # None for every other status.
       "trusted": bool,
           # True only when matched_recipe is not None AND
           # is_recipe_trusted(matched_recipe) is True.
       "selected_recipe": <recipe dict> | None,
           # the recipe this function says is SAFE to use for real
           # output -- equals matched_recipe when status is
           # trusted_match, otherwise always None. This is the field a
           # caller should actually build a swatch/pattern from.
       "provenance": "library" | None,
           # where selected_recipe came from -- "library" when there is
           # one, otherwise None. Never "ai": no path in this module
           # promotes a fresh AI proposal to selected/trusted status.
       "ai_proposal_usable_for_user_instructions": False,
           # ALWAYS False. Phase 6 has no mechanism by which a fresh AI
           # proposal itself becomes trusted output -- only a
           # pre-existing library recipe already at CONFIRMED can be
           # selected. This field exists so callers never have to
           # wonder or infer that; it is stated outright.
       "comparison": <compare_recipe_proposal() result> | None,
           # present whenever matched_recipe is not None (trusted_match
           # or untrusted_match); None otherwise. Lets a caller see
           # exactly how the AI's proposal differs from whichever
           # recipe (trusted or not) matched its identification, purely
           # for diagnostics -- never used by this function to decide
           # trust.
       "conflicting_pattern_ids": [str, ...] | None,
           # present only for ambiguous_match; every pattern_id that
           # matched one of the attempted lookup terms.
       "errors": [str, ...],
           # validate_recipe_v2()'s errors for invalid_ai_proposal;
           # empty for every other status (a mismatch or ambiguity is
           # not itself an "error" in this list -- see "status" and
           # "conflicting_pattern_ids" instead).
       "ai_proposal": <deep copy of ai_proposal, or the original value
                       unchanged if it wasn't a dict at all>}
           # preserved unconditionally, for comparison and diagnostics,
           # regardless of outcome -- this function never mutates the
           # caller's ai_proposal, and returns an independent copy so a
           # caller mutating the result can't corrupt the input either.

    TRUSTED-MATCH: selected_recipe is set to the LIBRARY recipe, never
    the AI's own instructions, even when they happen to agree exactly
    (compare_recipe_proposal() can be consulted to see whether they do)
    -- the library recipe overrides the AI proposal by construction,
    not by comparison outcome.

    NO-MATCH: selected_recipe stays None and provenance stays None; the
    AI proposal is preserved in "ai_proposal" as unverified candidate
    data only. Nothing here marks it physically confirmed or generates
    final user-facing instructions from it.

    AMBIGUOUS-MATCH: selected_recipe stays None; every conflicting
    pattern_id is listed in "conflicting_pattern_ids" rather than this
    function picking the first (or any) match on the caller's behalf.

    Never mutates ai_proposal or any recipe read from the library.
    """
    library = _load_or_validate_library(library)

    schema_errors = validate_recipe_v2(ai_proposal)
    ai_proposal_copy = deepcopy(ai_proposal) if isinstance(ai_proposal, dict) else ai_proposal

    if schema_errors:
        return {
            "status": STATUS_INVALID_AI_PROPOSAL,
            "lookup_terms": [],
            "matched_recipe": None,
            "trusted": False,
            "selected_recipe": None,
            "provenance": None,
            "ai_proposal_usable_for_user_instructions": False,
            "comparison": None,
            "conflicting_pattern_ids": None,
            "errors": schema_errors,
            "ai_proposal": ai_proposal_copy,
        }

    lookup_terms = []
    matched_by_pattern_id = {}

    # Uses the private, unchecked _..._in() helpers here, not the public
    # find_recipe_by_pattern_id()/find_recipe_by_name() -- `library` was
    # already validated once above (_load_or_validate_library()); this
    # avoids re-running validate_recipe_library() on the same library
    # once per lookup term.
    pattern_id = ai_proposal.get("pattern_id")
    lookup_terms.append(_lookup_term("pattern_id", pattern_id))
    by_id = _find_recipe_by_pattern_id_in(pattern_id, library)
    if by_id is not None:
        matched_by_pattern_id[by_id["pattern_id"]] = by_id

    name = ai_proposal.get("name")
    if isinstance(name, str):
        lookup_terms.append(_lookup_term("name", name, normalize_stitch_name(name)))
        for match in _find_recipe_by_name_in(name, library):
            matched_by_pattern_id[match["pattern_id"]] = match

    for alias in ai_proposal.get("aliases") or []:
        if not isinstance(alias, str):
            continue
        lookup_terms.append(_lookup_term("alias", alias, normalize_stitch_name(alias)))
        for match in _find_recipe_by_name_in(alias, library):
            matched_by_pattern_id[match["pattern_id"]] = match

    matches = list(matched_by_pattern_id.values())

    if len(matches) == 0:
        return {
            "status": STATUS_NO_MATCH,
            "lookup_terms": lookup_terms,
            "matched_recipe": None,
            "trusted": False,
            "selected_recipe": None,
            "provenance": None,
            "ai_proposal_usable_for_user_instructions": False,
            "comparison": None,
            "conflicting_pattern_ids": None,
            "errors": [],
            "ai_proposal": ai_proposal_copy,
        }

    if len(matches) > 1:
        return {
            "status": STATUS_AMBIGUOUS_MATCH,
            "lookup_terms": lookup_terms,
            "matched_recipe": None,
            "trusted": False,
            "selected_recipe": None,
            "provenance": None,
            "ai_proposal_usable_for_user_instructions": False,
            "comparison": None,
            "conflicting_pattern_ids": sorted(matched_by_pattern_id.keys()),
            "errors": [],
            "ai_proposal": ai_proposal_copy,
        }

    matched_recipe = matches[0]
    trusted = is_recipe_trusted(matched_recipe)
    comparison = compare_recipe_proposal(ai_proposal, matched_recipe)

    return {
        "status": STATUS_TRUSTED_MATCH if trusted else STATUS_UNTRUSTED_MATCH,
        "lookup_terms": lookup_terms,
        "matched_recipe": matched_recipe,
        "trusted": trusted,
        "selected_recipe": matched_recipe if trusted else None,
        "provenance": "library" if trusted else None,
        "ai_proposal_usable_for_user_instructions": False,
        "comparison": comparison,
        "conflicting_pattern_ids": None,
        "errors": [],
        "ai_proposal": ai_proposal_copy,
    }
