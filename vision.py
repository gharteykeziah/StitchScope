"""
Stand-in for the vision-model perception layer.

There are no API credentials for a real vision-language model here, so
get_vision_proposal() returns hand-written example proposals instead of
an actual model response. That's the one deliberately faked piece of this
project, and it's labeled as such -- everything downstream of it (schema
validation, DSL parsing, row checking) is real and runs exactly as it
would against a real model's output. Swapping in a real API call later
means replacing get_vision_proposal()'s body; nothing else has to change.
"""

from validator import check_full_row
from schema import validate_proposal
from renderer import render_row


def get_vision_proposal(which_example="good"):
    """
    STAND-IN for a real vision-model API call. A real version of this
    function would send a cropped reference photo to a vision-language
    model and parse its response into this same shape (see
    schema/proposal_schema_v1.json for what that shape has to be).
    """
    if which_example == "good":
        return {
            "stitch_family": "filet mesh",
            "confidence": 0.78,
            "rows": [
                {
                    "setup": [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}],
                    "repeat": [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}],
                    "repeat_count": 7,
                }
            ],
            "uncertain_fields": [],
        }
    else:
        return {
            "stitch_family": "unknown cluster stitch",
            "confidence": 0.35,
            "rows": [
                {
                    "setup": [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}],
                    "repeat": [{"stitch": "DC", "count": 5}],
                    "repeat_count": 7,
                }
            ],
            "uncertain_fields": ["stitch_count"],
        }


def _describe_steps(steps):
    if not steps:
        return "(none)"
    return ", ".join(f"{s['stitch']} {s['count']}" for s in steps)


def process_proposal(proposal, stitches_available):
    """
    Runs a vision-model proposal through the real validation pipeline:
    schema check first (is this even shaped like a valid proposal?), then
    each row through the row simulator (does the AI's claimed repeat_count
    actually fit the stitches available?).
    """
    schema_errors = validate_proposal(proposal)
    if schema_errors:
        print(f"AI proposal: {proposal.get('stitch_family', '?')} "
              f"(confidence: {proposal.get('confidence', '?')})")
        print("  REJECTED -- proposal doesn't match the schema:")
        for error in schema_errors:
            print(f"    - {error}")
        return

    print(f"AI proposal: {proposal['stitch_family']} (confidence: {proposal['confidence']})")
    if proposal["uncertain_fields"]:
        print(f"  AI is unsure about: {', '.join(proposal['uncertain_fields'])}")

    for i, row in enumerate(proposal["rows"], start=1):
        result = check_full_row(row, row["repeat_count"], stitches_available)
        setup_text = _describe_steps(row["setup"])
        repeat_text = _describe_steps(row["repeat"])
        status = "VALID" if result["valid"] else "REJECTED"
        print(f"  Row {i} (setup: {setup_text} | repeat: {repeat_text} x{row['repeat_count']}) "
              f"-> {status} (used {result['consumed']} of {stitches_available} available)")
        if result["valid"]:
            print(f"    In plain English: {render_row(row, row['repeat_count'])}")
