"""
Run the real AI integration against one actual garment photo, and
validate each detected region as a multi-row test swatch built from a
single stitch RECIPE -- not a photo call's own row proposal.

Two separate API calls now feed this, per region:
  1. get_vision_proposal_from_photo() -- IDENTIFIES the region
     (region_label, stitch_family, confidence, uncertain_fields), no
     row structure at all.
  2. resolve_recipe() -- gets that stitch_family's actual construction
     (setup/repeat/turning_chain), checking engine/confirmed_patterns.py
     FIRST: if something's already confirmed, uses it directly and
     skips calling get_stitch_recipe() entirely. Only when nothing's
     confirmed does it make that separate, non-photo call.

Either way, the recipe is fed to engine/swatch.py's
build_test_foundation() and simulate_swatch() exactly as before: a
foundation WE compute from a fixed test_repeat_count, and a row-by-row
simulation independent of any AI-stated number -- nothing here
reintroduces a concrete AI-stated foundation count anywhere in the
chain, since neither the identification call nor the recipe call ever
produces one (see contracts/proposal_schema_v3.json and
contracts/stitch_recipe_schema_v1.json).

Costs a fraction of a cent per call (usually one identification call
plus, at most, one recipe call per NEW stitch family). Separate from
main.py's demo (which uses free, hardcoded stand-in data and needs no
API key) so that demo keeps running instantly with no network access
or credentials required.

Usage: python3 run_real_photo.py path/to/photo.jpg
"""

import sys

from engine.confirmed_patterns import check_against_confirmed, get_confirmed_recipe
from engine.plausibility import check_setup_not_oversized, run_plausibility_checks
from engine.renderer import render_row
from engine.schema import validate_proposal
from engine.swatch import build_test_foundation, simulate_swatch
from engine.vision import get_stitch_recipe, get_vision_proposal_from_photo, VisionProposalError

# How many times to work the recipe's repeat, purely for building a
# foundation chain to TEST against -- ours, not any AI-stated number.
# See build_test_foundation()'s docstring for why using an AI's own
# number here would make the whole check circular.
TEST_REPEAT_COUNT = 6

# How many rows to simulate in the constructed test swatch: row 1 uses
# the recipe's setup, every row after uses its turning_chain. A fixed
# number we choose, same spirit as TEST_REPEAT_COUNT -- not read from
# anywhere the AI proposed.
NUM_TEST_ROWS = 4


def resolve_recipe(stitch_family):
    """
    Returns (recipe, source) for stitch_family, where source is
    "confirmed" or "unverified".

    Checks engine/confirmed_patterns.py first -- if a confirmed recipe
    already exists, uses it directly and never calls get_stitch_recipe()
    at all (no need to ask again once something's proven). Only when
    nothing's confirmed does it make that separate, non-photo call; the
    fresh result is recorded via check_against_confirmed() (so
    confirm_stitch.py has something to pull from later) and returned
    labeled "unverified".
    """
    confirmed = get_confirmed_recipe(stitch_family)
    if confirmed is not None:
        return confirmed, "confirmed"

    recipe = get_stitch_recipe(stitch_family)
    # Status is necessarily NO_CONFIRMED_ENTRY here (we just checked) --
    # this call is purely for its last_ai_proposal-recording side effect.
    check_against_confirmed(stitch_family, recipe["setup"], recipe["repeat"], recipe["turning_chain"])
    return recipe, "unverified"


def report_region(region):
    print(f"\n-- {region['region_label']}: {region['stitch_family']} "
          f"(confidence: {region['confidence']}) --")
    if region["uncertain_fields"]:
        print(f"   AI is unsure about: {', '.join(region['uncertain_fields'])}")

    stitch_family = region["stitch_family"]

    try:
        recipe, source = resolve_recipe(stitch_family)
    except VisionProposalError as e:
        print(f"   Could not get a recipe for '{stitch_family}': {e}")
        return

    if source == "confirmed":
        print(f"   Using the confirmed recipe for '{stitch_family}' (no recipe call needed).")
    else:
        print(f"   No confirmed recipe for '{stitch_family}' yet -- asked generically how it's constructed.")
        # Safety net on the fresh, unverified recipe: setup and
        # turning_chain are both one-time step lists that precede a
        # repeat, so both get the oversized-setup check; repeat gets
        # the degenerate check via run_plausibility_checks().
        warnings = run_plausibility_checks({"setup": recipe["setup"], "repeat": recipe["repeat"]})
        turning_chain_warning = check_setup_not_oversized(recipe["turning_chain"])
        if turning_chain_warning:
            warnings.append(f"turning_chain {turning_chain_warning}")
        if warnings:
            print(f"   [plausibility] unverified recipe for '{stitch_family}':")
            for w in warnings:
                print(f"     - {w}")
        else:
            print(f"   [plausibility] unverified recipe for '{stitch_family}' looks structurally reasonable.")

    # Build a short test swatch from this ONE recipe: row 1 uses the
    # recipe's setup, every row after uses its turning_chain -- the
    # same repeat unit throughout, matching how a real swatch works.
    row_1 = {"setup": recipe["setup"], "repeat": recipe["repeat"]}
    later_row = {"setup": recipe["turning_chain"], "repeat": recipe["repeat"]}
    rows = [row_1] + [later_row] * (NUM_TEST_ROWS - 1)

    foundation_length = build_test_foundation(row_1["setup"], row_1["repeat"], test_repeat_count=TEST_REPEAT_COUNT)
    print(f"   Foundation chain: {foundation_length} stitches "
          f"(test swatch: {TEST_REPEAT_COUNT} repeats of the recipe's repeat unit)")

    result = simulate_swatch(rows, foundation_length, test_repeat_count=TEST_REPEAT_COUNT)

    for entry in result["trail"]:
        row = rows[entry["row_number"] - 1]
        if entry["valid"]:
            print(f"   Row {entry['row_number']}: {render_row(row, TEST_REPEAT_COUNT)}")
        else:
            print(f"   Row {entry['row_number']}: FAILED -- needed {entry['consumed']} stitches, "
                  f"only {entry['stitches_available']} were available from the row before it")

    if result["success"]:
        print(f"   Swatch holds up across all {len(rows)} test rows.")
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
    print(f"Proposal for {proposal.get('photo_id', '?')}: {len(regions)} stitch region(s) identified")
    for region in regions:
        report_region(region)


if __name__ == "__main__":
    main()
