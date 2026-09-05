"""
Run the real vision-model integration against one actual garment photo.
Costs a fraction of a cent per call. Separate from main.py's demo (which
uses free, hardcoded stand-in data and needs no API key) so that demo
keeps running instantly with no network access or credentials required.

Usage: python3 run_real_photo.py path/to/photo.jpg
"""

import sys

from engine.vision import get_vision_proposal_from_photo, process_proposal, VisionProposalError

# Edit this to match the actual stitches available (foundation chain size,
# or prior row's produced count) for the photo you're running against.
STITCHES_AVAILABLE = 20


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

    process_proposal(proposal, stitches_available=STITCHES_AVAILABLE)


if __name__ == "__main__":
    main()
