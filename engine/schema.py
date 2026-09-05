"""
Validates the structured shapes the AI integration produces (and, since
Phase 2, the designed-but-not-yet-wired-in v2 recipe model), against
contracts/proposal_schema_v3.json, contracts/stitch_recipe_schema_v1.json,
and contracts/stitch_recipe_schema_v2.json. The project has no external
dependencies, so this enforces the same rules in plain Python rather
than pulling in a JSON Schema library -- the .json files are the
language-agnostic reference, this module is what actually runs.

v3, not v2 (proposal, not recipe -- see below for why "v2" means two
different things in this file): the photo call only IDENTIFIES stitch
regions (region_label, stitch_family, confidence, uncertain_fields) --
it no longer proposes any row structure. A photo-grounded call kept
inventing garment-specific numbers (oversized setup chains, inconsistent
turning chains) when asked to propose row structure from an image, but
the same model gives correct, standard answers when asked generically
how a named stitch is conventionally constructed, with no image
involved. proposal_schema_v1.json and proposal_schema_v2.json are kept
around, marked superseded, as a record of that evolution.

validate_recipe() checks the shape of that separate, non-photo recipe
call's response (engine/vision.py's get_stitch_recipe()) --
setup/repeat/turning_chain step lists, no absolute foundation chain
count anywhere in the shape at all. This is still what production code
actually uses; it is UNCHANGED by the addition below.

validate_recipe_v2() is new in Phase 2: it validates the canonical
recipe-model-v2 shape designed in docs/recipe_model_v2.md (identity,
a foundation-length formula, separate row_1/later_rows with a
context-restricted placement per step, an optional structured
counts_as, expected swatch structure, and a graduated verification
status). Nothing in production calls this yet -- see
docs/recipe_model_v2.md's "Status: design only" note and Phase 2's own
scope boundaries. It is a completely separate function/set of helpers
from validate_recipe()'s v1 path; the existing v1 _validate_step() and
_validate_step_list() are untouched and still used exactly as before.
"""

from engine.validator import STITCH_RULES

PROPOSAL_SCHEMA_VERSION = "3.0.0"
RECIPE_SCHEMA_VERSION = "1.0.0"
RECIPE_V2_SCHEMA_VERSION = "2.0.0"

# Same vocabulary as validator.py's STITCH_RULES -- one source of truth
# instead of a second hardcoded list that could drift out of sync.
KNOWN_STITCHES = set(STITCH_RULES.keys())


def _validate_step(step, path, errors):
    if not isinstance(step, dict):
        errors.append(f"{path}: expected an object, got {type(step).__name__}")
        return
    stitch = step.get("stitch")
    if stitch not in KNOWN_STITCHES:
        errors.append(f"{path}.stitch: '{stitch}' is not a known stitch {sorted(KNOWN_STITCHES)}")
    count = step.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        errors.append(f"{path}.count: must be a positive integer, got {count!r}")


def _validate_step_list(steps, path, errors, allow_empty=True):
    if not isinstance(steps, list):
        errors.append(f"{path}: must be a list")
        return
    if not allow_empty and len(steps) == 0:
        errors.append(f"{path}: must be a non-empty list")
        return
    for i, step in enumerate(steps):
        _validate_step(step, f"{path}[{i}]", errors)


def _validate_region(region, path, errors):
    if not isinstance(region, dict):
        errors.append(f"{path}: expected an object, got {type(region).__name__}")
        return

    for field in ("region_label", "stitch_family", "confidence", "uncertain_fields"):
        if field not in region:
            errors.append(f"{path}: missing required field '{field}'")

    if "region_label" in region and not isinstance(region["region_label"], str):
        errors.append(f"{path}.region_label: must be a string")

    if "stitch_family" in region and not isinstance(region["stitch_family"], str):
        errors.append(f"{path}.stitch_family: must be a string")

    if "confidence" in region:
        confidence = region["confidence"]
        is_number = isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        if not is_number or not (0 <= confidence <= 1):
            errors.append(f"{path}.confidence: must be a number between 0 and 1, got {confidence!r}")

    if "uncertain_fields" in region:
        uf = region["uncertain_fields"]
        if not isinstance(uf, list) or not all(isinstance(x, str) for x in uf):
            errors.append(f"{path}.uncertain_fields: must be a list of strings")


