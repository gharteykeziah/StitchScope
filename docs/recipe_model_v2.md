# StitchScope Recipe Model v2 — Design (Phase 1), now with schema enforcement (Phase 2), a foundation calculator (Phase 3), row-1 math validation (Phase 4A), typed later-row validation (Phase 5), a trusted recipe library (Phase 6), and a trusted swatch planner/renderer (Phase 7)

**Status: still not wired into the production photo pathway.**
`engine/vision.py`, `engine/swatch.py` (its own, different v1 foundation
logic), `engine/confirmed_patterns.py`, `run_real_photo.py`, and
`contracts/stitch_recipe_schema_v1.json` are all unchanged by anything
below. What *has* been built since this document was first written:
Phase 2 added `contracts/stitch_recipe_schema_v2.json` and
`engine/schema.py`'s `validate_recipe_v2()`, actually enforcing the
shape this document designs. Phase 3 added
`engine/foundation.py`'s `calculate_foundation()` — see "Phase 3: the
foundation calculator" for what it does and doesn't do. Phase 4A added
`engine/recipe_validator.py`'s `validate_row_1_against_foundation()` —
see "Phase 4A: row-1 math validation" for what it checks and why
later-row validation isn't part of it. Phase 5 added
`engine/later_row_validator.py`'s `validate_recipe_rows()` — see "Phase
5: typed later-row validation" for how it resolves (or explicitly
refuses to resolve) the open questions Phase 4A left for it. Phase 6
added `engine/recipe_library.py` and `data/confirmed_stitch_recipes_v2.json`
— see "Phase 6: trusted recipe library and recipe resolution" for how a
physically-confirmed recipe is stored, looked up, and made to override
a fresh (untrusted) AI proposal for the same stitch. Phase 7 added
`engine/swatch_planner_v2.py` and `engine/renderer_v2.py` — see "Phase
7: trusted swatch planner and user-facing renderer" for how a
`trusted_match` recipe is turned into a fully simulated, evidence
-backed swatch plan and rendered into plain instructions, and for every
explicit way that pipeline refuses instead. The rest of this document
(sections 1–11) is the original Phase 1 design discussion, left as
written; only this status note and the Phase 3/4A/5/6/7 sections are
new.

*This is the corrected revision of the Phase 1 design. See the changelog
at the bottom for what that correction pass fixed and why.*

## Why this exists

The current recipe shape (`setup` / `repeat` / `turning_chain`, each a
flat step list) doesn't distinguish several things that turned out to
matter in practice:

- **A foundation-chain formula** (how long to chain before touching any
  stitch) **vs. a row-1 action** (what you do once that foundation
  exists). These got conflated: a `CH 2` inside row 1's `setup` was
  simultaneously "2 more chains to make" and "a step to render as an
  instruction," and `run_real_photo.py` needed a manual patch
  (`new_chain_links()` plus a "don't print this chain again" special
  case) to stop double-counting and double-printing it. That patch
  works, but it's a symptom of the underlying model not having a place
  for "foundation length" as its own concept.
- **Row 1's placement vs. a later row's placement.** The current code
  reuses one `repeat` list for every row (`later_row = {"setup":
  turning_chain, "repeat": recipe["repeat"]}` in `run_real_photo.py`),
  but row 1's `DC` is worked into the *foundation chain*, while the
  same-looking `DC` on row 3 is worked into a *chain space* left by row
  2. Same stitch, same count, different place — and the current shape
  has no field for "different place."
- **Whether a turning chain counts as a stitch, a chain space, or
  both.** A real `ch-4, counts as one DC plus one CH` convention (see
  `main.py`'s `row_2` comment) changes how many real stitch tops *and*
  chain spaces a row actually produces. Nothing in the current model
  records this — the pre-v2 code fakes it by writing a turning chain as
  a literal `DC 1, CH 1` step pair, which is not a real DC and not a
  real CH, just two steps chosen because their combined `produces`
  total happens to come out right in the old flat model.

This ambiguity is exactly what let the pipeline produce foundations of
7 or 9 chains for the same six-repeat filet-mesh swatch depending on
which patch had landed, while a downstream step told the user to chain
*additional* setup stitches on top — the foundation count and the
row-1 instructions were computed from overlapping information without
an explicit boundary between them.

## 1. The complete data hierarchy

```
Recipe
├── pattern_id            (string)
├── name                  (string)
├── aliases               (list of string)
├── terminology           ("US" | "UK")
│
├── foundation_formula
│   ├── repeat_multiple       (int)
│   └── additional_chains     (int)
│
├── row_1
│   ├── setup             (list of Step)
│   └── repeat            (list of Step)
│
├── later_rows
│   ├── setup             (list of Step)   -- turning-chain instructions
│   └── repeat            (list of Step)
│
├── expected_swatch_structure
│   ├── expected_stitch_posts_per_repeat    (int | null)
│   └── expected_chain_spaces_per_repeat    (int | null)
│
└── verification
    ├── status             (one of 7 enum values, see section 7)
    ├── confirmations       (list of {photo, date, note})
    └── reason              (string, optional — present when status is REJECTED)

Step
├── stitch        (one of CH, SC, HDC, DC, SLST, SKIP, INC, DEC)
├── count         (positive int)
├── placement     (one of 7 enum values, see section 4)
└── counts_as     (optional object, see section 5)
```

Every list of steps in this model — `row_1.setup`, `row_1.repeat`,
`later_rows.setup`, `later_rows.repeat` — is a list of `Step`. There is
exactly one `Step` shape used everywhere; what differs between
contexts is which `placement` values make sense there (see section 4).

## 2. Foundation vs. row 1 vs. later rows

These are three different things that the v1 shape blurred together:

**Foundation formula** answers one question only: *how many chain
stitches do I physically make before I touch anything else?* It is a
pure arithmetic relationship, not a set of instructions:

```
foundation_count = repeat_multiple * requested_repeat_count + additional_chains
```

- `repeat_multiple` is how many foundation stitches one pass of the
  repeat unit actually uses up (its `consumes` total, in the existing
  `STITCH_RULES` sense — see `engine/validator.py`).
- `additional_chains` is everything *fixed*, independent of how many
  repeats you ask for: chain links that exist only to be skipped past,
  plus any brand-new links a lead-in needs before the repeat can start.
  A `CH` inside a later row's turning chain is never part of this
  number — that chain is built from an already-attached working loop,
  not pre-chained onto the foundation (this exact distinction is what
  `engine/validator.py`'s `new_chain_links()` was added to compute for
  the current shape; the v2 model gives it its own named field instead
  of a function that has to re-derive it from a step list every time).

**Phase 1 defines this formula's meaning only.** No calculator is
implemented — `foundation_formula` is data, not behavior, in this
phase.

**Row 1** is what you actually do once that foundation exists:
skipping past reserved chains, working into the first usable one,
starting the repeat. **Foundation length is never represented as a
row-one `CH` action** — nothing in `row_1.setup` or `row_1.repeat`
should ever itself be a `CH` step whose job is to *lengthen the
foundation*; that job belongs to `additional_chains` above. Row 1's
steps only ever act on a foundation that's already fully chained.

**Later rows** don't touch the foundation chain at all — they're built
by working into the *previous row's* output. `later_rows.setup` holds
the turning-chain instructions (which are a real, first-class action —
unlike the foundation formula, a turning chain genuinely does get
worked as a step, from the working loop), and `later_rows.repeat` is
the repeat unit worked after it.

`row_1.repeat` and `later_rows.repeat` are two **separate** fields even
when the underlying stitch and count look identical, because their
`placement` differs: row 1's `DC` goes `next_foundation_chain`; a
later row's same-looking `DC` might go `next_chain_space` or
`next_stitch`. Collapsing these into one shared `repeat` field (as v1
does) is exactly the bug class this document exists to name.

## 3. Setup vs. repeat

Unchanged in spirit from v1, restated precisely for v2: **setup** is
the one-time steps worked once at the start of a row, before the
repeating part begins. **Repeat** is the unit of steps worked some
number of times to fill the rest of the row. Both row 1 and later rows
have their own setup and repeat — row 1's setup is the foundation
lead-in action described above; a later row's setup is its turning
chain.

## 4. Placement

`placement` says **where** a step is worked — the piece of the fabric
(or the hook) a stitch actually attaches to. This is new in v2; v1
steps had only `stitch` and `count`, with no way to distinguish "DC
into the next foundation chain" from "DC into the next DC" from "DC
into the next chain space" even though a real pattern (and a real
crocheter) cares enormously about the difference.

Initial vocabulary:

| Value | Meaning |
|---|---|
| `working_loop` | A chain created directly from the loop currently on the hook — a floating chain hung off the last stitch made, not worked into anything else. |
| `next_foundation_chain` | Worked into the next unused loop of the original foundation chain. **Row 1 only** — there is no foundation chain to place into on any later row. |
| `next_stitch` | Worked into the top of the next stitch left by the previous row, generically — used when the specific stitch type doesn't matter for placement. |
| `next_dc` | Worked specifically into the top of the next double-crochet stitch from the previous row — more specific than `next_stitch`, for patterns where hitting a particular stitch type matters (shells, V-stitches). |
| `next_chain_space` | Worked into the open space formed by a chain. **Must refer to a chain space produced by the immediately previous row specifically** — not any earlier row, and not the current row's own not-yet-finished turning chain. If a real pattern needs to reach back further than one row, that is a different concept this vocabulary does not yet model (see open question 3). |
| `turning_chain` | Describes the **role** of a chain worked at the beginning of a later row — this step *is* that turning chain, produced from the working loop rather than worked into an existing thing. It is a role label, not a separate production mechanism from `working_loop`; a turning-chain step is always also, mechanically, a `working_loop` chain. |
| `same_stitch` | Worked into the same foundation position most recently targeted by a stitch. Intervening `working_loop` chains do not replace or clear that target — for stitches worked as a cluster (e.g. "5 DC in same stitch"). |

`placement` is context-dependent: `next_foundation_chain` only makes
sense on `row_1`; `next_chain_space` presupposes the previous row
actually left a chain space to place into. Phase 1 defines the
vocabulary; checking that a given placement is legal for the row it
appears in is schema/validation work for Phase 2 — **no enforcement is
implemented yet.**

## 5. `counts_as`

Optional field on a step, describing what that step contributes toward
the row's real stitch-post and chain-space totals, beyond what its own
`stitch` code alone would suggest. This matters because a single
turning-chain step can simultaneously stand in for a stitch post *and*
leave behind a chain space — one physical action, two structural
consequences — which a single string value cannot express.

Shape:

```json
"counts_as": {
  "stitch_posts": { "DC": 1 },
  "chain_spaces": 1
}
```

- **`stitch_posts`** is a mapping from stitch code to how many of that
  stitch's "top" this step contributes to the row's post count, purely
  as accounting — the step doesn't literally perform that stitch, it
  just counts toward the total the way one would. A real `ch-4`
  turning chain that conventionally counts as the row's first DC would
  carry `{"DC": 1}` here. A turning chain with no such convention (e.g.
  a plain `ch-1` before a single-crochet row) omits `stitch_posts`
  entirely, or gives it an empty object.
