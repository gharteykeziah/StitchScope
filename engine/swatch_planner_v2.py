"""
Phase 7: the trusted v2 swatch planner -- connects Phase 6's recipe
resolution and Phase 5's full row simulation into one pipeline that
either produces a complete, evidence-backed swatch plan, or refuses
clearly and explicitly, never a half-finished result someone could
mistake for real instructions.

CORE PIPELINE

    AI recipe proposal
        v
    Phase 6 recipe resolution (resolve_stitch_recipe())
        v
    require status == trusted_match, use ONLY selected_recipe
        v
    Phase 5 full row simulation (validate_recipe_rows(), on selected_recipe)
        v
    require valid simulation
        v
    build swatch plan (from selected_recipe + the validator's own results)
        v
    render instructions (engine/renderer_v2.py, a separate module)

This module never receives or analyzes an image -- it starts from an
already-structured AI proposal (the same v2 recipe shape Phase 6
already validates) and a caller-chosen requested_repeat_count/
later_row_count, exactly like calculate_foundation() and
validate_recipe_rows() already require those to be supplied by the
caller, never inferred from anything the AI claims.

THE PLANNER NEVER RENDERS TRUSTED-LOOKING INSTRUCTIONS FROM AN
UNTRUSTED AI PROPOSAL

Every field of the eventual swatch plan is built from
resolution["selected_recipe"] (the LIBRARY recipe) and the validators'
own results -- never from ai_proposal. This module never even reads
ai_proposal's own row_1/later_rows step lists for anything beyond what
resolve_stitch_recipe() already does internally to identify a match;
plan_trusted_swatch() itself only ever touches ai_proposal to pass it
to resolve_stitch_recipe() and to preserve it (via resolution's own
copy) for diagnostics. If resolution is anything other than
trusted_match, this module stops -- it never falls back to rendering
the AI's own proposal as if it were trustworthy output.

RELATIONSHIP TO THE EXISTING v1 SWATCH/RENDERER PATHWAY

engine/swatch.py (`build_test_foundation()`, `simulate_swatch()`) and
engine/renderer.py (`render_row()`) are a different, older pathway this
module does not touch, extend, or replace:
  - v1's `simulate_swatch()` works on flat, untyped step lists (no
    placement, no counts_as), tests EVERY row (including row 1) with
    the SAME externally-chosen `test_repeat_count`, and checks
    `consumed <= available` -- a "does this fit" question against a
    pool with no concept of stitch type or chain space, because the
    v1 step shape has no such concept to check.
  - v1's `render_row()` renders a flat setup+repeat step list with no
    placement-aware wording -- there is no "in the next chain space"
    vs "in the next stitch" distinction to render, because v1 steps
    don't carry a placement at all.
  - This module (and engine/renderer_v2.py) instead run entirely on
    the v2 recipe shape: typed, ordered, placement-aware validation
    (Phase 4A/5) and a recipe that has actually been resolved against
    a trust boundary (Phase 6) -- concepts v1 has no equivalent for.
Neither v1 module is imported here, and this module changes nothing
about how either of them behaves.

THIS MODULE DOES NOT DUPLICATE VALIDATOR LOGIC

plan_trusted_swatch() calls resolve_stitch_recipe() and
validate_recipe_rows() and reads their results; it never re-derives
foundation math, row math, or trust decisions itself. calculate_foundation()
is never called directly here either -- validate_recipe_rows() already
runs it internally and returns the result under "foundation", which
this module reuses rather than recomputing.

FOUR-INCH / GAUGE MEASUREMENT IS NOT IMPLEMENTED

The swatch plan states a repeat count and the resulting row/foundation
structure -- it never claims the swatch measures any particular
physical width (e.g. "four inches"). Relating repeat count to a
physical measurement requires gauge information this phase does not
have or compute; every ready plan's warnings say so explicitly.
"""

from copy import deepcopy

from engine.recipe_library import RecipeLibraryError, resolve_stitch_recipe, resolve_stitch_identity
from engine.recipe_validator import RecipeMathError
from engine.later_row_validator import validate_recipe_rows
from engine.renderer_v2 import render_swatch_plan
from engine.stitch_identification import validate_identification

