"""
Stand-in for the vision-model perception layer.

There are no API credentials for a real vision-language model here, so
get_vision_proposal() returns hand-written example proposals instead of
an actual model response. That's the one deliberately faked piece of this
project, and it's labeled as such -- everything downstream of it (schema
validation, DSL parsing, row checking) is real and runs exactly as it
would against a real model's output.

A single photo can show more than one stitch pattern -- a fan panel and
a mesh panel on the same garment, say -- so a proposal is a list of
"regions", each proposed and validated independently. One region being
wrong doesn't throw out the rest of the photo's proposal.
"""

from engine.validator import check_full_row
from engine.schema import validate_proposal
from engine.renderer import render_row


def get_vision_proposal(which_example="good"):
    """
    STAND-IN for a real vision-model API call. A real version of this
    function would send a photo to a vision-language model and parse its
    response into this same shape (see contracts/proposal_schema_v2.json
    for what that shape has to be).

    which_example="good"  -> two distinct stitch regions, both valid
    which_example="mixed" -> two regions from the same photo, one valid
                              and one that isn't -- the realistic case:
                              a model can be right about part of a photo
                              and wrong about another part of it
    """
    mesh_region = {
        "region_label": "center panel",
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

    if which_example == "good":
        border_region = {
            "region_label": "edge border",
            "stitch_family": "single crochet border",
            "confidence": 0.91,
            "rows": [
                {
                    "setup": [],
                    "repeat": [{"stitch": "SC", "count": 1}],
                    "repeat_count": 20,
                }
            ],
            "uncertain_fields": [],
        }
        return {"photo_id": "halter_top_front.jpg", "regions": [mesh_region, border_region]}

    else:
        unknown_cluster_region = {
            "region_label": "fan panel (left)",
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
        return {"photo_id": "halter_top_front.jpg", "regions": [mesh_region, unknown_cluster_region]}


def _describe_steps(steps):
    if not steps:
        return "(none)"
    return ", ".join(f"{s['stitch']} {s['count']}" for s in steps)


def process_proposal(proposal, stitches_available):
    """
    Runs a vision-model proposal through the real validation pipeline:
    schema check first (is this even shaped like a valid proposal?), then
    each region's rows through the row simulator (does the AI's claimed
    repeat_count actually fit the stitches available?). Each region is
    reported on independently -- a bad guess in one region of a photo
    doesn't hide a good guess in another.

    stitches_available can be a single number (applied to every region)
    or a list with one entry per region, since different panels of a
    real garment don't all start from the same stitch count.
    """
    schema_errors = validate_proposal(proposal)
    if schema_errors:
        print(f"Proposal for {proposal.get('photo_id', '?')}: REJECTED -- doesn't match the schema:")
        for error in schema_errors:
            print(f"  - {error}")
        return

    regions = proposal["regions"]
    if isinstance(stitches_available, int):
        stitches_available = [stitches_available] * len(regions)
    if len(stitches_available) != len(regions):
        raise ValueError(
            f"stitches_available has {len(stitches_available)} entries but "
            f"the proposal has {len(regions)} regions -- need one per region"
        )

    print(f"Proposal for {proposal.get('photo_id', '?')}: {len(regions)} stitch region(s) detected")

    for region, region_stitches_available in zip(regions, stitches_available):
        print(f"\n-- {region['region_label']}: {region['stitch_family']} "
              f"(confidence: {region['confidence']}) --")
        if region["uncertain_fields"]:
            print(f"   AI is unsure about: {', '.join(region['uncertain_fields'])}")

        for i, row in enumerate(region["rows"], start=1):
            result = check_full_row(row, row["repeat_count"], region_stitches_available)
            setup_text = _describe_steps(row["setup"])
            repeat_text = _describe_steps(row["repeat"])
            status = "VALID" if result["valid"] else "REJECTED"
            print(f"   Row {i} (setup: {setup_text} | repeat: {repeat_text} x{row['repeat_count']}) "
                  f"-> {status} (used {result['consumed']} of {region_stitches_available} available)")
            if result["valid"]:
                print(f"     In plain English: {render_row(row, row['repeat_count'])}")