- **`chain_spaces`** is an integer: how many floating chain spaces this
  step leaves behind for a later row to work into. A turning chain that
  is itself the mesh's chain space (as in a real filet-mesh turning
  chain) would carry `chain_spaces: 1`; one that counts as a stitch but
  leaves no usable space would carry `chain_spaces: 0`.
- **When `counts_as` is omitted**, the step contributes nothing beyond
  its own `stitch` code's ordinary meaning — no extra stitch-post
  credit, no extra chain space. This is the default for the large
  majority of steps (an ordinary `DC` in a repeat needs no `counts_as`
  at all; it already *is* a DC).
- **`counts_as` affects produced structure, not consumption.** It
  changes how many stitch posts and chain spaces this step is credited
  with *producing* for the next row to work into. It never means the
  chain itself *consumes* a stitch from the row below — a turning
  chain's `consumes` is still governed by its own `stitch` code
  (`CH` consumes 0, per `STITCH_RULES`) regardless of what it counts
  as. `counts_as` is additive bookkeeping on the output side only.

A turning chain that counts as one DC and leaves no separate chain
space (a solid, non-mesh fabric's turning chain, for instance) would be
written:

```json
{"stitch": "CH", "count": 3, "placement": "turning_chain",
 "counts_as": {"stitch_posts": {"DC": 1}, "chain_spaces": 0}}
```

## 6. Validation layers

Six distinct layers exist (or will exist) between "the AI said
something" and "a person can trust this recipe." Each proves a
different, narrower thing than the one after it, and none of the
earlier layers imply the later ones:

| Layer | What it proves | What it does NOT prove |
|---|---|---|
| **Schema validation** | The data is shaped correctly: required fields present, `stitch` is a known code, `count` is a positive integer, lists are the right type. | Nothing about whether the *pattern* makes sense — a schema-valid recipe can still be crochet-nonsensical (e.g. a `repeat_multiple` of 0). |
| **Plausibility checking** | The proposed numbers are not absurd on their face — a setup isn't wildly oversized, a repeat isn't degenerate (see `engine/plausibility.py`). This is a *separate concept from schema validation*: a value can be exactly the right type and still be implausible (a schema-valid `CH 40` setup is still an oversized, suspicious number). | Whether the recipe is actually correct for the named stitch — only that it doesn't look obviously broken. |
| **Mathematical validation** | The foundation formula and each row's consumed/produced arithmetic are internally consistent — the numbers add up without contradiction. | Whether the *placements* make physical sense, or whether the stitch pattern this arithmetic describes is the one it claims to be (see the known-bad example: its arithmetic is perfectly consistent and still wrong). |
| **Connected-row simulation** | A chosen number of rows, worked in sequence, hold together stitch-count-wise — row 2's claimed consumption fits what row 1 actually produced, and so on (`engine/swatch.py`'s `simulate_swatch()`). | Anything about the physical world. This is a computer simulation of the arithmetic across multiple rows — not a person making stitches with yarn and a hook. |
| **Physical swatch testing** | A person actually crocheted the exact candidate and recorded what happened — a real, physical result exists, whether it worked or not. | That the result is what was *intended* — a physical swatch can be made exactly as specified and still not be the stitch pattern someone meant to reproduce. |
| **Visual/human confirmation** | A person looked at (or made) the physical result and judged that it matches the intended stitch variation — this is the only layer that closes the loop between "the math works" and "this is actually the pattern I wanted." | Nothing further — this is the top of the chain. |

**A schema-valid recipe is not necessarily crochet-correct. A
mathematically valid recipe is not necessarily visually correct.**
These two rules are the reason the verification-status progression in
section 7 has more than two states.

## 7. Verification statuses

A recipe's trust level is a graduated status, tracked precisely because
the six layers above are genuinely separate — collapsing them (as the
current binary "confirmed or not" `confirmed_patterns.json` shape
does) hides exactly which layer a recipe has and hasn't passed.

| Status | Reached when | Layer(s) satisfied |
|---|---|---|
| `AI_PROPOSED` | Generated by AI. Unchecked. | None yet. |
| `STRUCTURE_VALID` | Passed schema field/type validation **only** — required fields present, `stitch` is a known code, `count` is a positive integer. | Schema validation. **Not** plausibility — those are separate concepts (see section 6); a `STRUCTURE_VALID` recipe can still be implausible. |
| `MATH_VALID` | The foundation formula and each row's arithmetic are individually, internally valid. | Schema validation + mathematical validation. |
| `SIMULATION_VALID` | All configured test rows pass the computer's connected row-to-row simulation (`simulate_swatch()`). | Schema + math + connected-row simulation. |
| `SWATCH_TESTED` | A person **physically crocheted** the exact candidate and recorded the results — whether the attempt succeeded or failed. | Physical swatch testing (regardless of outcome). |
| `CONFIRMED` | Physical testing **succeeded**, and a human verified the result matches the intended stitch variation. | All six layers, including visual/human confirmation. |
| `REJECTED` | Failed, or was otherwise determined incorrect. The reason is preserved (`verification.reason`), whether that determination came from a failed physical swatch or from other sufficient evidence (e.g. structural comparison against an already-verified reference — see the known-bad example in section 8). | Varies — a rejection can be reached without a fresh physical swatch if existing evidence is sufficient, but it must always be *reasoned*, not silent. |

**AI and computer code must never advance a recipe beyond
`SIMULATION_VALID`.** Nothing at `STRUCTURE_VALID`, `MATH_VALID`, or
`SIMULATION_VALID` involves a human or a physical object — those are
all computer-checkable, and computer checks are exactly what an AI
pipeline can run on its own. `SWATCH_TESTED` and `CONFIRMED` both
require a real person to have actually made the stitches; no amount of
passing schema, math, or simulation checks can substitute for that.
This is also why a schema-valid recipe is not necessarily
crochet-correct, and a mathematically valid recipe is not necessarily
visually correct: those are exactly the gap between `STRUCTURE_VALID`/
`MATH_VALID`/`SIMULATION_VALID` and `CONFIRMED`.

## 8. Complete illustrative examples

Two separate example files exist, deliberately not one — see item 3 of
the first changelog for why blending them was a problem. **Both
represent recipe candidates for the same broad stitch-family label,
filet mesh — they are different candidates/constructions proposed for
that one family, not examples from different, unrelated stitch
families.** One happens to be structurally sound enough to demonstrate
the model; the other happens to be rejected. That contrast is the
point, not a claim that they're about different stitches.

