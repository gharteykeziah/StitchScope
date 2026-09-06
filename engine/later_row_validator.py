"""
Phase 5: validates later_rows against the TYPED, ORDERED structure the
row before them actually produced -- never against one flat total
number, and never against unordered per-type totals either.

WHY ORDER, NOT JUST TYPE

A previous row containing 6 DC posts + 6 chain spaces is NOT the same
input as a row containing 12 DC posts + 0 chain spaces (typed, not
total -- the reason this module exists at all). But two rows can also
have IDENTICAL typed totals and still be different inputs: a row that
produced "DC, chain space, SC" is not the same sequence as one that
produced "SC, chain space, DC," even though both are
{"stitch_posts": {"DC": 1, "SC": 1}, "chain_spaces": 1}. next_stitch,
next_dc, next_chain_space, and SKIP are TRAVERSAL instructions -- "the
NEXT one, moving forward" -- which an unordered per-type count cannot
answer at all. This module therefore keeps each row's actual production
as an ORDERED list (see ORDERED TARGETS below) and walks it with a
single forward-only CURSOR, never an aggregate dict, for every question
that is actually about position (which placements answer). The
aggregate `produced_structure` dict still exists -- for summaries, for
`expected_swatch_structure`-style comparisons, and for backward-
compatible reporting -- but it is now a DERIVED PROJECTION of the
ordered list, never the other way around, and traversal logic never
reads it.

ORDERED TARGETS

A row's production is a plain list of small dicts, each one physical
position in real left-to-right order:

    {"kind": "stitch_post", "stitch": "DC", "source": "literal"}
    {"kind": "chain_space", "stitch": None, "source": "literal"}
    {"kind": "stitch_post", "stitch": "SC", "source": "counts_as"}

- "kind" is "stitch_post" or "chain_space".
- "stitch" is the stitch code for a stitch_post entry, None for a
  chain_space entry.
- "source" is "literal" (an ordinary stitch/chain actually worked) or
  "counts_as" (credited by a turning_chain's counts_as declaration,
  never a literal stitch -- see the turning_chain rule below). This is
  the ONLY thing that gates next_dc's open eligibility question (see
  below); nothing else in this module inspects it.

engine/recipe_validator.py's `_target()` builds the identical shape for
row 1's report (row 1 can only ever produce "literal" entries -- schema
v2 forbids counts_as on row_1 entirely -- but the shape is shared so
Phase 5 can consume row 1's ordered output exactly like any later row's).
This module defines its own `_target()` rather than importing the
"private" one, matching this project's existing convention of small,
independently-owned per-module helpers with an identical shape
(_empty_produced_structure() already does the same across both modules).

DIRECTION: A ROW'S OWN ordered_output IS ALWAYS IN PRODUCTION ORDER; THE
NEXT ROW'S ordered_input IS THE REVERSE OF THAT

A row's own `ordered_output` (row 1's, from engine/recipe_validator.py,
and every later row's, from this module) always means exactly one
thing: the order its steps actually produced those targets while
working THIS row, left to right. It is never itself reversed or
reinterpreted -- that is what "reporting in production order" means,
and it is why every "ordered_output" field this module or Phase 4A
returns can always be read the same way regardless of which row it
came from.

But flat crochet turns at the end of every row: you finish working
left-to-right, turn the piece over, and the next row is then worked
right-to-left relative to the fabric -- so the FIRST target the next
row's cursor encounters is the LAST one the previous row produced, not
the first. If a row's `ordered_output` is `[A, B, C]` (produced in that
order), the next row's cursor must walk `[C, B, A]` -- the reverse.
validate_recipe_rows() performs exactly this reversal, once, at the
point it hands one row's finished output to the next row's
_validate_one_later_row() call -- via `list(reversed(...))`, which
always builds a brand-new list rather than mutating anything already
stored in a returned report. Never reverse a list twice in a row (that
would silently model the crocheter turning back over TWO edges, i.e.
not turning at all) and never reverse the same stored list object in
place. A row's `ordered_input` field in its own report is therefore
the ALREADY-TURNED (reversed) list this row's cursor actually walks --
distinct from the previous row's `ordered_output`, which stays in that
row's own original production order for its own report.

FLAT ROWS ONLY -- CONTINUOUS ROUNDS ARE NOT SUPPORTED

Crochet also has continuous-round construction (worked in a spiral,
never turned, so the next round's cursor should continue in the SAME
direction the previous round finished in, not reverse). Schema v2
(contracts/stitch_recipe_schema_v2.json, engine/schema.py) has no field
anywhere stating whether a given recipe is flat (turned) or worked in
continuous rounds -- there is nothing in a recipe dict this module
could inspect to tell the two apart. Rather than guess, this module
ALWAYS applies the flat-row turn described above and makes no attempt
to detect or support continuous rounds; a recipe intended as continuous
rounds will be validated as if every row were turned, which is
incorrect for that construction and not something this module can
currently recognize as a mismatch. Supporting continuous rounds for
real would require a new schema field (e.g. a `construction` enum of
`"flat"` / `"round"`) this validator could branch on -- until that
field exists, "flat, turned rows" is Phase 5's only supported
construction, stated explicitly rather than silently assumed.

PART 1 -- RESOLVED PLACEMENT SEMANTICS (decided before any code below;
see docs/recipe_model_v2.md's Phase 5 section for the long-form version)

  turning_chain -- consumes nothing from the previous row's ordered
      output at all (the input cursor is never touched by this
      placement). If `counts_as` is present, it REPLACES this step's
      own contribution entirely: the ordered output gains exactly
      counts_as.stitch_posts and counts_as.chain_spaces worth of
      entries (each tagged source: "counts_as"), nothing more -- adding
      the raw CH production on top would double-count (a real "ch 4"
      turning chain is one edge, not 4 separate chain spaces). Without
      counts_as, it behaves exactly like a bare working_loop CH: raw
      produces*count "literal" chain_space entries, no stitch-post
      credit. It establishes a new target only when counts_as declares
      something positive; otherwise it PRESERVES whatever target
      already existed -- the same rule Phase 4A already applies to bare
      working_loop chains.

  next_stitch -- a forward search from the input cursor for the next
      entry whose kind is "stitch_post", regardless of stitch code or
      source. Every entry the search passes over (a chain_space, or a
      stitch_post the row didn't ask for by type) moves BEHIND the
      cursor and can never be targeted as "next" again by a later step
      in this row or a subsequent one -- crochet doesn't work backward
      across a row. Nothing here is decided by alphabetical order or
      any other unordered tie-break; it is decided purely by position.
      No matching entry anywhere ahead of the cursor is a validation
      FAILURE (reported in the row's result), never a silent
      chain-space grab.

  next_dc -- a forward search from the input cursor for the next entry
      whose kind is "stitch_post" and stitch is "DC" specifically (SC,
      HDC, and chain spaces are never matched, no matter how close to
      the cursor they sit -- they are passed over like anything else
      not being searched for). If the found entry's source is
      "literal", it is consumed and the result is unambiguous. If its
      source is "counts_as", this module REFUSES TO GUESS and raises
      RecipeMathError: whether next_dc may legally resolve to a stitch
      that exists only because of counts_as, or means a literal DC
      stitch only, is exactly open question 4 in docs/recipe_model_v2.md
      section 11, and is not decided here either way -- not even by
      skipping ahead to search for a LATER literal DC, since that would
      itself be a guess about whether the counts_as one may be passed
      over. If no DC entry exists anywhere ahead of the cursor at all,
      that is a plain, reported shortfall.

  next_chain_space -- a forward search from the input cursor for the
      next entry whose kind is "chain_space". None found ahead of the
      cursor is a reported failure. Multiple stitches worked into the
      SAME chain space are one next_chain_space step (which moves the
      cursor past that one chain-space entry) followed by same_stitch
      steps (which do not move the cursor again).

  same_stitch -- never moves the input cursor and never searches
      anything; it requires only that a target was already established
      earlier in this row's continuous processing (raises
      RecipeMathError if not) and is forbidden on a SKIP step (raises
      RecipeMathError) -- both exactly as Phase 4A already established
      for row 1. An intervening working_loop (or a counts_as-less
      turning_chain) does not clear the remembered target, so
      same_stitch can validly follow one.

  SKIP -- legal wherever schema v2 permits a non-CH placement
      (next_stitch/next_dc/next_chain_space). It performs the exact
      same forward search and cursor advance that placement would for
      any other stitch (including next_dc's counts_as-eligibility
      check -- skipping an ambiguous position is exactly as unresolved
      as stitching into it), produces no new ordered-output entry, and
      CLEARS the established target afterward -- identical to how
      Phase 4A treats a next_foundation_chain SKIP on row 1. SKIP with
      same_stitch remains invalid (raises), unchanged from Phase 4A.

This module validates only behavior already permitted by the v2 schema
(engine/schema.py) -- it never re-checks which placements are legal in
which context; that is schema validation's job and is assumed to have
already passed before this module is reached (validate_row_1_against_foundation()
already enforces this on every call).

WHAT REMAINS DELIBERATELY UNRESOLVED (not guessed at)

  - The next_dc / counts_as-DC eligibility gap above: raised as
    RecipeMathError, never silently decided.
  - The number of times later_rows.repeat can run is DERIVED by
    actually walking the cursor across the previous row's ordered
    output, pass after pass, until a pass can no longer complete (see
    _validate_one_later_row()) -- never assumed to equal
    requested_repeat_count, and never computed by subtracting unordered
    per-type totals (that would silently reintroduce the exact ordering
    blindness this module exists to remove). If later_rows.repeat never
    moves the cursor at all (every step is same_stitch/working_loop),
    nothing in the current recipe model constrains how many times it
    could run -- this is reported as an explicit "ambiguous repeat
    count" result (valid: False, a clear message), never a guessed
    number. Resolving this for real would require a new field on the
    recipe (e.g. an explicit later-row repeat count, or a declared
    per-repeat consumption contract) -- see this module's
    validate_recipe_rows() docstring.
  - Continuous-round construction: this module always turns between
    rows (see "FLAT ROWS ONLY" above) and has no way to detect or
    support a recipe meant as continuous rounds instead, since schema
    v2 has no field recording which construction a recipe uses.
    Resolving this for real would require a new schema field (e.g. a
    `construction` enum of `"flat"` / `"round"`) this validator could
    branch on.

VERIFICATION.STATUS IS NEVER TOUCHED

Exactly like Phase 4A: a True result here does not make a recipe
CONFIRMED (or even SIMULATION_VALID -- this module does not write to
verification at all), and a False result does not mutate it to
REJECTED. This function only reports evidence.
"""

