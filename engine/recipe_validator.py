"""
Phase 4A: compares two independent declarations for a v2 recipe's row 1 --
what the stored foundation_formula says the foundation contains, and what
row_1's own instructions actually account for -- and reports the typed
structure (stitch posts by code, chain spaces) row 1 produces.

This is deliberately row-1-only. Later-row validation needs decisions
Phase 4A refuses to guess at: whether a turning chain accounts for an
edge position from the previous row, whether next_dc passes over chain
spaces without consuming them, whether a counts_as DC can be targeted by
next_dc, and how chain spaces participate in traversal versus stitch
placement. See docs/recipe_model_v2.md's open questions -- none of them
are resolved here.

FOUNDATION-POSITION CONSUMPTION (row 1 only)

Every row_1 step advances (or doesn't) through the foundation according
to its placement, tracked as a single running "target_established" flag
that flows continuously across the row's whole real execution order:
setup, then repeat executed requested_repeat_count times in sequence,
each pass picking up exactly the target state the previous step (or the
previous repeat pass) left behind.

  next_foundation_chain -- consumes STITCH_RULES[stitch]["consumes"] *
      count foundation positions, exactly as engine/validator.py already
      defines per stitch (SKIP consumes 1 and produces 0; DC/SC/HDC/SLST
      each consume/produce 1; DEC consumes 2 and produces 1; INC consumes
      1 and produces 2). Only a step that actually PLACES a stitch there
      (produces > 0) leaves something same_stitch could later refer to --
      a SKIP consumes a position but places nothing, so it clears any
      established target.

  working_loop -- consumes zero foundation positions. Schema v2 already
      restricts this to CH steps on row_1 (a non-CH step can never reach
      here), so this module doesn't re-check that. A CH here produces new
      chain links -- chain spaces, not foundation consumption -- and
      PRESERVES whatever target was already established: a floating
      chain hung off the working loop doesn't touch the foundation, so
      it has no reason to erase the position most recently targeted by
      an actual stitch. A same_stitch step after an intervening
      working_loop chain still refers to that same foundation position.

  same_stitch -- consumes zero additional foundation positions; it
      reuses whatever position the immediately preceding placing step
      targeted, rather than advancing to a new one. Two things this
      module refuses to guess at, raising RecipeMathError instead:
        - same_stitch with no established prior target (nothing before
          it in the row's real execution order actually placed a
          stitch) -- there is nothing for "the same stitch" to mean.
        - same_stitch on a SKIP step -- skipping doesn't work into a
          stitch at all, so "the same stitch as a skip" has no referent
          either, regardless of what came before it.

This module never calls engine/validator.py's new_chain_links(), never
re-derives or "corrects" the foundation formula from row steps, and
never inspects any AI-stated concrete foundation number. The formula
(via engine/foundation.py's calculate_foundation()) and row 1's own
accounting are computed completely independently, then compared.

TYPED PRODUCTION

Every produced-structure dict has the shape
{"stitch_posts": {<CODE>: <int>, ...}, "chain_spaces": <int>,
"total_workable_positions": <int>} -- the last being the sum of every
stitch-post count plus chain_spaces. CH (working_loop) contributes only
chain_spaces; SKIP contributes neither; DC/SC/HDC/SLST contribute a
stitch post under their own code; INC and DEC also file under their own
code (e.g. {"INC": 2}) rather than a real stitch family, because this
phase does not yet know whether an increase's resulting posts should be
counted as SC, DC, or something else -- that is not invented here.
counts_as is never consulted: schema v2 doesn't permit it on row_1 at
all (turning_chain, the only placement counts_as ever attaches to, is
not a legal row_1 placement), so there's nothing for this analyzer to
read there.

ORDERED OUTPUT (for Phase 5's later-row traversal)

Alongside the aggregate produced_structure, this module also builds
"ordered_output": a list of the same production, in the row's actual
LEFT-TO-RIGHT physical order -- one entry per unit produced, each shaped
{"kind": "stitch_post"|"chain_space", "stitch": <code>|None, "source": "literal"}.
row_1 can never produce a "counts_as"-sourced entry (schema v2 forbids
counts_as on row_1 entirely), so every row_1 entry's source is always
"literal" -- the field exists here only so Phase 5's later rows, which
DO need it, share one entry shape across every row. The aggregate
produced_structure is a SUMMARY of ordered_output, not an independent
fact: `sum(1 for e in ordered_output if e["kind"]=="stitch_post" and
e["stitch"]==code) == produced_structure["stitch_posts"][code]` and
`sum(1 for e in ordered_output if e["kind"]=="chain_space") ==
produced_structure["chain_spaces"]` hold for every produced_structure
this module returns. Phase 5's later-row traversal (next_stitch,
next_dc, next_chain_space, SKIP) reads ordered_output with a moving
cursor -- never the aggregate dict, which cannot distinguish "DC, chain
space, SC" from "SC, chain space, DC" even though both have identical
stitch_posts/chain_spaces totals.

TRUST

A True result here does not make a recipe CONFIRMED, and a False result
does not mutate it to REJECTED -- this function only reports evidence;
verification.status is changed by nothing in this module. A recipe
already REJECTED (like contracts/examples/stitch_recipe_v2_known_bad_ai_example.json)
is still fully analyzable: its formula provides 9 foundation positions
for 6 repeats, but its row_1 only accounts for 7, so this correctly
returns valid: False with 2 unexplained positions -- a second,
independent piece of evidence against the same already-rejected recipe,
not a new decision this module is making on its own.
"""

