"""
Phase 7: turns an already-approved, structured v2 swatch plan (see
engine/swatch_planner_v2.py's _build_swatch_plan()) into plain,
readable crochet instructions.

This module does exactly one job and nothing else. It does NOT:
  - resolve recipes (engine/recipe_library.py's job),
  - perform validation (engine/recipe_validator.py's and
    engine/later_row_validator.py's job),
  - calculate foundation math (engine/foundation.py's job),
  - read the recipe library (engine/recipe_library.py's job),
  - decide trust (is_recipe_trusted(), also engine/recipe_library.py).

It accepts only a plan dict that engine/swatch_planner_v2.py has
already built AFTER every one of those checks passed, and translates
it into words.

render_swatch_plan() does check that its own argument is actually
shaped like such a plan before reading anything from it (see
_validate_plan()) -- None, a list, an empty dict, a dict missing
"ready_for_rendering" (or with it not exactly True), a missing
required field, malformed trust/foundation/step/later-row data, an
unknown stitch code, or an unknown placement all return a safe
{"status": "invalid_plan", ...} result rather than raising. This is
input validation of THIS FUNCTION'S OWN ARGUMENT, not a re-check of
recipe/foundation/row validity -- it never re-derives whether the
underlying recipe or simulation was correct (that was already decided,
successfully, before a plan could exist at all); it only confirms the
plan handed to it is safe to read fields from without crashing or
guessing at missing data.

This check enforces the INTERNAL READINESS CONTRACT strongly, not just
"does it have the right keys": "ready_for_rendering": True alone is not
enough. plan["trust"]["provenance"] must be exactly "library" AND
plan["trust"]["verification_status"] must be exactly "CONFIRMED";
plan["validation_evidence"]'s "row_1_valid", "later_rows_valid", and
"overall_valid" must each be exactly True; and every later-row summary
must itself have "valid": True. A handful of CROSS-FIELD consistency
checks also run -- total_rows agreeing with 1 + len(later_rows), row
1's repeat execution count agreeing with requested_repeat_count,
later-row numbers being consecutive starting at 2, and
foundation_chain_count agreeing with foundation_formula's own
foundation_count -- all comparisons of the plan's OWN fields against
each other, never a re-run of recipe resolution or simulation. A plan
forging `{"trust": {"provenance": "ai"}}` or an empty
`"validation_evidence": {}` is rejected by these checks exactly like a
plan missing a required field is -- both are "invalid_plan," never
silently rendered.

RELATIONSHIP TO engine/renderer.py (v1)

engine/renderer.py renders v1's flat, placement-less step shape
(stitch + count only) for the older pathway -- it is untouched by this
module and this module does not import it. v2 steps carry `placement`
(and sometimes `counts_as`), which is exactly what makes v1's
renderer's wording insufficient here: "double crochet in the next
stitch" is not always correct for a v2 DC step -- it might be worked
`next_foundation_chain`, `same_stitch`, `next_dc`, or `next_chain_space`
instead, each needing different wording (see PLACEMENT LANGUAGE below).

STITCH TERMINOLOGY

`_STITCH_NAMES_BY_TERMINOLOGY` is the one place stitch-code-to-language
mapping lives. Only `"US"` is currently implemented. If a plan's
`terminology` isn't a key in that dict, render_swatch_plan() returns a
safe `"unsupported_terminology"` result instead of guessing -- it never
silently renders US stitch names for an unknown or unimplemented
terminology system (schema v2 also allows `"UK"`, which is not
implemented here yet; a `"UK"` plan is reported unsupported, not
mis-rendered as US wording).

PLACEMENT LANGUAGE

Every schema-v2 placement is translated to plain wording, using only
words a crocheter would recognize -- never internal implementation
terms like target_established, ordered_output, cursor,
produced_structure, or "counts_as pool":

  next_foundation_chain -> "in the next foundation chain"
                            (or "in the next N foundation chains")
  working_loop           -> for CH: "chain N" (the only stitch schema v2
                            ever allows on this placement)
  same_stitch            -> "in the same stitch or space" -- always.
                            Neither validate_row_1_against_foundation()
                            nor validate_recipe_rows() records the KIND
                            (stitch vs. chain space) of the most
                            recently established target anywhere in
                            their returned reports -- only whether a
                            target exists at all. A structured plan
                            built from those reports therefore has no
                            safe way to know which of "in the same
                            stitch" / "in the same chain space" is
                            correct, so this module always uses the
                            generic phrase rather than guessing (see
                            this module's docstring principle: never
                            guess when the evidence doesn't distinguish
                            two possibilities). Adding that evidence
                            would mean changing what Phase 4A/5 track,
                            which is out of this renderer-only module's
                            scope.
  next_stitch             -> "in the next stitch" (or "...N stitches")
  next_dc                 -> "in the next double crochet" (or plural)
  next_chain_space        -> "in the next chain space" (or plural)
  turning_chain           -> "turn and chain N" -- schema v2 only ever
                            allows this placement on a CH step, and
                            only in later_rows.setup, so it always
                            begins a later row. If the step's counts_as
                            is present, a short plain-language note is
                            appended (e.g. "(this chain counts as 1
                            double crochet)") -- useful crochet
                            information a reader needs, not an
                            implementation detail.

Pluralization uses the number of foundation/stitch/chain-space
POSITIONS a step actually touches (STITCH_RULES[stitch]["consumes"] *
count -- reused read-only from engine/validator.py's existing table,
purely for correct English plurals; this is not validation or math,
just consistent vocabulary with the rest of the project), not the raw
step count -- so "DEC 2" (each decrease spanning 2 stitches) correctly
reads "...in the next 4 stitches", not "...in the next 2 stitches".
"""

