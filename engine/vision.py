"""
The AI integration layer: identifying stitch regions from a photo, and
separately, asking how a named stitch is conventionally constructed.

These are deliberately TWO different API calls, not one. A photo-
grounded call kept inventing garment-specific numbers when asked to
propose row structure from an image -- oversized setup chains sized to
the garment's width, inconsistent turning chains -- because it was
trying to (mis)measure something from the photo instead of stating the
stitch's actual convention. The same model gives correct, standard
answers when asked generically "how do you construct a [stitch name]"
with no image involved, nothing to measure against. So:

  get_vision_proposal_from_photo() -- PHOTO call, IDENTIFICATION only:
      region_label, stitch_family, confidence, uncertain_fields. No
      setup, no repeat, no row structure, no numbers at all.

  get_stitch_recipe() -- separate, NON-PHOTO call, given just a stitch
      family name: the conventional setup/repeat/turning_chain
      structure, as concrete steps. Never an absolute foundation count.

get_vision_proposal() is the identification-only STAND-IN (no API
credentials here), matching what get_vision_proposal_from_photo()
actually returns. That's the one deliberately faked piece of this
project, labeled as such -- everything downstream of it (schema
validation, DSL parsing, row checking) is real and runs exactly as it
would against a real model's output.

A single photo can show more than one stitch pattern -- a fan panel and
a mesh panel on the same garment, say -- so a proposal is a list of
"regions", each identified independently. One region being wrong
doesn't throw out the rest of the photo's proposal.
"""

import base64
import copy
import json
import os
from pathlib import Path

from dotenv import load_dotenv
import anthropic

from engine.schema import validate_proposal, validate_recipe

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "proposal_schema_v3.json"
_RECIPE_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "stitch_recipe_schema_v1.json"

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_VISION_PROMPT = (
    "This is a photo of a crocheted garment. Identify 2-3 visually distinct "
    "stitch regions on it (for example, a mesh panel vs. a fan panel vs. a "
    "border). For each region, give it a region_label describing where it "
    "is on the garment, and name the stitch_family -- your best guess at "
    "the conventional/standard name for this stitch pattern (e.g. 'filet "
    "mesh', 'shell stitch', 'single crochet border').\n\n"
    "Always give stitch_family as a real, recognized crochet stitch pattern "
    "name that a crocheter could look up and recognize -- for example "
    "'filet mesh', 'V-stitch', 'shell stitch', 'single crochet', 'granny "
    "stitch'. Even if you are not fully certain this region is a perfect "
    "textbook match, choose the closest real, established stitch name "
    "rather than inventing a descriptive label for what you see (like "
    "'open mesh with chain spaces') -- put your uncertainty in confidence "
    "and uncertain_fields instead, never into the name itself.\n\n"
    "Do NOT propose any row structure, stitch counts, setup steps, or "
    "repeat units here -- this call is identification only. How a named "
    "stitch is actually constructed is determined separately, by asking "
    "generically how it's conventionally made, with no photo involved.\n\n"
    "Be honest about uncertainty -- list any fields you aren't confident "
    "about in uncertain_fields rather than guessing silently."
)


def _recipe_prompt(stitch_family):
    return (
        f"You are about to actually crochet a small test swatch of "
        f"'{stitch_family}' from scratch, starting from a plain foundation "
        f"chain with nothing worked into it yet. Walk through exactly how "
        f"you would do that, all the way through to a workable swatch, as "
        f"concrete steps, not prose, using only these stitch codes: CH, SC, "
        f"HDC, DC, SLST, SKIP, INC, DEC.\n\n"
        f"Give three things:\n"
        f"1. setup: the one-time steps worked directly into the foundation "
        f"chain before row 1's repeat starts. This must include anything "
        f"genuinely needed to start row 1 correctly -- including skipping "
        f"chains to account for the height of the repeat's first stitch "
        f"(for example, a repeat starting with a double crochet "
        f"conventionally needs a few chains skipped first, the same way a "
        f"turning chain does on a later row). Only leave this empty if the "
        f"repeat's first stitch genuinely has no height and needs no "
        f"lead-in at all (like slip stitch, or single crochet worked "
        f"straight into the foundation chain) -- never leave it empty just "
        f"because you are unsure of the exact convention.\n"
        f"2. repeat: the unit that repeats across a row. Never empty.\n"
        f"3. turning_chain: the conventional turning-chain steps worked at "
        f"the start of EVERY row after the first, before that row's repeat "
        f"starts -- this applies to row 2 onward, not just row 1. Can be "
        f"empty if this stitch needs no turning chain.\n\n"
        f"Important context: you are describing the STRUCTURE of a small "
        f"test swatch used to verify the stitch pattern, not sizing an "
        f"actual finished garment section. A foundation chain of some "
        f"number of stitches will be created separately -- you don't know "
        f"that number, and you must not state or imply one. Describe only "
        f"the conventional setup/repeat/turning-chain structure for this "
        f"stitch, independent of any particular swatch size. If your "
        f"answer would naturally include an illustrative example number "
        f"(like 'e.g. chain 21 for a 20-stitch swatch'), leave it out "
        f"entirely -- only the structural steps matter here, never a "
        f"foundation-scale guess."
    )


