"""
Run the real vision-model integration against one actual garment photo,
and validate each detected region as a multi-row swatch: does the whole
short sequence of rows it proposed actually hold together, row after
row, against stitches counts WE compute (see engine/swatch.py) -- not
against a manually-set placeholder or anything the AI itself claimed.

Two more layers run before the swatch math, both on the AI's raw
proposal:
  - engine/plausibility.py: general sanity checks (an oversized setup,
    a degenerate repeat) that catch an obviously wrong proposal the
    first time a stitch is ever seen, no history required.
  - engine/confirmed_patterns.py: once a stitch family has a human-
    confirmed recipe on record (see confirm_stitch.py), that recipe is
    used to build the test swatch instead of a fresh, unconfirmed guess
    -- whether the fresh guess matches it or not.

Costs a fraction of a cent per call. Separate from main.py's demo (which
uses free, hardcoded stand-in data and needs no API key) so that demo
keeps running instantly with no network access or credentials required.

Usage: python3 run_real_photo.py path/to/photo.jpg
"""

import sys

from engine.confirmed_patterns import (
    MATCHES_CONFIRMED,
    NO_CONFIRMED_ENTRY,
    check_against_confirmed,
)
from engine.plausibility import run_plausibility_checks, setup_produced_count
from engine.renderer import render_row
from engine.schema import validate_proposal
from engine.swatch import build_test_foundation, simulate_swatch
from engine.vision import get_vision_proposal_from_photo, VisionProposalError

# How many times to work each region's first row's repeat, purely for
# building a foundation chain to TEST against -- ours, not the AI's own
# claimed repeat_count. See build_test_foundation()'s docstring for why
# using the AI's own number here would make the whole check circular.
TEST_REPEAT_COUNT = 6


def report_region(region):
    print(f"\n-- {region['region_label']}: {region['stitch_family']} "
          f"(confidence: {region['confidence']}) --")
    if region["uncertain_fields"]:
        print(f"   AI is unsure about: {', '.join(region['uncertain_fields'])}")

    rows = region["rows"]

    # General plausibility checks on every row's RAW AI proposal --
    # printed regardless of what happens next, independent of any
    # confirmed-pattern history.
    row_warnings = {}
    for i, row in enumerate(rows, start=1):
        warnings = run_plausibility_checks(row)
        row_warnings[i] = warnings
        for w in warnings:
            print(f"   [plausibility] Row {i}: {w}")

    # Compare row 1's proposed structure -- the region's "recipe" that
    # build_test_foundation() actually uses -- against whatever's
    # confirmed for this stitch family.
    first_row = rows[0]
    proposed_turning_chain = setup_produced_count(first_row["setup"])
    check_result = check_against_confirmed(
        region["stitch_family"], first_row["setup"], first_row["repeat"], proposed_turning_chain
    )

    if check_result["status"] == NO_CONFIRMED_ENTRY:
        if row_warnings[1]:
            print(f"   no confirmed recipe for '{region['stitch_family']}' yet, AND this proposal looks "
                  f"implausible ({'; '.join(row_warnings[1])}) -- treat this swatch's setup with real "
                  f"skepticism.")
        else:
            print(f"   No confirmed recipe for '{region['stitch_family']}' yet -- using this AI proposal as-is.")
        effective_row_1 = first_row
    else:
        confirmed = check_result["confirmed_entry"]
        if check_result["status"] == MATCHES_CONFIRMED:
            print(f"   Matches the confirmed recipe for '{region['stitch_family']}'.")
        else:  # CONFLICTS_WITH_CONFIRMED
            print(f"   CONFLICTS with the confirmed recipe for '{region['stitch_family']}':")
            for d in check_result["disagreements"]:
                print(f"     - {d}")
        print(f"   Using the confirmed recipe (not this fresh proposal) to build the test swatch.")
        effective_row_1 = {**first_row, "setup": confirmed["setup"], "repeat": confirmed["repeat"]}

    effective_rows = [effective_row_1] + rows[1:]

    foundation_length = build_test_foundation(
        effective_row_1["setup"], effective_row_1["repeat"], test_repeat_count=TEST_REPEAT_COUNT
    )
    print(f"   Foundation chain: {foundation_length} stitches "
          f"(test swatch: {TEST_REPEAT_COUNT} repeats of row 1's structure)")

    result = simulate_swatch(effective_rows, foundation_length, test_repeat_count=TEST_REPEAT_COUNT)

    for entry in result["trail"]:
        row = effective_rows[entry["row_number"] - 1]
        # The AI's own proposed repeat_count is never simulated (see
        # simulate_swatch()'s docstring) -- surfaced here only as a note,
        # never as something that was actually tested.
        ai_note = f" [AI proposed repeat_count={row['repeat_count']}, not simulated]"
        if entry["valid"]:
            print(f"   Row {entry['row_number']}: {render_row(row, TEST_REPEAT_COUNT)}{ai_note}")
        else:
            print(f"   Row {entry['row_number']}: FAILED -- needed {entry['consumed']} stitches, "
                  f"only {entry['stitches_available']} were available from the row before it{ai_note}")

    if result["success"]:
        print(f"   Swatch holds up across all {len(effective_rows)} proposed rows.")
    else:
        print(f"   Swatch breaks down at row {result['failed_at_row']} -- stopping here. "
              f"{len(result['trail']) - 1} row(s) before it can still be crocheted as a test swatch.")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 run_real_photo.py <path-to-photo>")
        sys.exit(1)

    image_path = sys.argv[1]

    try:
        proposal = get_vision_proposal_from_photo(image_path)
    except VisionProposalError as e:
        print(f"Could not get a usable proposal: {e}")
        sys.exit(1)

    schema_errors = validate_proposal(proposal)
    if schema_errors:
        print(f"Proposal for {proposal.get('photo_id', '?')}: REJECTED -- doesn't match the schema:")
        for error in schema_errors:
            print(f"  - {error}")
        sys.exit(1)

    regions = proposal["regions"]
    print(f"Proposal for {proposal.get('photo_id', '?')}: {len(regions)} stitch region(s) detected")
    for region in regions:
        report_region(region)


if __name__ == "__main__":
    main()