from engine.schema import V2_KNOWN_STITCHES, V2_PLACEMENTS
from engine.validator import STITCH_RULES

# Every field a plan built by engine/swatch_planner_v2.py's
# _build_swatch_plan() is documented to carry. "ready_for_rendering" is
# checked first and separately (see _validate_plan()) since its
# presence is the plan's own claim that it's safe to read at all.
_REQUIRED_PLAN_FIELDS = (
    "ready_for_rendering", "pattern_id", "name", "terminology", "trust",
    "requested_repeat_count", "total_rows", "foundation_chain_count",
    "foundation_formula", "row_1_setup", "row_1_repeat",
    "row_1_repeat_execution_count", "later_row_setup", "later_row_repeat",
    "later_rows", "validation_evidence", "warnings",
)

_STITCH_NAMES_BY_TERMINOLOGY = {
    "US": {
        "CH": "chain",
        "SC": "single crochet",
        "HDC": "half double crochet",
        "DC": "double crochet",
        "SLST": "slip stitch",
        "SKIP": "skip",
        "INC": "increase",
        "DEC": "decrease",
    },
}


def _plural_noun_phrase(count, singular, plural):
    if count == 1:
        return f"the next {singular}"
    return f"the next {count} {plural}"


def _placement_noun_phrase(placement, stitch, positions, terminology_map):
    if placement == "next_foundation_chain":
        return _plural_noun_phrase(positions, "foundation chain", "foundation chains")
    if placement == "next_stitch":
        return _plural_noun_phrase(positions, "stitch", "stitches")
    if placement == "next_chain_space":
        return _plural_noun_phrase(positions, "chain space", "chain spaces")
    if placement == "next_dc":
        dc_name = terminology_map["DC"]
        return _plural_noun_phrase(positions, dc_name, f"{dc_name}s")
    # Not reachable for a step that already passed validate_recipe_v2()
    # (working_loop/turning_chain/same_stitch are handled by their own
    # branches in _render_step() before this function is ever called),
    # but never fabricate wording for something unrecognized.
    return f"the next {positions} position(s)"


def _describe_counts_as(counts_as, terminology_map):
    parts = []
    for code, n in (counts_as.get("stitch_posts") or {}).items():
        if n:
            name = terminology_map.get(code, code)
            noun = name if n == 1 else f"{name}s"
            parts.append(f"counts as {n} {noun}")
    chain_spaces = counts_as.get("chain_spaces") or 0
    if chain_spaces:
        noun = "chain space" if chain_spaces == 1 else "chain spaces"
        parts.append(f"forms {chain_spaces} {noun}")
    return "; ".join(parts)


