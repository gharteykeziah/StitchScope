"""
Checks whether a row of stitches is actually possible, given how
many stitches were available from the row before it (or the
foundation chain, for row 1).
"""

STITCH_RULES = {
    "DC":   {"consumes": 1, "produces": 1},
    "SC":   {"consumes": 1, "produces": 1},
    "HDC":  {"consumes": 1, "produces": 1},
    "CH":   {"consumes": 0, "produces": 1},
    "SKIP": {"consumes": 1, "produces": 0},
    "SLST": {"consumes": 1, "produces": 1},
    "INC":  {"consumes": 1, "produces": 2},
    "DEC":  {"consumes": 2, "produces": 1},
}


def _totals(steps):
    consumed = 0
    produced = 0
    for step in steps:
        rule = STITCH_RULES[step["stitch"]]
        consumed += rule["consumes"] * step["count"]
        produced += rule["produces"] * step["count"]
    return consumed, produced


def check_row(row_steps, stitches_available):
    """Checks a simple flat list of steps (no setup/repeat split)."""
    consumed, produced = _totals(row_steps)
    return {
        "consumed": consumed,
        "produced": produced,
        "stitches_available": stitches_available,
        "valid": consumed <= stitches_available,
    }


def check_full_row(full_row, repeat_count, stitches_available):
    """
    Checks a REAL row: the one-time setup, plus the repeat worked
    repeat_count times, against how many stitches were available.
    """
    setup_consumed, setup_produced = _totals(full_row["setup"])
    repeat_consumed, repeat_produced = _totals(full_row["repeat"])

    consumed = setup_consumed + (repeat_consumed * repeat_count)
    produced = setup_produced + (repeat_produced * repeat_count)

    return {
        "consumed": consumed,
        "produced": produced,
        "stitches_available": stitches_available,
        "repeat_count": repeat_count,
        "valid": consumed <= stitches_available,
    }
