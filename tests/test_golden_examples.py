"""
Regression tests built from real, hand-verified examples (see
tests/golden/*.json and docs/domain_glossary.md for what a "golden
example" is). Each fixture is a real row -- either from the physical
concierge-test swatch or from the main.py demo -- with the exact output
the engine is expected to produce for it. If a future change to
pattern_reader.py or validator.py breaks one of these, that's the engine
disagreeing with a row it used to get right.

Run with:  python3 -m unittest discover -s tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.pattern_reader import read_full_row
from engine.validator import check_full_row
from engine.schema import validate_proposal

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")


def load_golden_fixtures():
    fixtures = []
    for filename in sorted(os.listdir(GOLDEN_DIR)):
        if filename.endswith(".json"):
            with open(os.path.join(GOLDEN_DIR, filename)) as f:
                fixtures.append(json.load(f))
    return fixtures


class GoldenExampleTests(unittest.TestCase):
    """Runs every fixture in tests/golden/ through read_full_row + check_full_row."""

    def test_golden_fixtures_match_engine_output(self):
        fixtures = load_golden_fixtures()
        self.assertGreater(len(fixtures), 0, "expected at least one golden fixture in tests/golden/")

        for fixture in fixtures:
            with self.subTest(fixture=fixture["name"]):
                inp = fixture["input"]
                row = read_full_row(inp["setup_text"], inp["repeat_text"])
                result = check_full_row(row, inp["repeat_count"], inp["stitches_available"])

                expected = fixture["expected"]
                self.assertEqual(result["consumed"], expected["consumed"],
                                  f"{fixture['name']}: consumed mismatch")
                self.assertEqual(result["produced"], expected["produced"],
                                  f"{fixture['name']}: produced mismatch")
                self.assertEqual(result["valid"], expected["valid"],
                                  f"{fixture['name']}: valid mismatch")


class ProposalSchemaTests(unittest.TestCase):
    """The vision-proposal stand-ins should conform to the schema they're supposed to model."""

    def test_good_and_bad_stand_in_proposals_are_schema_valid(self):
        # Both example proposals are internally well-formed even though
        # the "bad" one describes a row that fails validation later --
        # schema-valid and structurally-valid-against-real-yarn are
        # different checks.
        from engine.vision import get_vision_proposal

        for which in ("good", "bad"):
            proposal = get_vision_proposal(which)
            errors = validate_proposal(proposal)
            self.assertEqual(errors, [], f"'{which}' proposal should be schema-valid, got: {errors}")

    def test_schema_rejects_a_malformed_proposal(self):
        malformed = {"stitch_family": "mystery stitch", "confidence": 1.5, "rows": []}
        errors = validate_proposal(malformed)
        self.assertTrue(len(errors) > 0, "a proposal missing fields / with an out-of-range confidence should fail")


if __name__ == "__main__":
    unittest.main()
