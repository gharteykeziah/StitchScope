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

from engine.validator import check_full_row


def build_test_foundation(setup_steps, repeat_steps, test_repeat_count=6):
    """
    Computes the foundation chain length to use for TESTING a region's
    first row as a physical swatch: the setup's one-time consumed
    stitches, plus the repeat's consumed stitches worked test_repeat_count
    times.

    test_repeat_count is a number WE choose (default 6) for the purpose
    of building a test swatch -- it is never read from anything the AI
    proposed as its own repeat_count. If it were, the foundation would be
    built by construction to exactly fit whatever the model claims, and a
    row could then never fail validation: "does this row fit?" would
    always trivially say yes. Using our own fixed test_repeat_count keeps
    the swatch check an independent test of the model's proposed stitch
    math, not a restatement of it.

    Reuses check_full_row() for the actual per-step consumed/produced
    math rather than reimplementing it -- stitches_available is set to
    infinity here because we only want the "consumed" figure back, not
    whether it happens to fit anything.
    """
    probe_row = {"setup": setup_steps, "repeat": repeat_steps}
    result = check_full_row(probe_row, repeat_count=test_repeat_count, stitches_available=float("inf"))
    return result["consumed"]


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
