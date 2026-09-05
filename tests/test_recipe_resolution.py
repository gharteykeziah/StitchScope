"""
Tests for run_real_photo.py's resolve_recipe() -- the glue between
engine/confirmed_patterns.py and engine/vision.py's get_stitch_recipe()
that decides whether a fresh, non-photo recipe call is even needed.

Every test redirects engine.confirmed_patterns' on-disk patterns file
to a scratch temp file (see ConfirmedPatternsTestCase in
test_confirmed_patterns.py's pattern), and mocks
run_real_photo.get_stitch_recipe directly -- proving with a call count,
not just a plausible-looking result, that the confirmed path never
calls it at all.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.confirmed_patterns as cp
import run_real_photo

MESH_SETUP = [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
MESH_REPEAT = [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]
MESH_TURNING_CHAIN = [{"stitch": "CH", "count": 3}]


class ResolveRecipeTests(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._tmp_path = os.path.join(self._tmp_dir, "confirmed_stitch_patterns.json")
        with open(self._tmp_path, "w") as f:
            f.write("{}")
        self._original_path = cp._PATTERNS_PATH
        cp._PATTERNS_PATH = self._tmp_path

    def tearDown(self):
        cp._PATTERNS_PATH = self._original_path
        shutil.rmtree(self._tmp_dir)

    @patch("run_real_photo.get_stitch_recipe")
    def test_uses_confirmed_recipe_and_never_calls_get_stitch_recipe(self, mock_get_recipe):
        cp.confirm_pattern("filet mesh", MESH_SETUP, MESH_REPEAT, turning_chain=MESH_TURNING_CHAIN,
                            photo_filename="a.jpg", note="hand swatched")

        recipe, source = run_real_photo.resolve_recipe("filet mesh")

        self.assertEqual(source, "confirmed")
        self.assertEqual(recipe, {"setup": MESH_SETUP, "repeat": MESH_REPEAT, "turning_chain": MESH_TURNING_CHAIN})
        mock_get_recipe.assert_not_called()

    @patch("run_real_photo.get_stitch_recipe")
    def test_calls_get_stitch_recipe_when_nothing_confirmed_and_records_it(self, mock_get_recipe):
        fresh_recipe = {"setup": [], "repeat": [{"stitch": "SC", "count": 1}], "turning_chain": [{"stitch": "CH", "count": 1}]}
        mock_get_recipe.return_value = fresh_recipe

        recipe, source = run_real_photo.resolve_recipe("single crochet border")

        mock_get_recipe.assert_called_once_with("single crochet border")
        self.assertEqual(source, "unverified")
        self.assertEqual(recipe, fresh_recipe)

        # Recorded as last_ai_proposal for confirm_stitch.py to pull from later.
        data = cp.load_patterns()
        self.assertEqual(data["single crochet border"]["last_ai_proposal"]["repeat"], fresh_recipe["repeat"])
        self.assertEqual(data["single crochet border"]["confirmations"], [])


if __name__ == "__main__":
    unittest.main()
