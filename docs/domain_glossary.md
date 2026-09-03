# StitchScope Domain Glossary

Plain-English definitions for terms used across the codebase and docs.

**Stitch** — a single crochet operation (DC, SC, CH, etc. — see the table
in `docs/dsl_grammar.md`). Has a fixed consumes/produces rule.

**Step** — one instruction in the DSL: a stitch plus a count, e.g. `DC 3`
means "double crochet, three times." Represented in code as
`{"stitch": "DC", "count": 3}`.

**Setup** — the one-time stitches at the start of a row, worked before the
repeating part begins (e.g. skipping to and DC-ing into the 6th foundation
chain). Not repeated.

**Repeat** — the unit of steps that repeats across the rest of a row.
Worked some number of times (the **repeat count**) to fill the row.

**Row** — one full pass across the piece: a setup plus a repeat worked a
given number of times.

**Foundation chain** — the starting chain a piece is built from. Its
length is the "stitches available" for row 1.

**Consumes / produces** — every stitch either uses up ("consumes") a
certain number of stitches from the row/chain below it, and/or leaves
behind ("produces") a certain number of new stitches for the next row to
work into. A DC consumes 1 and produces 1; a chain consumes 0 and
produces 1; a skip consumes 1 and produces 0. This is what lets the
simulator check a row's math without a human tracing it by hand.

**Stitches available** — how many stitches a row has to work with: the
foundation chain's length for row 1, or the previous row's `produced`
count for every row after that.

**Repeat count** — how many times a row's repeat unit is worked. Fixed by
the pattern (real garment) or proposed by the AI perception layer (a
vision-model guess) — either way, the engine checks whether that count
actually fits the stitches available.

**Repeat divisibility** — the constraint that a row's total stitch count
has to be reachable by some whole number of repeats plus the setup — you
can't work "half a repeat." This is the binding constraint the sizing
solver (`sizing.py`) has to respect.

**Gauge** — how many stitches and rows fit in a fixed length (usually 2–4
inches), for a specific thread/hook/tension combination. Needed to
convert a target body measurement into a target stitch count.

**Swatch** — a small hand-crocheted sample used to test a guessed
pattern and measure real gauge before committing to a full piece.

**Golden example** — a real, hand-verified input/output pair (see
`tests/golden/`) used as a regression test: given this exact row, the
engine must always produce this exact result.

**Proposal** — the structured guess a vision-model perception layer
returns for a photographed row: which stitch family, what the setup and
repeat look like, a confidence score, and which fields it's unsure about.
Defined formally in `contracts/proposal_schema_v1.json`.

**Confidence** — the proposal's own self-reported certainty, 0 to 1. Not
validated for correctness by the engine — it's metadata about the guess,
not a guarantee.

**Uncertain fields** — a list of field names the proposal's source
(currently a hand-written stand-in; eventually a real vision model) is
not confident about. An empty list means high confidence in everything
proposed.

**Valid / invalid row** — the outcome of running a row through
`engine/validator.py`'s `check_full_row()`: valid means it consumes no more stitches
than are actually available; invalid means it doesn't, and the row as
proposed cannot really be crocheted as described.
