"""
Finds the best stitch count for a target measurement, given a
pattern's repeat, without breaking that repeat.
"""

def find_valid_stitch_count(target_stitches, repeat_width, border=0):
    """Finds the closest valid stitch count to the target."""
    best_count = None
    best_diff = None
    k = 0

    while True:
        count = (k * repeat_width) + border
        if count > target_stitches + repeat_width:
            break

        diff = abs(count - target_stitches)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_count = count

        k += 1

    return best_count


def greedy_stitch_count(target_stitches, repeat_width, border=0):
    """Naive baseline: rounds up to the first valid count reached."""
    k = 0
    while True:
        count = (k * repeat_width) + border
        if count >= target_stitches:
            return count
        k += 1