class VisionProposalError(Exception):
    """Raised when a real API call (photo identification or stitch recipe) can't produce a usable result."""


def _add_additional_properties_false(node):
    """
    The contracts/*.json files are written as human-readable contracts,
    not API request payloads, so they don't set additionalProperties on
    every object -- structured outputs requires that on every object
    schema. Added here, recursively, on an in-memory copy, so the
    schema files themselves stay untouched and don't need retyping.
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

# Non-standard metadata keys the contracts/*.json files carry for human
# readers ($schema/$id identify the draft-07 document, schemaVersion is
# this project's own field) but that structured outputs doesn't
# recognize as schema keywords -- dropped outright, no bound to
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
    the constraint even though the API won't enforce it -- validate_proposal()/
    validate_recipe() is what actually enforces it once the response comes
    back, so this doesn't weaken what's ultimately trusted.
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


def _load_api_schema(schema_path):
    with open(schema_path) as f:
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


def _call_claude_for_structured_json(model, content, schema):
    """
    Shared plumbing for get_vision_proposal_from_photo() and
    get_stitch_recipe(): loads the API key, calls Claude with structured
    outputs constrained to schema, and returns the parsed JSON dict.

    Raises VisionProposalError with a clear message on any failure:
    missing/invalid API key, network/API errors, a safety refusal,
    truncation, or a response that isn't valid JSON. Callers still run
    their own schema-specific validate_proposal()/validate_recipe()
    afterward -- this never trusts the response as usable just because
    it came back through structured outputs.
    """
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise VisionProposalError(
            "ANTHROPIC_API_KEY is not set. Put it in a .env file at the "
            "project root (ANTHROPIC_API_KEY=...) or export it in your shell."
        )

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
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
        raise VisionProposalError("Claude declined to answer (safety refusal).")
    if response.stop_reason == "max_tokens":
        raise VisionProposalError(
            "Response was cut off at the max_tokens limit before finishing -- "
            "increase max_tokens in engine/vision.py."
        )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise VisionProposalError(
            f"No text content in the API response (stop_reason={response.stop_reason!r})"
        )

    try:
        return json.loads(text_blocks[0])
    except json.JSONDecodeError as e:
        raise VisionProposalError(f"Response wasn't valid JSON: {e}") from e


def get_vision_proposal_from_photo(image_path, model="claude-haiku-4-5"):
    """
    Sends a real garment photo to Claude and returns a proposal dict in
    the same shape get_vision_proposal() already returns: IDENTIFICATION
    only -- region_label, stitch_family, confidence, uncertain_fields per
    region. No row structure. For a named stitch_family's actual
    construction, see get_stitch_recipe() -- a separate, non-photo call.

    Uses the Messages API's structured-outputs feature, constrained to
    contracts/proposal_schema_v3.json. That constraint is never trusted
    blindly: the parsed response is still run through validate_proposal()
    before being returned.

    Raises VisionProposalError with a clear message whenever a usable
    proposal can't be produced: missing API key, a missing/unreadable
    image, a network/API failure, or a response that fails
    validate_proposal().
    """
    image_file = Path(image_path)
    if not image_file.is_file():
        raise VisionProposalError(f"Image not found: {image_path}")

    media_type = _media_type_for(image_path)
    image_data = base64.standard_b64encode(image_file.read_bytes()).decode("utf-8")
    schema = _load_api_schema(_SCHEMA_PATH)

    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_data},
        },
        {"type": "text", "text": _VISION_PROMPT},
    ]
    proposal = _call_claude_for_structured_json(model, content, schema)

    errors = validate_proposal(proposal)
    if errors:
        raise VisionProposalError(
            "Real proposal failed schema validation, even though it came "
            "back through structured outputs:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return proposal


def get_stitch_recipe(stitch_family, model="claude-haiku-4-5"):
    """
    Makes a SEPARATE API call -- NO image attached -- asking generically
    how stitch_family is conventionally constructed. This is the fix for
    a real failure mode: the same model that invents garment-specific
    numbers (oversized setup chains, inconsistent turning chains) when
    asked to propose row structure from a photo gives correct, standard
    answers when asked this generically, with nothing to (mis)measure
    against.

    Returns {"setup": [...], "repeat": [...], "turning_chain": [...]} --
    concrete step lists only, constrained by
    contracts/stitch_recipe_schema_v1.json, which has no field for an
    absolute foundation chain count at all. If the model's answer would
    naturally include an illustrative concrete number, the prompt tells
    it to leave that out; either way, nothing downstream ever extracts
    or reads a number from anywhere but these three step lists -- there
    is no other channel (like scanning response text) for a number to
    arrive through.

    Raises VisionProposalError on the same failure modes as
    get_vision_proposal_from_photo(): missing key, network/API errors,
    refusal, truncation, bad JSON, or a response that fails
    validate_recipe().
    """
    schema = _load_api_schema(_RECIPE_SCHEMA_PATH)
    content = [{"type": "text", "text": _recipe_prompt(stitch_family)}]
    recipe = _call_claude_for_structured_json(model, content, schema)

    errors = validate_recipe(recipe)
    if errors:
        raise VisionProposalError(
            "Recipe response failed schema validation, even though it came "
            "back through structured outputs:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return recipe


def get_vision_proposal(which_example="good"):
    """
    STAND-IN for a real photo-identification call. A real call would
    send a photo to a vision-language model and parse its response into
    this same shape (see contracts/proposal_schema_v3.json): IDENTIFICATION
    only, no row structure -- get_stitch_recipe() is what supplies that,
    separately, once a stitch_family is known.

    which_example="good"  -> two distinct stitch regions, both confidently identified
    which_example="mixed" -> two regions, one identification confident,
                              one much less so -- the realistic case: a
                              model can be sure about part of a photo and
                              unsure about another part of it
    """
    mesh_region = {
        "region_label": "center panel",
        "stitch_family": "filet mesh",
        "confidence": 0.78,
        "uncertain_fields": [],
    }

    if which_example == "good":
        border_region = {
            "region_label": "edge border",
            "stitch_family": "single crochet border",
            "confidence": 0.91,
            "uncertain_fields": [],
        }
        return {"photo_id": "halter_top_front.jpg", "regions": [mesh_region, border_region]}

    else:
        unknown_cluster_region = {
            "region_label": "fan panel (left)",
            "stitch_family": "unknown cluster stitch",
            "confidence": 0.35,
            "uncertain_fields": ["stitch_family"],
        }
        return {"photo_id": "halter_top_front.jpg", "regions": [mesh_region, unknown_cluster_region]}


def process_proposal(proposal):
    """
    Prints a photo proposal's region identifications, after checking it
    against the schema. IDENTIFICATION only -- region_label,
    stitch_family, confidence, uncertain_fields -- no row structure or
    stitch counts here; see get_stitch_recipe() for how a named stitch
    family's actual construction is determined (a separate, non-photo
    call), and run_real_photo.py for the full pipeline that turns an
    identification into a validated test swatch.
    """
    schema_errors = validate_proposal(proposal)
    if schema_errors:
        print(f"Proposal for {proposal.get('photo_id', '?')}: REJECTED -- doesn't match the schema:")
        for error in schema_errors:
            print(f"  - {error}")
        return

    regions = proposal["regions"]
    print(f"Proposal for {proposal.get('photo_id', '?')}: {len(regions)} stitch region(s) detected")

    for region in regions:
        print(f"\n-- {region['region_label']}: {region['stitch_family']} "
              f"(confidence: {region['confidence']}) --")
        if region["uncertain_fields"]:
            print(f"   AI is unsure about: {', '.join(region['uncertain_fields'])}")
