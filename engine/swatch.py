"""
Validates a multi-row swatch: does the whole short sequence of rows a
vision-model proposal claims for one region actually hold together,
row after row, against stitches counts WE compute -- never against
the model's own claimed numbers.

Checking a single row in isolation against a placeholder stitch count
(as run_real_photo.py used to) isn't a real test: if the placeholder
were instead derived from the model's own claimed repeat_count, the
check would become circular (repeat cost x repeat_count -> validate
that same row against that number always passes trivially). This
module builds an independent foundation chain from a fixed test
repeat count, then walks the region's rows in order, deriving each
later row's available stitches from what the row before it actually
produced -- not from anything the AI proposed.
"""

from engine.validator import check_full_row, new_chain_links


def build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6):
    """
    Computes the foundation chain length to use for TESTING a region's
    first row as a physical swatch: the setup's one-time consumed
    stitches, plus the repeat's consumed stitches worked test_repeat_count
    times -- PLUS any brand-new chain links row 1's setup itself adds.

    That last part matters and is easy to get wrong: a CH step inside
    row 1's setup (e.g. "chain 2, skip 1" before a DC-based repeat) is
    not like a CH inside the repeat, and not like a later row's turning
    chain. It's worked before row 1 has touched the foundation at all,
    so it necessarily extends the SAME starting chain you cast on --
    those links have to be included in how many stitches you physically
    chain, on top of whatever setup/repeat actually consume from the
    foundation. Skipping this made the foundation come out too SHORT:
    a setup of "chain 2, skip 1" plus a 6x "DC, chain 1" repeat was
    computing a foundation of 7 (1 skip + 6 DC insertions), silently
    dropping the 2 fresh chain links setup itself adds -- 9 is correct.

    A later row's turning_chain never needs this treatment: it's built
    from an already-attached working loop at the end of the previous
    row, not pre-chained into anything, so its CH steps are genuinely
    free the way STITCH_RULES already treats them. Same for any CH
    inside the repeat itself (a floating chain-space hung off a stitch
    that's already been worked) -- also genuinely free. Only setup's
    OWN chain-producing steps need this extra credit, because setup is
    the one place a CH step can run before any stitch exists to hang it
    off of.

    test_repeat_count is a number WE choose (default 6) for the purpose
    of building a test swatch -- it is never read from anything the AI
    proposed as its own repeat_count. If it were, the foundation would be
    built by construction to exactly fit whatever the model claims, and a
    row could then never fail validation: "does this row fit?" would
    always trivially say yes. Using our own fixed test_repeat_count keeps
    the swatch check an independent test of the model's proposed stitch
    math, not a restatement of it.

    Reuses check_full_row() for the setup/repeat consumed math rather
    than reimplementing it -- stitches_available is set to infinity here
    because we only want the "consumed" figure back, not whether it
    happens to fit anything.
    """
    probe_row = {"setup": setup_steps, "repeat": repeat_steps}
    result = check_full_row(probe_row, repeat_count=test_repeat_count, stitches_available=float("inf"))
    return result["consumed"] + new_chain_links(setup_steps)


def simulate_swatch(rows, foundation_length, test_repeat_count=6):
    """
    Walks a list of proposed rows (each supplying only its "setup" and
    "repeat" stitch structure, in order) as one continuous test swatch.
    Every row's repeat unit -- including row 1 -- is worked
    test_repeat_count times: the SAME fixed count used to build
    foundation_length (see build_test_foundation()), chosen by us.

    A row's own proposed "repeat_count" field is never read here. Using
    it for row 1 would check row 1 against a foundation sized for a
    DIFFERENT repeat count than the one actually simulated -- row 1
    would then fail (or pass) for reasons that have nothing to do with
    whether its stitch structure is sound, only whether the AI's row-1
    repeat_count happened to match our test_repeat_count. Using it for
    row 2 onward is exactly the circularity build_test_foundation()'s
    docstring warns about. The AI's proposed repeat_count is only ever a
    data point worth noting elsewhere -- never a number this function
    simulates against, for any row.

    Row 1's available stitches come from foundation_length. Every row
    after that uses the PREVIOUS row's actual produced count -- computed
    the same way check_full_row() computes it for any other row, reused
    here rather than reimplemented.

    Stops at the first row that fails. Returns either:
      {"success": False, "failed_at_row": <1-indexed row number>,
       "needed": <stitches that row's steps consume>,
       "available": <stitches actually available going into that row>,
       "trail": [...]}
    or, if every row holds up:
      {"success": True, "trail": [...]}

    "trail" is the full row-by-row consumed/produced result list (see
    check_full_row()) up to and including the point where the swatch was
    stopped, each entry tagged with its 1-indexed "row_number".
    """
    trail = []
    available = foundation_length

    for row_number, row in enumerate(rows, start=1):
        result = check_full_row(row, test_repeat_count, available)
        trail.append({"row_number": row_number, **result})

        if not result["valid"]:
            return {
                "success": False,
                "failed_at_row": row_number,
                "needed": result["consumed"],
                "available": available,
                "trail": trail,
            }

        available = result["produced"]

    return {"success": True, "trail": trail}