from engine.recipe_validator import RecipeMathError, validate_row_1_against_foundation
from engine.validator import STITCH_RULES

TARGETED_PLACEMENTS = ("next_stitch", "next_dc", "next_chain_space")


def _target(kind, stitch=None, source="literal"):
    """One ordered-output entry -- see this module's docstring ("ORDERED
    TARGETS"). Identical shape to engine/recipe_validator.py's _target();
    each module keeps its own copy by this project's existing convention."""
    return {"kind": kind, "stitch": stitch, "source": source}


def _empty_typed_amount():
    return {"stitch_posts": {}, "chain_spaces": 0}


def _empty_produced_structure():
    return {"stitch_posts": {}, "chain_spaces": 0, "total_workable_positions": 0}


def _tally_ordered_targets(ordered_targets):
    """Projects an ordered target list down to the aggregate
    produced_structure shape -- a SUMMARY derived from the ordered
    ground truth, never itself used to decide traversal."""
    stitch_posts = {}
    chain_spaces = 0
    for entry in ordered_targets:
        if entry["kind"] == "chain_space":
            chain_spaces += 1
        else:
            stitch_posts[entry["stitch"]] = stitch_posts.get(entry["stitch"], 0) + 1
    return {
        "stitch_posts": stitch_posts,
        "chain_spaces": chain_spaces,
        "total_workable_positions": sum(stitch_posts.values()) + chain_spaces,
    }


