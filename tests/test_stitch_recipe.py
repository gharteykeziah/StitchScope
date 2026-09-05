"""
Tests for engine/vision.py's get_stitch_recipe() -- the separate,
non-photo API call that asks generically how a named stitch is
conventionally constructed.

No real API call is made: engine.vision._call_claude_for_structured_json
is mocked to return a fixed fake response, so these test
get_stitch_recipe()'s own logic (schema validation, what it returns)
in isolation. There is deliberately no test that scans response TEXT
for an "illustrative number" and strips it -- get_stitch_recipe() has
no such code path at all. Structured outputs constrains the ENTIRE
response to the recipe schema (setup/repeat/turning_chain step lists,
additionalProperties: false), so there is no prose channel for an
illustrative number to arrive through in the first place; the tests
below confirm the function only ever reads those three step lists,
exactly as the mocked JSON provided them, with no other extraction
logic in between.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.vision import get_stitch_recipe, VisionProposalError

VALID_RECIPE_RESPONSE = {
    "setup": [{"stitch": "SKIP", "count": 4}, {"stitch": "DC", "count": 1}],
    "repeat": [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}],
    "turning_chain": [{"stitch": "CH", "count": 3}],
}


class GetStitchRecipeTests(unittest.TestCase):

    @patch("engine.vision._call_claude_for_structured_json")
    def test_extracts_setup_repeat_turning_chain_from_the_response(self, mock_call):
        mock_call.return_value = VALID_RECIPE_RESPONSE

        recipe = get_stitch_recipe("filet mesh")

        self.assertEqual(recipe, VALID_RECIPE_RESPONSE)
        # Called with the recipe schema (not the photo-proposal schema)
        # and no image content -- just a single text prompt.
        args, kwargs = mock_call.call_args
        model, content, schema = args
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("filet mesh", content[0]["text"])
        self.assertEqual(schema.get("title"), "StitchScope Stitch Recipe (non-photo, generic construction)")

    @patch("engine.vision._call_claude_for_structured_json")
    def test_an_illustrative_concrete_number_in_a_step_count_is_passed_through_unmodified(self, mock_call):
        # If the model ignores the prompt's instructions and answers
        # with an oversized illustrative count anyway (e.g. a turning
        # chain sized like a real foundation), get_stitch_recipe() does
        # NOT try to detect or "fix" that itself -- it has no logic for
        # that at all. It only extracts the three step lists as given.
        # Catching an implausible number is engine/plausibility.py's
        # job, applied by the caller (see run_real_photo.py), not
        # get_stitch_recipe()'s.
        response_with_oversized_turning_chain = {
            "setup": [],
            "repeat": [{"stitch": "DC", "count": 1}],
            "turning_chain": [{"stitch": "CH", "count": 40}],
        }
        mock_call.return_value = response_with_oversized_turning_chain

        recipe = get_stitch_recipe("some stitch")

        self.assertEqual(recipe["turning_chain"], [{"stitch": "CH", "count": 40}])

    @patch("engine.vision._call_claude_for_structured_json")
    def test_raises_when_response_fails_recipe_validation(self, mock_call):
        # Missing "repeat" entirely -- structured outputs shouldn't
        # allow this given the schema, but get_stitch_recipe() must
        # never trust that blindly.
        mock_call.return_value = {"setup": [], "turning_chain": []}

        with self.assertRaises(VisionProposalError):
            get_stitch_recipe("filet mesh")

    @patch("engine.vision._call_claude_for_structured_json")
    def test_raises_when_repeat_is_empty(self, mock_call):
        mock_call.return_value = {"setup": [], "repeat": [], "turning_chain": []}

        with self.assertRaises(VisionProposalError):
            get_stitch_recipe("filet mesh")


if __name__ == "__main__":
    unittest.main()
