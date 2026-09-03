"""
Reads crochet pattern text into the structured step lists the rest of
the engine works with. Actual parsing -- turning text into tokens, then
tokens into steps -- lives in tokenizer.py and parser.py; this module is
the public API everything else imports, plus the setup+repeat/whole-
pattern shaping built on top of a single parsed row.
"""

from parser import parse_steps


def read_row(row_text):
    """Reads ONE comma-separated list of steps, like 'CH 1, SKIP 1, DC 1'."""
    return parse_steps(row_text)


def read_full_row(setup_text, repeat_text):
    """Reads a real row: a one-time setup part, plus the part that repeats
    across the rest of the row."""
    return {
        "setup": read_row(setup_text),
        "repeat": read_row(repeat_text),
    }


def read_pattern(rows_text):
    """Reads a WHOLE pattern - a list of simple flat rows - row by row."""
    return [read_row(row_text) for row_text in rows_text]