STATUS_READY = "ready"
STATUS_NO_TRUSTED_RECIPE = "no_trusted_recipe"
STATUS_AMBIGUOUS_RECIPE = "ambiguous_recipe"
STATUS_INVALID_AI_PROPOSAL = "invalid_ai_proposal"
STATUS_INVALID_IDENTIFICATION = "invalid_identification"
STATUS_INVALID_LIBRARY = "invalid_library"
STATUS_SIMULATION_FAILED = "simulation_failed"
STATUS_SIMULATION_UNSUPPORTED = "simulation_unsupported"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_RENDER_UNSUPPORTED = "render_unsupported"

_FOUR_INCH_WARNING = (
    "This plan states a repeat count and the resulting row/foundation "
    "structure only -- it does not claim any physical measurement (e.g. "
    "\"four inches\"). Relating repeat count to a physical width requires "
    "gauge information this phase does not compute; measure a worked "
    "swatch by hand to know its actual size."
)


def _is_plain_positive_int(value, minimum):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _empty_result(status, requested_repeat_count, later_row_count, errors, warnings=None,
                   resolution=None, foundation=None, row_validation=None):
    return {
        "status": status,
        "ready_for_user_instructions": False,
        "resolution": resolution,
        "selected_recipe": None,
        "provenance": None,
        "requested_repeat_count": requested_repeat_count,
        "later_row_count": later_row_count,
        "foundation": foundation,
        "row_validation": row_validation,
        "swatch_plan": None,
        "rendered_instructions": None,
        "warnings": warnings or [],
        "errors": errors,
    }


def _invalid_request_result(requested_repeat_count, later_row_count):
    """
    Shared by plan_trusted_swatch() and plan_swatch_from_identification():
    validates requested_repeat_count/later_row_count with the exact rules
    the validators already use (plain int, bool excluded;
    requested_repeat_count >= 1; later_row_count >= 0). Returns an
    already-built STATUS_INVALID_REQUEST result if either is malformed,
    or None if both are fine -- a bad request never reaches resolution
    in either pipeline.
    """
    if not _is_plain_positive_int(requested_repeat_count, 1):
        return _empty_result(
            STATUS_INVALID_REQUEST, requested_repeat_count, later_row_count,
            errors=[f"requested_repeat_count must be a plain integer >= 1, got {requested_repeat_count!r}"],
        )
    if not _is_plain_positive_int(later_row_count, 0):
        return _empty_result(
            STATUS_INVALID_REQUEST, requested_repeat_count, later_row_count,
            errors=[f"later_row_count must be a plain integer >= 0, got {later_row_count!r}"],
        )
    return None


