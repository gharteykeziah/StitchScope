"""
Validates a vision-model proposal against the StitchScope proposal schema
(schema/proposal_schema_v1.json). The project has no external dependencies,
so this enforces the same rules in plain Python rather than pulling in a
JSON Schema library -- the .json file is the language-agnostic reference,
this module is what actually runs.
"""

SCHEMA_VERSION = "1.0.0"

KNOWN_STITCHES = {"CH", "SC", "HDC", "DC", "SLST", "SKIP", "INC", "DEC"}


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


def validate_proposal(proposal):
    """
    Checks a vision-model proposal dict against the v1 schema.
    Returns a list of error strings -- an empty list means it's valid.
    """
    if not isinstance(proposal, dict):
        return [f"proposal must be an object, got {type(proposal).__name__}"]

    errors = []

    for field in ("stitch_family", "confidence", "rows", "uncertain_fields"):
        if field not in proposal:
            errors.append(f"missing required field: '{field}'")

    if "stitch_family" in proposal and not isinstance(proposal["stitch_family"], str):
        errors.append("stitch_family: must be a string")

    if "confidence" in proposal:
        confidence = proposal["confidence"]
        is_number = isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        if not is_number or not (0 <= confidence <= 1):
            errors.append(f"confidence: must be a number between 0 and 1, got {confidence!r}")

    if "uncertain_fields" in proposal:
        uf = proposal["uncertain_fields"]
        if not isinstance(uf, list) or not all(isinstance(x, str) for x in uf):
            errors.append("uncertain_fields: must be a list of strings")

    if "rows" in proposal:
        rows = proposal["rows"]
        if not isinstance(rows, list) or len(rows) == 0:
            errors.append("rows: must be a non-empty list")
        else:
            for i, row in enumerate(rows):
                _validate_row(row, f"rows[{i}]", errors)

    return errors
