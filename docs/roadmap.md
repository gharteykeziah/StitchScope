# StitchScope v1 Roadmap & Status

What v1 is actually scoped to do, what's built, and what's left. Written
to stay accurate as the project moves -- when a build changes what's
true here, update this file in the same commit.

## What v1 does

A user uploads a photo (or a well-lit crop) of a crochet garment showing
one or more stitch patterns they don't recognize.

1. **Detect and name each distinct stitch region in the photo.** A real
   garment often isn't one stitch pattern -- a fan panel here, a mesh
   panel there. v1 identifies each region separately and names it (e.g.
   "center panel: filet mesh", "fan panel (left): shell stitch").
2. **Propose how to work each one.** For each region, a structured guess:
   the one-time setup, the repeating part, how many times it repeats,
   a confidence score, and which fields the guess is unsure about.
3. **Validate every guess before showing it to anyone.** Each region's
   proposal is checked twice -- first against the schema (is it even
   shaped correctly), then against real stitch arithmetic (does this
   repeat actually fit the stitches available, row over row). A region
   that fails either check is reported as rejected, never shown as if it
   were correct. One bad region doesn't hide a good one from the same
   photo.
4. **Explain what a validated guess actually means, in plain English.**
   Not a data structure -- a sentence a crocheter could follow.
5. **Size it to the user, if they give a measurement and gauge.** Find
   the closest stitch count to their target that still divides evenly
   into the repeat, instead of them doing that math by hand.

## What v1 is explicitly not

- It does not produce a full multi-panel garment build plan (which
  pieces to make, how they assemble) -- that's the original vision's
  "build plan" output, still ahead.
- It does not compare a photo of the user's own swatch against the
  reference automatically -- that comparison is still done by eye and
  logged by hand (see `data/concierge_log.csv`).
- It is not a general pattern-writing tool -- it identifies and
  validates specific stitch regions a user is stuck on, not an entire
  garment's construction from scratch.

## Status by component

| Component | Status | Where |
|---|---|---|
| Tokenizer (text -> tokens, rejects bad input with a clear error) | Done, tested | `engine/tokenizer.py` |
| Parser (tokens -> structured steps, enforces the grammar) | Done, tested | `engine/parser.py` |
| Pattern reader (setup + repeat row shaping) | Done, tested | `engine/pattern_reader.py` |
| Semantic validator / row simulator (consumes/produces math) | Done, tested | `engine/validator.py` |
| Constraint-based sizing solver | Done, tested | `engine/sizing.py` -- has one real example comparison against a greedy baseline; a proper benchmark (many targets, real accuracy/runtime numbers) is not built yet |
| Plain-language renderer | Done, tested | `engine/renderer.py` |
| Multi-region proposal contract (schema) | Done, tested | `contracts/proposal_schema_v2.json`, `engine/schema.py` |
| Vision-model perception layer | **Stand-in only** -- returns hand-written example proposals, no real API call | `engine/vision.py` |
| DSL grammar, domain glossary, copyright/safety policy | Done | `docs/` |
| Concierge validation (real hand-tested evidence) | Done for 1 garment (halter/corset top), mesh panel only | `data/concierge_log.csv` |
| Automated tests | 27 passing (golden examples, tokenizer/parser errors, schema validation, renderer phrasing) | `tests/` |
| Real photo run end-to-end | Not started -- blocked on the API key + real vision.py call | -- |
| Swatch-photo comparison (automated) | Not started -- stretch phase | -- |
| Repeat-periodicity detection (classical CV, no AI) | Not started -- stretch phase | -- |
| Formal evaluation vs. a naive single-prompt baseline | Not started -- stretch phase, matters most if the research-paper track stays active | -- |

## Concrete next steps, in order

1. Finish getting a real API key set up (Anthropic or otherwise) and
   store it in `.env` (already gitignored, never committed).
2. Replace `engine/vision.py`'s `get_vision_proposal()` stand-in with a
   real call: send a photo, get back JSON matching
   `contracts/proposal_schema_v2.json`, handle a malformed or failed
   response without crashing.
3. Run the real pipeline end-to-end on an actual photo -- the halter/
   corset top's mesh panel is the obvious first target, since it's the
   one region with real hand-verified ground truth already.
4. Write up what actually happened -- what worked, what a single photo
   genuinely couldn't tell the model, where the real run disagreed with
   the concierge-test expectations -- as a case-study section, and turn
   real numbers into real resume bullets.
5. Only after that: revisit the stretch phases (classical CV signal,
   automated swatch comparison, a correction system, the formal
   evaluation harness) if time remains.
