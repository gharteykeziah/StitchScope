"""
Tests for the tokenizer/parser upgrade: pattern_reader.py used to do its
own ad hoc splitting; now tokenizer.py scans text into tokens and
parser.py turns those into steps, with real errors instead of a generic
Python crash on bad input. These tests cover both the happy path and the
error path -- a parser that only gets tested on valid input hasn't
really been tested.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.tokenizer import tokenize, TokenType, TokenizeError
from engine.parser import parse_steps, ParseError
from engine.pattern_reader import read_row, read_full_row


class TokenizerTests(unittest.TestCase):

    def test_tokenizes_a_simple_row(self):
        tokens = tokenize("DC 1, CH 1")
        got = [(t.type, t.value) for t in tokens]
        self.assertEqual(got, [
            (TokenType.STITCH, "DC"), (TokenType.NUMBER, 1),
            (TokenType.COMMA, None),
            (TokenType.STITCH, "CH"), (TokenType.NUMBER, 1),
        ])

    def test_stitch_names_are_case_insensitive(self):
        tokens = tokenize("dc 3")
        self.assertEqual(tokens[0].value, "DC")

    def test_unknown_stitch_raises(self):
        with self.assertRaises(TokenizeError):
            tokenize("XYZ 1")

    def test_unrecognized_character_raises(self):
        with self.assertRaises(TokenizeError):
            tokenize("DC 1 #")


class ParserTests(unittest.TestCase):

    def test_parses_multiple_steps(self):
        steps = parse_steps("SKIP 5, DC 1")
        self.assertEqual(steps, [
            {"stitch": "SKIP", "count": 5},
            {"stitch": "DC", "count": 1},
        ])

    def test_empty_text_parses_to_empty_list(self):
        self.assertEqual(parse_steps(""), [])
        self.assertEqual(parse_steps("   "), [])

    def test_missing_count_raises(self):
        with self.assertRaises(ParseError):
            parse_steps("DC")

    def test_missing_comma_between_steps_raises(self):
        with self.assertRaises(ParseError):
            parse_steps("DC 1 CH 1")

    def test_trailing_comma_raises(self):
        with self.assertRaises(ParseError):
            parse_steps("DC 1,")

    def test_zero_count_raises(self):
        with self.assertRaises(ParseError):
            parse_steps("DC 0")


class PatternReaderStillWorksTests(unittest.TestCase):
    """pattern_reader.py's public functions are now backed by the real
    tokenizer/parser -- these confirm the swap didn't change behavior for
    valid input."""

    def test_read_row_matches_previous_behavior(self):
        self.assertEqual(read_row("CH 1, SKIP 1, DC 1"), [
            {"stitch": "CH", "count": 1},
            {"stitch": "SKIP", "count": 1},
            {"stitch": "DC", "count": 1},
        ])

    def test_read_full_row_matches_previous_behavior(self):
        row = read_full_row("SKIP 5, DC 1", "CH 1, SKIP 1, DC 1")
        self.assertEqual(row["setup"], [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}])
        self.assertEqual(row["repeat"], [
            {"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}
        ])


if __name__ == "__main__":
    unittest.main()