def _finish_pipeline_from_resolution(resolution, requested_repeat_count, later_row_count, ambiguous_context):
    """
    Shared tail of both plan_trusted_swatch() and
    plan_swatch_from_identification(): takes a resolution dict already
    produced by EITHER resolve_stitch_recipe() or resolve_stitch_identity()
    -- whose "status" is one of "no_match" / "untrusted_match" /
    "ambiguous_match" / "trusted_match" (never "invalid_ai_proposal";
    only resolve_stitch_recipe() can produce that, and callers handle it
    themselves before reaching here, since resolve_stitch_identity() has
    no equivalent status) -- and runs Phase 5 row simulation, structured
    plan-building, and rendering exactly once, so this logic exists in
    only one place for both pipelines.

    `ambiguous_context` is a short phrase describing what was looked up,
    used only to phrase the STATUS_AMBIGUOUS_RECIPE error message (e.g.
    "the AI proposal's identification" or "the identified stitch_name
    'filet mesh' / aliases") -- purely cosmetic, never affects behavior.

    Returns the same shaped result dict plan_trusted_swatch() documents
    in its own docstring (STATUS_AMBIGUOUS_RECIPE / STATUS_NO_TRUSTED_RECIPE
    / STATUS_SIMULATION_UNSUPPORTED / STATUS_SIMULATION_FAILED /
    STATUS_RENDER_UNSUPPORTED / STATUS_READY), built the same way
    regardless of which resolver produced `resolution`.
    """
    if resolution["status"] == "ambiguous_match":
        return _empty_result(
            STATUS_AMBIGUOUS_RECIPE, requested_repeat_count, later_row_count,
            errors=[
                f"{ambiguous_context} matches more than one library recipe: "
                f"{resolution['conflicting_pattern_ids']}"
            ],
            resolution=resolution,
        )
    if resolution["status"] in ("no_match", "untrusted_match"):
        return _empty_result(
            STATUS_NO_TRUSTED_RECIPE, requested_repeat_count, later_row_count,
            errors=[], resolution=resolution,
        )

    # resolution["status"] == "trusted_match" from here on.
    selected_recipe = resolution["selected_recipe"]

    try:
        row_validation = validate_recipe_rows(selected_recipe, requested_repeat_count, later_row_count)
    except RecipeMathError as e:
        return _empty_result(
            STATUS_SIMULATION_UNSUPPORTED, requested_repeat_count, later_row_count,
            errors=[str(e)], resolution=resolution,
        )

    if not row_validation["valid"]:
        return _empty_result(
            STATUS_SIMULATION_FAILED, requested_repeat_count, later_row_count,
            errors=[
                f"row-by-row simulation failed at row {row_validation['first_failing_row']}"
                if row_validation["first_failing_row"] is not None
                else "row-by-row simulation reported invalid without a specific failing row"
            ],
            resolution=resolution,
            foundation=row_validation["foundation"],
            row_validation=row_validation,
        )

    swatch_plan = _build_swatch_plan(selected_recipe, requested_repeat_count, later_row_count, row_validation)
    render_result = render_swatch_plan(swatch_plan)
    warnings = list(swatch_plan["warnings"]) + list(render_result.get("warnings", []))

    if render_result["status"] != "rendered":
        # Every earlier check passed (trusted match, valid simulation),
        # but the trusted recipe's own terminology isn't one this
        # renderer implements -- report clearly, never silently render
        # US wording for a different terminology system, and never
        # claim "ready" when there are no rendered instructions to use.
        return {
            "status": STATUS_RENDER_UNSUPPORTED,
            "ready_for_user_instructions": False,
            "resolution": resolution,
            "selected_recipe": selected_recipe,
            "provenance": "library",
            "requested_repeat_count": requested_repeat_count,
            "later_row_count": later_row_count,
            "foundation": row_validation["foundation"],
            "row_validation": row_validation,
            "swatch_plan": swatch_plan,
            "rendered_instructions": None,
            "warnings": warnings,
            "errors": list(render_result["errors"]),
        }

    return {
        "status": STATUS_READY,
        "ready_for_user_instructions": True,
        "resolution": resolution,
        "selected_recipe": selected_recipe,
        "provenance": "library",
        "requested_repeat_count": requested_repeat_count,
        "later_row_count": later_row_count,
        "foundation": row_validation["foundation"],
        "row_validation": row_validation,
        "swatch_plan": swatch_plan,
        "rendered_instructions": render_result["text"],
        "warnings": warnings,
        "errors": [],
    }


