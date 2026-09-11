"""
Phase 8: the final integration -- a real (or injected) photo, through
identification, through the Phase 6/7/8 trust boundary, to a rendered
swatch plan (or a clear, honest refusal), one independent result per
identified region.

CORE PIPELINE

    image_path
        v
    engine.vision.get_vision_proposal_from_photo() (or an injected
        vision_client) -- IDENTIFICATION ONLY, no row structure
        v
    validate_proposal() (defense in depth: validated again here even
        though the real function already validates internally, because
        an injected test double is not guaranteed to)
        v
    for each region, independently:
        identification_from_vision_region() (engine/stitch_identification.py)
            v
        plan_swatch_from_identification() (engine/swatch_planner_v2.py,
            Phase 8) -- validates the identification, resolves it
            against the trusted v2 library (resolve_stitch_identity()),
            and only for a trusted match runs Phase 5 simulation and
            Phase 6 rendering
            v
        one structured per-region result -- rendered instructions ONLY
            when that region's plan status is "ready"

WHY THIS MODULE CALLS NOTHING NEW FOR TRUST DECISIONS

Every trust decision here -- what counts as identification-only, what
counts as a "trusted" recipe, what a swatch plan requires before it can
render -- already lives in engine/stitch_identification.py,
engine/recipe_library.py, and engine/swatch_planner_v2.py. This module
is glue: it drives one photo's regions through those, one at a time,
and shapes the results for a caller (run_trusted_swatch_from_photo.py).
It does not re-implement, weaken, or duplicate the resolution or
simulation logic that already lives in those modules.

DEPENDENCY-INJECTED VISION CALL

generate_swatch_from_image() takes an optional `vision_client` --
defaults to engine.vision.get_vision_proposal_from_photo, the real
(paid) API call. Tests and offline demonstrations pass a fake callable
instead, so this module (and everything it drives) can be fully
exercised without ever contacting the real API. `vision_client` must
have the same signature/contract as get_vision_proposal_from_photo():
called as `vision_client(image_path)`, returning an identification-only
proposal dict, or raising VisionProposalError.

WHY EVERY LOCALLY-KNOWABLE INPUT IS VALIDATED BEFORE THE VISION CALL

Anything this function can determine without contacting the API is
checked before vision_client is ever invoked -- a malformed image_path
(None, a non-string/non-Path, an empty string), a malformed
requested_repeat_count/later_row_count, a non-callable vision_client, a
missing file or unsupported extension, and an invalid library (default
or directly supplied) all short-circuit first. This is not just
tidiness: it means a caller can never be charged for a paid API call
that was always going to be thrown away because the request itself was
unusable, and it makes "the vision client was never called" an
independently verifiable property in tests (e.g. a vision_client that
records whether it was invoked -- see tests/test_image_swatch_pipeline.py).

LIBRARY VALIDATION REUSES PHASE 6'S TRUST BOUNDARY, NEVER RE-IMPLEMENTS IT

The library (default or directly supplied) is validated with
engine.recipe_library's own `_load_or_validate_library()` -- the exact
same trust-boundary gate resolve_stitch_recipe()/resolve_stitch_identity()
use -- rather than re-deriving "is this library valid" rules here. A
directly-supplied library that fails validate_recipe_library() is
caught as RecipeLibraryError and reported as STATUS_INVALID_LIBRARY; a
broken default file (library=None) fails the exact same way, since
`_load_or_validate_library(None)` calls load_recipe_library() itself.
Either way, this happens before vision_client is invoked, and the
already-validated library dict is reused for every region afterward --
it is not re-loaded from disk once per region.

RAW AI-RESPONSE FIELDS OUTSIDE THE IDENTIFICATION CONTRACT ARE ALWAYS
DISCARDED, NEVER READ

A region dict from vision_client could, in principle, contain fields
beyond region_label/stitch_family/confidence/uncertain_fields --
engine.schema's validate_proposal()/`_validate_region()` check that the
required fields are present and well-typed, but do not reject a region
carrying EXTRA fields (there is no additionalProperties: false gate at
that layer). The chosen, deliberate safe behavior here is: DISCARD, not
reject. identification_from_vision_region() (engine/stitch_identification.py)
builds a brand-new dict by reading exactly five named keys off the
region (region_label, stitch_family, confidence, uncertain_fields, and
the always-synthesized aliases) -- it is not a `dict(region)` copy and
never uses `**region`. Any other field on the raw region -- an AI
hallucinating a "setup", "repeat", "row_1", or "later_rows" key
straight into its identification response -- is structurally left
behind at that translation step and never reaches
validate_identification(), resolve_stitch_identity(), or the renderer.
See tests/test_image_swatch_pipeline.py's
RawInstructionFieldsAreDiscardedTests for a test proving such fields
cannot affect a region's selected recipe or rendered instructions even
when they are present and internally consistent-looking.

NEVER A SILENT FALLBACK TO THE OLD (v1) PATHWAY

This module never imports or calls engine.confirmed_patterns,
engine.swatch, engine.renderer, or data/confirmed_stitch_patterns.json
-- the old, untyped, un-trust-gated image pathway run_real_photo.py
still uses. A region this module cannot produce trusted instructions
for is reported with a clear non-ready status; it is never silently
completed with untrusted v1 output.

PER-REGION, NEVER MERGED

Every region from the photo is processed completely independently, in
the order the AI returned them. Regions are never grouped, deduplicated,
or merged by similar-looking stitch names -- two regions the AI
happened to both call "mesh" still get two separate results, with two
separate resolutions, even if those resolutions turn out identical.
"""

