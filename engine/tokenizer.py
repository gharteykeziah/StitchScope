"""
Turns raw row text (e.g. "SKIP 5, DC 1") into a stream of Tokens: the
lexical scanning step of parsing. parser.py consumes what this produces.

This is the classic first stage of a real parser -- scan characters left
to right, classify each chunk as a token, and reject anything that isn't
recognizable at all (an unknown word, a stray symbol) before parsing even
starts trying to make sense of the grammar.
"""

import re
from dataclasses import dataclass
from enum import Enum

from engine.validator import STITCH_RULES


class TokenType(Enum):
    STITCH = "STITCH"
    NUMBER = "NUMBER"
    COMMA = "COMMA"


@dataclass
class Token:
    type: TokenType
    value: object       # str for STITCH, int for NUMBER, None for COMMA
    position: int        # character index in the source text -- for error messages


class TokenizeError(Exception):
    """Raised when the source text contains something the lexer doesn't recognize."""
    pass


# The vocabulary of known stitches lives in exactly one place: validator.py's
# STITCH_RULES. Deriving it here instead of re-listing the 8 names means
# there's no second copy that could quietly drift out of sync.
KNOWN_STITCHES = set(STITCH_RULES.keys())

_TOKEN_PATTERN = re.compile(r"""
    (?P<WS>\s+)
  | (?P<COMMA>,)
  | (?P<WORD>[A-Za-z]+)
  | (?P<NUMBER>\d+)
""", re.VERBOSE)


def tokenize(text):
    """
    Scans row text into a list of Tokens. Raises TokenizeError on anything
    it doesn't recognize -- an unknown stitch name, a stray symbol, a
    character that isn't a letter, digit, comma, or whitespace.
    """
    tokens = []
    pos = 0
    length = len(text)

    while pos < length:
        match = _TOKEN_PATTERN.match(text, pos)
        if not match:
            raise TokenizeError(f"Unrecognized character {text[pos]!r} at position {pos}")

        kind = match.lastgroup
        value = match.group()

        if kind == "WS":
            pos = match.end()
            continue
        elif kind == "COMMA":
            tokens.append(Token(TokenType.COMMA, None, pos))
        elif kind == "WORD":
            stitch_name = value.upper()
            if stitch_name not in KNOWN_STITCHES:
                raise TokenizeError(
                    f"Unknown stitch '{value}' at position {pos} "
                    f"(known stitches: {sorted(KNOWN_STITCHES)})"
                )
            tokens.append(Token(TokenType.STITCH, stitch_name, pos))
        elif kind == "NUMBER":
            tokens.append(Token(TokenType.NUMBER, int(value), pos))

        pos = match.end()

    return tokens