def _counts_as_stitch_posts(ordered_targets):
    """The counts_as-sourced subset of an ordered target list's stitch
    posts, by code -- used solely to let a later row's next_dc tell a
    literal DC apart from one that exists only via counts_as credit."""
    result = {}
    for entry in ordered_targets:
        if entry["kind"] == "stitch_post" and entry["source"] == "counts_as":
            result[entry["stitch"]] = result.get(entry["stitch"], 0) + 1
    return result


def _merge_typed_amount(first, second):
    stitch_posts = dict(first["stitch_posts"])
    for code, count in second["stitch_posts"].items():
        stitch_posts[code] = stitch_posts.get(code, 0) + count
    return {"stitch_posts": stitch_posts, "chain_spaces": first["chain_spaces"] + second["chain_spaces"]}


def _find_forward(input_targets, cursor, predicate):
    """The core traversal primitive: scans input_targets[cursor:] for the
    first entry matching predicate, returning its index or None. Never
    looks behind cursor -- positions before it are already gone, whether
    they were consumed or merely passed over while searching for
    something else."""
    for i in range(cursor, len(input_targets)):
        if predicate(input_targets[i]):
            return i
    return None


def _run_later_steps(steps, target_established, input_targets, cursor, context_label):
    """
    Executes one ordered list of later-row steps (later_rows.setup, or
    one pass of later_rows.repeat) against the previous row's ordered
    output, starting the input cursor at `cursor`. input_targets is
    read-only and never mutated -- it is the SAME list object for every
    call across a row's setup and every repeat pass; only `cursor`
    (a plain int) advances between calls, so each call must be given
    whatever cursor value the previous call returned.

    Stops at the first step that cannot be satisfied (a "shortfall";
    not an exception -- see this module's docstring for which cases DO
    raise). On success, everything actually produced by this step list
    is returned ONLY as `ordered_output`; `produced_structure` is
    derived from it, never tracked independently.

    Returns a dict:
      {"target_established": bool,
       "consumed": {"stitch_posts": {...}, "chain_spaces": int},  # aggregate, derived from what the cursor actually passed
       "produced_structure": {"stitch_posts": {...}, "chain_spaces": int,
                               "total_workable_positions": int},   # derived from ordered_output
       "ordered_output": [ {...}, ... ],
       "final_cursor": int | None,     # None if shortfall
       "shortfall": None or {"step_index": int, "placement": str,
                              "stitch": str, "pool": "stitch_posts"|"chain_spaces",
                              "code": str|None, "needed": int, "available": int}}

    Raises RecipeMathError for same_stitch's two "refuses to guess"
    cases (no established target; SKIP referent), and for next_dc's
    counts_as-eligibility gap -- see module docstring.
    """
    ordered_output = []
    consumed = _empty_typed_amount()

    for step_index, step in enumerate(steps):
        stitch = step["stitch"]
        count = step["count"]
        placement = step["placement"]
        rule = STITCH_RULES[stitch]

        if placement == "working_loop":
            n = rule["produces"] * count
            ordered_output.extend(_target("chain_space") for _ in range(n))
            # cursor and target_established untouched -- see module docstring.

        elif placement == "turning_chain":
            counts_as = step.get("counts_as")
            if counts_as:
                stitch_credit = counts_as.get("stitch_posts", {})
                chain_credit = counts_as.get("chain_spaces", 0)
                for code, n in stitch_credit.items():
                    ordered_output.extend(_target("stitch_post", code, source="counts_as") for _ in range(n))
                ordered_output.extend(_target("chain_space", source="counts_as") for _ in range(chain_credit))
                established_now = chain_credit > 0 or any(v > 0 for v in stitch_credit.values())
                if established_now:
                    target_established = True
                # else: preserve whatever target already existed.
            else:
                n = rule["produces"] * count
                ordered_output.extend(_target("chain_space") for _ in range(n))
                # No counts_as: same as bare working_loop -- preserve target.
            # cursor untouched either way -- turning_chain never consumes
            # a position from the previous row.

        elif placement in TARGETED_PLACEMENTS:
            need = rule["consumes"] * count

            if placement == "next_chain_space":
                predicate = lambda t: t["kind"] == "chain_space"
                pool_kind, code = "chain_spaces", None
            elif placement == "next_dc":
                predicate = lambda t: t["kind"] == "stitch_post" and t["stitch"] == "DC"
                pool_kind, code = "stitch_posts", "DC"
            else:  # next_stitch
                predicate = lambda t: t["kind"] == "stitch_post"
                pool_kind, code = "stitch_posts", None

            available = sum(1 for t in input_targets[cursor:] if predicate(t))
            if available < need:
                return {
                    "target_established": target_established,
                    "consumed": consumed,
                    "produced_structure": _tally_ordered_targets(ordered_output),
                    "ordered_output": ordered_output,
                    "final_cursor": None,
                    "shortfall": {
                        "step_index": step_index, "placement": placement, "stitch": stitch,
                        "pool": pool_kind, "code": code, "needed": need, "available": available,
                    },
                }

            for _ in range(need):
                idx = _find_forward(input_targets, cursor, predicate)
                entry = input_targets[idx]
                if placement == "next_dc" and entry["source"] == "counts_as":
                    raise RecipeMathError(
                        f"{context_label}[{step_index}]: next_dc's next matching position (index {idx} "
                        f"of the previous row's ordered output) is a DC that exists only via a previous "
                        f"row's turning-chain counts_as credit, not a literal DC stitch. Whether next_dc "
                        f"may legally resolve to a counts_as-derived DC is an open physical question "
                        f"(docs/recipe_model_v2.md section 11, question 4). This validator refuses to "
                        f"guess either way -- including by skipping ahead to search for a later literal "
                        f"DC, since that would itself be a guess about whether this one may be passed "
                        f"over. Treat this recipe as unsupported here until that question is resolved by "
                        f"physical testing."
                    )
                cursor = idx + 1
                if entry["kind"] == "chain_space":
                    consumed["chain_spaces"] += 1
                else:
                    consumed["stitch_posts"][entry["stitch"]] = consumed["stitch_posts"].get(entry["stitch"], 0) + 1

            produced_count = rule["produces"] * count
            if produced_count:
                ordered_output.extend(_target("stitch_post", stitch) for _ in range(produced_count))
            target_established = produced_count > 0

        elif placement == "same_stitch":
            if stitch == "SKIP":
                raise RecipeMathError(
                    f"{context_label}[{step_index}]: a SKIP step with placement 'same_stitch' -- "
                    f"skipping doesn't work into a stitch, so there is nothing for 'the same stitch' "
                    f"to refer to."
                )
            if not target_established:
                raise RecipeMathError(
                    f"{context_label}[{step_index}]: a 'same_stitch' step with no established prior "
                    f"targeted position (stitch or chain space) to refer back to."
                )
            produced_count = rule["produces"] * count
            if produced_count:
                ordered_output.extend(_target("stitch_post", stitch) for _ in range(produced_count))
            # cursor untouched -- no new target consumed; target_established stays True.

        else:
            # Not reachable for a recipe that already passed validate_recipe_v2().
            raise RecipeMathError(
                f"{context_label}[{step_index}]: placement '{placement}' is not one this Phase 5 "
                f"analyzer knows how to interpret."
            )

    return {
        "target_established": target_established,
        "consumed": consumed,
        "produced_structure": _tally_ordered_targets(ordered_output),
        "ordered_output": ordered_output,
        "final_cursor": cursor,
        "shortfall": None,
    }


