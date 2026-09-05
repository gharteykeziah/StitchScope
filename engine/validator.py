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


def step_totals(steps):
    """
    Public wrapper around _totals(): total (consumed, produced) for a
    flat list of steps. Exists so other engine modules (engine/swatch.py)
    can get per-step-list totals without reaching into a private helper.
    """
    return _totals(steps)


def new_chain_links(steps):
    """
    How many brand-new chain LINKS a flat list of steps adds -- as
    opposed to a stitch TOP produced by working into something that
    already exists (DC/SC/etc.), or a floating chain-space created
    mid-fabric. Only CH steps count: each one is a literal new link on
    whatever chain is currently being made.

    This distinction matters specifically for row 1's setup (see
    engine/swatch.py's build_test_foundation()): a CH step there is
    worked before anything else exists, so it necessarily extends the
    SAME starting chain you're casting on -- it must be added to how
    many stitches you physically chain, not just counted as something
    that gets "produced" for free the way a later row's turning chain
    is (that one starts from an already-attached working loop, no
    pre-chaining needed).
    """
    return sum(step["count"] for step in steps if step["stitch"] == "CH")


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
