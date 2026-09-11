"""
Phase 8: the small, validated IDENTIFICATION contract the image
pathway's AI call is trusted for -- and ONLY for.

WHY A SEPARATE, MINIMAL CONTRACT

engine/vision.py's `get_vision_proposal_from_photo()` already returns
identification only (region_label, stitch_family, confidence,
uncertain_fields) -- no row structure, no setup/repeat/turning_chain --
see that module's own docstring for why that split already exists (a
photo-grounded call kept inventing garment-specific numbers when asked
to also propose row structure). This module does not change that call.
It defines the small shape the REST of the Phase 8 pipeline
(resolve_stitch_identity(), plan_swatch_from_identification(),
engine/image_swatch_pipeline.py) actually trusts an identification to
look like -- with field names that match this project's v2 vocabulary
(`stitch_name`/`aliases`, the same names engine/recipe_library.py's
recipes and normalize_stitch_name() already use) rather than the older
proposal shape's `stitch_family`/`uncertain_fields`. `identification_from_vision_region()`
below is the small, explicit adapter between the two -- it does not
touch how the image is encoded or how the API is called.

THE IDENTIFICATION CONTRACT

    {"region_label": "cuff",
     "stitch_name": "filet mesh",
     "aliases": [],
     "confidence": 0.82,
     "uncertainty": "..."}

  region_label  (required) -- non-empty string. Where this identified
      stitch pattern is on the garment.
  stitch_name   (required) -- non-empty string. The AI's best guess at
      the stitch's real, recognized name -- the ONLY thing ever used to
      look up a trusted recipe (see resolve_stitch_identity()). This
      module never asks for, and never accepts, foundation/row_1/
      later-row instructions here -- identification is not recipe
      generation.
  aliases       (optional, defaults to []) -- a list of non-empty
      strings, additional names the AI (or a caller) believes refer to
      the same stitch. The current vision proposal shape has no field
      for this at all, so identification_from_vision_region() always
      produces [] here; a caller with a richer source of aliases may
      supply them directly.
  confidence    (required) -- a real number (int or float; bool
      explicitly excluded, since it's technically an int subclass but
      never a legitimate confidence value) between 0 and 1 inclusive.
      Metadata about the guess ONLY -- see TRUST below.
  uncertainty   (optional, nullable, defaults to None) -- a non-empty
      string describing what the AI is unsure about, or None/absent if
      the AI is confident in everything it reported for this region.

UNEXPECTED FIELDS ARE REJECTED

validate_identification() only accepts the five fields above -- the
same closed-shape discipline every other v2-era contract in this
project already uses (contracts/stitch_recipe_schema_v2.json's
additionalProperties: false, engine/recipe_library.py's top-level
library check). An identification carrying some other field (e.g. a
smuggled "setup"/"repeat" instruction list) is rejected outright, never
silently ignored.

TRUST: CONFIDENCE IS METADATA, NEVER PROOF

`confidence` is validated for SHAPE only (a real number in [0, 1]) --
this module never reads its VALUE to decide anything. Nothing here (or
anywhere downstream: resolve_stitch_identity() doesn't even accept a
confidence parameter) treats a high confidence as evidence that a
stitch is correctly identified, let alone that any recipe for it is
physically confirmed. A confidence of 1.0 carries exactly as much
trust-deciding weight as a confidence of 0.0: none.
"""

_ALLOWED_IDENTIFICATION_FIELDS = frozenset({
    "region_label", "stitch_name", "aliases", "confidence", "uncertainty",
})
_REQUIRED_IDENTIFICATION_FIELDS = ("region_label", "stitch_name", "confidence")