def _validate_one_later_row(later_rows, row_number, input_targets):
    """
    Validates one later row against its ORDERED typed input. Runs
    later_rows.setup exactly once, then executes later_rows.repeat pass
    after pass, walking a single forward-only cursor across
    input_targets, until a pass can no longer complete against what
    remains ahead of the cursor.

    input_targets must ALREADY be turned: this row's cursor walks it
    exactly as given, front to back, with no reversal performed here.
    The caller (validate_recipe_rows()) is responsible for building it
    as `list(reversed(previous_row_output))` -- the previous row's own
    ordered_output, reversed once, modeling the crocheter turning the
    work at the end of every row (see this module's docstring,
    "DIRECTION"). This function never knows or cares whether the list it
    receives is "really" reversed relative to anything; it only ever
    walks forward through whatever it's given.

    input_targets is the ONE ordered list this whole row reads from
    (setup and every repeat pass share it); only the cursor position
    advances between calls to _run_later_steps().

    Returns one later-row report dict (see validate_recipe_rows()'s
    docstring for the full field list) -- never raises for a supply/
    demand mismatch (that is reported as valid: False); still propagates
    RecipeMathError for the semantic "refuses to guess" cases (see
    _run_later_steps()).
    """
    input_structure = _tally_ordered_targets(input_targets)

    setup_context = f"later_rows.setup (row {row_number})"
    setup_result = _run_later_steps(
        later_rows["setup"], target_established=False,
        input_targets=input_targets, cursor=0,
        context_label=setup_context,
    )

    if setup_result["shortfall"] is not None:
        sf = setup_result["shortfall"]
        pool_desc = "DC post(s)" if sf["code"] == "DC" else ("chain space(s)" if sf["pool"] == "chain_spaces" else "stitch post(s)")
        message = (
            f"Row {row_number} setup step {sf['step_index']} ('{sf['placement']}') needs "
            f"{sf['needed']} {pool_desc}, but only {sf['available']} remain ahead of the cursor in row "
            f"{row_number - 1}'s output."
        )
        return {
            "row_number": row_number,
            "input_structure": input_structure,
            "ordered_input": input_targets,
            "setup_result": {
                "consumed": setup_result["consumed"],
                "produced_structure": setup_result["produced_structure"],
                "ordered_output": setup_result["ordered_output"],
                "counts_as_stitch_posts": _counts_as_stitch_posts(setup_result["ordered_output"]),
            },
            "repeat_count_derivable": None,
            "repeat_execution_count": 0,
            "repeat_once_consumed": None,
            "repeat_result": {"consumed": _empty_typed_amount(), "produced_structure": _empty_produced_structure(), "ordered_output": []},
            "output_structure": _empty_produced_structure(),
            "ordered_output": [],
            "output_counts_as_stitch_posts": {},
            "remaining_unused_input_targets": input_structure,
            "attempted_overdraw": {"pool": sf["pool"], "code": sf["code"], "needed": sf["needed"], "available": sf["available"]},
            "valid": False,
            "errors": [message],
        }

    cursor_after_setup = setup_result["final_cursor"]
    target_after_setup = setup_result["target_established"]

    repeat_context = f"later_rows.repeat (row {row_number})"
    first_pass = _run_later_steps(
        later_rows["repeat"], target_established=target_after_setup,
        input_targets=input_targets, cursor=cursor_after_setup,
        context_label=repeat_context,
    )

    if first_pass["shortfall"] is None and first_pass["final_cursor"] == cursor_after_setup:
        message = (
            f"Row {row_number}'s later_rows.repeat never moves the cursor forward across the previous "
            f"row's output (every step is same_stitch/working_loop) -- nothing in the current recipe "
            f"model says how many times it should run. The recipe has no field for a later-row repeat "
            f"count, and requested_repeat_count is not assumed to apply here (see this module's "
            f"validate_recipe_rows() docstring for what would need to be added to resolve this)."
        )
        return {
            "row_number": row_number,
            "input_structure": input_structure,
            "ordered_input": input_targets,
            "setup_result": {
                "consumed": setup_result["consumed"],
                "produced_structure": setup_result["produced_structure"],
                "ordered_output": setup_result["ordered_output"],
                "counts_as_stitch_posts": _counts_as_stitch_posts(setup_result["ordered_output"]),
            },
            "repeat_count_derivable": False,
            "repeat_execution_count": None,
            "repeat_once_consumed": first_pass["consumed"],
            "repeat_result": {"consumed": _empty_typed_amount(), "produced_structure": _empty_produced_structure(), "ordered_output": []},
            "output_structure": setup_result["produced_structure"],
            "ordered_output": setup_result["ordered_output"],
            "output_counts_as_stitch_posts": _counts_as_stitch_posts(setup_result["ordered_output"]),
            "remaining_unused_input_targets": _tally_ordered_targets(input_targets[cursor_after_setup:]),
            "attempted_overdraw": None,
            "valid": False,
            "errors": [message],
        }

    repeat_total_consumed = _empty_typed_amount()
    repeat_total_ordered = []
    pass_count = 0
    cursor = cursor_after_setup
    target = target_after_setup

    if first_pass["shortfall"] is None:
        max_passes = len(input_targets) - cursor_after_setup + 1
        pending = first_pass
        while pass_count < max_passes:
            if pending["shortfall"] is not None:
                break
            repeat_total_consumed = _merge_typed_amount(repeat_total_consumed, pending["consumed"])
            repeat_total_ordered.extend(pending["ordered_output"])
            cursor = pending["final_cursor"]
            target = pending["target_established"]
            pass_count += 1
            pending = _run_later_steps(
                later_rows["repeat"], target_established=target,
                input_targets=input_targets, cursor=cursor,
                context_label=repeat_context,
            )

    repeat_total_produced = _tally_ordered_targets(repeat_total_ordered)
    row_ordered_output = setup_result["ordered_output"] + repeat_total_ordered
    output_structure = _tally_ordered_targets(row_ordered_output)
    output_counts_as = _counts_as_stitch_posts(row_ordered_output)
    remaining = _tally_ordered_targets(input_targets[cursor:])

    # Leftover input targets are reported in remaining_unused_input_targets
    # but do NOT by themselves make this row invalid: unlike row 1 vs. the
    # foundation formula (which must describe the exact same physical
    # chain), a later row legitimately may not target everything the row
    # before it produced -- a real filet-mesh repeat's "dc in next dc, ch 1"
    # passes right over the previous row's chain space by design, leaving
    # it as the mesh's open hole rather than something to consume.
    #
    # An actual shortfall is different: it means later_rows.repeat asked
    # for something on a specific pass and nothing ahead of the cursor
    # could satisfy it. A shortfall on pass 2+ is the ordinary, expected
    # way this module DERIVES the repeat count (see
    # validate_recipe_rows()'s docstring) -- not an error. A shortfall on
    # pass 1 (pass_count still 0) is different: the repeat could not be
    # worked even a single time against this row's actual input, which is
    # a genuine overdraw, not a benign "nothing left over" situation --
    # there is no notation in this recipe model for "run this later row's
    # repeat zero times on purpose," so failing to complete even one pass
    # is always reported as an error.
    errors = []
    attempted_overdraw = None
    if pass_count == 0 and first_pass["shortfall"] is not None:
        sf = first_pass["shortfall"]
        pool_desc = "DC post(s)" if sf["code"] == "DC" else ("chain space(s)" if sf["pool"] == "chain_spaces" else "stitch post(s)")
        errors.append(
            f"Row {row_number}'s later_rows.repeat cannot be worked even once against row "
            f"{row_number - 1}'s actual output: step {sf['step_index']} ('{sf['placement']}') needs "
            f"{sf['needed']} {pool_desc}, but only {sf['available']} remain ahead of the cursor."
        )
        attempted_overdraw = {"pool": sf["pool"], "code": sf["code"], "needed": sf["needed"], "available": sf["available"]}

    valid = attempted_overdraw is None

    return {
        "row_number": row_number,
        "input_structure": input_structure,
        "ordered_input": input_targets,
        "setup_result": {
            "consumed": setup_result["consumed"],
            "produced_structure": setup_result["produced_structure"],
            "ordered_output": setup_result["ordered_output"],
            "counts_as_stitch_posts": _counts_as_stitch_posts(setup_result["ordered_output"]),
        },
        "repeat_count_derivable": True,
        "repeat_execution_count": pass_count,
        "repeat_once_consumed": first_pass["consumed"],
        "repeat_result": {
            "consumed": repeat_total_consumed,
            "produced_structure": repeat_total_produced,
            "ordered_output": repeat_total_ordered,
        },
        "output_structure": output_structure,
        "ordered_output": row_ordered_output,
        "output_counts_as_stitch_posts": output_counts_as,
        "remaining_unused_input_targets": remaining,
        "attempted_overdraw": attempted_overdraw,
        "valid": valid,
        "errors": errors,
    }


