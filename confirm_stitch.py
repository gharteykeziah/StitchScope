"""
Confirm a stitch family's real setup/repeat/turning_chain, pulled from
the most recent AI proposal already on record for it (see
engine/confirmed_patterns.py) -- i.e. "I hand-swatched this and here's
what it actually is." Run run_real_photo.py against a photo showing
the stitch first; that's what populates the proposal this script pulls
from.

Usage:
  python3 confirm_stitch.py "double crochet mesh" --photo IMG_2413.jpg \
      --note "matched the halter mesh panel exactly"
"""

import argparse
import sys

from engine.confirmed_patterns import (
    ConfirmationConflictError,
    confirm_pattern,
    load_patterns,
    normalize_stitch_family,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stitch_family", help="e.g. 'double crochet mesh'")
    parser.add_argument("--photo", required=True, help="source photo filename this confirmation is based on")
    parser.add_argument("--note", required=True, help="short human note, e.g. how it was verified")
    args = parser.parse_args()

    key = normalize_stitch_family(args.stitch_family)
    data = load_patterns()
    entry = data.get(key)

    if entry is None or entry.get("last_ai_proposal") is None:
        print(f"No AI proposal on record yet for '{args.stitch_family}' -- "
              f"run run_real_photo.py against a photo showing it first.")
        sys.exit(1)

    proposal = entry["last_ai_proposal"]

    try:
        confirmed = confirm_pattern(
            args.stitch_family,
            setup=proposal["setup"],
            repeat=proposal["repeat"],
            turning_chain=proposal["turning_chain"],
            photo_filename=args.photo,
            note=args.note,
        )
    except ConfirmationConflictError as e:
        print(f"Could not confirm '{args.stitch_family}':\n{e}")
        sys.exit(1)

    print(f"Confirmed '{args.stitch_family}':")
    print(f"  setup:         {confirmed['setup']}")
    print(f"  repeat:        {confirmed['repeat']}")
    print(f"  turning_chain: {confirmed['turning_chain']}")
    print(f"  confirmations: {len(confirmed['confirmations'])} on record")


if __name__ == "__main__":
    main()