**`contracts/examples/stitch_recipe_v2_structural_example.json`** is
the reference example for *shape*. It demonstrates every part of the
v2 hierarchy, including `counts_as`, using numbers grounded in this
project's own filet-mesh regression fixtures
(`tests/golden/halter_mesh_row1_*.json` — its `foundation_formula`
reproduces both fixtures' numbers exactly). Those fixtures document
expected engine behavior and real hand-crocheted observations — they
are **not** confirmed, authoritative crochet ground truth; they carry
their own unresolved discrepancy (see open question 1 below). Its
`verification.status` is still `AI_PROPOSED`: the *row-1* numbers trace
back to those fixtures, but the `later_rows` placement and `counts_as`
values are new v2 modeling choices layered on top, and those
specifically have not themselves been physically re-verified — the
file says so explicitly in its own `later_rows.note` field. **Its
purpose is to demonstrate the data model clearly, not to claim the
recipe as a whole is correct.**

**`contracts/examples/stitch_recipe_v2_known_bad_ai_example.json`**
preserves a real, actual API proposal (from
`data/confirmed_stitch_patterns.json`'s `filet mesh` entry) — a
*different construction proposed for the same filet-mesh label* than
the structural example above. Its `verification.status` is `REJECTED`,
not because it disagrees with golden-fixture arithmetic, but because
its row-1 repeat **conflicts with the specific target construction
being tested**: it lacks a per-repeat skipped foundation chain, so it
never opens the gap that construction's open mesh grid requires and
therefore cannot produce the intended structure. A `reason` and a
`known_issues` list record exactly what's wrong and how that was
determined — see the file itself for the precise wording, since it
deliberately does not claim that passing or comparing golden-fixture
arithmetic alone proves crochet truth. It exists as a regression
example — so this specific bad shape is recognizable if it's proposed
again — not as something to build on.

**Do not treat either file as `CONFIRMED`.** Neither has been through
physical swatch testing.

## 9. Two invalid or ambiguous examples

**Invalid example A — a foundation formula with `repeat_multiple: 0`.**

```json
{"foundation_formula": {"repeat_multiple": 0, "additional_chains": 5}}
```

This is schema-shape-valid (both fields are plain integers) and the
arithmetic evaluates fine — but `foundation_count` collapses to just
`additional_chains` regardless of `requested_repeat_count`. A repeat
that consumes nothing means the fabric never actually grows in width
no matter how many times you work it. This is the foundation-formula
equivalent of the flat-model bug `engine/plausibility.py`'s
`check_repeat_not_degenerate()` already catches (a repeat that consumes
0 stitches) — schema-valid, but crochet-nonsensical. It could reach
`STRUCTURE_VALID` and even `MATH_VALID` (the arithmetic is internally
consistent) without ever being sound — exactly why those two statuses
must not be conflated with correctness.

**Invalid example B — a `row_1` step with `placement: "next_chain_space"`.**

```json
{"row_1": {"repeat": [{"stitch": "DC", "count": 1, "placement": "next_chain_space"}]}}
```

`next_chain_space` is a real, recognized value from the vocabulary in
section 4 — so this is schema-valid in isolation. But row 1 has no
prior row, and chain spaces only exist once a row has actually been
worked and left floating chains behind. There is nothing for row 1 to
place into here; this placement is only legal on `later_rows`. This is
the concrete case behind the design rule "row-one placement and
later-row placement are different concepts" — the same enum value can
be valid in one row context and meaningless in another, so validating
`placement` requires knowing which row it appears in, not just
checking it against a flat list of allowed strings.

## 10. v1 → v2 field mapping

| v1 | v2 | Why it changed |
|---|---|---|
| `setup` (one flat step list, reused conceptually for "chain more" and "act on what exists") | `row_1.setup` (actions only) **+** `foundation_formula.additional_chains` (a count) | v1 conflated "how many more chains to physically make" with "what to do once they exist." v2 splits the chain-length contribution into the foundation formula and keeps only in-foundation actions (`SKIP`, working into an existing chain) in `row_1.setup`. |
| `repeat` (one list, reused for every row via `run_real_photo.py`'s `later_row = {"repeat": recipe["repeat"]}`) | `row_1.repeat` **and** `later_rows.repeat` (two separate lists) | Same stitch/count can need different `placement` depending on whether it's worked into the foundation (row 1) or into the previous row's output (later rows). One shared list can't represent that. |
| `turning_chain` (a bare step list) | `later_rows.setup` (steps, each with `placement: "turning_chain"` and an optional structured `counts_as`) | Same concept, now explicitly tagged instead of being a bare list whose role has to be inferred from its field name alone. |
| A turning chain represented as fake `DC 1, CH 1` steps to get the right `produces` total (see `main.py`'s `row_2`) | A single real `CH` step with `counts_as: {"stitch_posts": {...}, "chain_spaces": N}` | v1 had no way to say "this one action counts as both a stitch and a chain space" except by writing steps that didn't actually happen. v2's `counts_as` says it directly. |
| Row's own `repeat_count` (an AI's claimed number) | `requested_repeat_count` — an input to the foundation formula, supplied by the caller, never read from the AI | No behavior change in spirit — `engine/swatch.py` already never trusts an AI-claimed `repeat_count` for simulation. Phase 1 just names this input's role in the formula explicitly. |
| *(none)* | `pattern_id`, `name`, `aliases`, `terminology` | v1 had no stable identifier separate from the free-text `stitch_family` string used as `confirmed_patterns.json`'s dict key — no alias handling, no US/UK distinction. |
| *(none)* | `placement` (per step) | New. v1 steps carried no notion of where a stitch attaches. |
| *(none)* | `counts_as` (optional structured object per step) | New. |
| *(none)* | `expected_swatch_structure` | New — a place to declare expected per-repeat stitch-post/chain-space counts once known, for reconciling against a future physical hand-count. |
| `confirmations` (list, inside a `confirmed_patterns.json` entry) | `verification.confirmations` | Same shape and purpose, now nested under a formal `verification` block. |
| *Implicit*: "confirmed" meant `confirmations` was non-empty; nothing in between | `verification.status`, a 7-value graduated enum, plus `MATH_VALID`/`SIMULATION_VALID` separated from `SWATCH_TESTED`/`CONFIRMED` | v1 only distinguished confirmed vs. not, and never distinguished "the computer checked this" from "a person actually made it." v2 makes that boundary explicit and names every layer between. |
| *(none)* | `verification.reason` | New — present when `status` is `REJECTED`, so a rejection is always traceable to a specific, recorded cause. |

## 11. Questions that must be resolved through physical crochet testing

1. **Does the row-1 lead-in "count as" the first DC**, the same way a
   later-row turning chain conventionally does? This is the leading
   hypothesis for the real, still-open discrepancy logged in
   `data/concierge_log.csv`: a hand-crocheted swatch produced 5 DC
   where the flat model predicted 4 — a consistent off-by-one that a
   missing `counts_as` on the row-1 lead-in would fully explain.
2. **Is the structural example's turning-chain `counts_as` value
   correct** — `{"stitch_posts": {"DC": 1}, "chain_spaces": 1}` for a
   `ch-4` — or does the real halter-mesh pattern's turning chain count
   differently? The pre-v2 code's `DC 1, CH 1` hack encodes the same
   claim, but neither has been physically re-verified under this exact
   framing.
3. The structural example's `later_rows.repeat` DC is now modeled as
   `next_dc` (worked into the previous row's DC stitch), matching the
   intended "CH 1, then DC into the next DC" instruction — but is that
   actually the right placement, or should it have been
   `next_chain_space` after all? And if the turning chain's `counts_as`
   still declares `chain_spaces: 1`, but nothing in this repeat is ever
   placed `next_chain_space`, **does that declared chain space mean
   anything**, or was `chain_spaces: 1` a leftover assumption that
   needs revisiting now that the repeat's DC is modeled as `next_dc`?
   Neither question is resolved by this document.
4. Can `next_dc` legally resolve to a stitch that only exists because
   of a `counts_as` (a turning chain standing in for a DC), or does
   `next_dc` mean a *literal* DC stitch only?
5. Is an empty `row_1.setup` ever actually correct for a DC-based
   repeat (as one real photo-run region proposed), or does every
   DC-based repeat require at least a 1-chain-equivalent skip lead-in
   on row 1, with no legitimate exception?
6. Is the known-bad example's rejection basis (conflicting with the
   specific open-grid target construction by lacking a per-repeat SKIP)
   actually sufficient, or could there exist a legitimate filet-mesh
   variant that genuinely has no per-repeat skip? Phase 2 should not
   assume the rejection reasoning in section 8 is beyond question just
   because it's already recorded.

None of these are answered by this document — they are exactly what
Phase 1 is supposed to surface clearly enough to go test by hand,
rather than continue guessing around in code. **Phase 2 must not guess
at any of these** — each requires either a physical swatch or an
explicit, separate decision recorded the way section 7 requires.

## Phase 3: the foundation calculator

`engine/foundation.py`'s **`calculate_foundation(recipe, requested_repeat_count)`**
implements the formula from section 2, exactly as designed there:

```
foundation_count = repeat_multiple * requested_repeat_count + additional_chains
```

**Its two inputs**: a complete v2 recipe dict, and `requested_repeat_count`
— a plain positive int the *caller* chooses. It is never read from the
recipe itself (there is no `repeat_count` field anywhere in the v2
shape), the same way `engine/swatch.py`'s older, unrelated
`build_test_foundation()` already never trusts an AI-claimed repeat
count for the v1 pathway.

**Its returned breakdown** is a dict with five keys: `repeat_multiple`,
`requested_repeat_count`, `repeated_chains` (`repeat_multiple *
requested_repeat_count`), `additional_chains`, and `foundation_count`
(`repeated_chains + additional_chains`) — every number that went into
the result, not just the final total.

**Calculating a recipe whose `verification.status` is `REJECTED` or
`AI_PROPOSED` does not establish crochet correctness.**
`calculate_foundation()` only requires that the recipe pass
`validate_recipe_v2()` (structural shape) — it does not look at
`verification.status` at all. The known-bad example
(`contracts/examples/stitch_recipe_v2_known_bad_ai_example.json`)
calculates to `foundation_count: 9` for 6 repeats exactly like any other
structurally valid recipe would; that number is an honest evaluation of
its stored formula, not a claim that the recipe describes real filet
mesh — it remains `REJECTED`, for the reasons in section 8, regardless
of what any calculation on it produces.

**This module is not connected to the production photo pathway yet.**
`run_real_photo.py`, `engine/vision.py`, and `engine/swatch.py`'s own
v1 `build_test_foundation()` are all unchanged and untouched by this
addition. Nothing yet compares `calculate_foundation()`'s result against
what `row_1` actually consumes — that comparison, and everything about
typed stitch positions, the swatch planner, and physical confirmation,
is later-phase work this document does not cover.

## Phase 4A: row-1 math validation

`engine/recipe_validator.py`'s **`validate_row_1_against_foundation(recipe, requested_repeat_count)`**
is the first place two independent declarations get compared: what
`calculate_foundation()` says the foundation contains, and what `row_1`'s
own setup/repeat instructions actually account for.

**Exact accounting, not `<=`.** Row 1 must consume *exactly*
`foundation_count` — not merely fit within it. `engine/swatch.py`'s v1
pathway (and `engine/validator.py`'s `check_full_row()`) accept `consumed
<= available`, because that model is checking whether a claimed row
*fits* a foundation whose size came from somewhere else. Phase 4A is
answering a narrower, stricter question — does the formula and row_1
*agree* — so any gap in either direction is reported: `unused_foundation_positions`
when row_1 consumes less than the formula provides, `overdrawn_foundation_positions`
when it needs more.

**Typed production**, returned as `{"stitch_posts": {<CODE>: <int>,
...}, "chain_spaces": <int>, "total_workable_positions": <int>}` for
`setup`, `repeat_once`, `repeat_total`, and the combined `row_1`. `INC`/
`DEC` are filed under their own code (e.g. `{"INC": 2}`) rather than a
guessed real stitch family — Phase 4A does not invent what an increase's
resulting posts "really" are. `counts_as` is never consulted here: schema
v2 doesn't permit it on `row_1` at all.

**The known-bad example, concretely**: for 6 repeats its formula gives
`foundation_count: 9`, but its `row_1` (setup `SKIP 1` = 1, repeat `DC 1,
CH 1` ×6 = 6) only accounts for `7` — `valid: False`, with `"Row 1
accounts for 7 of 9 foundation positions; 2 positions are unexplained."`
in `errors`. **This does not change `verification.status`.** The recipe
was already `REJECTED` for the reasons in section 8; this is a second,
independent piece of evidence against it, not a new decision this module
makes — a `True` result never means `CONFIRMED` either, and nothing here
writes to `verification` at all.

**`same_stitch`, in this limited model**: it consumes zero additional
foundation positions (it reuses whatever position the immediately
preceding *placing* step targeted, rather than advancing). A
`working_loop` chain in between does not clear that target — a floating
chain hung off the working loop never touches the foundation, so it has
no reason to erase the position a stitch most recently placed into. For
example, `DC next_foundation_chain` → `CH working_loop` → `DC
same_stitch` is valid: the final `DC` refers back to the same foundation
chain the first `DC` did, consuming exactly 1 foundation position while
producing 2 DC posts + 1 chain space (3 total workable positions). Two
combinations Phase 4A still refuses to guess at, raising
`RecipeMathError` instead of a report: `same_stitch` with nothing before
it that placed a stitch, and `same_stitch` on a `SKIP` (skipping doesn't
work into a stitch, so there's no "same stitch" to mean).

**Target state flows across the row's whole real execution order, not
just within one list.** `row_1.repeat` is executed *sequentially*,
`requested_repeat_count` times — never analyzed once and multiplied. The
first pass picks up the target `setup` leaves behind; each subsequent
pass picks up the target the *previous pass* left behind, not whatever
`setup` originally left. This matters whenever one pass's last placing
step (or a trailing `SKIP`, which clears the target) leaves a different
target state than the pass started with: a `same_stitch` that opens the
next pass must see that carried-forward state, and an implementation
that analyzed `repeat` once and multiplied the result would miss a case
where only a later pass becomes invalid. `consumed_foundation_positions`
and `produced_structure` accumulate the same way — pass by pass — for
`repeat_total`; `repeat_once` always reports the first pass specifically
(the one whose target came from `setup`).

**Later-row typed validation is not implemented.** `later_rows` is not
touched by this function at all — turning-chain interpretation, whether
`next_dc` passes over chain spaces, whether a `counts_as` DC can be
targeted by `next_dc`, and connected multi-row simulation over the typed
model remain exactly as unresolved as section 11 leaves them. That is
Phase 5, covered next.

## Phase 5: typed later-row validation

`engine/later_row_validator.py`'s **`validate_recipe_rows(recipe,
requested_repeat_count, later_row_count)`** validates a chain of rows —
row 1, then `later_row_count` later rows — each one fed the row
before it's ACTUAL typed output, never a claimed or assumed number.
Row 1 itself is delegated wholesale to Phase 4A's
`validate_row_1_against_foundation()`, not reimplemented.

**Typed AND ordered, never a total, and never an unordered per-type
count either.** This is the central rule the whole module exists to
enforce, in two layers. First: a previous row containing 6 DC posts + 6
chain spaces is NOT the same input as a row containing 12 DC posts + 0
chain spaces, even though both sum to 12 "workable positions" — a
`next_dc` step needs a DC post specifically; a `next_chain_space` step
needs a chain space specifically; neither substitutes for the other.
Second, and just as important: two rows can have IDENTICAL typed totals
and still be different inputs. A row that produced "DC, chain space,
SC" is not the same sequence as one that produced "SC, chain space,
DC," even though both are `{"stitch_posts": {"DC": 1, "SC": 1},
"chain_spaces": 1}`. `next_stitch`, `next_dc`, `next_chain_space`, and
`SKIP` are TRAVERSAL instructions — "the next one, moving forward" — a
question an unordered per-type count cannot answer at all. Every row's
actual production is therefore kept as an **ordered list** of small
target entries (`{"kind": "stitch_post"|"chain_space", "stitch":
<code>|None, "source": "literal"|"counts_as"}`, one per physical
position, in real left-to-right order — see `engine/recipe_validator.py`
and `engine/later_row_validator.py`'s module docstrings for the exact
shape), walked with a single forward-only cursor. The aggregate
`produced_structure` dict still exists, for summaries and for
`expected_swatch_structure`-style comparisons, but it is now a
**projection derived from the ordered list**, never an independent fact,
and traversal logic never reads it.

**Resolved placement semantics, via the ordered cursor** (the full
reasoning for each is in `engine/later_row_validator.py`'s module
docstring; summarized here):

- **`turning_chain`** never touches the input cursor at all (it
  consumes nothing from the previous row — CH always consumes 0). With
  `counts_as`, it REPLACES this step's own contribution entirely — the
  ordered output gains exactly `counts_as.stitch_posts` and
  `counts_as.chain_spaces` worth of entries (each tagged `source:
  "counts_as"`), not those numbers *plus* the raw CH production (a real
  "ch 4" turning chain is one edge, not 4 separate chain spaces; adding
  both would double-count, contradicting section 5's own "changes how
  many stitch posts and chain spaces this step is credited with
  producing"). Without `counts_as`, it behaves exactly like a bare
  `working_loop` chain: raw `produces × count` "literal" chain-space
  entries, no stitch-post credit. It establishes a new target only when
  `counts_as` declares something positive; otherwise it preserves
  whatever target already existed — the same rule Phase 4A already
  applies to bare `working_loop` chains.
- **`next_stitch`** is a forward search from the input cursor for the
  next entry whose kind is `stitch_post`, regardless of code or source.
  Every entry the search passes over — a chain space, or a stitch post
  of a type this step didn't ask for — moves BEHIND the cursor and can
  never be targeted as "next" again, by this step or any later one in
  this row or a subsequent row: crochet doesn't work backward across a
  row. Nothing here is decided by alphabetical order or any other
  unordered tie-break; it is decided purely by position. (An earlier
  version of this module picked among same-type candidates via
  `sorted(pool)` on an unordered dict — that was never valid crochet
  traversal and has been replaced entirely by this cursor walk; see the
  fourth correction pass in the changelog.) No matching entry anywhere
  ahead of the cursor is a reported failure, never a silent chain-space
  grab.
- **`next_dc`** is a forward search from the input cursor for the next
  entry whose kind is `stitch_post` and stitch is `DC` specifically —
  SC, HDC, and chain spaces are never matched no matter how close to
  the cursor they sit; they are passed over (and lost) like anything
  else not being searched for. If the found entry's source is
  `"literal"`, it's consumed and the result is unambiguous. If its
  source is `"counts_as"`, `validate_recipe_rows()` REFUSES TO GUESS and
  raises `RecipeMathError` — not even by skipping ahead to search for a
  LATER literal DC, since that would itself be a guess about whether the
  counts_as one may be passed over. Whether `next_dc` may legally
  resolve to a stitch that exists only because of `counts_as` is exactly
  open question 4 in section 11, and is not decided here either way. If
  no DC entry exists anywhere ahead of the cursor, that's a plain,
  reported shortfall.
- **`next_chain_space`** is a forward search from the input cursor for
  the next entry whose kind is `chain_space`. None found ahead of the
  cursor is a reported failure. Multiple stitches worked into the SAME
  chain space are one `next_chain_space` step (which moves the cursor
  past that one entry) followed by `same_stitch` steps (which do not
  move the cursor again).
- **`same_stitch`** never moves the input cursor and never searches
  anything; it requires only that a target was already established
  earlier in this row's continuous processing (raises `RecipeMathError`
  if not) and is forbidden on a SKIP step (raises `RecipeMathError`) —
  both exactly as Phase 4A already established for row 1. An
  intervening `working_loop` (or a counts_as-less `turning_chain`) does
  not clear the remembered target.
- **`SKIP`** performs the exact same forward search and cursor advance
  that placement would for any other stitch (including `next_dc`'s
  counts_as-eligibility check — skipping an ambiguous position is
  exactly as unresolved as stitching into it), produces no new ordered
  entry, and clears the established target afterward — identical to how
  Phase 4A treats a `next_foundation_chain` SKIP on row 1. SKIP with
  `same_stitch` remains invalid.

**A later row's own ordered output, and the TURN before it becomes the
next row's input.** Every row's `setup_result` and `repeat_result` each
carry their own `ordered_output`; concatenated (setup's entries first,
then every executed repeat pass's in order), they form the row's own
`ordered_output` — always in that row's actual production order, never
reversed or reinterpreted, so it can always be read as "left to right,
as this row was worked" regardless of which row it came from.
`output_structure` (the aggregate summary) and
`output_counts_as_stitch_posts` (the counts_as-only slice, so a later
`next_dc` several rows down can still tell literal DC apart from
counts_as-derived DC) are both projections computed from that ordered
list, never tracked independently of it.

Flat crochet turns the work at the end of every row: you finish
left-to-right, flip the fabric over, and the next row is worked
right-to-left relative to the piece — so the first target the next
row's cursor meets is the LAST one the previous row produced, not the
first. `validate_recipe_rows()` performs exactly this reversal, once,
whenever it hands one row's finished output to the next row: a row's
`ordered_input` is `list(reversed(previous_row["ordered_output"]))`, a
brand-new list built fresh at that hand-off — never the previous row's
`ordered_output` reused as-is, and never mutated in place (reversing
twice would silently model turning back over two edges, i.e. not
turning at all, so each hand-off reverses exactly once). Concretely: if
row 1 produces `[DC, chain_space, SC]` (in that order), row 2 receives
`[SC, chain_space, DC]` — a `next_stitch` step in row 2 therefore lands
on the SC first, not the DC, even though the DC was produced first. Row
3 then receives `reversed(row 2's ordered_output)`, and so on for every
row after that.

**This validator supports flat, turned rows only.** Crochet also has
continuous-round construction (worked in a spiral, never turned, so the
next round continues in the SAME direction the previous one finished
in rather than reversing). Schema v2 has no field anywhere recording
whether a recipe is flat or worked in continuous rounds — there is
nothing in a recipe dict this module could inspect to tell the two
apart. Rather than guess which behavior a given recipe wants, this
module always applies the flat-row turn described above; a recipe
actually intended as continuous rounds will be validated as if every
row were turned, which is not correct for that construction, and this
module has no way to detect that mismatch from the data available to
it today. Supporting continuous rounds for real would require a new
schema field (e.g. a `construction` enum of `"flat"` / `"round"`) this
validator could branch on — until that field exists, "flat, turned
rows" is stated explicitly as Phase 5's only supported construction,
not silently assumed.

**Later-row repeat count is DERIVED BY WALKING THE CURSOR, never
assumed, and never computed by subtracting unordered per-type totals.**
Unlike row 1 (whose repeat count is `requested_repeat_count`, an
explicit caller choice), the v2 schema has no field stating how many
times `later_rows.repeat` should run. `validate_recipe_rows()` derives
it by actually running `later_rows.repeat`, pass after pass, moving the
SAME forward-only cursor across the row's ordered input each time,
until a pass can no longer complete — the number of passes that DID
complete is `repeat_execution_count`. This is never assumed to equal
`requested_repeat_count`, even though a well-formed recipe will
typically make them equal by construction, and it is deliberately never
computed by dividing an unordered pool size by a per-pass consumption
count — that would silently throw away exactly the position information
this redesign exists to keep (a per-type division can't know that a
later pass's `next_dc` needs to pass over an intervening chain space it
hasn't reached yet). If `later_rows.repeat` never moves the cursor at
all (every step is `same_stitch`/`working_loop`), nothing constrains
how many times it could run; that row's `repeat_count_derivable` is
reported `False` with a clear message, never a guessed number.
**Resolving this for real would require a new field the current schema
doesn't have** — e.g. an explicit `later_rows.repeat_count` the AI must
state, or a declared per-repeat consumption contract this validator
could check claims against — see `engine/later_row_validator.py`'s
module docstring for the same statement in code.

**Leftover input is reported, not automatically invalid — but "leftover"
now means the SUFFIX after the final cursor position, not merely
anything untouched by type.** Unlike row 1 vs. the foundation formula
(which must describe the exact same physical chain, so any gap either
direction is an error), a later row legitimately may not target
everything the row before it produced — a real filet-mesh repeat's "dc
in next dc, ch 1" passes right over the previous row's chain space by
design, leaving it as the mesh's open hole rather than something to
consume. `remaining_unused_input_targets` reports this honestly without
deciding it's wrong. Because the cursor only ever moves forward, an
entry the cursor passed OVER while searching for something else (rather
than reaching the tail end untouched) is already gone by the time the
row finishes — it is not reported as "remaining" even though no step
ever explicitly claimed it; see
`tests/test_later_row_validator.py`'s `OrderMattersTests` for a
concrete pair of recipes with identical row-1 totals whose row-2
leftovers differ purely because of this. What DOES make a later row
invalid is `attempted_overdraw`: `later_rows.setup` demanding more of
some type than exists ahead of the cursor, or `later_rows.repeat`
failing to complete even a single pass against the actual input (there
is no notation in this recipe model for "run this later row's repeat
zero times on purpose," so that is always reported as a genuine
mismatch, not a benign leftover).

**Stops at the first invalid row.** If row 1 is invalid, no later row
is ever evaluated (`first_failing_row: 1`, `later_rows: []`). If a
later row fails, every row after it is left unevaluated —
`later_rows` in the returned report contains only the rows actually
attempted, up to and including the failing one.

**`verification.status` is never touched**, exactly like Phase 4A: a
`True` result here does not make a recipe `CONFIRMED` (or even
`SIMULATION_VALID` — this module writes to `verification` nowhere at
all), and a `False` result does not mutate it to `REJECTED`. This
function only reports evidence.

**What remains explicitly unresolved, not guessed at:** the
`next_dc`/counts_as eligibility gap (raises `RecipeMathError`, citing
open question 4) and the later-row repeat-count derivation when the
repeat touches neither pool (`repeat_count_derivable: False`, citing
the missing schema field above) — see
`tests/test_later_row_validator.py`'s `NextDcCountsAsAmbiguityTests`
and `AmbiguousRepeatCountTests` for concrete, hand-checkable examples of
both.

## Phase 6: trusted recipe library and recipe resolution

`engine/recipe_library.py` stores validated v2 recipes and safely
resolves an AI-proposed stitch (a name/aliases claim plus untrusted
instructions) against them. **This library is generic** — every
function operates on the v2 shape and a name/alias lookup any stitch
family can use; nothing about filet mesh, or any other specific stitch,
is hard-coded into it. The structural and known-bad examples in
`contracts/examples/` remain illustrative fixtures, never entries this
module trusts by name.

### Why mathematical validity is not physical confirmation

Schema validity, foundation math, Phase 4A's row-1 check, and Phase 5's
later-row check are all still purely computer-checkable layers (section
6) — none of them involve a human or a physical object. A recipe can
pass every one of them and still describe the wrong stitch, or the
right stitch worked the wrong way. `engine/recipe_library.py` never
promotes a recipe's `verification.status`; it only ever *reads* it.
Nothing in this module runs `calculate_foundation()`,
`validate_row_1_against_foundation()`, or `validate_recipe_rows()` at
all — attaching that evidence is left to whatever calls this module
(Phase 7), once there's an actual `requested_repeat_count`/
`later_row_count` to run those validators against; duplicating that
logic here, or guessing those numbers, is exactly the kind of invention
this project has consistently refused to do at each prior phase.

### How recipes enter the library

`data/confirmed_stitch_recipes_v2.json` is a **new, separate** file —
`{"schema_version": "2.0.0", "recipes": [...], "notes": "..." (optional)}`
— never the older, flat `data/confirmed_stitch_patterns.json` (see the
comparison below). `load_recipe_library()` reads it, parses it, and
validates it as a whole via `validate_recipe_library()`:

- the top level accepts only `schema_version`, `recipes`, and the
  optional `notes` — any other top-level field is rejected outright,
  the same closed-shape discipline
  `contracts/stitch_recipe_schema_v2.json` already applies to every
  object inside a v2 recipe (`additionalProperties: false`);
- `schema_version` is required, must be a string, and must equal
  exactly `"2.0.0"` (`LIBRARY_SCHEMA_VERSION`) — a missing, non-string,
  or different value is rejected; this module never guesses how to
  read a library format it wasn't written for;
- `notes`, if present, must be a non-empty string;
- `recipes` is required and must be a list, and every entry must
  independently pass `validate_recipe_v2()`, with no two entries
  sharing a `pattern_id` and no two entries' normalized name/alias sets
  overlapping.

Any failure — bad JSON, an unexpected top-level field, a missing or
unsupported `schema_version`, one malformed recipe among many, a
duplicate `pattern_id`, an ambiguous shared alias — raises
`RecipeLibraryError` naming exactly what's wrong; nothing is silently
dropped or skipped to make the rest of the file "still work." **An
empty `recipes` list is a valid, ordinary result**, distinct from a
library that fails to load at all — the production file ships empty
because no v2 recipe has actually been physically confirmed yet; that
is the honest state, not a placeholder to be filled with an invented
confirmation.

### Trust boundary: a directly-supplied library is validated too

`find_recipe_by_pattern_id()`, `find_recipe_by_name()`, and
`resolve_stitch_recipe()` all accept a `library` argument directly, not
only the real file `load_recipe_library()` reads. A library passed in
this way is **not** assumed to have already gone through
`validate_recipe_library()` — a hand-built or externally-supplied dict
could otherwise claim `verification.status == "CONFIRMED"` on a recipe
that never actually passed `validate_recipe_v2()`, or hide a duplicate
`pattern_id` behind a "first match wins" lookup, and be selected as
trusted output without ever being checked.

Every one of those three functions therefore runs the supplied library
through `validate_recipe_library()` (via the shared internal
`_load_or_validate_library()` gate) **before** doing anything else with
it, and raises `RecipeLibraryError` — the exact same exception,
constructed the exact same way, `load_recipe_library()` raises for a
broken file — if it fails. This is unconditional: there is no code path
in this module that reaches `is_recipe_trusted()`, a name/alias match,
or `selected_recipe` using a library that hasn't passed validation.
`resolve_stitch_recipe()` validates its library exactly once per call
(not once per lookup term, via private `_find_recipe_by_pattern_id_in()`/
`_find_recipe_by_name_in()` helpers that assume an already-validated
library); `find_recipe_by_pattern_id()` and `find_recipe_by_name()`
remain the safe, independently-validating **public** entry points for
any other caller — they are not downgraded to "unsafe" helpers, since
they are documented public library operations.

### Name and alias normalization

`normalize_stitch_name()` is the one normalization function every
lookup in this module uses: trim, casefold, collapse every run of
hyphens/underscores to a single space, collapse every run of remaining
whitespace to a single space, trim again. `"Filet Mesh"`, `"filet
mesh"`, `" FILET   MESH "`, `"filet-mesh"`, and `"filet_mesh"` all
normalize to `"filet mesh"`. This is exact string normalization only —
never fuzzy matching, stemming, or plural handling, and it never
decides that "mesh," "open mesh," and "filet mesh" are the same stitch
on its own; two terms only resolve to the same recipe when that
recipe's own `name`/`aliases` explicitly declares both.

### Trusted versus untrusted lookup

`is_recipe_trusted(recipe)` is `True` only when `verification.status`
is exactly `"CONFIRMED"` — the one status in the existing 7-value v2
vocabulary (section 7) meaning a person physically crocheted the exact
candidate **and** a human verified the result matches the intended
stitch. Every other status, deliberately including `SWATCH_TESTED`
(a physical attempt happened, but section 7 is explicit that this
doesn't mean it matched — "whether the attempt succeeded or failed"),
returns `False`. The library can still load and hold `AI_PROPOSED`,
`STRUCTURE_VALID`, `MATH_VALID`, `SIMULATION_VALID`, `SWATCH_TESTED`,
and `REJECTED` entries for review, comparison, or future confirmation —
`load_recipe_library()` doesn't filter by status at all — but
`resolve_stitch_recipe()`'s `trusted` field and `selected_recipe`
always distinguish them clearly from a `CONFIRMED` one.

### How AI proposals are resolved

`resolve_stitch_recipe(ai_proposal, library=None)`:

1. Validates `ai_proposal` with `validate_recipe_v2()`. A structurally
   invalid proposal short-circuits as `invalid_ai_proposal` immediately
   — nothing is looked up, since its `pattern_id`/`name`/`aliases`
   can't be trusted to mean what they claim.
2. Searches the library deterministically: `pattern_id` first (via
   `find_recipe_by_pattern_id()`), then `name`, then every declared
   alias (each via `find_recipe_by_name()`), recording every attempted
   term in `lookup_terms` regardless of outcome.
3. Every recipe any of those terms matched is collected (deduplicated
   by `pattern_id`). Zero matches → `no_match`. More than one distinct
   recipe matched → `ambiguous_match`, naming every conflicting
   `pattern_id` — this function never guesses which one the AI "must
   have meant" (`find_recipe_by_name()` itself returns every match it
   finds, never just the first, for exactly this reason).
4. Exactly one matched recipe → `trusted_match` if
   `is_recipe_trusted()` is `True` for it, otherwise `untrusted_match`.

### Why trusted recipes override AI instructions

For `trusted_match`, `selected_recipe` is set to the **library**
recipe unconditionally — never the AI's own instructions, even when
`compare_recipe_proposal()` finds they agree exactly. The library
recipe overrides by construction (it is the one recipe with actual
physical confirmation behind it), not by comparison outcome; the AI
proposal is preserved unmodified in the result's `ai_proposal` field
purely for comparison and diagnostics. `ai_proposal_usable_for_user_
instructions` is always `False` — Phase 6 has no mechanism by which a
fresh AI proposal itself becomes trusted output, stated outright rather
than left for a caller to infer.

### What happens when no trusted recipe exists

`no_match`: `selected_recipe` and `provenance` both stay `None`; the AI
proposal is returned as unverified candidate data only, never marked
physically confirmed, and no final user-facing instructions are
generated from it here. `untrusted_match` behaves the same way for
`selected_recipe`/`provenance` — a library entry existing under that
name is not itself permission to use it as trusted output; only
`is_recipe_trusted()` being `True` is. `ambiguous_match` also leaves
`selected_recipe` `None`, listing every conflicting `pattern_id` in
`conflicting_pattern_ids` instead of picking one.

### Structural comparison

`compare_recipe_proposal(ai_recipe, library_recipe)` reports agreement
and disagreement only — it never decides which recipe (if either) is
physically correct. It compares `pattern_id`; normalized name and
alias sets; `foundation_formula.repeat_multiple` and
`.additional_chains`; `row_1.setup`, `row_1.repeat`,
`later_rows.setup`, and `later_rows.repeat` **index by index** (a
length mismatch is reported in addition to, not instead of, comparing
every index the two lists share, so a reordering is never hidden
behind matching totals); each step's `stitch`/`count`/`placement`/
`counts_as`; and both `expected_swatch_structure` fields. Every
difference names its exact path — `foundation_formula.repeat_multiple`,
`row_1.repeat[1].placement`, `later_rows.setup[0].counts_as` — never
just "these differ somewhere."

### v1 vs. v2 confirmed-pattern systems (unrelated, not migrated)

`engine/confirmed_patterns.py` and `data/confirmed_stitch_patterns.json`
are a different, older system this phase does not touch, extend, or
migrate. v1 keys a flat dict by one normalized "stitch family" string
and stores three bare step lists (`setup`/`repeat`/`turning_chain`)
with no `placement`, no `counts_as`, no `pattern_id`/`aliases`, and a
binary confirmed-or-not distinction. v2 (this module) stores complete
schema-valid recipe objects — with `placement`, `counts_as`, a
foundation formula, `row_1` vs. `later_rows`, and the graduated 7-value
`verification.status` — in a list, looked up by `pattern_id` or by
normalized name/alias, with an explicit trust predicate rather than a
bare non-empty check. `data/confirmed_stitch_patterns.json`'s two
existing entries (`"filet mesh"`, `"single crochet"`) both have empty
`confirmations` lists — neither is actually confirmed there either, so
there is nothing to migrate even in spirit. This phase reads and writes
only `data/confirmed_stitch_recipes_v2.json`.

### What remains for Phase 7

`resolve_stitch_recipe()` decides WHICH recipe (library or AI) should
be used; it never runs the math/simulation validators against it.
Attaching that evidence (`calculate_foundation()`,
`validate_row_1_against_foundation()`, `validate_recipe_rows()`) once a
caller has an actual repeat count to test against, generating real
swatch/pattern output from `selected_recipe`, and the confirmation
workflow that would ever move a stored recipe to `CONFIRMED` in the
first place, are all Phase 7 (and later) work, not covered here.

## Phase 7: trusted swatch planner and user-facing renderer

`engine/swatch_planner_v2.py`'s **`plan_trusted_swatch(ai_proposal,
requested_repeat_count, later_row_count, library=None)`** connects
Phase 6's resolution and Phase 5's full row simulation into one
pipeline: it either returns a complete, evidence-backed swatch plan
with rendered instructions, or refuses clearly and explicitly — never a
half-finished result someone could mistake for a usable pattern. This
phase begins with an already-structured AI proposal (the same v2
recipe shape Phase 6 already validates); it does not receive or
analyze an image.

### The pipeline

```
AI recipe proposal
    ↓
Phase 6 recipe resolution (resolve_stitch_recipe())
    ↓
require status == trusted_match; use ONLY selected_recipe
    ↓
Phase 5 full row simulation (validate_recipe_rows(), on selected_recipe)
    ↓
require valid simulation
    ↓
build swatch plan (from selected_recipe + the validators' own results)
    ↓
render instructions (engine/renderer_v2.py, a separate module)
```

Every field of the eventual plan comes from `resolution["selected_recipe"]`
(the LIBRARY recipe) and the validators' own results — never from
`ai_proposal`. If resolution is anything other than `trusted_match`,
the pipeline stops there; it never falls back to rendering the AI's own
proposal as if it were trustworthy output, even when the AI's numbers
happen to look plausible.

### Explicit outcomes, never collapsed into one generic error

`plan_trusted_swatch()` returns one of: `ready`, `no_trusted_recipe`,
`ambiguous_recipe`, `invalid_ai_proposal`, `invalid_library`,
`simulation_failed`, `simulation_unsupported`, `invalid_request`, or
`render_unsupported` (added because Phase 6/5's outcome vocabulary had
no name for "everything passed except the trusted recipe's own
terminology isn't one the renderer implements" — see PART 6 below).
`resolve_stitch_recipe()`'s `untrusted_match` and `no_match` both
collapse to `no_trusted_recipe` at this layer — a library entry
existing under the identified name is not itself permission to use it;
only `trusted_match` is — but the full `resolution` dict (including
`matched_recipe` and its comparison against the AI proposal) is still
returned for diagnostics either way. For every non-`ready` outcome,
`ready_for_user_instructions` is `False` and `rendered_instructions` is
`None`, unconditionally.

`RecipeLibraryError` (an invalid library, default or directly supplied)
and `RecipeMathError` (one of Phase 4A/5's "refuses to guess" semantic
cases, e.g. a `same_stitch` with no established target) are both caught
here and turned into `invalid_library`/`simulation_unsupported`
results respectively — never an uncaught traceback for an expected
failure mode. An ordinary math mismatch `validate_recipe_rows()`
reports as `valid: False` (rather than raising) becomes
`simulation_failed`, carrying the full row-validation report so a
caller can see exactly which row failed.

### The structured swatch plan

Built only from `selected_recipe` and the validators' own results,
never from `ai_proposal` — every step list embedded in it
(`row_1_setup`, `row_1_repeat`, `later_row_setup`, `later_row_repeat`)
is a deep copy of the trusted recipe's own data, so mutating a returned
plan can never reach back into the library recipe it came from. It
records `pattern_id`, display `name`, `terminology`, trust/provenance,
`requested_repeat_count`, `total_rows`, the foundation chain count and
full formula breakdown, row 1's setup/repeat steps and its repeat
execution count (`requested_repeat_count` itself — row 1's repeat count
is always the caller's explicit choice, never derived), each later
row's own setup/repeat steps and its *actual derived*
`repeat_execution_count` (from Phase 5's cursor walk, never assumed
equal to `requested_repeat_count`), summarized validation evidence, and
warnings. **It never claims a physical measurement** ("four inches" or
otherwise) — a warning states this explicitly on every ready plan;
relating repeat count to gauge/physical width is not implemented at
this phase.

### The renderer does exactly one job

`engine/renderer_v2.py`'s **`render_swatch_plan(plan)`** accepts only
an already-built structured plan and translates it into words. It does
not resolve recipes, perform validation, calculate foundation math,
read the library, or decide trust — those are Phases 4A/5/6's jobs,
already done by the time a plan exists at all. This mirrors why
`engine/renderer.py` (v1) is untouched and unrelated: v1 renders a
flat, placement-less step shape with no `placement`/`counts_as`
concept to translate, so its wording (e.g. "double crochet in the next
stitch" unconditionally) is insufficient for v2, where the same `DC`
step might be worked `next_foundation_chain`, `same_stitch`, `next_dc`,
or `next_chain_space` — each needing different, precise wording.

**`render_swatch_plan()` validates its own argument before reading a
single field from it — and that validation enforces the INTERNAL
READINESS CONTRACT strongly, not merely "does it have the right keys."**
`plan_trusted_swatch()`'s `_build_swatch_plan()` only ever runs after
resolution and simulation have both succeeded, and every plan it
returns now carries `"ready_for_rendering": True` — a plan's own claim
that it was built that way. `render_swatch_plan()` does not simply
trust that claim by skipping straight to reading fields, though: it
checks the WHOLE plan's shape first (a dict; `ready_for_rendering`
present and exactly `True`; every other required field present; step
lists whose steps each have a known stitch code, a valid `count`, and a
placement that is both a known v2 placement AND legal in that specific
section (see NESTED-STEP VALIDATION below); later-row summaries;
repeat counts) — `render_swatch_plan(None)`, `render_swatch_plan([])`,
`render_swatch_plan({})`, and `render_swatch_plan({"terminology": "US"})`
all return `{"status": "invalid_plan", "text": None, "warnings": [],
"errors": [...]}` rather than raising.

**NESTED-STEP VALIDATION is CONTEXT-AWARE, not just "does the stitch
and placement each exist somewhere in v2."** `row_1_setup` and
`row_1_repeat` are checked against `ROW1_PLACEMENTS`; `later_row_setup`
against `LATER_SETUP_PLACEMENTS`; `later_row_repeat` against
`LATER_REPEAT_PLACEMENTS` — the exact same context-restricted sets
`validate_recipe_v2()` itself enforces, imported unmodified from
`engine/schema.py` rather than re-invented. `{"stitch": "CH", "count":
1, "placement": "next_dc"}` inside `row_1_repeat` is rejected on two
independent grounds: `next_dc` isn't in `ROW1_PLACEMENTS` at all, AND a
CH step may only ever use `working_loop` or `turning_chain`, regardless
of section. `{"stitch": "DC", "count": 1, "placement": "turning_chain"}`
is rejected the same way in every section — including
`later_row_setup`, where `turning_chain` itself is otherwise a legal
placement value, because a non-CH stitch must never use it. Each step's
`counts_as` (if present) is fully validated before anything reads it:
an object (never a string, list, or anything else); allowed only when
the step is CH with placement `turning_chain`; `stitch_posts` an
object whose keys are all known stitch codes and whose values are all
plain non-negative integers (`bool` explicitly excluded, since it's a
Python `int` subclass but never a legitimate count); `chain_spaces` a
plain non-negative integer; no field beyond `stitch_posts`/
`chain_spaces`. A `counts_as` of `"bad"` (a bare string) previously
reached `_describe_counts_as()` and crashed with `AttributeError`
instead of being rejected here — see the ninth correction pass below.

Beyond shape, it enforces exactly what "ready" is supposed to mean:
`trust.provenance` must be exactly `"library"` (never `"ai"` or any
other value) AND `trust.verification_status` must be exactly
`"CONFIRMED"` — both, not either; `validation_evidence`'s
`row_1_valid`, `later_rows_valid`, and `overall_valid` must each be
present and exactly `True` (missing, `False`, or a truthy non-bool like
`1` are all rejected); every later-row summary's own `"valid"` must
likewise be exactly `True`. A handful of CROSS-FIELD consistency checks
also run — `total_rows == 1 + len(later_rows)`, row 1's repeat
execution count agreeing with `requested_repeat_count`, later-row
numbers being consecutive starting at 2, and `foundation_chain_count`
agreeing with `foundation_formula`'s own `foundation_count` — comparing
the plan's own fields against each other, catching a forged or
hand-edited plan whose individual fields each look fine in isolation
but don't add up together. A plan forging `{"trust": {"provenance":
"ai"}}` or an empty `"validation_evidence": {}` is rejected exactly
like a plan missing a required field is.

This is all validation of the RENDERER'S OWN ARGUMENT — confirming what
it was handed is safe to read and internally self-consistent — not a
re-check of recipe/foundation/row correctness, which was already
decided, successfully, before a plan could exist at all.
`_validate_plan()` never reruns recipe resolution or mathematical
simulation to reach these conclusions; it only compares fields the plan
already carries against each other. A plan that passes this check but
names an unimplemented terminology still returns the existing
`"unsupported_terminology"` result, not `"invalid_plan"` — the plan
itself is fine; only the terminology isn't supported yet.

**Stitch terminology** lives in one dict,
`_STITCH_NAMES_BY_TERMINOLOGY`, keyed by the schema's own `terminology`
values. Only `"US"` is implemented (`CH`→chain, `SC`→single crochet,
`HDC`→half double crochet, `DC`→double crochet, `SLST`→slip stitch,
`SKIP`→skip, `INC`→increase, `DEC`→decrease); counts render naturally
("DC 1" → "make 1 double crochet", "DC 3" → "make 3 double crochets").
Schema v2 also allows `"UK"`, which is **not yet implemented** — a
`"UK"` plan returns `{"status": "unsupported_terminology", "text":
None, ...}` rather than silently rendering US wording under a UK label;
`plan_trusted_swatch()` surfaces this as its own `render_unsupported`
outcome (see above), never a false `ready`.

**Placement language** translates every placement into wording a
crocheter recognizes, never an internal implementation term
(`target_established`, `ordered_output`, `cursor`, `produced_structure`,
"counts_as pool"): `next_foundation_chain` → "in the next foundation
chain"; `working_loop` (always `CH`) → "chain N"; `next_stitch` → "in
the next stitch"; `next_dc` → "in the next double crochet";
`next_chain_space` → "in the next chain space"; `turning_chain` (always
`CH`, always opens a later row) → "turn and chain N", with a short
plain-language note appended when `counts_as` is present (e.g. "(counts
as 1 double crochet; forms 1 chain space)"). Every one of these
pluralizes by the number of foundation/stitch/chain-space POSITIONS a
step actually touches (`STITCH_RULES[stitch]["consumes"] * count`,
reused read-only purely for correct English plurals — not validation or
math), not the raw step count, so `DEC 2` (each decrease spanning 2
stitches) correctly reads "...in the next 4 stitches."

**`same_stitch` always renders as "in the same stitch or space,"
never a guess between the two.** PART 7 of this phase's task allowed
the more precise "in the same stitch" / "in the same chain space"
wording *if* the plan retains evidence of which kind was actually
targeted — but neither `validate_row_1_against_foundation()`'s nor
`validate_recipe_rows()`'s returned report records the KIND of the most
recently established target anywhere, only whether one exists (a plain
`target_established`-style boolean, or its ordered-cursor equivalent).
A structured plan built from those reports therefore has no safe way to
distinguish the two, so the renderer always uses the generic phrase.
Making the more precise wording possible would mean changing what
Phase 4A/5 track — out of scope for a renderer-only module that must
not perform validation itself.

## Changelog — first correction pass

1. **Separated computer simulation from physical swatch testing.**
   `SWATCH_TESTED` no longer means "passed `simulate_swatch()`" — that
   is now its own status, `SIMULATION_VALID`. `SWATCH_TESTED` means a
   person physically crocheted the candidate. `STRUCTURE_VALID` no
   longer includes plausibility checking — schema validity and
   plausibility are stated as separate concepts (section 6).
2. **Redesigned `counts_as`** from a bare string to a structured object
   (`stitch_posts` + `chain_spaces`), since a single turning chain can
   count as both at once (section 5).
3. **Replaced the single, ambiguous example** with two clearly named,
   separately purposed files: a structural reference example grounded
   in real regression fixtures, and a known-bad/rejected regression
   example preserving the actual suspicious AI proposal.
   `contracts/examples/stitch_recipe_v2_example.json` no longer exists.
4. **Added the validation-layers section** (section 6), stating what
   each of schema validation, plausibility checking, mathematical
   validation, connected-row simulation, physical swatch testing, and
   visual/human confirmation each proves and does not prove.
5. **Sharpened the placement vocabulary** (section 4): `working_loop`
   is specifically a chain from the active loop; `turning_chain`
   describes a role, not a separate mechanism; `next_foundation_chain`
   is row-1-only; `next_chain_space` refers to the immediately
   previous row specifically; foundation length is restated as never
   being a row-one `CH` action.

## Changelog — second correction pass (this pass)

1. **Removed the "different, unrelated stitch families" framing.** The
   structural and known-bad examples both represent recipe candidates
   for the same broad stitch-family label (filet mesh) — they are
   different candidates/constructions for that one family, not
   examples drawn from unrelated stitches. Fixed in both example
   files' `_comment` fields and in section 8.
2. **Stopped calling `tests/golden/halter_mesh_row1_*.json`
   "hand-verified," "confirmed," or authoritative crochet ground
   truth**, everywhere that phrasing appeared (section 8, both example
   files). Those fixtures document expected engine behavior and real
   hand-crocheted observations, but also preserve their own unresolved
   4-predicted-vs-5-physical-DC discrepancy — restated wherever the
   fixtures are referenced. The known-bad example's rejection reasoning
   is reframed accordingly: it is rejected because its row-1 repeat
   **conflicts with the specific target construction being tested** (no
   per-repeat skipped foundation chain, so no open mesh grid), not
   because comparing golden-fixture arithmetic alone proves crochet
   truth — the file and section 8 now say this explicitly.
3. **Changed the structural example's `later_rows.repeat` DC placement
   from `next_chain_space` to `next_dc`**, matching the intended "CH 1,
   then DC into the next DC" instruction (`main.py`'s `row_2`
   `repeat_text`). Updated the file's own `later_rows.note` and open
   question 3 accordingly, and recorded a new open question this fix
   surfaces: whether the turning chain's declared `chain_spaces: 1`
   still means anything now that nothing in the repeat is placed
   `next_chain_space`. This candidate remains explicitly unconfirmed.
4. **Audited both example files and this document** for remaining
   claims that the physical discrepancy has been resolved, that the
   structural example is confirmed, or that regression fixtures alone
   prove physical correctness. None were found beyond items 1–3 above,
   which are now corrected. No historical evidence (dates, logged
   findings, past discrepancies) was altered — only the framing around
   it.

## Changelog — third correction pass (Phase 4A semantics fix)

1. **`working_loop` no longer clears the previously established target.**
   `engine/recipe_validator.py`'s `_analyze_row1_steps()` previously reset
   `target_established` to `False` on every `working_loop` step, on the
   reasoning that "a floating chain isn't a stitch `same_stitch` could
   reference." That conflated the chain itself (correctly not a valid
   `same_stitch` referent) with the *target established before it*
   (which a floating chain does nothing to erase). `DC
   next_foundation_chain` → `CH working_loop` → `DC same_stitch` is now
   correctly valid — the final `DC` refers back to the same foundation
   chain the first `DC` did — consuming exactly 1 foundation position
   and producing 2 DC posts + 1 chain space (3 total workable
   positions). `same_stitch` with no established prior target, and
   `same_stitch` on a `SKIP` step, still both raise `RecipeMathError`
   exactly as before — this fix only changes what `working_loop` does to
   the *carried* target, nothing else.
2. **`row_1.repeat` is now executed sequentially, not analyzed once and
   multiplied.** `validate_row_1_against_foundation()` previously called
   `_analyze_row1_steps()` on `repeat` exactly once (seeded from
   `setup`'s ending target) and multiplied that single pass's consumed
   count and produced structure by `requested_repeat_count`. Because
   target state can now legitimately change across a `repeat` pass (via
   item 1's fix, or a trailing `SKIP` clearing it), a later pass's
   starting target can differ from what `setup` left behind, and only
   sequential, pass-by-pass execution — each pass's target carried
   verbatim into the next — catches a `same_stitch` that only becomes
   invalid partway through the repeats. `repeat_once` now specifically
   means the first pass (the one whose target came from `setup`);
   `repeat_total` accumulates consumed positions and produced structure
   pass by pass. All previously-documented report fields (`setup`,
   `repeat_once`, `repeat_total`, `row_1`, `consumed_foundation_positions`,
   `produced_structure`, `unused_foundation_positions`,
   `overdrawn_foundation_positions`, the expected-repeat comparisons,
   `valid`, `errors`) are unchanged in shape and meaning.

## Changelog — fourth correction pass (Phase 5 ordering fix)

1. **Replaced Phase 5's unordered typed pools with an ordered target
   list and a forward-only cursor.** The first Phase 5 implementation
   represented a row's typed output as two aggregate dicts —
   `stitch_posts: {code: int}` and `chain_spaces: int` — the same shape
   `produced_structure` already used for summaries. That shape cannot
   distinguish a row that produced "DC, chain space, SC" from one that
   produced "SC, chain space, DC," even though `next_stitch`, `next_dc`,
   `next_chain_space`, and SKIP are all TRAVERSAL instructions —
   "the next one, moving forward" — a question an unordered count can't
   answer. Concretely, `next_stitch` picked among same-type candidates
   via `sorted(pool["stitch_posts"])`, which is not, and was never
   claimed to be, valid crochet traversal (there is no reason a real
   row's next stitch would be whichever stitch code sorts first
   alphabetically). Every row's actual production is now kept as an
   ordered list of `{"kind", "stitch", "source"}` entries, one per
   physical position, in real left-to-right order (see
   `engine/recipe_validator.py` and `engine/later_row_validator.py`'s
   module docstrings for the exact shape and full placement-by-placement
   cursor rules). `produced_structure` still exists, but only as a
   projection derived from the ordered list, never read by traversal
   logic itself.
2. **Extended Phase 4A's report with `ordered_output`, without removing
   or renaming any existing field.** `validate_row_1_against_foundation()`
   now returns `ordered_output` alongside `produced_structure` in
   `setup`, `repeat_once`, `repeat_total`, and the combined `row_1` —
   row 1's own production, in order, since it seeds row 2's ordered
   input. Row 1 itself never needs to READ an ordered input (it draws
   from the foundation chain via a flat consumed count, not from a
   previous row's output), so this is purely an addition on the output
   side; every field Phase 4A already documented is unchanged in shape
   and meaning.
3. **Redefined what "remaining unused input" means.** Because the
   cursor only moves forward, an entry it passed OVER while searching
   for something else is gone by the time a row finishes processing —
   it is no longer reported as "remaining" merely because no step
   explicitly claimed it, the way the unordered-pool version would have
   reported it. "Remaining" now specifically means the suffix of the
   previous row's ordered output the cursor never reached at all. Two
   recipes whose row 1 has identical aggregate totals can therefore
   report different leftovers in row 2 purely because of production
   order — see `tests/test_later_row_validator.py`'s `OrderMattersTests`
   for a concrete pair demonstrating this.
4. **The `next_dc`/counts_as eligibility check now operates on a single
   found position's `source` tag, not on separate literal/counts_as pool
   counts.** The conclusion is unchanged (still refuses to guess,
   raising the same `RecipeMathError`), but the check is now more
   crochet-faithful: it fires on whichever DC-shaped position the cursor
   actually reaches next, even if a "safer" literal DC exists later in
   the row — skipping ahead to that later one would itself be a guess
   about whether the closer, ambiguous one may be passed over, which
   this module still refuses to make.
5. **Repeat-count derivation is now a real cursor walk, not per-type
   floor division.** The number of times `later_rows.repeat` can run was
   already derived by executing real passes rather than being assumed
   equal to `requested_repeat_count` (unchanged from the original Phase
   5 design) — but each pass's success or failure is now decided by
   whether the ordered cursor can complete a full pass, never by
   comparing unordered per-type totals. This matters concretely: a pass
   can fail even when the aggregate pool would appear to have "enough"
   of every type, if reaching what it needs requires passing over (and
   losing) something an earlier step in the same pass already needed —
   see `NextChainSpaceRespectsOrderTests` and `CannotMoveBackwardTests`
   in `tests/test_later_row_validator.py`.

## Changelog — fifth correction pass (Phase 5 row-turn direction fix)

1. **A row's ordered input is now the REVERSE of the previous row's
   ordered output, not that same list reused unchanged.** The fourth
   correction pass introduced the ordered cursor but passed one row's
   `ordered_output` straight into the next row's `_validate_one_later_row()`
   call as its `ordered_input`, and the original tests explicitly
   asserted this was unchanged. That models a crocheter continuing in
   the SAME direction after finishing a row, which is what continuous
   rounds do — not what flat, turned rows do. In flat crochet you turn
   the work at the end of every row, so the next row's cursor meets the
   previous row's production in reverse: if row 1 produces `[DC, chain
   space, SC]`, row 2 must receive `[SC, chain space, DC]`, not `[DC,
   chain space, SC]` again. `validate_recipe_rows()` now builds each
   row's input as `list(reversed(previous_row's ordered_output))` — a
   fresh list at every hand-off, reversed exactly once, never mutating
   the previous row's stored `ordered_output` and never applied twice in
   a row (which would silently cancel out and stop modeling a turn at
   all).
2. **Clarified what `ordered_output` means, precisely, everywhere it
   appears.** It is now stated explicitly, in both this document and
   `engine/later_row_validator.py`'s module docstring, that
   `ordered_output` ALWAYS means "the order this row's own steps
   actually produced these targets, left to right" — never the order
   the next row will traverse them in. The turn/reversal is entirely the
   orchestrating function's responsibility at the moment it hands one
   row's output to the next row's input; no row's own `ordered_output`
   field is ever itself reversed, and `ordered_input` (a field only
   later rows have) is the one place the already-turned list appears.
3. **Stated explicitly that this validator supports flat, turned rows
   only**, and that continuous-round construction (where consecutive
   rows/rounds are worked in the same direction, never turned) is
   unsupported — not silently mishandled, but not guessed at either.
   Schema v2 has no field distinguishing the two constructions, so
   there is nothing this validator could branch on; supporting rounds
   for real would need a new field (e.g. a `construction` enum). See
   this document's "Phase 5" section, "This validator supports flat,
   turned rows only," and the same statement in
   `engine/later_row_validator.py`'s module docstring
   ("FLAT ROWS ONLY -- CONTINUOUS ROUNDS ARE NOT SUPPORTED").
4. **Corrected every Phase 5 test whose expected result depended on
   direction.** Several tests built a specific row-1 production order
   expecting a specific row-2 traversal outcome; since row 2 now
   receives the REVERSE of what it received before this fix, a number
   of fixtures needed their row-1 step order swapped (not their
   assertions loosened) to keep testing the same claim under the
   corrected direction — for example, `NextChainSpaceRespectsOrderTests`
   and `OrderMattersTests`. New tests were added specifically for the
   turn itself (`OrderedOutputThreadingTests`) and for proving the
   reversal never mutates an already-returned report's stored lists
   (`NoMutationTests.test_turning_a_rows_output_does_not_mutate_the_stored_report`).

## Changelog — sixth correction pass (Phase 6 trust-boundary fix)

1. **`validate_recipe_library()` now checks the library's top-level
   contract, not just `recipes`.** It previously only required
   `recipes` to be a list; it now also requires `schema_version` (a
   string, equal to exactly `"2.0.0"`), rejects any top-level field
   other than `schema_version`/`recipes`/`notes`, and validates `notes`
   (if present) as a non-empty string. An unsupported or missing
   `schema_version` is rejected rather than silently read as if it were
   the current format.
2. **`resolve_stitch_recipe()`, `find_recipe_by_pattern_id()`, and
   `find_recipe_by_name()` all validate a directly-supplied `library`
   before searching it.** Previously, `load_recipe_library()` (the
   default disk path) validated, but a `library` argument passed
   directly to any of these three functions was searched as-is — a
   hand-built or externally-supplied dict could claim
   `verification.status == "CONFIRMED"` on a recipe that had never
   actually passed `validate_recipe_v2()`, or hide a duplicate
   `pattern_id` behind whichever entry a lookup happened to reach
   first, and be selected as trusted output without ever being checked.
   Every one of those three functions now runs the supplied library
   through `validate_recipe_library()` first (via the shared internal
   `_load_or_validate_library()` gate) and raises `RecipeLibraryError`
   — consistently, the same exception a broken file already raised —
   before any lookup, match, or selection happens if it fails.
   `resolve_stitch_recipe()` validates once per call, not once per
   lookup term, via private `_find_recipe_by_pattern_id_in()`/
   `_find_recipe_by_name_in()` helpers that assume an already-validated
   library; `find_recipe_by_pattern_id()` and `find_recipe_by_name()`
   remain the safe, independently-validating public functions they were
   always documented as.
3. **`ambiguous_match`'s reachable cause narrowed, correctly.**
   Because a library-internal ambiguous shared alias (or duplicate
   `pattern_id`) is now rejected at validation time before any search
   happens, `resolve_stitch_recipe()` can no longer report
   `ambiguous_match` because of a defect in the library itself — that
   case now raises `RecipeLibraryError` instead. `ambiguous_match`
   remains reachable, correctly, when the AI PROPOSAL's own name and
   one of its own declared aliases each independently match a
   DIFFERENT, individually valid and unambiguous library recipe — see
   `tests/test_recipe_library.py`'s
   `test_ambiguous_match_lists_conflicting_pattern_ids_and_picks_none`,
   rewritten to exercise this cause specifically, and the new
   `TrustBoundaryTests` class for the library-defect cases that now
   raise instead.

## Changelog — seventh correction pass (Phase 7 plan-validation fix)

1. **`_build_swatch_plan()` now stamps every plan it returns with
   `"ready_for_rendering": True`.** This is the plan's own claim that
   it was built only after resolution (`trusted_match`) and simulation
   (`validate_recipe_rows()` reporting `valid: True`) both already
   succeeded — exactly the precondition `render_swatch_plan()` was
   always documented to assume, now stated as an explicit field instead
   of an unstated assumption about how the caller got there.
2. **`render_swatch_plan()` now validates its own argument before
   reading any field from it.** Previously it read `plan["name"]`,
   `plan["foundation_chain_count"]`, `plan["row_1_setup"]`, etc.
   directly, trusting that whatever it was handed came from
   `_build_swatch_plan()`. `render_swatch_plan(None)`,
   `render_swatch_plan([])`, and `render_swatch_plan({})` would all
   have raised `AttributeError`/`KeyError` rather than returning a
   structured result. A new `_validate_plan()` check — a dict; the new
   `ready_for_rendering` field present and exactly `True`; every other
   required field present; well-formed `trust`, `foundation_chain_count`,
   `foundation_formula`, step lists (each step needing a known stitch
   code and a known placement — reusing `engine/schema.py`'s existing
   `V2_KNOWN_STITCHES`/`V2_PLACEMENTS` constants, not a second
   hand-maintained list), later-row summaries, and repeat counts — now
   runs first, returning `{"status": "invalid_plan", "text": None,
   "warnings": [], "errors": [...]}` for any of the above rather than
   raising. A plan that passes this check but names an unimplemented
   terminology still returns `"unsupported_terminology"`, unchanged —
   see `tests/test_renderer_v2.py`'s
   `test_valid_ready_plan_with_unsupported_terminology_is_not_invalid_plan`.
   This is validation of the renderer's own argument shape, not a
   re-check of recipe/foundation/row correctness (already decided
   before any plan exists) — `_validate_plan()` never re-derives
   whether the underlying recipe or simulation was correct.

## Changelog — eighth correction pass (Phase 7 internal-readiness-contract fix)

1. **`_validate_plan()` previously checked only shape, not meaning.**
   A plan with `"ready_for_rendering": True`, `"trust": {"provenance":
   "ai"}`, and `"validation_evidence": {}` would have passed every
   check from the seventh correction pass (a dict with a string
   `provenance`, an object `validation_evidence`) and gone on to render
   — even though nothing about it actually represented a trusted,
   successfully-simulated recipe. `_validate_plan()` now requires
   `trust.provenance == "library"` exactly and
   `trust.verification_status == "CONFIRMED"` exactly (both, not
   either); `validation_evidence.row_1_valid`,
   `.later_rows_valid`, and `.overall_valid` must each be present and
   exactly `True` (a new `_is_exactly_true()` helper — `value is True`,
   never a truthy non-bool like `1`); and every later-row summary's own
   `"valid"` is now REQUIRED (previously only type-checked if present)
   and must also be exactly `True`.
2. **Added cross-field consistency checks** comparing the plan's own
   fields against each other — never re-running recipe resolution or
   mathematical simulation, which already happened successfully before
   a plan could exist: `total_rows == 1 + len(later_rows)`,
   `row_1_repeat_execution_count == requested_repeat_count`, later-row
   `row_number`s consecutive starting at 2, and `foundation_chain_count
   == foundation_formula["foundation_count"]`. Each check only runs
   once its own inputs already passed their individual type checks, so
   one malformed field produces one clear error, not a cascade.
   `warnings` is now also checked to contain only strings.
3. **Fixed a latent bug this surfaced in the test suite itself.**
   `tests/test_renderer_v2.py`'s `minimal_plan()` fixture computed
   `total_rows` from the raw `later_rows` FUNCTION PARAMETER (`None` by
   default) rather than the actual list used for the plan's
   `"later_rows"` field (which defaulted to a 1-item list) — an
   inconsistency that existed before this pass but was invisible until
   the new `total_rows == 1 + len(later_rows)` check could detect it.
   Fixed by resolving the default `later_rows` list once, at the top of
   the fixture, and using that same resolved value for both fields.
4. **Reverted an unrelated formatting-only change to `docs/testing.md`**
   (Markdown table alignment and `*emphasis*` → `_emphasis_` markers,
   apparently from an auto-formatter) that was present in the working
   tree but outside this phase's scope — restored to its original
   content via `git checkout -- docs/testing.md`, no content changed.

## Changelog — ninth correction pass (Phase 7 nested-step validation fix)

1. **`_validate_step()` previously checked stitch/placement legality
   GLOBALLY, not per section.** It confirmed a step's `stitch` was in
   `V2_KNOWN_STITCHES` and its `placement` was in `V2_PLACEMENTS`
   somewhere in the v2 vocabulary, but never that the specific
   combination was legal in the specific list it appeared in.
   `{"stitch": "CH", "count": 1, "placement": "next_dc"}` inside
   `row_1_repeat`, and `{"stitch": "DC", "count": 1, "placement":
   "turning_chain"}` in any section, both passed this check and reached
   `_render_step()` — which has no defined behavior for either
   combination and would render something, not refuse. `_validate_step()`
   now takes the section's specific allowed-placement set
   (`ROW1_PLACEMENTS` / `LATER_SETUP_PLACEMENTS` / `LATER_REPEAT_PLACEMENTS`,
   imported from `engine/schema.py`) and reapplies the same
   stitch/placement compatibility rule `validate_recipe_v2()` already
   enforces (a CH step may only use `working_loop`/`turning_chain`; any
   other stitch must not use either) — both checks run independently,
   so a step can fail on section-legality, stitch/placement
   compatibility, or both at once, and every applicable error is
   reported.
2. **`counts_as` was never validated at all before this pass** — only
   its presence gated whether `_describe_counts_as()` got called at
   render time. A `counts_as` of a bare string (`"bad"`) reached
   `_describe_counts_as()`'s `.get("stitch_posts")` call and crashed
   with `AttributeError` instead of producing `invalid_plan`. A new
   `_validate_counts_as_value()` — an independently-owned copy of
   `engine/schema.py`'s own `_validate_counts_as()` rules (not
   imported, since that is a private helper of another module; kept in
   sync by hand with `contracts/stitch_recipe_schema_v2.json`, the same
   convention `engine/later_row_validator.py` already follows for its
   own `_target()`) — now checks: `counts_as` is an object; only
   `stitch_posts`/`chain_spaces` are present; `stitch_posts` is an
   object of known stitch codes to plain non-negative integers (`bool`
   excluded); `chain_spaces` is itself a plain non-negative integer.
   Every problem is reported, never just the first, and nothing raises.
3. **Both failures were specifically about nested nodes, not the
   top-level shape the eighth pass already covered** — the eighth
   pass's `_validate_plan()` correctly rejected a top-level
   `ready_for_rendering`/`trust`/`validation_evidence` forgery, but had
   no opinion on what was INSIDE a step or a step's `counts_as`, which
   is exactly the gap this pass closes. See
   `tests/test_renderer_v2.py`'s new `NestedStepValidationTests` class
   for all cases, including a `test_no_malformed_nested_step_raises_an_exception`
   sweep proving none of them ever reach an uncaught exception, and
   confirmation that a real `plan_trusted_swatch()` plan (with a valid
   `counts_as`-bearing turning chain) still renders successfully.