def _render_step(step, terminology_map):
    stitch = step["stitch"]
    count = step["count"]
    placement = step["placement"]
    rule = STITCH_RULES[stitch]

    if stitch == "CH":
        if placement == "working_loop":
            return f"chain {count}"
        if placement == "turning_chain":
            phrase = f"turn and chain {count}"
            counts_as = step.get("counts_as")
            if counts_as:
                description = _describe_counts_as(counts_as, terminology_map)
                if description:
                    phrase = f"{phrase} ({description})"
            return phrase
        # Schema v2 never allows CH with any other placement.
        return f"chain {count}"

    if placement == "same_stitch":
        noun_phrase = "the same stitch or space"
    else:
        positions = rule["consumes"] * count
        noun_phrase = _placement_noun_phrase(placement, stitch, positions, terminology_map)

    if stitch == "SKIP":
        return f"skip {noun_phrase}"

    stitch_name = terminology_map[stitch]
    if stitch == "INC":
        noun = "increase" if count == 1 else "increases"
    elif stitch == "DEC":
        noun = "decrease" if count == 1 else "decreases"
    else:
        noun = stitch_name if count == 1 else f"{stitch_name}s"

    return f"make {count} {noun} in {noun_phrase}"


def _render_step_list(steps, terminology_map):
    return [_render_step(step, terminology_map) for step in steps]


def _render_row(label, setup_steps, repeat_steps, repeat_count, terminology_map):
    setup_phrases = _render_step_list(setup_steps, terminology_map)
    repeat_phrases = _render_step_list(repeat_steps, terminology_map)

    pieces = []
    if setup_phrases:
        setup_text = ", then ".join(setup_phrases)
        pieces.append(setup_text[0].upper() + setup_text[1:] + ".")
    if repeat_phrases:
        repeat_text = ", then ".join(repeat_phrases)
        times_word = "time" if repeat_count == 1 else "times"
        pieces.append(f"Then repeat {repeat_count} {times_word}: {repeat_text}.")

    body = " ".join(pieces) if pieces else "(no steps)"
    return f"{label}: {body}"


def _is_plain_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_exactly_true(value):
    """
    True only for the literal bool True -- never for a truthy non-bool
    (1, "yes", a non-empty list, ...). Every "must be exactly True"
    check in this module (ready_for_rendering, trust.verification_status
    being CONFIRMED-gated, validation_evidence's three fields, and each
    later-row summary's "valid") uses this, because a forged or
    carelessly-built plan claiming readiness with `1` instead of `True`
    is exactly the kind of "truthy but not actually true" gap this
    validation exists to close -- see this module's docstring.
    """
    return value is True


def _validate_step(step, path, errors):
    if not isinstance(step, dict):
        errors.append(f"{path}: step must be an object, got {type(step).__name__}")
        return
    stitch = step.get("stitch")
    if stitch not in V2_KNOWN_STITCHES:
        errors.append(f"{path}.stitch: unknown stitch code {stitch!r}")
    count = step.get("count")
    if not _is_plain_int(count) or count < 1:
        errors.append(f"{path}.count: must be a positive integer, got {count!r}")
    placement = step.get("placement")
    if placement not in V2_PLACEMENTS:
        errors.append(f"{path}.placement: unknown placement {placement!r}")


def _validate_step_list(steps, path, errors):
    if not isinstance(steps, list):
        errors.append(f"{path}: must be a list, got {type(steps).__name__}")
        return
    for i, step in enumerate(steps):
        _validate_step(step, f"{path}[{i}]", errors)


def _validate_later_row_summary(summary, index, errors):
    path = f"plan.later_rows[{index}]"
    if not isinstance(summary, dict):
        errors.append(f"{path}: must be an object, got {type(summary).__name__}")
        return
    row_number = summary.get("row_number")
    if not _is_plain_int(row_number) or row_number < 2:
        errors.append(f"{path}.row_number: must be an integer >= 2, got {row_number!r}")
    count = summary.get("repeat_execution_count")
    if not (_is_plain_int(count) and count >= 0):
        errors.append(f"{path}.repeat_execution_count: must be a non-negative integer, got {count!r}")
    if "valid" not in summary:
        errors.append(f"{path}: missing required field 'valid'")
    elif not _is_exactly_true(summary["valid"]):
        # A later row this renderer is asked to produce text for must
        # itself have been reported valid by the simulation that built
        # this plan -- exactly True, not merely truthy (see
        # _is_exactly_true()'s docstring for why bool identity matters
        # here the same way it does for ready_for_rendering).
        errors.append(f"{path}.valid: must be exactly True, got {summary['valid']!r}")