def _build_swatch_plan(selected_recipe, requested_repeat_count, later_row_count, row_validation):
    """
    Builds the structured swatch plan from the SELECTED TRUSTED RECIPE
    and the validators' own results -- never from an AI proposal, never
    inventing a step list of its own. Every step list embedded here is
    a deep copy of the trusted recipe's own data, so nothing a caller
    later does to the returned plan can ever mutate the library recipe
    it came from.

    Every plan this function returns carries "ready_for_rendering": True
    -- this function only ever runs after resolution and simulation have
    both already succeeded (see plan_trusted_swatch()), so a plan that
    exists at all is, by construction, one engine/renderer_v2.py may
    read fields from. render_swatch_plan() checks for this flag (and
    the rest of the plan's shape) itself before reading anything else,
    rather than trusting that whatever it's handed came from here.
    """
    row_1_report = row_validation["row_1"]
    later_row_reports = row_validation["later_rows"]

    later_row_summaries = [
        {
            "row_number": report["row_number"],
            "repeat_execution_count": report["repeat_execution_count"],
            "valid": report["valid"],
        }
        for report in later_row_reports
    ]

    verification = selected_recipe.get("verification", {})

    warnings = [_FOUR_INCH_WARNING]
    if later_row_count == 0:
        warnings.append(
            "later_row_count was 0 -- this plan covers only the foundation and row 1; "
            "no later rows were requested or validated."
        )

    return {
        "ready_for_rendering": True,
        "pattern_id": selected_recipe["pattern_id"],
        "name": selected_recipe["name"],
        "terminology": selected_recipe["terminology"],
        "trust": {
            "verification_status": verification.get("status"),
            "provenance": "library",
        },
        "requested_repeat_count": requested_repeat_count,
        "total_rows": 1 + later_row_count,
        "foundation_chain_count": row_validation["foundation"]["foundation_count"],
        "foundation_formula": dict(row_validation["foundation"]),
        "row_1_setup": deepcopy(selected_recipe["row_1"]["setup"]),
        "row_1_repeat": deepcopy(selected_recipe["row_1"]["repeat"]),
        "row_1_repeat_execution_count": requested_repeat_count,
        "later_row_setup": deepcopy(selected_recipe["later_rows"]["setup"]),
        "later_row_repeat": deepcopy(selected_recipe["later_rows"]["repeat"]),
        "later_rows": later_row_summaries,
        "validation_evidence": {
            "row_1_valid": row_1_report["valid"],
            "row_1_consumed_foundation_positions": row_1_report["row_1"]["consumed_foundation_positions"],
            "later_rows_valid": all(r["valid"] for r in later_row_reports),
            "overall_valid": row_validation["valid"],
        },
        "warnings": warnings,
    }