def validate_proposal(proposal):
    """
    Checks a vision-model PHOTO proposal dict against the v3
    (identification-only) schema: a photo can contain multiple stitch
    regions, so this expects {"regions": [region, ...]}, each region
    being just region_label/stitch_family/confidence/uncertain_fields --
    no row structure. Returns a list of error strings -- an empty list
    means it's valid.
    """
    if not isinstance(proposal, dict):
        return [f"proposal must be an object, got {type(proposal).__name__}"]

    errors = []

    if "regions" not in proposal:
        errors.append("missing required field: 'regions'")
    else:
        regions = proposal["regions"]
        if not isinstance(regions, list) or len(regions) == 0:
            errors.append("regions: must be a non-empty list")
        else:
            for i, region in enumerate(regions):
                _validate_region(region, f"regions[{i}]", errors)

    return errors


def validate_recipe(recipe):
    """
    Checks a stitch-recipe response (engine/vision.py's
    get_stitch_recipe()) against the recipe schema: setup (step list,
    can be empty), repeat (step list, never empty), turning_chain (step
    list, can be empty) -- and nothing else. There is no field for an
    absolute foundation chain count anywhere in this shape; that's
    deliberate, not an oversight. Returns a list of error strings -- an
    empty list means it's valid.
    """
    if not isinstance(recipe, dict):
        return [f"recipe must be an object, got {type(recipe).__name__}"]

    errors = []

    for field in ("setup", "repeat", "turning_chain"):
        if field not in recipe:
            errors.append(f"recipe: missing required field '{field}'")

    if "setup" in recipe:
        _validate_step_list(recipe["setup"], "recipe.setup", errors, allow_empty=True)
    if "repeat" in recipe:
        _validate_step_list(recipe["repeat"], "recipe.repeat", errors, allow_empty=False)
    if "turning_chain" in recipe:
        _validate_step_list(recipe["turning_chain"], "recipe.turning_chain", errors, allow_empty=True)

    return errors


# ---------------------------------------------------------------------------
# Recipe model v2 (Phase 2) -- a separate, self-contained validator. Nothing
# above this line is read by any of it; nothing below is read by v1's
# validate_recipe() or validate_proposal(). See docs/recipe_model_v2.md for
# what every field below means and why.
# ---------------------------------------------------------------------------

# Same vocabulary as validator.py's STITCH_RULES / v1's KNOWN_STITCHES above
# -- one source of truth, not a second hardcoded list that could drift.
V2_KNOWN_STITCHES = KNOWN_STITCHES

V2_PLACEMENTS = frozenset({
    "working_loop", "next_foundation_chain", "next_stitch", "next_dc",
    "next_chain_space", "turning_chain", "same_stitch",
})

# Context-restricted placement sets (docs/recipe_model_v2.md's "PLACEMENT
# CONTEXT RULES"). row_1 uses ROW1_PLACEMENTS for BOTH its setup and repeat
# -- Phase 1 settled row_1's placement rules as one set covering the whole
# row, not split further. later_rows.setup and later_rows.repeat each get
# their own distinct set.
ROW1_PLACEMENTS = frozenset({"next_foundation_chain", "working_loop", "same_stitch"})
LATER_SETUP_PLACEMENTS = frozenset({
    "working_loop", "next_stitch", "next_dc", "next_chain_space", "turning_chain", "same_stitch",
})
LATER_REPEAT_PLACEMENTS = frozenset({
    "working_loop", "next_stitch", "next_dc", "next_chain_space", "same_stitch",
})

V2_VERIFICATION_STATUSES = (
    "AI_PROPOSED", "STRUCTURE_VALID", "MATH_VALID", "SIMULATION_VALID",
    "SWATCH_TESTED", "CONFIRMED", "REJECTED",
)


