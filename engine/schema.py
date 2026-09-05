"""
Validates the two structured shapes the AI integration produces, against
contracts/proposal_schema_v3.json and contracts/stitch_recipe_schema_v1.json.
The project has no external dependencies, so this enforces the same
rules in plain Python rather than pulling in a JSON Schema library --
the .json files are the language-agnostic reference, this module is
what actually runs.

v3, not v2: the photo call now only IDENTIFIES stitch regions
(region_label, stitch_family, confidence, uncertain_fields) -- it no
longer proposes any row structure. A photo-grounded call kept inventing
garment-specific numbers (oversized setup chains, inconsistent turning
chains) when asked to propose row structure from an image, but the same
model gives correct, standard answers when asked generically how a
named stitch is conventionally constructed, with no image involved.
proposal_schema_v1.json and proposal_schema_v2.json are kept around,
marked superseded, as a record of that evolution.

validate_recipe() is new alongside v3: it checks the shape of that
separate, non-photo recipe call's response (engine/vision.py's
get_stitch_recipe()) -- setup/repeat/turning_chain step lists, no
absolute foundation chain count anywhere in the shape at all.
"""

from engine.validator import STITCH_RULES

PROPOSAL_SCHEMA_VERSION = "3.0.0"
RECIPE_SCHEMA_VERSION = "1.0.0"

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