def _validate_plan(plan):
    """
    Checks that `plan` is actually shaped like a plan
    engine/swatch_planner_v2.py's _build_swatch_plan() would produce,
    BEFORE render_swatch_plan() reads a single field from it. This is
    input validation of this module's own argument -- distinct from
    recipe/foundation/row validation (Phases 4A/5/6's job, already done
    long before a plan exists at all) -- so checking it here does not
    put recipe validation logic in the renderer; it puts "is this
    argument safe to read" checking in the function that's about to
    read it, exactly as any function should for its own inputs.

    Checks, every one reported (not just the first):
      - plan is a dict.
      - "ready_for_rendering" is present and is exactly True (not just
        truthy) -- a plan's own claim that resolution and simulation
        already succeeded (see _build_swatch_plan()'s docstring); its
        absence or falsity means this was never a plan this module
        should trust, regardless of what else it might contain.
      - every other required field (see _REQUIRED_PLAN_FIELDS) is
        present.
      - trust is an object whose "provenance" is EXACTLY "library" AND
        whose "verification_status" is EXACTLY "CONFIRMED" -- both, not
        either. This is the internal-readiness contract this module
        actually enforces, not merely "trust looks like an object": a
        plan claiming provenance "ai," some other string, or a
        verification_status other than "CONFIRMED" (missing, "AI_PROPOSED",
        etc.) is rejected here, before it could ever be mistaken for
        real trusted-recipe output.
      - requested_repeat_count, total_rows, row_1_repeat_execution_count
        are each a plain integer >= 1; foundation_chain_count is a
        plain integer >= 0 (a foundation can be legitimately empty in
        principle, but never negative or fractional).
      - foundation_formula is an object; validation_evidence is an
        object whose "row_1_valid", "later_rows_valid", and
        "overall_valid" are each present and EXACTLY True -- missing,
        False, or a truthy non-bool (e.g. `1`) are all rejected.
      - row_1_setup, row_1_repeat, later_row_setup, later_row_repeat are
        each a list of well-formed steps: an object with a known stitch
        code (V2_KNOWN_STITCHES), a positive integer count, and a known
        placement (V2_PLACEMENTS) -- an unknown stitch or placement is
        rejected here rather than reaching _render_step() at all.
      - later_rows is a list of well-formed summaries: a row_number
        integer >= 2, a non-negative integer repeat_execution_count,
        and a "valid" field that is present and EXACTLY True.
      - warnings is a list containing only strings.

    Cross-field consistency (checks on the plan's own fields agreeing
    with EACH OTHER -- never a re-run of recipe resolution or
    mathematical simulation, which already happened, successfully,
    before this plan could exist; see this function's inline comments):
      - total_rows == 1 + len(later_rows).
      - row_1_repeat_execution_count == requested_repeat_count (row 1's
        repeat count is always the caller's explicit choice, never
        derived independently the way later rows' are).
      - later_rows' row_number values are consecutive starting at 2.
      - foundation_chain_count == foundation_formula["foundation_count"].

    Each cross-field check only runs once its own inputs have already
    passed their individual type/shape checks above, so a single
    malformed field never produces a confusing cascade of unrelated
    consistency errors on top of its own clear one.

    Returns a list of readable error strings -- empty means the plan is
    safe to read from. Never raises.
    """
    if not isinstance(plan, dict):
        return [f"plan must be an object, got {type(plan).__name__}"]

    errors = []

    for field in _REQUIRED_PLAN_FIELDS:
        if field not in plan:
            errors.append(f"plan: missing required field '{field}'")

    if "ready_for_rendering" in plan and not _is_exactly_true(plan["ready_for_rendering"]):
        errors.append(f"plan.ready_for_rendering: must be exactly True, got {plan['ready_for_rendering']!r}")

    if "pattern_id" in plan and (not isinstance(plan["pattern_id"], str) or not plan["pattern_id"]):
        errors.append(f"plan.pattern_id: must be a non-empty string, got {plan['pattern_id']!r}")

    if "name" in plan and (not isinstance(plan["name"], str) or not plan["name"]):
        errors.append(f"plan.name: must be a non-empty string, got {plan['name']!r}")

    if "terminology" in plan and not isinstance(plan["terminology"], str):
        errors.append(f"plan.terminology: must be a string, got {plan['terminology']!r}")

    if "trust" in plan:
        trust = plan["trust"]
        if not isinstance(trust, dict):
            errors.append(f"plan.trust: must be an object, got {type(trust).__name__}")
        else:
            # A renderable plan's trust must name the LIBRARY specifically
            # (never "ai" or any other value) AND a verification_status of
            # exactly "CONFIRMED" -- both, not either. A plan claiming
            # provenance "library" with a non-CONFIRMED status (or vice
            # versa) is exactly the kind of forged/inconsistent readiness
            # claim this check exists to catch; see this module's
            # docstring and docs/recipe_model_v2.md's Phase 7 section.
            provenance = trust.get("provenance")
            if provenance != "library":
                errors.append(
                    f"plan.trust.provenance: must be exactly 'library' for a renderable plan, "
                    f"got {provenance!r}"
                )
            verification_status = trust.get("verification_status")
            if verification_status != "CONFIRMED":
                errors.append(
                    f"plan.trust.verification_status: must be exactly 'CONFIRMED' for a renderable "
                    f"plan, got {verification_status!r}"
                )

    if "requested_repeat_count" in plan and not (
        _is_plain_int(plan["requested_repeat_count"]) and plan["requested_repeat_count"] >= 1
    ):
        errors.append(
            f"plan.requested_repeat_count: must be an integer >= 1, got {plan['requested_repeat_count']!r}"
        )

    if "total_rows" in plan and not (_is_plain_int(plan["total_rows"]) and plan["total_rows"] >= 1):
        errors.append(f"plan.total_rows: must be an integer >= 1, got {plan['total_rows']!r}")

    if "foundation_chain_count" in plan and not (
        _is_plain_int(plan["foundation_chain_count"]) and plan["foundation_chain_count"] >= 0
    ):
        errors.append(
            f"plan.foundation_chain_count: must be a non-negative integer, got {plan['foundation_chain_count']!r}"
        )

    if "foundation_formula" in plan and not isinstance(plan["foundation_formula"], dict):
        errors.append(f"plan.foundation_formula: must be an object, got {type(plan['foundation_formula']).__name__}")

    if "row_1_setup" in plan:
        _validate_step_list(plan["row_1_setup"], "plan.row_1_setup", errors)
    if "row_1_repeat" in plan:
        _validate_step_list(plan["row_1_repeat"], "plan.row_1_repeat", errors)
    if "later_row_setup" in plan:
        _validate_step_list(plan["later_row_setup"], "plan.later_row_setup", errors)
    if "later_row_repeat" in plan:
        _validate_step_list(plan["later_row_repeat"], "plan.later_row_repeat", errors)

    if "row_1_repeat_execution_count" in plan and not (
        _is_plain_int(plan["row_1_repeat_execution_count"]) and plan["row_1_repeat_execution_count"] >= 1
    ):
        errors.append(
            f"plan.row_1_repeat_execution_count: must be an integer >= 1, "
            f"got {plan['row_1_repeat_execution_count']!r}"
        )

    if "later_rows" in plan:
        if not isinstance(plan["later_rows"], list):
            errors.append(f"plan.later_rows: must be a list, got {type(plan['later_rows']).__name__}")
        else:
            for i, summary in enumerate(plan["later_rows"]):
                _validate_later_row_summary(summary, i, errors)

    if "validation_evidence" in plan:
        evidence = plan["validation_evidence"]
        if not isinstance(evidence, dict):
            errors.append(f"plan.validation_evidence: must be an object, got {type(evidence).__name__}")
        else:
            for field in ("row_1_valid", "later_rows_valid", "overall_valid"):
                if field not in evidence:
                    errors.append(f"plan.validation_evidence: missing required field '{field}'")
                elif not _is_exactly_true(evidence[field]):
                    errors.append(
                        f"plan.validation_evidence.{field}: must be exactly True, got {evidence[field]!r}"
                    )

    if "warnings" in plan:
        if not isinstance(plan["warnings"], list):
            errors.append(f"plan.warnings: must be a list, got {type(plan['warnings']).__name__}")
        else:
            for i, warning in enumerate(plan["warnings"]):
                if not isinstance(warning, str):
                    errors.append(f"plan.warnings[{i}]: must be a string, got {type(warning).__name__}")

    # Cross-field consistency -- checks on the plan's own INTERNAL
    # agreement only. These never re-run recipe resolution or
    # mathematical simulation (that already happened, successfully,
    # before this plan could exist) -- they only confirm the plan's own
    # fields agree with each other, catching a forged or hand-edited
    # plan whose individual fields each look superficially fine in
    # isolation but don't add up together.
    if (
        "later_rows" in plan and isinstance(plan["later_rows"], list)
        and "total_rows" in plan and _is_plain_int(plan.get("total_rows"))
    ):
        expected_total_rows = 1 + len(plan["later_rows"])
        if plan["total_rows"] != expected_total_rows:
            errors.append(
                f"plan.total_rows ({plan['total_rows']}) is inconsistent with 1 + len(later_rows) "
                f"({expected_total_rows})"
            )

    if (
        "row_1_repeat_execution_count" in plan and _is_plain_int(plan.get("row_1_repeat_execution_count"))
        and "requested_repeat_count" in plan and _is_plain_int(plan.get("requested_repeat_count"))
        and plan["row_1_repeat_execution_count"] != plan["requested_repeat_count"]
    ):
        errors.append(
            f"plan.row_1_repeat_execution_count ({plan['row_1_repeat_execution_count']}) must equal "
            f"plan.requested_repeat_count ({plan['requested_repeat_count']}) -- row 1's repeat count "
            f"is always the caller's explicit choice, never derived independently"
        )

    if "later_rows" in plan and isinstance(plan["later_rows"], list):
        expected_row_number = 2
        for i, summary in enumerate(plan["later_rows"]):
            if isinstance(summary, dict):
                row_number = summary.get("row_number")
                if _is_plain_int(row_number) and row_number != expected_row_number:
                    errors.append(
                        f"plan.later_rows[{i}].row_number: later rows must be numbered consecutively "
                        f"starting at 2 -- expected {expected_row_number}, got {row_number!r}"
                    )
            expected_row_number += 1

    if (
        "foundation_chain_count" in plan and _is_plain_int(plan.get("foundation_chain_count"))
        and "foundation_formula" in plan and isinstance(plan.get("foundation_formula"), dict)
    ):
        formula_count = plan["foundation_formula"].get("foundation_count")
        if plan["foundation_chain_count"] != formula_count:
            errors.append(
                f"plan.foundation_chain_count ({plan['foundation_chain_count']}) must equal "
                f"plan.foundation_formula.foundation_count ({formula_count!r})"
            )

    return errors