from pathlib import Path

from engine.recipe_library import RecipeLibraryError, _load_or_validate_library
from engine.schema import validate_proposal
from engine.stitch_identification import identification_from_vision_region
from engine.swatch_planner_v2 import _is_plain_positive_int, plan_swatch_from_identification
from engine.vision import VisionProposalError, get_vision_proposal_from_photo, _MEDIA_TYPES

STATUS_PROCESSED = "processed"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_IMAGE_NOT_FOUND = "image_not_found"
STATUS_UNSUPPORTED_IMAGE_TYPE = "unsupported_image_type"
STATUS_INVALID_LIBRARY = "invalid_library"
STATUS_IMAGE_UNREADABLE = "image_unreadable"
STATUS_API_FAILED = "api_failed"
STATUS_INVALID_AI_RESPONSE = "invalid_ai_response"

_SUPPORTED_IMAGE_EXTENSIONS = frozenset(_MEDIA_TYPES)


def _pipeline_result(status, image_path, regions=None, errors=None):
    return {
        "status": status,
        "image_path": str(image_path),
        "regions": regions,
        "errors": errors or [],
    }


def _is_non_empty_str_or_path(image_path):
    """
    True only for a str or Path whose string form is non-blank. Used to
    reject image_path=None, image_path=123, and image_path="" BEFORE
    Path(image_path) is ever constructed -- Path(None) and Path(123)
    raise a raw TypeError, and Path("") silently becomes Path(".") (the
    current directory, never a photo) rather than failing at all.
    """
    if isinstance(image_path, (str, Path)):
        return str(image_path).strip() != ""
    return False


def _region_result(region, requested_repeat_count, later_row_count, library):
    """
    Runs one region dict (one entry of the vision proposal's "regions"
    list) through identification adaptation and the full Phase 8 trusted
    pipeline, independently of every other region.

    Never raises for an expected outcome -- plan_swatch_from_identification()
    already reports every expected failure mode (invalid identification,
    invalid library, no trusted recipe, ambiguous recipe, simulation
    failure/unsupported, unsupported terminology) as a status rather
    than an exception; this function reads that status, it does not
    re-derive it.
    """
    identification = identification_from_vision_region(region)
    plan = plan_swatch_from_identification(identification, requested_repeat_count, later_row_count, library)

    resolution = plan.get("resolution")
    selected_recipe = plan.get("selected_recipe")

    return {
        "region_label": identification.get("region_label"),
        "identification": identification,
        "confidence": identification.get("confidence"),
        "uncertainty": identification.get("uncertainty"),
        "recipe_resolution_status": resolution["status"] if resolution else None,
        "selected_pattern_id": selected_recipe["pattern_id"] if selected_recipe else None,
        "swatch_status": plan["status"],
        "ready_for_user_instructions": plan["ready_for_user_instructions"],
        "rendered_instructions": plan["rendered_instructions"],
        "errors": plan["errors"],
        "warnings": plan["warnings"],
    }