from engine.foundation import calculate_foundation
from engine.schema import validate_recipe_v2
from engine.validator import STITCH_RULES


def _target(kind, stitch=None, source="literal"):
    """One ordered-output entry -- see this module's docstring ("ORDERED
    OUTPUT") for the shape and why it exists alongside produced_structure."""
    return {"kind": kind, "stitch": stitch, "source": source}


class RecipeMathError(ValueError):
    """
    Raised when validate_row_1_against_foundation() cannot produce a
    report at all: the recipe isn't a dict, fails validate_recipe_v2(),
    requested_repeat_count is invalid, or row_1 contains a structurally
    valid combination this Phase 4A analyzer refuses to guess at
    (same_stitch with no established prior target, or same_stitch on a
    SKIP step -- see this module's docstring).

    A mathematical MISMATCH (row 1 doesn't account for exactly
    foundation_count, or doesn't match a non-null expected value) is
    never raised as this error -- that's reported as valid: False in the
    returned dict instead, with readable messages in "errors".
    """


def _analyze_row1_steps(steps, target_established):
    """
    Processes one ordered list of row_1 steps (row_1.setup, or one pass
    of row_1.repeat), given whatever target_established state flowed in
    from immediately before it in the row's real execution order --
    which, for any repeat pass after the first, is whatever this same
    function returned at the end of the previous pass, not a value
    re-derived from setup each time.

    Returns (consumed_foundation_positions, produced_structure,
    ordered_output, target_established_after_these_steps).
    ordered_output is this step list's production in actual left-to-right
    order -- see this module's docstring ("ORDERED OUTPUT").
    """
    consumed = 0
    stitch_posts = {}
    chain_spaces = 0
    ordered_output = []

    for step in steps:
        stitch = step["stitch"]
        count = step["count"]
        placement = step["placement"]
        rule = STITCH_RULES[stitch]

        if placement == "working_loop":
            chain_spaces += rule["produces"] * count
            ordered_output.extend(_target("chain_space") for _ in range(rule["produces"] * count))
            # target_established is left untouched -- a working-loop
            # chain doesn't touch the foundation, so it preserves
            # whatever position a prior placing step most recently
            # targeted.

        elif placement == "next_foundation_chain":
            consumed += rule["consumes"] * count
            produced_count = rule["produces"] * count
            if produced_count:
                stitch_posts[stitch] = stitch_posts.get(stitch, 0) + produced_count
                ordered_output.extend(_target("stitch_post", stitch) for _ in range(produced_count))
            target_established = produced_count > 0

        elif placement == "same_stitch":
            if stitch == "SKIP":
                raise RecipeMathError(
                    "row_1 has a SKIP step with placement 'same_stitch' -- skipping doesn't "
                    "work into a stitch, so there is nothing for 'the same stitch' to refer to. "
                    "This Phase 4A analyzer cannot safely interpret that combination."
                )
            if not target_established:
                raise RecipeMathError(
                    "row_1 has a 'same_stitch' step with no established prior targeted "
                    "foundation position to refer back to in this row's executable sequence."
                )
            produced_count = rule["produces"] * count
            if produced_count:
                stitch_posts[stitch] = stitch_posts.get(stitch, 0) + produced_count
                ordered_output.extend(_target("stitch_post", stitch) for _ in range(produced_count))
            # target_established stays True -- the referenced position is unchanged.

        else:
            # Not reachable for a recipe that already passed
            # validate_recipe_v2() (row_1's placement enum has no other
            # members), but never silently guess at an unknown value.
            raise RecipeMathError(
                f"row_1 step has placement '{placement}', which this Phase 4A analyzer "
                f"does not know how to interpret."
            )

    total_workable_positions = sum(stitch_posts.values()) + chain_spaces
    produced_structure = {
        "stitch_posts": stitch_posts,
        "chain_spaces": chain_spaces,
        "total_workable_positions": total_workable_positions,
    }
    return consumed, produced_structure, ordered_output, target_established