def _is_int_at_least(value, minimum):
    """True integer only -- bool is a Python int subclass, so it's explicitly excluded everywhere a count/chain-space/status-carrying number is checked."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _reject_unexpected_properties(obj, allowed_keys, path, errors):
    for key in obj:
        if key not in allowed_keys:
            errors.append(f"{path}: unexpected property '{key}'")


def _validate_v2_step(step, path, errors, allowed_placements, context_label):
    """
    Validates one v2 step against a context's allowed placement set (one
    of ROW1_PLACEMENTS / LATER_SETUP_PLACEMENTS / LATER_REPEAT_PLACEMENTS),
    plus the stitch/placement compatibility rules that apply everywhere:
    a CH step may only use working_loop or turning_chain; a non-CH step
    must not use either; counts_as is only ever valid on a CH step whose
    placement is turning_chain.
    """
    if not isinstance(step, dict):
        errors.append(f"{path}: expected an object, got {type(step).__name__}")
        return

    _reject_unexpected_properties(step, {"stitch", "count", "placement", "counts_as"}, path, errors)

    stitch = step.get("stitch")
    if "stitch" not in step:
        errors.append(f"{path}: missing required field 'stitch'")
    elif stitch not in V2_KNOWN_STITCHES:
        errors.append(f"{path}.stitch: '{stitch}' is not a known stitch {sorted(V2_KNOWN_STITCHES)}")

    if "count" not in step:
        errors.append(f"{path}: missing required field 'count'")
    else:
        count = step["count"]
        if not _is_int_at_least(count, 1):
            errors.append(f"{path}.count: must be a positive integer, got {count!r}")

    placement = step.get("placement")
    if "placement" not in step:
        errors.append(f"{path}: missing required field 'placement'")
    elif placement not in V2_PLACEMENTS:
        errors.append(f"{path}.placement: '{placement}' is not a known placement {sorted(V2_PLACEMENTS)}")
    elif placement not in allowed_placements:
        errors.append(
            f"{path}.placement: '{placement}' is not valid for {context_label} "
            f"(allowed here: {sorted(allowed_placements)})"
        )

    # Stitch/placement compatibility -- checked whenever both are at least
    # the right type, independent of whether either already failed an
    # earlier check above (a step can be wrong in more than one way at once).
    if isinstance(stitch, str) and isinstance(placement, str):
        if stitch == "CH":
            if placement not in ("working_loop", "turning_chain"):
                errors.append(
                    f"{path}: stitch CH must use placement 'working_loop' or 'turning_chain', got '{placement}'"
                )
        else:
            if placement in ("working_loop", "turning_chain"):
                errors.append(f"{path}: non-CH stitch '{stitch}' must not use placement '{placement}'")

    if "counts_as" in step:
        counts_as_ok_context = stitch == "CH" and placement == "turning_chain"
        if not counts_as_ok_context:
            errors.append(f"{path}.counts_as: only allowed on a CH step whose placement is turning_chain")
        _validate_counts_as(step["counts_as"], f"{path}.counts_as", errors)


def _validate_v2_step_list(steps, path, errors, allowed_placements, context_label, allow_empty):
    if not isinstance(steps, list):
        errors.append(f"{path}: must be a list")
        return
    if not allow_empty and len(steps) == 0:
        errors.append(f"{path}: must be a non-empty list")
        return
    for i, step in enumerate(steps):
        _validate_v2_step(step, f"{path}[{i}]", errors, allowed_placements, context_label)


def _validate_counts_as(counts_as, path, errors):
    """
    stitch_posts maps known stitch codes to nonnegative integers;
    chain_spaces is a nonnegative integer. Rejects a counts_as with no
    effect at all -- chain_spaces is 0 and every stitch_posts entry (if
    any) is also 0 -- since that communicates nothing beyond what
    omitting counts_as already means.
    """
    if not isinstance(counts_as, dict):
        errors.append(f"{path}: expected an object, got {type(counts_as).__name__}")
        return

    _reject_unexpected_properties(counts_as, {"stitch_posts", "chain_spaces"}, path, errors)

    stitch_posts = counts_as.get("stitch_posts")
    stitch_posts_valid = False
    if "stitch_posts" not in counts_as:
        errors.append(f"{path}: missing required field 'stitch_posts'")
    elif not isinstance(stitch_posts, dict):
        errors.append(f"{path}.stitch_posts: expected an object, got {type(stitch_posts).__name__}")
    else:
        stitch_posts_valid = True
        for stitch_key, value in stitch_posts.items():
            if stitch_key not in V2_KNOWN_STITCHES:
                errors.append(f"{path}.stitch_posts.{stitch_key}: '{stitch_key}' is not a known stitch {sorted(V2_KNOWN_STITCHES)}")
                stitch_posts_valid = False
            if not _is_int_at_least(value, 0):
                errors.append(f"{path}.stitch_posts.{stitch_key}: must be a nonnegative integer, got {value!r}")
                stitch_posts_valid = False

    chain_spaces = counts_as.get("chain_spaces")
    chain_spaces_valid = False
    if "chain_spaces" not in counts_as:
        errors.append(f"{path}: missing required field 'chain_spaces'")
    elif not _is_int_at_least(chain_spaces, 0):
        errors.append(f"{path}.chain_spaces: must be a nonnegative integer, got {chain_spaces!r}")
    else:
        chain_spaces_valid = True

    if stitch_posts_valid and chain_spaces_valid:
        if chain_spaces == 0 and all(v == 0 for v in stitch_posts.values()):
            errors.append(f"{path}: has no effect -- all stitch_posts counts are 0 and chain_spaces is 0")


def _validate_foundation_formula(formula, path, errors):
    if not isinstance(formula, dict):
        errors.append(f"{path}: expected an object, got {type(formula).__name__}")
        return

    _reject_unexpected_properties(formula, {"repeat_multiple", "additional_chains", "notes"}, path, errors)

    if "repeat_multiple" not in formula:
        errors.append(f"{path}: missing required field 'repeat_multiple'")
    else:
        value = formula["repeat_multiple"]
        if not _is_int_at_least(value, 1):
            errors.append(f"{path}.repeat_multiple: must be an integer >= 1, got {value!r}")

    if "additional_chains" not in formula:
        errors.append(f"{path}: missing required field 'additional_chains'")
    else:
        value = formula["additional_chains"]
        if not _is_int_at_least(value, 0):
            errors.append(f"{path}.additional_chains: must be an integer >= 0, got {value!r}")

    _validate_optional_notes(formula, path, errors)


def _validate_v2_row(row, path, errors, setup_placements, repeat_placements, setup_label, repeat_label):
    if not isinstance(row, dict):
        errors.append(f"{path}: expected an object, got {type(row).__name__}")
        return

    _reject_unexpected_properties(row, {"setup", "repeat", "notes"}, path, errors)

    if "setup" not in row:
        errors.append(f"{path}: missing required field 'setup'")
    else:
        _validate_v2_step_list(row["setup"], f"{path}.setup", errors, setup_placements, setup_label, allow_empty=True)

    if "repeat" not in row:
        errors.append(f"{path}: missing required field 'repeat'")
    else:
        _validate_v2_step_list(row["repeat"], f"{path}.repeat", errors, repeat_placements, repeat_label, allow_empty=False)

    _validate_optional_notes(row, path, errors)


def _validate_expected_swatch_structure(structure, path, errors):
    if not isinstance(structure, dict):
        errors.append(f"{path}: expected an object, got {type(structure).__name__}")
        return

    _reject_unexpected_properties(
        structure,
        {"expected_stitch_posts_per_repeat", "expected_chain_spaces_per_repeat", "notes"},
        path, errors,
    )

    for field in ("expected_stitch_posts_per_repeat", "expected_chain_spaces_per_repeat"):
        if field not in structure:
            errors.append(f"{path}: missing required field '{field}'")
        else:
            value = structure[field]
            if value is not None and not _is_int_at_least(value, 0):
                errors.append(f"{path}.{field}: must be null or a nonnegative integer, got {value!r}")

    _validate_optional_notes(structure, path, errors)


def _validate_confirmation(confirmation, path, errors):
    if not isinstance(confirmation, dict):
        errors.append(f"{path}: expected an object, got {type(confirmation).__name__}")
        return

    _reject_unexpected_properties(confirmation, {"photo", "date", "note"}, path, errors)

    for field in ("photo", "date", "note"):
        if field not in confirmation:
            errors.append(f"{path}: missing required field '{field}'")
        else:
            value = confirmation[field]
            if not isinstance(value, str) or len(value) == 0:
                errors.append(f"{path}.{field}: must be a non-empty string, got {value!r}")


def _validate_verification(verification, path, errors):
    if not isinstance(verification, dict):
        errors.append(f"{path}: expected an object, got {type(verification).__name__}")
        return

    _reject_unexpected_properties(verification, {"status", "confirmations", "reason"}, path, errors)

    status = verification.get("status")
    if "status" not in verification:
        errors.append(f"{path}: missing required field 'status'")
    elif status not in V2_VERIFICATION_STATUSES:
        errors.append(f"{path}.status: '{status}' is not a known status {V2_VERIFICATION_STATUSES}")

    confirmations = verification.get("confirmations")
    if "confirmations" not in verification:
        errors.append(f"{path}: missing required field 'confirmations'")
        confirmations = None
    elif not isinstance(confirmations, list):
        errors.append(f"{path}.confirmations: must be a list, got {type(confirmations).__name__}")
        confirmations = None
    else:
        for i, confirmation in enumerate(confirmations):
            _validate_confirmation(confirmation, f"{path}.confirmations[{i}]", errors)

    reason = verification.get("reason")
    reason_present = False
    if "reason" in verification:
        if not isinstance(reason, str) or len(reason) == 0:
            errors.append(f"{path}.reason: must be a non-empty string, got {reason!r}")
        else:
            reason_present = True

    # Status/confirmation/reason consistency -- only meaningful once status
    # and confirmations are individually well-formed.
    if status in V2_VERIFICATION_STATUSES and isinstance(confirmations, list):
        if status == "CONFIRMED" and len(confirmations) == 0:
            errors.append(f"{path}: status CONFIRMED requires at least one confirmation")
        if status == "SWATCH_TESTED" and len(confirmations) == 0:
            errors.append(f"{path}: status SWATCH_TESTED requires at least one confirmation")
    if status == "REJECTED" and not reason_present:
        errors.append(f"{path}: status REJECTED requires a non-empty 'reason'")


def _validate_optional_notes(obj, path, errors):
    if "notes" in obj:
        notes = obj["notes"]
        if not isinstance(notes, str) or len(notes) == 0:
            errors.append(f"{path}.notes: must be a non-empty string, got {notes!r}")


def validate_recipe_v2(recipe):
    """
    Checks a v2 recipe dict (docs/recipe_model_v2.md) against the
    canonical shape: pattern_id/name/aliases/terminology, a
    foundation_formula (meaning only -- no calculation performed here),
    row_1 and later_rows (each setup/repeat step lists, with a
    context-restricted placement per step), expected_swatch_structure,
    and a graduated verification status.

    Returns a list of readable error strings with precise paths (e.g.
    "recipe.row_1.repeat[1].placement", "recipe.verification.confirmations[0].date")
    -- an empty list means the recipe is structurally valid. This checks
    SHAPE and the context/compatibility rules Phase 1 settled clearly; it
    does not attempt foundation math, crochet correctness, or anything
    beyond what docs/recipe_model_v2.md's placement-context rules
    already state outright -- see that document for what remains an open
    physical question. Never crashes on wrong-typed nested data --
    every nested validator checks isinstance() before indexing further.
    """
    if not isinstance(recipe, dict):
        return [f"recipe must be an object, got {type(recipe).__name__}"]

    errors = []

    required_fields = (
        "pattern_id", "name", "aliases", "terminology",
        "foundation_formula", "row_1", "later_rows",
        "expected_swatch_structure", "verification",
    )
    allowed_top_level = set(required_fields) | {"notes", "known_issues"}

    _reject_unexpected_properties(recipe, allowed_top_level, "recipe", errors)

    for field in required_fields:
        if field not in recipe:
            errors.append(f"recipe: missing required field '{field}'")

    if "pattern_id" in recipe:
        value = recipe["pattern_id"]
        if not isinstance(value, str) or len(value) == 0:
            errors.append(f"recipe.pattern_id: must be a non-empty string, got {value!r}")

    if "name" in recipe:
        value = recipe["name"]
        if not isinstance(value, str) or len(value) == 0:
            errors.append(f"recipe.name: must be a non-empty string, got {value!r}")

    if "aliases" in recipe:
        aliases = recipe["aliases"]
        if not isinstance(aliases, list):
            errors.append(f"recipe.aliases: must be a list, got {type(aliases).__name__}")
        else:
            for i, alias in enumerate(aliases):
                if not isinstance(alias, str) or len(alias) == 0:
                    errors.append(f"recipe.aliases[{i}]: must be a non-empty string, got {alias!r}")

    if "terminology" in recipe:
        value = recipe["terminology"]
        if value not in ("US", "UK"):
            errors.append(f"recipe.terminology: must be 'US' or 'UK', got {value!r}")

    if "foundation_formula" in recipe:
        _validate_foundation_formula(recipe["foundation_formula"], "recipe.foundation_formula", errors)

    if "row_1" in recipe:
        _validate_v2_row(
            recipe["row_1"], "recipe.row_1", errors,
            setup_placements=ROW1_PLACEMENTS, repeat_placements=ROW1_PLACEMENTS,
            setup_label="row_1", repeat_label="row_1",
        )

    if "later_rows" in recipe:
        _validate_v2_row(
            recipe["later_rows"], "recipe.later_rows", errors,
            setup_placements=LATER_SETUP_PLACEMENTS, repeat_placements=LATER_REPEAT_PLACEMENTS,
            setup_label="later_rows.setup", repeat_label="later_rows.repeat",
        )

    if "expected_swatch_structure" in recipe:
        _validate_expected_swatch_structure(
            recipe["expected_swatch_structure"], "recipe.expected_swatch_structure", errors
        )

    if "verification" in recipe:
        _validate_verification(recipe["verification"], "recipe.verification", errors)

    _validate_optional_notes(recipe, "recipe", errors)

    if "known_issues" in recipe:
        known_issues = recipe["known_issues"]
        if not isinstance(known_issues, list):
            errors.append(f"recipe.known_issues: must be a list, got {type(known_issues).__name__}")
        else:
            for i, issue in enumerate(known_issues):
                if not isinstance(issue, str) or len(issue) == 0:
                    errors.append(f"recipe.known_issues[{i}]: must be a non-empty string, got {issue!r}")

    return errors