def generate_swatch_from_image(image_path, requested_repeat_count=6, later_row_count=3,
                                library=None, vision_client=None):
    """
    Phase 8's top-level entry point: image -> AI identification -> the
    trusted v2 pipeline -> one structured result per region.

    Parameters:
      image_path              -- path to a photo; must be a non-empty
                                  str or Path.
      requested_repeat_count  -- caller-chosen int >= 1, excluding bool
                                  (True/False are technically ints but
                                  are never accepted as counts), passed
                                  through unchanged to
                                  plan_swatch_from_identification() for
                                  every region (same repeat count for
                                  the whole photo, exactly like Phase 7's
                                  plan_trusted_swatch() takes one
                                  requested_repeat_count per call).
      later_row_count         -- caller-chosen int >= 0, same rules as
                                  requested_repeat_count.
      library                 -- optional; defaults to the real
                                  production v2 library. EITHER way, it
                                  is validated ONCE here, before
                                  vision_client is ever called (see
                                  "LIBRARY VALIDATION REUSES PHASE 6'S
                                  TRUST BOUNDARY" in this module's
                                  docstring) -- an invalid library (the
                                  default file, or a directly-supplied
                                  dict) produces STATUS_INVALID_LIBRARY
                                  before any API call and before any
                                  region is processed, never an
                                  uncaught RecipeLibraryError and never
                                  a per-region failure.
      vision_client            -- optional; defaults to
                                  engine.vision.get_vision_proposal_from_photo
                                  (the real, paid API call). If supplied,
                                  must be callable. Pass a fake callable
                                  with the same
                                  `vision_client(image_path) -> proposal`
                                  contract to exercise this pipeline
                                  without ever contacting the real API --
                                  every test and offline demonstration in
                                  this project does exactly that.

    Process -- everything through step 5 is knowable WITHOUT contacting
    the API, and all of it happens before vision_client is ever called:
      1. Validates image_path is a non-empty str or Path -- rejects
         None, non-string/non-Path types (e.g. an int), and "" as
         STATUS_INVALID_REQUEST before Path(image_path) is even
         constructed (Path(None) raises a raw TypeError; Path("")
         silently becomes the current directory rather than failing).
      2. Validates requested_repeat_count (plain int >= 1, bool
         excluded) and later_row_count (plain int >= 0, bool excluded)
         -- either failing is STATUS_INVALID_REQUEST.
      3. Validates vision_client is either None (use the real default)
         or callable -- a non-callable value is STATUS_INVALID_REQUEST.
      4. Checks the image file exists (Path(image_path).is_file()) and
         has a supported extension (the same extensions
         engine.vision._media_type_for() accepts). Fails as
         STATUS_IMAGE_NOT_FOUND or STATUS_UNSUPPORTED_IMAGE_TYPE
         respectively.
      5. Validates the library (default or directly supplied) via
         engine.recipe_library's own `_load_or_validate_library()` --
         Phase 6's exact trust boundary, not a re-implementation of it.
         A RecipeLibraryError here (broken default file OR an invalid
         directly-supplied dict) is caught and reported as
         STATUS_INVALID_LIBRARY. The resulting already-validated
         library dict is reused for every region below, never reloaded
         from disk per region.
      6. Calls vision_client(image_path). Catches VisionProposalError
         (the one exception type engine.vision.py's real calls raise for
         every expected failure: missing API key, network/API error,
         refusal, truncation, bad JSON, schema-validation failure) as
         STATUS_API_FAILED, and OSError (a file that passed the checks
         in step 4 but could not actually be read -- permissions,
         corruption, a race) as STATUS_IMAGE_UNREADABLE. Neither is
         allowed to propagate as an uncaught, raw-traceback exception.
      7. Validates whatever vision_client returned with validate_proposal()
         -- run again here even though the real get_vision_proposal_from_photo()
         already validates internally, because an injected vision_client
         (as every test in this project uses) is not guaranteed to. A
         schema-invalid response (missing/malformed "regions", including
         an empty "regions" list) -> STATUS_INVALID_AI_RESPONSE, carrying
         the validator's own errors; no region is ever processed from an
         unvalidated proposal. Note that validate_proposal() checks that
         REQUIRED fields are present and well-typed, but does not reject
         a region carrying EXTRA fields (e.g. a smuggled "setup" or
         "row_1") -- see "RAW AI-RESPONSE FIELDS OUTSIDE THE
         IDENTIFICATION CONTRACT ARE ALWAYS DISCARDED, NEVER READ" in
         this module's docstring for why that's still safe.
      8. Runs every region in "regions" through _region_result()
         independently, in order -- adapting it to this project's
         identification contract (identification_from_vision_region())
         and then through the full Phase 8 trusted pipeline
         (plan_swatch_from_identification()), reusing the library
         already validated in step 5. Regions are never merged,
         deduplicated, or skipped because of another region's outcome --
         one region's failure never affects another's result.

    Returns a dict:
      {"status": one of STATUS_PROCESSED / STATUS_INVALID_REQUEST /
                 STATUS_IMAGE_NOT_FOUND / STATUS_UNSUPPORTED_IMAGE_TYPE /
                 STATUS_INVALID_LIBRARY / STATUS_IMAGE_UNREADABLE /
                 STATUS_API_FAILED / STATUS_INVALID_AI_RESPONSE,
       "image_path": str(image_path),
       "regions": [<per-region result>, ...] | None,
           # present ONLY for STATUS_PROCESSED; None for every
           # earlier-stopping status, since no region was ever reached.
       "errors": [str, ...]}
           # top-level errors for every non-processed status; always []
           # for STATUS_PROCESSED (per-region errors live inside each
           # region's own "errors", not here).

    Each entry of "regions" (only present for STATUS_PROCESSED) is:
      {"region_label": str | None,
       "identification": <the adapted identification dict>,
       "confidence": float | None,
       "uncertainty": str | None,
       "recipe_resolution_status": str | None,
           # resolve_stitch_identity()'s own status
           # (trusted_match/untrusted_match/no_match/ambiguous_match),
           # or None only if identification itself was invalid (so no
           # resolution was even attempted).
       "selected_pattern_id": str | None,
           # the trusted library recipe's pattern_id, present only when
           # a trusted match was found; None otherwise.
       "swatch_status": str,
           # plan_swatch_from_identification()'s own "status" (see that
           # function's docstring for the full vocabulary) -- the single
           # most complete answer to "what happened for this region."
       "ready_for_user_instructions": bool,
       "rendered_instructions": str | None,
           # present ONLY when ready_for_user_instructions is True --
           # never partial or AI-authored instructions for any other
           # outcome.
       "errors": [str, ...],
       "warnings": [str, ...]}

    For every non-"ready" per-region outcome, "rendered_instructions" is
    None -- this function never returns partial or AI-authored
    instructions that could be mistaken for a physically confirmed
    pattern, and it never falls back to the old (v1) pathway's untrusted
    output for a region the trusted pipeline could not resolve.

    Never mutates its inputs; never raises for an expected failure mode
    (see steps 1-7 above) -- every one of them is reported as a status,
    with readable errors, never a raw traceback.
    """
    if not _is_non_empty_str_or_path(image_path):
        return _pipeline_result(
            STATUS_INVALID_REQUEST, image_path,
            errors=[f"image_path must be a non-empty str or Path, got {image_path!r}"],
        )

    if not _is_plain_positive_int(requested_repeat_count, 1):
        return _pipeline_result(
            STATUS_INVALID_REQUEST, image_path,
            errors=[f"requested_repeat_count must be a plain integer >= 1, got {requested_repeat_count!r}"],
        )

    if not _is_plain_positive_int(later_row_count, 0):
        return _pipeline_result(
            STATUS_INVALID_REQUEST, image_path,
            errors=[f"later_row_count must be a plain integer >= 0, got {later_row_count!r}"],
        )

    if vision_client is not None and not callable(vision_client):
        return _pipeline_result(
            STATUS_INVALID_REQUEST, image_path,
            errors=[f"vision_client must be callable, got {vision_client!r}"],
        )
    if vision_client is None:
        vision_client = get_vision_proposal_from_photo

    path = Path(image_path)

    if not path.is_file():
        return _pipeline_result(
            STATUS_IMAGE_NOT_FOUND, image_path, errors=[f"Image not found: {image_path}"]
        )

    if path.suffix.lower() not in _SUPPORTED_IMAGE_EXTENSIONS:
        return _pipeline_result(
            STATUS_UNSUPPORTED_IMAGE_TYPE, image_path,
            errors=[
                f"Unsupported image type {path.suffix!r} "
                f"(expected one of {sorted(_SUPPORTED_IMAGE_EXTENSIONS)})"
            ],
        )

    try:
        validated_library = _load_or_validate_library(library)
    except RecipeLibraryError as e:
        return _pipeline_result(STATUS_INVALID_LIBRARY, image_path, errors=[str(e)])

    try:
        proposal = vision_client(image_path)
    except VisionProposalError as e:
        return _pipeline_result(STATUS_API_FAILED, image_path, errors=[str(e)])
    except OSError as e:
        return _pipeline_result(STATUS_IMAGE_UNREADABLE, image_path, errors=[str(e)])

    proposal_errors = validate_proposal(proposal)
    if proposal_errors:
        return _pipeline_result(STATUS_INVALID_AI_RESPONSE, image_path, errors=proposal_errors)

    regions = [
        _region_result(region, requested_repeat_count, later_row_count, validated_library)
        for region in proposal["regions"]
    ]

    return _pipeline_result(STATUS_PROCESSED, image_path, regions=regions)
