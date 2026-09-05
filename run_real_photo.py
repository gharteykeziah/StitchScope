"""
Run the real vision-model integration against one actual garment photo,
and validate each detected region as a multi-row swatch: does the whole
short sequence of rows it proposed actually hold together, row after
row, against stitches counts WE compute (see engine/swatch.py) -- not
against a manually-set placeholder or anything the AI itself claimed.

Costs a fraction of a cent per call. Separate from main.py's demo (which
uses free, hardcoded stand-in data and needs no API key) so that demo
keeps running instantly with no network access or credentials required.

Usage: python3 run_real_photo.py path/to/photo.jpg
"""

import sys

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
    first_row = rows[0]
    foundation_length = build_test_foundation(
        first_row["setup"], first_row["repeat"], test_repeat_count=TEST_REPEAT_COUNT
    )
    print(f"   Foundation chain: {foundation_length} stitches "
          f"(test swatch: {TEST_REPEAT_COUNT} repeats of row 1's structure)")

    result = simulate_swatch(rows, foundation_length, test_repeat_count=TEST_REPEAT_COUNT)

    for entry in result["trail"]:
        row = rows[entry["row_number"] - 1]
        # The AI's own proposed repeat_count is never simulated (see
        # simulate_swatch()'s docstring) -- surfaced here only as a data
        # point, not as something that was actually tested.
        ai_note = f" [AI proposed repeat_count={row['repeat_count']}, not simulated]"
        if entry["valid"]:
            print(f"   Row {entry['row_number']}: {render_row(row, TEST_REPEAT_COUNT)}{ai_note}")
        else:
            print(f"   Row {entry['row_number']}: FAILED -- needed {entry['consumed']} stitches, "
                  f"only {entry['stitches_available']} were available from the row before it{ai_note}")

    if result["success"]:
        print(f"   Swatch holds up across all {len(rows)} proposed rows.")
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
