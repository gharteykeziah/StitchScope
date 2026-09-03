"""
Runs the StitchScope pipeline end to end on the REAL mesh pattern:
read it, validate it, size it, and check an AI proposal against the
validator.
"""

from engine.pattern_reader import read_row, read_full_row
from engine.validator import check_full_row
from engine.sizing import find_valid_stitch_count, greedy_stitch_count
from engine.vision import get_vision_proposal, process_proposal
from engine.renderer import render_row


def run_demo():
    print("== Reading the REAL mesh pattern ==")

    # Row 1: foundation chain, then "DC into the 6th chain from the
    # hook" (which is really "skip 5 chains, then DC"), then the
    # real repeat: chain 1, skip 1, double crochet 1 - across.
    row_1 = read_full_row(setup_text="SKIP 5, DC 1", repeat_text="CH 1, SKIP 1, DC 1")

    # Row 2: "chain 4 and turn - counts as one DC plus one CH",
    # then the repeat: chain 1, DC into the next DC.
    row_2 = read_full_row(setup_text="DC 1, CH 1", repeat_text="CH 1, DC 1")

    print("Row 1 setup:", row_1["setup"])
    print("Row 1 repeat:", row_1["repeat"])
    print("Row 2 setup:", row_2["setup"])
    print("Row 2 repeat:", row_2["repeat"])

    print()
    print("== ...and in plain English, not just raw steps ==")
    print("Row 1:", render_row(row_1, repeat_count=7))
    print("Row 2:", render_row(row_2, repeat_count=14))

    print()
    print("== Validating against a real foundation chain ==")
    foundation_chain = 20  # any even number, per your instructions
    row_1_repeats = 7      # how many times the repeat fits across

    row_1_result = check_full_row(row_1, repeat_count=row_1_repeats, stitches_available=foundation_chain)
    print(f"Row 1 (foundation chain of {foundation_chain}):", row_1_result)

    row_2_repeats = 14
    row_2_result = check_full_row(row_2, repeat_count=row_2_repeats, stitches_available=row_1_result["produced"])
    print(f"Row 2 (using row 1's {row_1_result['produced']} stitches produced):", row_2_result)

    print()
    print("== A DELIBERATELY BROKEN row, to check the validator catches it ==")
    broken_row = read_full_row(setup_text="SKIP 5, DC 1", repeat_text="DC 5")
    broken_result = check_full_row(broken_row, repeat_count=7, stitches_available=foundation_chain)
    print("Broken row check:", broken_result)

    print()
    print("== Sizing to a target ==")
    target = 61
    repeat_width = 5
    smart_count = find_valid_stitch_count(target, repeat_width)
    naive_count = greedy_stitch_count(target, repeat_width)
    print(f"Target: {target} stitches, repeat width: {repeat_width}")
    print(f"Solver picked:  {smart_count}  (off by {abs(smart_count - target)})")
    print(f"Naive round-up: {naive_count}  (off by {abs(naive_count - target)})")

    print()
    print("== AI proposes, we validate ==")
    print("-- Example 1: a good proposal (a real repeat that fits) --")
    process_proposal(get_vision_proposal("good"), stitches_available=foundation_chain)
    print()
    print("-- Example 2: a bad proposal (claims more repeats than fit) --")
    process_proposal(get_vision_proposal("bad"), stitches_available=foundation_chain)


if __name__ == "__main__":
    run_demo()