def plan_trusted_swatch(ai_proposal, requested_repeat_count, later_row_count, library=None):
    """
    Runs the full Phase 6 -> Phase 5 -> plan -> render pipeline for one
    AI-proposed recipe, returning a single structured result -- never an
    uncaught traceback for any of the failure modes this module knows
    about (a bad request, an unusable library, an unresolved or
    untrusted recipe, or a failing/unsupportable simulation).

    Parameters:
      ai_proposal            -- a v2 recipe dict (or malformed input --
                                 this function never assumes it's valid).
      requested_repeat_count -- caller-chosen int >= 1, exactly like
                                 calculate_foundation()/
                                 validate_row_1_against_foundation()
                                 already require; never read from
                                 ai_proposal.
      later_row_count        -- caller-chosen int >= 0, exactly like
                                 validate_recipe_rows() already requires.
      library                -- optional; defaults to the real
                                 production library (see
                                 engine/recipe_library.py). A directly
                                 -supplied library is validated before
                                 anything is resolved against it (Phase
                                 6's trust boundary), so an invalid one
                                 here also produces STATUS_INVALID_LIBRARY,
                                 never an uncaught RecipeLibraryError.

    Process (see this module's docstring, CORE PIPELINE):
      1. Validates requested_repeat_count and later_row_count itself,
         with the exact same rules the validators already use (plain
         int, bool excluded; requested_repeat_count >= 1; later_row_count
         >= 0) -- a bad request never even reaches resolution.
      2. Calls resolve_stitch_recipe(ai_proposal, library). Any
         RecipeLibraryError it raises (an invalid library, whether the
         default file or a directly-supplied one) is caught here and
         reported as STATUS_INVALID_LIBRARY -- never propagated as an
         uncaught exception.
      3. Inspects the resolution status:
           - invalid_ai_proposal  -> STATUS_INVALID_AI_PROPOSAL
           - ambiguous_match      -> STATUS_AMBIGUOUS_RECIPE
           - no_match             -> STATUS_NO_TRUSTED_RECIPE
           - untrusted_match      -> STATUS_NO_TRUSTED_RECIPE (a name/id
             match existing in the library is not itself permission to
             use it; only trusted_match is. The full resolution dict --
             including matched_recipe and the comparison against it --
             is still returned under "resolution" for diagnostics.)
           - trusted_match        -> continue, using ONLY
             resolution["selected_recipe"] from here on. ai_proposal's
             own row_1/later_rows are never read again.
      4. Calls validate_recipe_rows(selected_recipe, requested_repeat_count,
         later_row_count). Any RecipeMathError it raises (one of Phase
         4A/5's "refuses to guess" semantic cases -- e.g. a same_stitch
         with no established target, or the next_dc/counts_as
         eligibility gap) is caught and reported as
         STATUS_SIMULATION_UNSUPPORTED, carrying the exception's message
         in "errors" -- this is different from an ordinary math
         mismatch, which validate_recipe_rows() reports as valid: False
         rather than raising.
      5. If validate_recipe_rows() returns normally but its own "valid"
         is False, reports STATUS_SIMULATION_FAILED, carrying the full
         "row_validation" report so a caller can see exactly which row
         failed and why (see validate_recipe_rows()'s own
         "first_failing_row").
      6. Only once every prior step has passed does this build the
         structured swatch plan (see _build_swatch_plan()) and call
         engine/renderer_v2.py's render_swatch_plan() on it. If
         rendering itself succeeds, returns STATUS_READY. If the
         trusted recipe's own terminology isn't one the renderer
         implements, returns STATUS_RENDER_UNSUPPORTED instead --
         every earlier check passed, but this module never silently
         renders one terminology's wording for another, and never
         reports "ready" when there is no rendered text to use.

    Returns a dict:
      {"status": one of the STATUS_* constants above,
       "ready_for_user_instructions": bool,   # True ONLY for STATUS_READY
       "resolution": <resolve_stitch_recipe() result> | None,
           # None only for STATUS_INVALID_REQUEST and STATUS_INVALID_LIBRARY
           # (resolution was never attempted, or the library it would
           # have run against was itself unusable).
       "selected_recipe": <recipe dict> | None,
           # the trusted library recipe, present for STATUS_READY and
           # STATUS_RENDER_UNSUPPORTED (resolution and simulation both
           # succeeded in that case; only rendering the text did not).
       "provenance": "library" | None,
           # "library" whenever selected_recipe is present, else None --
           # this module never produces a plan whose provenance is "ai".
       "requested_repeat_count": <as given>,
       "later_row_count": <as given>,
       "foundation": <calculate_foundation() result, via row_validation> | None,
       "row_validation": <validate_recipe_rows() result> | None,
           # present whenever validate_recipe_rows() actually ran and
           # returned (STATUS_SIMULATION_FAILED, STATUS_RENDER_UNSUPPORTED,
           # and STATUS_READY); None for every earlier-stopping status.
       "swatch_plan": <structured plan dict, see _build_swatch_plan()> | None,
           # present for STATUS_READY and STATUS_RENDER_UNSUPPORTED --
           # the structured data was built successfully either way; only
           # the rendered TEXT is status-dependent.
       "rendered_instructions": <str> | None,
           # present ONLY for STATUS_READY.
       "warnings": [str, ...],
       "errors": [str, ...]}

    For every non-ready outcome, "ready_for_user_instructions" is False
    and "rendered_instructions" is None -- this function never returns
    partial crochet instructions that could be mistaken for a usable
    pattern.

    Never mutates ai_proposal, the library, any recipe read from it, or
    any validator report -- resolve_stitch_recipe() and
    validate_recipe_rows() already guarantee this for their own inputs;
    this function additionally deep-copies every step list it embeds in
    "swatch_plan" so mutating the returned plan can never reach back
    into the trusted library recipe.
    """
    invalid_request = _invalid_request_result(requested_repeat_count, later_row_count)
    if invalid_request is not None:
        return invalid_request

    try:
        resolution = resolve_stitch_recipe(ai_proposal, library)
    except RecipeLibraryError as e:
        return _empty_result(
            STATUS_INVALID_LIBRARY, requested_repeat_count, later_row_count,
            errors=[str(e)],
        )

    if resolution["status"] == "invalid_ai_proposal":
        return _empty_result(
            STATUS_INVALID_AI_PROPOSAL, requested_repeat_count, later_row_count,
            errors=list(resolution["errors"]), resolution=resolution,
        )

    return _finish_pipeline_from_resolution(
        resolution, requested_repeat_count, later_row_count,
        ambiguous_context="the AI proposal's identification",
    )