def render_swatch_plan(plan):
    """
    Renders a structured swatch plan (see engine/swatch_planner_v2.py's
    _build_swatch_plan()) into plain-text instructions.

    Validates `plan` itself first (see _validate_plan()) before reading
    a single field from it -- this function never raises for a
    malformed plan (None, a list, an empty dict, a dict missing
    "ready_for_rendering" or any other required field, a plan with
    malformed trust/foundation/step/later-row data, an unknown stitch
    code, or an unknown placement). Any such problem is reported as:

      {"status": "invalid_plan", "text": None, "warnings": [],
       "errors": [str, ...]}

    A plan that passes that check but names a terminology this renderer
    doesn't implement still returns the existing safe result instead of
    guessing:

      {"status": "unsupported_terminology", "text": None,
       "warnings": [], "errors": [str, ...]}

    Returns a dict:
      {"status": "rendered" | "unsupported_terminology" | "invalid_plan",
       "text": <str> | None,       # only set when status is "rendered"
       "warnings": [str, ...],
       "errors": [str, ...]}       # only non-empty when not "rendered"

    Never raises for any of the above -- always returns one of these
    three structured results. Reads `plan` only; never mutates it.
    """
    plan_errors = _validate_plan(plan)
    if plan_errors:
        return {"status": "invalid_plan", "text": None, "warnings": [], "errors": plan_errors}

    terminology = plan.get("terminology")
    terminology_map = _STITCH_NAMES_BY_TERMINOLOGY.get(terminology)
    if terminology_map is None:
        return {
            "status": "unsupported_terminology",
            "text": None,
            "warnings": [],
            "errors": [
                f"terminology {terminology!r} is not supported by this renderer -- "
                f"only {sorted(_STITCH_NAMES_BY_TERMINOLOGY)} are implemented"
            ],
        }

    lines = [
        f"Pattern: {plan['name']} ({plan['pattern_id']})",
        f"Terminology: {terminology}",
        "",
        f"Foundation: Chain {plan['foundation_chain_count']}.",
        "",
        _render_row("Row 1", plan["row_1_setup"], plan["row_1_repeat"],
                    plan["row_1_repeat_execution_count"], terminology_map),
    ]

    for later_row in plan["later_rows"]:
        lines.append("")
        lines.append(_render_row(
            f"Row {later_row['row_number']}",
            plan["later_row_setup"], plan["later_row_repeat"],
            later_row["repeat_execution_count"], terminology_map,
        ))

    if plan.get("warnings"):
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"- {w}" for w in plan["warnings"])

    return {"status": "rendered", "text": "\n".join(lines), "warnings": [], "errors": []}
