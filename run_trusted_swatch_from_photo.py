"""
Phase 8 CLI: run one real garment photo through the trusted v2 image
pipeline (engine/image_swatch_pipeline.py) -- AI identification, then
resolution against the physically-confirmed v2 recipe library, then
(only for a trusted match) full row simulation and rendering.

This is a NEW, separate entry point from run_real_photo.py (the old,
v1 pathway: engine.confirmed_patterns / engine.swatch / engine.renderer
/ data/confirmed_stitch_patterns.json). Running this script never
touches that old pathway, and never falls back to it -- a region with
no CONFIRMED v2 recipe is reported honestly as having no trusted
instructions available, never silently completed with the old,
un-trust-gated output.

As of Phase 8, data/confirmed_stitch_recipes_v2.json (the production v2
library) has ZERO confirmed recipes -- so a real run against this
script, with no --library override, will currently and correctly report
"no trusted recipe" for every region, no matter how confidently the AI
identifies the stitch. That is the intended, honest behavior until a
recipe is physically confirmed and added to that file; see
docs/recipe_model_v2.md.

Costs a fraction of a cent per call, exactly like run_real_photo.py
(one identification call per photo) -- this script makes NO API call
merely by being imported; the real call only happens inside main(),
which only runs when this file is executed directly.

Usage:
    python3 run_trusted_swatch_from_photo.py path/to/photo.jpg
    python3 run_trusted_swatch_from_photo.py path/to/photo.jpg --repeats 6 --later-rows 3
    python3 run_trusted_swatch_from_photo.py path/to/photo.jpg --library path/to/alt_library.json
"""

import argparse
import json
import sys

from engine.image_swatch_pipeline import STATUS_PROCESSED, generate_swatch_from_image

DEFAULT_REPEAT_COUNT = 6
DEFAULT_LATER_ROW_COUNT = 3


def _load_library_from_path(library_path):
    with open(library_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _print_region(region):
    stitch_name = region["identification"].get("stitch_name")
    print(f"\n-- {region['region_label']}: {stitch_name} (confidence: {region['confidence']}) --")
    if region["uncertainty"]:
        print(f"   AI is unsure: {region['uncertainty']}")

    print(f"   recipe resolution: {region['recipe_resolution_status']}")
    if region["selected_pattern_id"]:
        print(f"   selected trusted pattern: {region['selected_pattern_id']}")

    if region["ready_for_user_instructions"]:
        print(f"   Instructions:\n{region['rendered_instructions']}")
    else:
        print(f"   No trusted instructions available (status: {region['swatch_status']}).")
        for error in region["errors"]:
            print(f"     - {error}")

    for warning in region["warnings"]:
        print(f"   [warning] {warning}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Identify stitches in a photo and produce swatch instructions only "
            "for a stitch whose recipe is already physically confirmed in the "
            "trusted v2 library -- never from the AI's own proposed instructions."
        )
    )
    parser.add_argument("image_path", help="Path to a garment photo (.jpg, .jpeg, or .png)")
    parser.add_argument(
        "--repeats", type=int, default=DEFAULT_REPEAT_COUNT, dest="requested_repeat_count",
        help=f"Repeat count to test each region's swatch against (default: {DEFAULT_REPEAT_COUNT})",
    )
    parser.add_argument(
        "--later-rows", type=int, default=DEFAULT_LATER_ROW_COUNT, dest="later_row_count",
        help=f"Number of later rows to simulate (default: {DEFAULT_LATER_ROW_COUNT})",
    )
    parser.add_argument(
        "--library", type=str, default=None, dest="library_path",
        help="Optional path to an alternate v2 recipe library JSON file (defaults to the real production library)",
    )
    args = parser.parse_args()

    library = None
    if args.library_path:
        try:
            library = _load_library_from_path(args.library_path)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read library file {args.library_path}: {e}")
            sys.exit(1)

    result = generate_swatch_from_image(
        args.image_path,
        requested_repeat_count=args.requested_repeat_count,
        later_row_count=args.later_row_count,
        library=library,
    )

    if result["status"] != STATUS_PROCESSED:
        print(f"Could not process {result['image_path']}: {result['status']}")
        for error in result["errors"]:
            print(f"  - {error}")
        sys.exit(1)

    print(f"Processed {result['image_path']}: {len(result['regions'])} stitch region(s) identified")
    for region in result["regions"]:
        _print_region(region)


if __name__ == "__main__":
    main()
