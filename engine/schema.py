"""
Validates a vision-model proposal against the StitchScope proposal schema
(contracts/proposal_schema_v2.json). The project has no external
dependencies, so this enforces the same rules in plain Python rather than
pulling in a JSON Schema library -- the .json file is the language-
agnostic reference, this module is what actually runs.

v2, not v1: a real garment photo can show more than one distinct stitch
pattern (a fan panel and a mesh panel, say), so the top-level shape is a
list of "regions" -- each one is what v1's whole proposal used to be
(stitch_family, confidence, rows, uncertain_fields), plus a label saying
where on the garment it is. contracts/proposal_schema_v1.json is kept
around, marked superseded, as a record of that change.
"""

from engine.validator import STITCH_RULES

SCHEMA_VERSION = "2.0.0"

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


def _validate_row(row, path, errors):
    if not isinstance(row, dict):
        errors.append(f"{path}: expected an object, got {type(row).__name__}")
        return

    if "setup" not in row:
        errors.append(f"{path}: missing 'setup'")
    elif not isinstance(row["setup"], list):
        errors.append(f"{path}.setup: must be a list")
    else:
        for i, step in enumerate(row["setup"]):
            _validate_step(step, f"{path}.setup[{i}]", errors)

    if "repeat" not in row:
        errors.append(f"{path}: missing 'repeat'")
    elif not isinstance(row["repeat"], list) or len(row["repeat"]) == 0:
        errors.append(f"{path}.repeat: must be a non-empty list")
    else:
        for i, step in enumerate(row["repeat"]):
            _validate_step(step, f"{path}.repeat[{i}]", errors)

    if "repeat_count" not in row:
        errors.append(f"{path}: missing 'repeat_count'")
    else:
        repeat_count = row["repeat_count"]
        if not isinstance(repeat_count, int) or isinstance(repeat_count, bool) or repeat_count < 1:
            errors.append(f"{path}.repeat_count: must be a positive integer, got {repeat_count!r}")


def _validate_region(region, path, errors):
    if not isinstance(region, dict):
        errors.append(f"{path}: expected an object, got {type(region).__name__}")
        return

    for field in ("region_label", "stitch_family", "confidence", "rows", "uncertain_fields"):
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

    if "rows" in region:
        rows = region["rows"]
        if not isinstance(rows, list) or len(rows) == 0:
            errors.append(f"{path}.rows: must be a non-empty list")
        else:
            for i, row in enumerate(rows):
                _validate_row(row, f"{path}.rows[{i}]", errors)


def validate_proposal(proposal):
    """
    Checks a vision-model proposal dict against the v2 schema: a photo
    can contain multiple stitch regions, so this expects
    {"regions": [region, ...]}, not a single region at the top level.
    Returns a list of error strings -- an empty list means it's valid.
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
