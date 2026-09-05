"""
The one authoritative calculation for the recipe-v2 pathway: how many
foundation chains a stored foundation_formula requests, for a caller-
chosen number of repeats.

    foundation_count = foundation_formula.repeat_multiple * requested_repeat_count
                      + foundation_formula.additional_chains

foundation_formula is the ONLY source of this number. calculate_foundation()
never inspects row_1/later_rows CH steps, setup or repeat consumption,
engine/validator.py's new_chain_links(), or any AI-stated concrete
foundation number to compute or "correct" this value -- see
engine/swatch.py's build_test_foundation() for the older, v1 pathway's
very different approach (which this module does not call, replace, or
otherwise touch).

Whether row 1 actually consumes exactly foundation_count stitches is a
separate question this module does not answer -- that comparison is
Phase 4's job (see docs/recipe_model_v2.md). calculate_foundation() only
evaluates the stored formula honestly, for whatever recipe it's given,
regardless of that recipe's verification.status. A REJECTED recipe's
formula is calculated exactly the same way a CONFIRMED one's would be;
producing a number is not a claim that the recipe is crochet-correct --
structural validity and physical trust are different questions (see
docs/recipe_model_v2.md section 6).
"""

from engine.schema import validate_recipe_v2


class FoundationCalculationError(ValueError):
    """
    Raised when calculate_foundation() can't produce a number: the
    recipe fails validate_recipe_v2() (a malformed shape -- calculating
    from that would just be arithmetic on garbage, not a real answer),
    or requested_repeat_count isn't a plain positive int.

    This is never raised merely because a recipe's verification.status
    is REJECTED -- a structurally valid REJECTED recipe still has its
    formula evaluated exactly as stored. Whether a rejected recipe may
    actually be *used* is a decision for whatever calls this function,
    not something calculate_foundation() decides on the caller's behalf.
    """


def calculate_foundation(recipe, requested_repeat_count):
    """
    Evaluates a v2 recipe's stored foundation_formula for
    requested_repeat_count repeats:

        foundation_count = repeat_multiple * requested_repeat_count + additional_chains

    Both pieces of the formula come only from recipe["foundation_formula"]
    -- never re-derived from row_1/later_rows step data -- and
    requested_repeat_count is never inferred from anything the recipe
    itself claims (there is no "repeat_count" field anywhere in the v2
    shape, precisely so nothing here could be tempted to read one). The
    caller picks the repeat count -- for a physical test swatch that's
    typically a small fixed number chosen independently of the recipe,
    the same principle engine/swatch.py's build_test_foundation()
    already follows for the older v1 pathway.

    Defensive validation, in this order:
      1. recipe must be an object and pass validate_recipe_v2() -- a
         malformed recipe raises FoundationCalculationError carrying the
         validator's own readable error strings; nothing is calculated
         from it.
      2. requested_repeat_count must be a plain int (bool excluded --
         bool is a subclass of int in Python) and at least 1. Nothing is
         coerced: "6", 6.0, and True are all rejected outright, never
         converted to 6.

    Returns a dict:
      {"repeat_multiple": int, "requested_repeat_count": int,
       "repeated_chains": int, "additional_chains": int,
       "foundation_count": int}

    Never mutates the supplied recipe -- every field is only read, never
    assigned.
    """
    if not isinstance(recipe, dict):
        raise FoundationCalculationError(f"recipe must be an object, got {type(recipe).__name__}")

    errors = validate_recipe_v2(recipe)
    if errors:
        raise FoundationCalculationError(
            "recipe failed v2 schema validation, so no foundation was calculated:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    if not isinstance(requested_repeat_count, int) or isinstance(requested_repeat_count, bool):
        raise FoundationCalculationError(
            f"requested_repeat_count must be a plain integer, got {requested_repeat_count!r}"
        )
    if requested_repeat_count < 1:
        raise FoundationCalculationError(
            f"requested_repeat_count must be at least 1, got {requested_repeat_count!r}"
        )

    formula = recipe["foundation_formula"]
    repeat_multiple = formula["repeat_multiple"]
    additional_chains = formula["additional_chains"]

    repeated_chains = repeat_multiple * requested_repeat_count
    foundation_count = repeated_chains + additional_chains

    return {
        "repeat_multiple": repeat_multiple,
        "requested_repeat_count": requested_repeat_count,
        "repeated_chains": repeated_chains,
        "additional_chains": additional_chains,
        "foundation_count": foundation_count,
    }
