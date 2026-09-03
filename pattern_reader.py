"""
Reads a crochet pattern written in our simple format and turns it
into something the rest of the program can work with.

A real row has two different parts: a SETUP (done once - like the
first stitch worked into the foundation chain) and a REPEAT (the
part that's worked over and over across the rest of the row). Those
are different things, so we read them separately.
"""

def read_row(row_text):
    """Reads ONE comma-separated list of steps, like 'CH 1, SKIP 1, DC 1'."""
    steps = []
    if not row_text:
        return steps

    pieces = row_text.split(",")
    for piece in pieces:
        piece = piece.strip()
        words = piece.split(" ")
        stitch_name = words[0]
        stitch_count = int(words[1])
        steps.append({"stitch": stitch_name, "count": stitch_count})

    return steps


def read_full_row(setup_text, repeat_text):
    """
    Reads a real row: a one-time setup part, plus the part that
    repeats across the rest of the row.
    """
    return {
        "setup": read_row(setup_text),
        "repeat": read_row(repeat_text),
    }


def read_pattern(rows_text):
    """Reads a WHOLE pattern - a list of simple flat rows - row by row."""
    pattern = []
    for row_text in rows_text:
        pattern.append(read_row(row_text))
    return pattern
