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

import base64
import copy
import json
import os
from pathlib import Path

from dotenv import load_dotenv
import anthropic

from engine.validator import check_full_row
from engine.schema import validate_proposal
from engine.renderer import render_row

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "proposal_schema_v2.json"

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_VISION_PROMPT = (
    "This is a photo of a crocheted garment. Identify 2-3 visually distinct "
    "stitch regions on it (for example, a mesh panel vs. a fan panel vs. a "
    "border). For each region: give it a region_label describing where it "
    "is on the garment, name the stitch_family, and propose the row(s) as "
    "setup/repeat steps plus how many times the repeat is worked "
    "(repeat_count), using only these stitch codes: CH, SC, HDC, DC, SLST, "
    "SKIP, INC, DEC. Be honest about uncertainty -- list any fields you "
    "aren't confident about in uncertain_fields rather than guessing "
    "silently."
)


class VisionProposalError(Exception):
    """Raised when a real vision-model call can't produce a usable proposal."""


def _add_additional_properties_false(node):
    """
    contracts/proposal_schema_v2.json is written as the human-readable
    contract, not an API request payload, so it doesn't set
    additionalProperties on every object -- structured outputs require
    that on every object schema. Added here, recursively, so the schema
    file itself stays untouched and doesn't need retyping.
    """
    if isinstance(node, dict):
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
        for value in node.values():
            _add_additional_properties_false(value)
    elif isinstance(node, list):
        for item in node:
            _add_additional_properties_false(item)
    return node


_UNSUPPORTED_SCHEMA_KEYWORDS = ("minLength", "maxLength", "pattern", "minItems", "maxItems")

# Non-standard metadata keys that contracts/proposal_schema_v2.json carries
# for human readers ($schema/$id identify it as a draft-07 document,
# schemaVersion is this project's own field) but that structured outputs
# doesn't recognize as schema keywords -- dropped outright, no bound to
# preserve, unlike minimum/maximum.
_UNSUPPORTED_METADATA_KEYS = ("$schema", "$id", "schemaVersion")


def _strip_unsupported_schema_keywords(schema_node):
    """
    Claude's structured-outputs feature (output_config.format.schema) only
    supports a subset of JSON Schema -- it rejects the whole request if it
    sees minimum, maximum, minLength, maxLength, pattern, minItems,
    maxItems, or non-standard metadata keys like schemaVersion anywhere in
    the schema, including nested inside properties, items, or
    oneOf/anyOf/allOf entries. This walks a deep copy of the schema and
    removes them wherever they appear. A removed numeric minimum/maximum is
    folded into that node's description instead, so the model still knows
    the constraint even though the API won't enforce it -- validate_proposal()
    is what actually enforces it once the response comes back, so this
    doesn't weaken what's ultimately trusted.
    """
    node = copy.deepcopy(schema_node)
    _strip_in_place(node)
    return node


def _strip_in_place(node):
    if isinstance(node, dict):
        minimum = node.pop("minimum", None)
        maximum = node.pop("maximum", None)
        for key in _UNSUPPORTED_SCHEMA_KEYWORDS:
            node.pop(key, None)
        for key in _UNSUPPORTED_METADATA_KEYS:
            node.pop(key, None)

        if minimum is not None or maximum is not None:
            if minimum is not None and maximum is not None:
                bound_note = f"Must be between {minimum} and {maximum}."
            elif minimum is not None:
                bound_note = f"Must be at least {minimum}."
            else:
                bound_note = f"Must be at most {maximum}."
            existing_description = node.get("description")
            node["description"] = (
                f"{existing_description} {bound_note}" if existing_description else bound_note
            )

        for value in node.values():
            _strip_in_place(value)
    elif isinstance(node, list):
        for item in node:
            _strip_in_place(item)


def _load_api_schema():
    with open(_SCHEMA_PATH) as f:
        schema = json.load(f)
    schema = _add_additional_properties_false(schema)
    schema = _strip_unsupported_schema_keywords(schema)
    return schema


def _media_type_for(image_path):
    ext = Path(image_path).suffix.lower()
    if ext not in _MEDIA_TYPES:
        raise VisionProposalError(
            f"Unsupported image extension '{ext}' for {image_path} "
            f"(expected one of {sorted(_MEDIA_TYPES)})"
        )
    return _MEDIA_TYPES[ext]


def get_vision_proposal_from_photo(image_path, model="claude-haiku-4-5"):
    """
    Sends a real garment photo to Claude and returns a proposal dict in
    the same shape get_vision_proposal() already returns -- a drop-in
    replacement anywhere that shape is expected (process_proposal(), a
    real-photo script, etc).

    Uses the Messages API's structured-outputs feature (output_config
    with format type "json_schema", loaded from
    contracts/proposal_schema_v2.json) to constrain the response shape.
    That constraint is never trusted blindly: the parsed response is
    still run through validate_proposal() before being returned, the
    same defensive check any other proposal gets.

    Raises VisionProposalError with a clear message whenever a usable
    proposal can't be produced: missing API key, a missing/unreadable
    image, a network/API failure, or a response that fails
    validate_proposal().
    """
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise VisionProposalError(
            "ANTHROPIC_API_KEY is not set. Put it in a .env file at the "
            "project root (ANTHROPIC_API_KEY=...) or export it in your shell."
        )

    image_file = Path(image_path)
    if not image_file.is_file():
        raise VisionProposalError(f"Image not found: {image_path}")

    media_type = _media_type_for(image_path)
    image_data = base64.standard_b64encode(image_file.read_bytes()).decode("utf-8")
    schema = _load_api_schema()

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AuthenticationError as e:
        raise VisionProposalError(f"Anthropic API rejected the API key: {e}") from e
    except anthropic.RateLimitError as e:
        raise VisionProposalError(f"Rate limited by the Anthropic API: {e}") from e
    except anthropic.APIConnectionError as e:
        raise VisionProposalError(f"Network error calling the Anthropic API: {e}") from e
    except anthropic.APIStatusError as e:
        raise VisionProposalError(
            f"Anthropic API returned an error (status {e.status_code}): {e.message}"
        ) from e

    if response.stop_reason == "refusal":
        raise VisionProposalError(
            "Claude declined to answer (safety refusal) -- try a different photo."
        )
    if response.stop_reason == "max_tokens":
        raise VisionProposalError(
            "Response was cut off at the max_tokens limit before finishing -- "
            "increase max_tokens in get_vision_proposal_from_photo()."
        )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise VisionProposalError(
            f"No text content in the API response (stop_reason={response.stop_reason!r})"
        )

    try:
        proposal = json.loads(text_blocks[0])
    except json.JSONDecodeError as e:
        raise VisionProposalError(f"Response wasn't valid JSON: {e}") from e

    errors = validate_proposal(proposal)
    if errors:
        raise VisionProposalError(
            "Real proposal failed schema validation, even though it came "
            "back through structured outputs:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return proposal


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