def validate_recipe_rows(recipe, requested_repeat_count, later_row_count):
    """
    Phase 5: validates a chain of rows -- row 1, then later_row_count
    later rows -- each one fed the ACTUAL ordered output of the row
    before it, never a claimed or assumed number, and never an unordered
    per-type total either (see this module's docstring for why order
    matters: two rows with identical typed totals but different physical
    orders are different inputs, and only an ordered cursor walk can
    tell them apart).

    Process (see PART 4 of the task this implements):
      1. Delegates recipe/requested_repeat_count validation, foundation
         calculation, and row 1's own math to
         engine/recipe_validator.py's validate_row_1_against_foundation()
         (Phase 4A) -- reused wholesale, not reimplemented. Any
         RecipeMathError it raises propagates unchanged. Row 1's own
         ordered_output field (added to Phase 4A's report so it can
         seed row 2) is read from `row_1_report["row_1"]["ordered_output"]`.
      2. If row 1 is invalid (its own "valid" is False), stops
         immediately: later_rows is an empty list, first_failing_row is
         1, and no later row is ever evaluated.
      3. Otherwise, for row_number = 2 .. 1 + later_row_count: builds
         that row's ordered input by TURNING the previous row's actual
         ordered_output -- reversing it once, a fresh list each time
         (`list(reversed(previous_row_output))`), modeling the
         crocheter turning the work at the end of every row (row 1's
         from the Phase 4A report; row N's from this module's own
         previous iteration's "ordered_output" -- see this module's
         docstring, "DIRECTION," for why the reversal happens and why it
         is never applied twice or skipped). It then runs
         later_rows.setup exactly once, then executes later_rows.repeat
         pass after pass, walking a single forward cursor across that
         TURNED ordered input, until a pass can no longer complete (see
         _validate_one_later_row() and the module docstring's "PART 1"
         section for exactly how each placement moves the cursor).
         Stops at the first row whose own "valid" is False -- no
         subsequent row is evaluated once one fails.

    later_row_count must be a plain non-negative int (bool excluded).
    0 is legal and means "only check row 1."

    LATER-ROW REPEAT COUNT IS DERIVED BY WALKING THE CURSOR, NEVER BY
    SUBTRACTING UNORDERED TOTALS. Unlike row 1 (whose repeat count is
    requested_repeat_count, an explicit caller choice), the v2 recipe
    schema has no field stating how many times later_rows.repeat should
    run. This function derives it by actually running later_rows.repeat,
    pass after pass, moving the SAME forward-only cursor across the
    row's ordered input each time, until a pass can no longer complete
    -- the number of passes that DID complete is repeat_execution_count.
    This is never assumed to equal requested_repeat_count, even though a
    well-formed recipe will typically make them equal by construction,
    and it is never computed by dividing an unordered per-type pool size
    by a per-pass per-type consumption count -- that would silently
    throw away exactly the position information this module exists to
    keep (e.g. it could not tell that a later pass's next_dc needs to
    pass over an intervening chain space it hasn't reached yet). If
    later_rows.repeat never moves the cursor at all (e.g. it is only
    same_stitch/working_loop steps), NOTHING constrains how many times
    it could run; that row's repeat_count_derivable is reported False,
    with a clear message, rather than guessing a number (see the module
    docstring's "WHAT REMAINS DELIBERATELY UNRESOLVED" section). Making
    this resolvable for real would require adding a new field to the
    recipe -- e.g. an explicit `later_rows.repeat_count` the AI must
    state, or a declared per-repeat consumption contract this validator
    could check against -- neither of which docs/recipe_model_v2.md
    currently defines.

    Returns a dict:
      {"valid": bool,
       "foundation": {...},                 # from calculate_foundation()
       "row_1": {...},                       # Phase 4A's full report (now including ordered_output)
       "later_rows": [ {...}, ... ],         # one entry per row actually evaluated
       "first_failing_row": int | None,      # 1-indexed; None if every evaluated row is valid
       "errors": [ str, ... ]}               # top-level errors not tied to one row

    Each later_rows[i] entry:
      {"row_number": int,
       "input_structure": {"stitch_posts": {...}, "chain_spaces": int,
                            "total_workable_positions": int},   # aggregate summary of ordered_input
       "ordered_input": [ {...}, ... ],         # the previous row's ordered_output, TURNED (reversed) -- see "DIRECTION" in the module docstring
       "setup_result": {"consumed": {...}, "produced_structure": {...},
                         "ordered_output": [...], "counts_as_stitch_posts": {...}},
       "repeat_count_derivable": bool | None,   # None only when setup itself overdrew
       "repeat_execution_count": int | None,    # None when repeat_count_derivable is False
       "repeat_once_consumed": {...} | None,    # one pass's typed consumption, diagnostic
       "repeat_result": {"consumed": {...}, "produced_structure": {...}, "ordered_output": [...]},  # totals across all executed passes
       "output_structure": {...},               # setup + repeat produced_structure -- this row's own output, aggregate summary
       "ordered_output": [ {...}, ... ],         # THIS ROW'S OWN production order (never reversed here) -- the caller turns (reverses) it before it becomes the NEXT row's ordered_input
       "output_counts_as_stitch_posts": {...},  # the counts_as-only subset of ordered_output's stitch posts
       "remaining_unused_input_targets": {"stitch_posts": {...}, "chain_spaces": int},
       "attempted_overdraw": {...} | None,       # populated only when setup itself couldn't be satisfied
       "valid": bool,
       "errors": [str, ...]}

    Raises RecipeMathError (never returns a report) for every case
    validate_row_1_against_foundation() already raises for, for
    later_row_count being invalid, and for the same_stitch/next_dc
    semantic cases documented in this module's docstring -- all of
    these are "refuses to guess" cases, not ordinary math mismatches.

    NEVER mutates the supplied recipe, and NEVER writes to
    verification.status -- exactly like Phase 4A, a True result here
    does not make a recipe CONFIRMED (nor even SIMULATION_VALID; this
    module does not touch verification at all), and a False result does
    not mutate it to REJECTED.
    """
    row_1_report = validate_row_1_against_foundation(recipe, requested_repeat_count)

    if not isinstance(later_row_count, int) or isinstance(later_row_count, bool):
        raise RecipeMathError(
            f"later_row_count must be a plain integer, got {later_row_count!r}"
        )
    if later_row_count < 0:
        raise RecipeMathError(
            f"later_row_count must be at least 0, got {later_row_count!r}"
        )

    later_rows_spec = recipe["later_rows"]

    if not row_1_report["valid"]:
        return {
            "valid": False,
            "foundation": row_1_report["foundation"],
            "row_1": row_1_report,
            "later_rows": [],
            "first_failing_row": 1,
            "errors": [],
        }

    later_row_reports = []
    first_failing_row = None
    # previous_row_output always stays in THAT row's own production
    # order (row 1's from Phase 4A, or a later row's own "ordered_output"
    # -- never reversed, never mutated). Each iteration below builds a
    # fresh, separately-reversed list from it for the row about to be
    # validated -- flat crochet turns at the end of every row, so the
    # next row's cursor walks the previous row's production in reverse
    # (see this module's docstring, "DIRECTION"). list(reversed(...))
    # always allocates a new list; it never mutates previous_row_output
    # or anything stored in an already-returned report.
    previous_row_output = row_1_report["row_1"]["ordered_output"]

    for offset in range(later_row_count):
        row_number = 2 + offset
        turned_input = list(reversed(previous_row_output))
        row_report = _validate_one_later_row(later_rows_spec, row_number, turned_input)
        later_row_reports.append(row_report)

        if not row_report["valid"]:
            first_failing_row = row_number
            break

        previous_row_output = row_report["ordered_output"]

    overall_valid = first_failing_row is None

    return {
        "valid": overall_valid,
        "foundation": row_1_report["foundation"],
        "row_1": row_1_report,
        "later_rows": later_row_reports,
        "first_failing_row": first_failing_row,
        "errors": [],
    }
