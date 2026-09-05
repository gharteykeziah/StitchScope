"""
General plausibility checks for a single proposed row -- catches an
obviously wrong AI proposal the FIRST time a stitch is ever seen, with
no confirmation history needed at all. This is the other half of
engine/confirmed_patterns.py: that module compares against ground
truth once something HAS been confirmed; this module needs nothing
confirmed to flag a row that looks wrong on its face.

This starts as a small, deliberately incomplete set of checks. New AI
failure modes surface every time a real photo is run through
run_real_photo.py -- add a new named check function here and register
it in _SETUP_CHECKS or _REPEAT_CHECKS as they turn up. This list is
expected to grow; it is a starting set, not a complete one.
"""

from engine.validator import check_row

# Anything a one-time setup step produces above this is suspicious -- a
# normal turning chain is small (commonly 1-4 chains for the stitches
# in STITCH_RULES). Starting heuristic, not a hard rule: adjust as real
# examples turn up.
OVERSIZED_SETUP_THRESHOLD = 8


def setup_produced_count(setup_steps):
    """How many new stitches a row's setup contributes, e.g. 40 for a lone 'CH 40' step."""
    return check_row(setup_steps, stitches_available=float("inf"))["produced"]


def check_setup_not_oversized(setup_steps):
    """Flags a setup whose produced count is implausibly large for a turning chain."""
    produced = setup_produced_count(setup_steps)
    if produced > OVERSIZED_SETUP_THRESHOLD:
        return (
            f"setup produces {produced} stitches, expected a small turning chain "
            f"(>{OVERSIZED_SETUP_THRESHOLD} is suspicious)"
        )
    return None


def check_repeat_not_degenerate(repeat_steps):
    """Flags an empty repeat, or one that consumes 0 stitches (would repeat forever without using anything up)."""
    if not repeat_steps:
        return "repeat unit is empty -- nothing to repeat"
    consumed = check_row(repeat_steps, stitches_available=float("inf"))["consumed"]
    if consumed == 0:
        return "repeat unit consumes 0 stitches -- would repeat forever without using anything up"
    return None


# Every check here runs against a row's "setup" or "repeat" step list
# and returns either a human-readable warning string or None. Add new
# checks by writing a function with this shape and registering it below.
_SETUP_CHECKS = [check_setup_not_oversized]
_REPEAT_CHECKS = [check_repeat_not_degenerate]


def run_plausibility_checks(row):
    """
    Runs every registered check against row's "setup" and "repeat", in
    order. Returns a list of human-readable warning strings -- empty if
    nothing looks wrong. Warnings are informational, not a hard reject:
    callers (see run_real_photo.py) decide what to do with them.
    """
    warnings = []
    for check in _SETUP_CHECKS:
        result = check(row["setup"])
        if result:
            warnings.append(result)
    for check in _REPEAT_CHECKS:
        result = check(row["repeat"])
        if result:
            warnings.append(result)
    return warnings