def _empty_produced_structure():
    return {"stitch_posts": {}, "chain_spaces": 0, "total_workable_positions": 0}


def _merge_produced_structures(first, second):
    stitch_posts = dict(first["stitch_posts"])
    for stitch, count in second["stitch_posts"].items():
        stitch_posts[stitch] = stitch_posts.get(stitch, 0) + count
    chain_spaces = first["chain_spaces"] + second["chain_spaces"]
    return {
        "stitch_posts": stitch_posts,
        "chain_spaces": chain_spaces,
        "total_workable_positions": sum(stitch_posts.values()) + chain_spaces,
    }


def validate_row_1_against_foundation(recipe, requested_repeat_count):
    """
    Compares row_1's own accounting against the recipe's stored
    foundation_formula (via engine/foundation.py's calculate_foundation()),
    and reports the typed structure row_1 produces. See this module's
    docstring for the full accounting rules.

    Raises RecipeMathError (never returns a report) when:
      - recipe is not a dict;
      - recipe fails validate_recipe_v2();
      - requested_repeat_count is not a plain int >= 1 (bool excluded --
        bool is a subclass of int in Python; no coercion of floats/strings);
      - row_1 contains same_stitch with no established prior target, or
        same_stitch on a SKIP step. row_1.repeat is executed sequentially,
        requested_repeat_count times, with target state carried from
        setup into the first pass and from each pass into the next, so
        this can be raised by any pass -- not only the first -- if the
        target state carried into it makes that pass invalid.

    Otherwise always returns a dict -- including when the math doesn't
    add up. A mismatch is reported as {"valid": False, ...}, never an
    exception; see "errors" for readable messages.

    valid is True only when ALL of:
      1. row_1's total consumed foundation positions exactly equals
         foundation_count (not <=; exact accounting is required here).
      2. expected_swatch_structure.expected_stitch_posts_per_repeat is
         null, OR matches row_1.repeat's actual stitch posts from its
         first pass (the pass whose target state was carried from setup).
      3. expected_swatch_structure.expected_chain_spaces_per_repeat is
         null, OR matches row_1.repeat's actual chain spaces (first pass).
      4. No semantic interpretation error occurred (if one did, this
         function already raised RecipeMathError above instead of
         reaching this point).

    Never mutates the supplied recipe -- every field is only read.
    """
    if not isinstance(recipe, dict):
        raise RecipeMathError(f"recipe must be an object, got {type(recipe).__name__}")

    schema_errors = validate_recipe_v2(recipe)
    if schema_errors:
        raise RecipeMathError(
            "recipe failed v2 schema validation, so row 1 cannot be analyzed:\n"
            + "\n".join(f"  - {e}" for e in schema_errors)
        )

    if not isinstance(requested_repeat_count, int) or isinstance(requested_repeat_count, bool):
        raise RecipeMathError(
            f"requested_repeat_count must be a plain integer, got {requested_repeat_count!r}"
        )
    if requested_repeat_count < 1:
        raise RecipeMathError(
            f"requested_repeat_count must be at least 1, got {requested_repeat_count!r}"
        )

    foundation = calculate_foundation(recipe, requested_repeat_count)
    foundation_count = foundation["foundation_count"]

    setup_steps = recipe["row_1"]["setup"]
    repeat_steps = recipe["row_1"]["repeat"]

    setup_consumed, setup_produced, setup_ordered, target_after_setup = _analyze_row1_steps(
        setup_steps, target_established=False
    )

    # row_1.repeat is executed sequentially, requested_repeat_count times
    # -- not analyzed once and multiplied. Each pass carries the target
    # state left behind by the pass before it (the first pass carries it
    # from setup), and consumed positions / produced structure accumulate
    # pass by pass. Any RecipeMathError a given pass raises (e.g. a
    # same_stitch that only becomes invalid partway through the repeats)
    # surfaces at that pass, matching the row's real execution order.
    # ordered_output accumulates the same way, in real left-to-right
    # order: pass 1's production comes immediately after setup's, pass
    # 2's immediately after pass 1's, and so on.
    target = target_after_setup
    repeat_consumed = None
    repeat_produced = None
    repeat_ordered = None
    repeat_total_consumed = 0
    repeat_total_produced = _empty_produced_structure()
    repeat_total_ordered = []
    for pass_index in range(requested_repeat_count):
        pass_consumed, pass_produced, pass_ordered, target = _analyze_row1_steps(
            repeat_steps, target_established=target
        )
        if pass_index == 0:
            repeat_consumed = pass_consumed
            repeat_produced = pass_produced
            repeat_ordered = pass_ordered
        repeat_total_consumed += pass_consumed
        repeat_total_produced = _merge_produced_structures(repeat_total_produced, pass_produced)
        repeat_total_ordered.extend(pass_ordered)

    row1_consumed = setup_consumed + repeat_total_consumed
    row1_produced = _merge_produced_structures(setup_produced, repeat_total_produced)
    row1_ordered = setup_ordered + repeat_total_ordered

    unused = max(0, foundation_count - row1_consumed)
    overdrawn = max(0, row1_consumed - foundation_count)

    errors = []
    if row1_consumed < foundation_count:
        errors.append(
            f"Row 1 accounts for {row1_consumed} of {foundation_count} foundation positions; "
            f"{unused} positions are unexplained."
        )
    elif row1_consumed > foundation_count:
        errors.append(
            f"Row 1 requires {row1_consumed} foundation positions, but the formula provides "
            f"{foundation_count}; short by {overdrawn}."
        )

    expected = recipe["expected_swatch_structure"]
    expected_stitch_posts = expected["expected_stitch_posts_per_repeat"]
    expected_chain_spaces = expected["expected_chain_spaces_per_repeat"]
    actual_stitch_posts = sum(repeat_produced["stitch_posts"].values())
    actual_chain_spaces = repeat_produced["chain_spaces"]

    if expected_stitch_posts is None:
        stitch_posts_match = None
    else:
        stitch_posts_match = actual_stitch_posts == expected_stitch_posts
        if not stitch_posts_match:
            errors.append(
                f"Expected {expected_stitch_posts} stitch post(s) per repeat, but row_1.repeat "
                f"produces {actual_stitch_posts}."
            )

    if expected_chain_spaces is None:
        chain_spaces_match = None
    else:
        chain_spaces_match = actual_chain_spaces == expected_chain_spaces
        if not chain_spaces_match:
            errors.append(
                f"Expected {expected_chain_spaces} chain space(s) per repeat, but row_1.repeat "
                f"produces {actual_chain_spaces}."
            )

    valid = (
        row1_consumed == foundation_count
        and stitch_posts_match is not False
        and chain_spaces_match is not False
    )

    return {
        "valid": valid,
        "requested_repeat_count": requested_repeat_count,
        "foundation": foundation,
        "setup": {
            "consumed_foundation_positions": setup_consumed,
            "produced_structure": setup_produced,
            "ordered_output": setup_ordered,
        },
        "repeat_once": {
            "consumed_foundation_positions": repeat_consumed,
            "produced_structure": repeat_produced,
            "ordered_output": repeat_ordered,
        },
        "repeat_total": {
            "consumed_foundation_positions": repeat_total_consumed,
            "produced_structure": repeat_total_produced,
            "ordered_output": repeat_total_ordered,
        },
        "row_1": {
            "consumed_foundation_positions": row1_consumed,
            "produced_structure": row1_produced,
            "ordered_output": row1_ordered,
            "unused_foundation_positions": unused,
            "overdrawn_foundation_positions": overdrawn,
        },
        "expected_repeat_structure": {
            "expected_stitch_posts_per_repeat": expected_stitch_posts,
            "actual_stitch_posts_per_repeat": actual_stitch_posts,
            "stitch_posts_match": stitch_posts_match,
            "expected_chain_spaces_per_repeat": expected_chain_spaces,
            "actual_chain_spaces_per_repeat": actual_chain_spaces,
            "chain_spaces_match": chain_spaces_match,
        },
        "errors": errors,
    }
