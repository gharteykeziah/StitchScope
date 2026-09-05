# StitchScope Test Suite

## Overview

The test suite has two jobs: prove the deterministic engine (tokenizer,
parser, validator, sizing, renderer, schema, swatch) behaves correctly on
inputs we fully control, and catch a subtler failure — a validator that
checks an AI's claim against a number derived from that same claim can
never fail, no matter how wrong the AI is. `test_swatch.py` proves, with a
real broken fixture, that StitchScope's validator doesn't have that flaw.

## What each file covers

| File | Tests | Without it |
|---|---|---|
| `test_tokenizer_and_parser.py` | Text → tokens → steps, happy path and every error path (unknown stitch, missing count, bad comma, zero count) | Malformed input silently parsing wrong, or a generic Python crash instead of a clear `ParseError`/`TokenizeError` |
| `test_renderer.py` | Plain-English phrasing — singular vs. plural, setup+repeat joined correctly | Grammatically wrong instructions reaching someone actually crocheting from them |
| `test_golden_examples.py` | Real rows through read → validate, checked against hand-verified expected output; stand-in proposals checked against the schema | A change to `validator.py`/`pattern_reader.py` silently altering what an already-worked real row computes to |
| `test_swatch.py` | The multi-row swatch validator — see below | A validator that always says "valid," no matter what's claimed |

Two of `test_golden_examples.py`'s five fixtures aren't synthetic:
`halter_mesh_row1_hand_swatch.json` and `halter_mesh_row2_hand_swatch.json`
come from an actual hand-crocheted swatch (`data/concierge_log.csv`). Both
carry a `known_discrepancy` field — the code's produced-stitch count
doesn't match the real hand count (an unresolved DC-vs-chain-space
question), left in deliberately: a real open question, not a test bug to
paper over by changing the expected value.

## test_swatch.py: proving the validator has teeth

Checking a proposed row against a number derived from that same AI's own
claim proves nothing — the row is sized to fit by construction and can
never fail. `engine/swatch.py` avoids this: `build_test_foundation()`
builds a foundation chain from a fixed repeat count *we* choose (default
6), never the model's; `simulate_swatch()` then walks each later row's
available stitches from what the *previous row actually produced*.

The core regression test hand-builds a fixture where row 1 produces
exactly 5 stitches and row 2 claims a `repeat_count` needing 8. It asserts
`simulate_swatch()` fails specifically at row 2 (not row 1) with
`needed=8`/`available=5`, and a companion test confirms row 3 is never
evaluated once row 2 fails. This is the test that proves the validator
can actually catch a bad claim, not just that it's shaped correctly.

## Running the tests

Full suite:

```
python3 -m unittest discover -s tests
```

One file:

```
python3 -m unittest tests.test_swatch
```

pytest is installed and can run these too, but there's no `pytest.ini` —
`unittest discover` is what `test_golden_examples.py` documents and what
any future CI should use.

## What's not tested yet

No test calls the real Claude API — costly and flaky in CI.
`get_vision_proposal_from_photo()` in `engine/vision.py` is only
exercised manually, via `run_real_photo.py` against a real photo.
Automated coverage stops at the stand-in `get_vision_proposal()`; this is
a known gap, not an oversight.