def _is_real_number_excluding_bool(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_identification(identification):
    """
    Validates one identification dict against the contract described in
    this module's docstring. Returns a list of readable error strings --
    an empty list means it's safe to read `stitch_name`/`aliases`/etc.
    from. Never raises; every problem is reported, not just the first.

    Checks: an object; only the five documented fields present (no
    smuggled instruction data); `region_label` and `stitch_name` each
    required and a non-empty string; `aliases`, if present, a list of
    non-empty strings; `confidence` required, a real number (bool
    excluded) between 0 and 1 inclusive; `uncertainty`, if present,
    either None or a non-empty string.
    """
    if not isinstance(identification, dict):
        return [f"identification must be an object, got {type(identification).__name__}"]

    errors = []

    for key in identification:
        if key not in _ALLOWED_IDENTIFICATION_FIELDS:
            errors.append(f"identification: unexpected field {key!r}")

    for field in _REQUIRED_IDENTIFICATION_FIELDS:
        if field not in identification:
            errors.append(f"identification: missing required field '{field}'")

    if "region_label" in identification:
        value = identification["region_label"]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"identification.region_label: must be a non-empty string, got {value!r}")

    if "stitch_name" in identification:
        value = identification["stitch_name"]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"identification.stitch_name: must be a non-empty string, got {value!r}")

    if "aliases" in identification:
        aliases = identification["aliases"]
        if not isinstance(aliases, list) or not all(
            isinstance(a, str) and a.strip() for a in aliases
        ):
            errors.append(f"identification.aliases: must be a list of non-empty strings, got {aliases!r}")

    if "confidence" in identification:
        confidence = identification["confidence"]
        if not _is_real_number_excluding_bool(confidence) or not (0 <= confidence <= 1):
            errors.append(
                f"identification.confidence: must be a real number between 0 and 1, got {confidence!r}"
            )

    if "uncertainty" in identification:
        uncertainty = identification["uncertainty"]
        if uncertainty is not None and (not isinstance(uncertainty, str) or not uncertainty.strip()):
            errors.append(
                f"identification.uncertainty: must be null or a non-empty string, got {uncertainty!r}"
            )

    return errors


def identification_from_vision_region(region):
    """
    Adapts one region dict from engine/vision.py's proposal shape
    (region_label, stitch_family, confidence, uncertain_fields --
    contracts/proposal_schema_v3.json) into this module's identification
    contract (region_label, stitch_name, aliases, confidence,
    uncertainty). This is a field-name/shape translation ONLY -- it does
    not touch image encoding, the API call, or engine/vision.py's own
    schema/prompt.

      stitch_family -> stitch_name       (same value; renamed to match
                                           this project's v2 name/alias
                                           vocabulary, e.g.
                                           normalize_stitch_name())
      uncertain_fields -> uncertainty    (a LIST of field names the
                                           model was unsure about becomes
                                           ONE human-readable string, or
                                           None if the list was empty --
                                           a shape change for the same
                                           underlying concept, not a
                                           lossy rename)
      (none) -> aliases: []              (the current vision proposal
                                           shape has no alias field at
                                           all)

    CHOSEN SAFE BEHAVIOR FOR RAW/UNEXPECTED FIELDS: DISCARD, NEVER READ.

    engine.schema's validate_proposal()/_validate_region() check that a
    region carries its four REQUIRED fields with the right shapes, but
    do not reject a region carrying additional, unexpected fields (e.g.
    an AI hallucinating a "setup", "repeat", "row_1", or "later_rows"
    key directly into an identification response). This function is
    where that gap is closed: it builds the returned dict by reading
    exactly five named keys off `region` (region_label, stitch_family,
    confidence, uncertain_fields, and the always-synthesized aliases)
    -- it is never a `dict(region)` copy and never uses `**region`. Any
    other field present on `region` is structurally left behind here
    and can never reach validate_identification(), resolve_stitch_identity(),
    or the renderer -- there is no code path by which it could. This was
    chosen over the alternative (rejecting the whole proposal as
    invalid_ai_response for carrying an extra field) because
    contracts/proposal_schema_v3.json's own schema does not forbid extra
    fields at that layer, and rejecting a well-formed identification
    over an unrelated extra field the AI happened to include would be a
    stricter refusal than this contract promises; discarding is
    sufficient because instruction data has no field in the
    identification contract it could occupy in the first place. See
    tests/test_image_swatch_pipeline.py's
    RawInstructionFieldsAreDiscardedTests for a full end-to-end proof
    that such fields cannot affect a selected recipe or rendered
    instructions.

    Does not validate its output -- callers should run
    validate_identification() on the result (engine/image_swatch_pipeline.py
    always does). Reads `region` only; never mutates it.
    """
    uncertain_fields = region.get("uncertain_fields") or []
    uncertainty = f"uncertain about: {', '.join(uncertain_fields)}" if uncertain_fields else None
    return {
        "region_label": region.get("region_label"),
        "stitch_name": region.get("stitch_family"),
        "aliases": [],
        "confidence": region.get("confidence"),
        "uncertainty": uncertainty,
    }
