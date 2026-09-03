"""
Parses a token stream (from tokenizer.py) into the structured step list
the rest of the engine works with: [{"stitch": "DC", "count": 1}, ...].

Enforces the grammar in docs/dsl_grammar.md -- a step is a stitch name
followed by a count, steps are separated by commas, nothing else is
allowed. Anything that breaks that shape raises a ParseError naming
exactly what was expected and where, instead of a generic Python error
from indexing into a list that turned out to be the wrong length.
"""

from tokenizer import tokenize, TokenType


class ParseError(Exception):
    """Raised when the token stream doesn't match the row grammar."""
    pass


def parse_steps(text):
    """
    Parses row text like "SKIP 5, DC 1" into
    [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}].
    Empty or blank text parses to an empty list -- a row's setup is
    allowed to be empty.
    """
    if not text or not text.strip():
        return []

    tokens = tokenize(text)
    steps = []
    i = 0
    n = len(tokens)

    while i < n:
        token = tokens[i]

        if token.type != TokenType.STITCH:
            raise ParseError(
                f"Expected a stitch name at position {token.position}, "
                f"found {token.type.value} instead"
            )

        if i + 1 >= n or tokens[i + 1].type != TokenType.NUMBER:
            raise ParseError(
                f"Expected a count after stitch '{token.value}' "
                f"(position {token.position}), but none was found"
            )

        stitch_name = token.value
        count = tokens[i + 1].value
        if count < 1:
            raise ParseError(
                f"Stitch count must be a positive number, got {count} "
                f"for '{stitch_name}' at position {token.position}"
            )

        steps.append({"stitch": stitch_name, "count": count})
        i += 2

        if i < n:
            if tokens[i].type != TokenType.COMMA:
                raise ParseError(
                    f"Expected ',' between steps at position {tokens[i].position}, "
                    f"found {tokens[i].type.value} instead"
                )
            i += 1
            if i >= n:
                raise ParseError("Trailing comma with nothing after it")

    return steps