def plan_swatch_from_identification(identification, requested_repeat_count, later_row_count, library=None):
    """
    Phase 8: the same trusted pipeline as plan_trusted_swatch(), but
    starting from an AI IDENTIFICATION (engine/stitch_identification.py's
    {"region_label", "stitch_name", "aliases", "confidence", "uncertainty"}
    contract -- the shape engine/image_swatch_pipeline.py actually has
    from a photo) instead of a full AI-proposed v2 recipe.

    This never fabricates a fake AI recipe to hand to
    resolve_stitch_recipe(); it resolves the identity directly via
    resolve_stitch_recipe()'s sibling, resolve_stitch_identity() (Phase
    8, engine/recipe_library.py) -- an identity-only lookup that never
    invents, infers, or requires row/step data. From the point a trusted
    match is found onward, this function shares plan_trusted_swatch()'s
    exact tail (Phase 5 row simulation, plan-building, rendering) via
    _finish_pipeline_from_resolution() -- the same code, not a re-
    implementation of it, so both pipelines produce identically-shaped,
    identically-earned results and carry the same safety guarantees
    plan_trusted_swatch() documents (only a CONFIRMED library recipe is
    ever used; an AI's own confidence never overrides trust; every
    non-ready outcome returns no instructions).

    Parameters:
      identification          -- a dict expected to match
                                  engine.stitch_identification's
                                  contract; validated with
                                  validate_identification() before
                                  anything else -- this function never
                                  assumes it's already valid.
      requested_repeat_count  -- caller-chosen int >= 1, same rule as
                                  plan_trusted_swatch().
      later_row_count         -- caller-chosen int >= 0, same rule as
                                  plan_trusted_swatch().
      library                 -- optional; defaults to the real
                                  production library, exactly like
                                  plan_trusted_swatch().

    Process:
      1. Validates requested_repeat_count/later_row_count (see
         _invalid_request_result()) -- a bad request never reaches
         identification validation or resolution.
      2. Validates `identification` with validate_identification(). Any
         error -> STATUS_INVALID_IDENTIFICATION, carrying the exact
         validation errors -- nothing is looked up against the library
         from a malformed identification.
      3. Calls resolve_stitch_identity(identification["stitch_name"],
         aliases=identification.get("aliases"), library=library) --
         `pattern_id` is never supplied here, since this contract has no
         such field; identity is resolved by name/alias alone. Any
         RecipeLibraryError -> STATUS_INVALID_LIBRARY, exactly like
         plan_trusted_swatch().
      4. From here, identical to plan_trusted_swatch() from the point it
         has a resolution in hand (see _finish_pipeline_from_resolution()):
         ambiguous_match -> STATUS_AMBIGUOUS_RECIPE; no_match or
         untrusted_match -> STATUS_NO_TRUSTED_RECIPE; trusted_match ->
         Phase 5 simulation, plan-building, and rendering, exactly as
         plan_trusted_swatch() documents in full.

    Returns the same shaped dict plan_trusted_swatch() returns (see its
    docstring) -- "resolution" here is a resolve_stitch_identity() result
    rather than a resolve_stitch_recipe() one (no "comparison" or
    "ai_proposal" fields; has "reasons" instead -- see
    resolve_stitch_identity()'s own docstring), but every field this
    module itself reads from "resolution" (status, selected_recipe,
    conflicting_pattern_ids) is present in both.

    `identification`'s own `confidence` and `uncertainty` are never read
    by this function at all -- they carry no weight in whether a match
    is trusted; a caller wanting to surface them alongside the result
    (e.g. engine/image_swatch_pipeline.py, per region) already has the
    original `identification` dict to do so.

    Never mutates identification, the library, or any recipe read from
    it.
    """
    invalid_request = _invalid_request_result(requested_repeat_count, later_row_count)
    if invalid_request is not None:
        return invalid_request

    identification_errors = validate_identification(identification)
    if identification_errors:
        return _empty_result(
            STATUS_INVALID_IDENTIFICATION, requested_repeat_count, later_row_count,
            errors=identification_errors,
        )

    try:
        resolution = resolve_stitch_identity(
            identification["stitch_name"],
            aliases=identification.get("aliases"),
            library=library,
        )
    except RecipeLibraryError as e:
        return _empty_result(
            STATUS_INVALID_LIBRARY, requested_repeat_count, later_row_count,
            errors=[str(e)],
        )

    return _finish_pipeline_from_resolution(
        resolution, requested_repeat_count, later_row_count,
        ambiguous_context=f"the identified stitch_name {identification['stitch_name']!r} / aliases",
    )
