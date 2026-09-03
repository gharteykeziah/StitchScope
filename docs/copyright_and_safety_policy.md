# Copyright & Safety Policy

These are the non-negotiable rules for what StitchScope will and won't do
with a photo, independent of anything a vision model or the reconstruction
engine proposes.

## What StitchScope does

A user uploads a photo of a finished garment they like. The system
visually analyzes it and independently generates a new, original
construction plan for something comparable — it does not obtain, copy, or
rewrite any designer's paid written pattern.

## Rules

1. **No pattern text ever enters the system.** StitchScope reasons from a
   photograph, not from a designer's written instructions. It never
   ingests, stores, retrieves, or reproduces the text of a paid or
   copyrighted pattern.

2. **Output is always labeled as an independent recreation.** Every
   result StitchScope produces is presented as an AI-generated best guess
   at how a similar piece could be constructed — never as "the designer's
   exact method" or "this garment's real pattern."

3. **Protected imagery is refused, not reproduced.** If a photo contains
   a recognizable logo, licensed character, or clearly original/branded
   artwork (as opposed to a generic stitch pattern), the system declines
   to recreate that specific element and says so, rather than attempting
   to reconstruct it.

4. **Uncertainty is reported, not hidden.** When a single photo can't
   show something (the back of a garment, an interior seam, exact
   stitch count in a low-resolution area), the system says what it
   can't determine instead of inventing a confident-sounding answer.
   This is enforced structurally: every proposal carries an
   `uncertain_fields` list (see `contracts/proposal_schema_v1.json`), and a
   proposal with unresolved uncertainty about a load-bearing detail
   should prompt a follow-up question rather than a final answer.

5. **No real designer or brand is named as the source.** Output describes
   the stitch pattern and construction generically (e.g. "a filet mesh
   panel"), never attributes it to a specific designer's named pattern
   unless the user themselves provided that attribution.

## Why this boundary matters

The product's value proposition is "visual inspiration should be
reachable to someone who already knows how to crochet but can't reverse-
engineer an unfamiliar stitch." That's defensible. "Designers shouldn't
be able to sell patterns" is a different, much weaker claim, and one this
project deliberately does not make — nothing here is built to replace or
undercut a specific designer's own written pattern.
