"""
Tests for renderer.py -- the plain-language output half of the compiler
pipeline (parse -> validate -> render). These check that the phrasing is
exactly what a crocheter would expect, singular vs. plural included,
since the whole point of this module is to be read by a person, not
just be technically correct.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from renderer import render_step, render_steps, render_row


class RenderStepTests(unittest.TestCase):

    def test_chain_one(self):
        self.assertEqual(render_step({"stitch": "CH", "count": 1}), "chain 1")

    def test_chain_many(self):
        self.assertEqual(render_step({"stitch": "CH", "count": 4}), "chain 4")

    def test_dc_singular_vs_plural_phrasing(self):
        self.assertEqual(
            render_step({"stitch": "DC", "count": 1}),
            "double crochet in the next stitch",
        )
        self.assertEqual(
            render_step({"stitch": "DC", "count": 3}),
            "double crochet in each of the next 3 stitches",
        )

    def test_skip_singular_vs_plural_phrasing(self):
        self.assertEqual(render_step({"stitch": "SKIP", "count": 1}), "skip the next stitch")
        self.assertEqual(render_step({"stitch": "SKIP", "count": 5}), "skip the next 5 stitches")

    def test_increase_and_decrease_say_what_they_do(self):
        inc = render_step({"stitch": "INC", "count": 1})
        dec = render_step({"stitch": "DEC", "count": 1})
        self.assertIn("increase", inc)
        self.assertIn("decrease", dec)


class RenderStepsTests(unittest.TestCase):

    def test_empty_list_renders_empty_string(self):
        self.assertEqual(render_steps([]), "")

    def test_single_step_has_no_connector(self):
        self.assertEqual(render_steps([{"stitch": "CH", "count": 1}]), "chain 1")

    def test_multiple_steps_joined_with_then(self):
        text = render_steps([
            {"stitch": "CH", "count": 1},
            {"stitch": "SKIP", "count": 1},
            {"stitch": "DC", "count": 1},
        ])
        self.assertEqual(text, "chain 1, then skip the next stitch, then double crochet in the next stitch")


class RenderRowTests(unittest.TestCase):

    def test_real_mesh_row_1(self):
        row = {
            "setup": [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}],
            "repeat": [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}],
        }
        text = render_row(row, repeat_count=7)
        self.assertEqual(
            text,
            "Skip the next 5 stitches, then double crochet in the next stitch. "
            "Then repeat 7 times: chain 1, then skip the next stitch, then "
            "double crochet in the next stitch."
        )

    def test_row_with_no_setup(self):
        row = {"setup": [], "repeat": [{"stitch": "SC", "count": 1}]}
        text = render_row(row, repeat_count=10)
        self.assertEqual(text, "Repeat 10 times: single crochet in the next stitch.")

    def test_row_with_no_repeat_and_no_setup_renders_empty(self):
        row = {"setup": [], "repeat": []}
        self.assertEqual(render_row(row, repeat_count=1), "")


if __name__ == "__main__":
    unittest.main()
