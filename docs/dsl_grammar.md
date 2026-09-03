# StitchScope Row DSL — Grammar

StitchScope represents one crochet row as two step lists: a **setup** (the
one-time stitches worked at the start of a row, before the pattern starts
repeating) and a **repeat** (the unit that repeats across the rest of the
row). This document formalizes the text format `pattern_reader.py` parses
into that structure.

## Grammar

```
row         := setup_text ";" repeat_text      (setup and repeat are supplied
                                                  as two separate strings today,
                                                  not one delimited string --
                                                  see "Current implementation")
setup_text  := step_list | ""
repeat_text := step_list
step_list   := step ("," step)*
step        := STITCH WS COUNT
STITCH      := "CH" | "SC" | "HDC" | "DC" | "SLST" | "SKIP" | "INC" | "DEC"
COUNT       := positive integer
WS          := one or more spaces
```

Commas separate steps within a list. Leading/trailing whitespace around a
step, and around the stitch name/count pair inside a step, is stripped and
ignored. A setup can be empty (a row with no one-time start, e.g. a plain
repeated border round).

## Current implementation

`pattern_reader.read_full_row(setup_text, repeat_text)` takes the two step
lists as separate string arguments rather than one row string with a
delimiter, since that maps more directly onto how a row is actually
described ("this is the one-time part, this is what repeats"). The grammar
above documents the row conceptually; the two-argument function signature
is the concrete API.

## Stitch vocabulary and their consumes/produces rule

| Stitch | Consumes | Produces | Meaning |
|---|---|---|---|
| CH   | 0 | 1 | Chain stitch — doesn't use up a stitch from the row below, adds one new loop |
| SC   | 1 | 1 | Single crochet |
| HDC  | 1 | 1 | Half double crochet |
| DC   | 1 | 1 | Double crochet |
| SLST | 1 | 1 | Slip stitch |
| SKIP | 1 | 0 | Skips a stitch from the row below without working into it |
| INC  | 1 | 2 | Increase — works two stitches into one |
| DEC  | 2 | 1 | Decrease — works two stitches together into one |

This table is the single source of truth for the stitch simulator in
`validator.py` (`STITCH_RULES`) — if the two ever disagree, the code is
right and this table is out of date; fix the table.

## Worked example

```
setup:  "SKIP 5, DC 1"
repeat: "CH 1, SKIP 1, DC 1"
```

parses to:

```
setup:  [{"stitch": "SKIP", "count": 5}, {"stitch": "DC", "count": 1}]
repeat: [{"stitch": "CH", "count": 1}, {"stitch": "SKIP", "count": 1}, {"stitch": "DC", "count": 1}]
```

This is the halter/corset top's real mesh-panel row 1: skip to the 6th
foundation chain, DC there (setup), then chain-1/skip-1/DC-1 across the
rest (repeat). See `tests/golden/` for real hand-verified numbers from
this exact row.

## Deliberately out of scope for v1

- **Nested repeats** — a repeat inside a repeat (e.g. a fan motif that
  itself repeats every few rows, worked as a unit that also repeats
  across a row). Real patterns have these; v1's DSL is flat.
- **Row-to-row references beyond stitch count** — "work into the same
  stitch as 3 rows below" isn't representable yet; only "how many
  stitches did the previous row produce" is.
- **Color changes, joins, and finishing instructions** — fasten off,
  weave in ends, join in the round. StitchScope validates stitch-count
  structure, not a full construction script.

These gaps are documented on purpose rather than silently guessed around.
Anything a real garment needs that the DSL can't represent yet should
surface as an `uncertain_fields` entry on a proposal (see
`docs/domain_glossary.md` and `schema/proposal_schema_v1.json`), not get
dropped or approximated without saying so.
