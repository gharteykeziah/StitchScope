"""
Turns a photo into a structured stitch-pattern proposal.

get_vision_proposal() is currently a STAND-IN for a real call to a
vision-language model - it returns the same shape of answer a real
model would, so everything that uses it already works correctly.
Swap this one function for a real API call once credentials exist;
nothing else in the project needs to change.
"""

from pattern_reader import read_row
from validator import check_row


def get_vision_proposal(which_example="good"):
    """STAND-IN for a real vision-model call on a photo crop."""
    if which_example == "good":
        return {
            "stitch_family": "filet mesh",
            "confidence": 0.78,
            "rows": ["CH 1, DC 1, SKIP 1"],
            "uncertain_fields": [],
        }
    else:
        return {
            "stitch_family": "unknown cluster stitch",
            "confidence": 0.35,
            "rows": ["DC 5, SKIP 1"],
            "uncertain_fields": ["stitch_count"],
        }


def process_proposal(proposal, stitches_available):
    """Checks an AI proposal for validity using the reader and validator."""
    print(f"AI proposal: {proposal['stitch_family']} (confidence: {proposal['confidence']})")
    if proposal["uncertain_fields"]:
        print(f"  AI is unsure about: {', '.join(proposal['uncertain_fields'])}")

    all_valid = True
    for row_text in proposal["rows"]:
        steps = read_row(row_text)
        result = check_row(steps, stitches_available)
        status = "VALID" if result["valid"] else "REJECTED"
        print(f"  Row '{row_text}' -> {status} (used {result['consumed']} of {stitches_available} available)")
        if not result["valid"]:
            all_valid = False

    return all_valid
