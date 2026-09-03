"""
Turns a parsed row (setup + repeat, from pattern_reader.py) into plain,
conversational instructions -- the "render the structure back out as
plain language" half of the compiler idea from the product plan. This
module only describes what a row says, in words; it doesn't check
whether the row is actually valid -- that's validator.py's job.
"""

# How each stitch reads in a sentence. Singular and plural get different
# phrasing ("skip the next stitch" vs "skip the next 3 stitches") rather
# than an awkward "skip 3 stitch(es)".
_STITCH_PHRASES = {
    "CH":   {"one": "chain 1", "many": "chain {count}"},
    "SC":   {"one": "single crochet in the next stitch",
             "many": "single crochet in each of the next {count} stitches"},
    "HDC":  {"one": "half double crochet in the next stitch",
             "many": "half double crochet in each of the next {count} stitches"},
    "DC":   {"one": "double crochet in the next stitch",
             "many": "double crochet in each of the next {count} stitches"},
    "SLST": {"one": "slip stitch in the next stitch",
             "many": "slip stitch in each of the next {count} stitches"},
    "SKIP": {"one": "skip the next stitch", "many": "skip the next {count} stitches"},
    "INC":  {"one": "work 2 stitches into the next stitch (an increase)",
             "many": "work 2 stitches into each of the next {count} stitches (an increase)"},
    "DEC":  {"one": "work the next 2 stitches together (a decrease)",
             "many": "work the next 2 stitches together {count} times (a decrease)"},
}


def render_step(step):
    """Renders one step, e.g. {"stitch": "DC", "count": 3}, as a phrase."""
    stitch = step["stitch"]
    count = step["count"]
    if stitch not in _STITCH_PHRASES:
        # Shouldn't happen for a step that's already passed the tokenizer/
        # parser, but render *something* honest instead of crashing.
        return f"{stitch.lower()} {count} time(s)"
    phrasing = _STITCH_PHRASES[stitch]
    template = phrasing["one"] if count == 1 else phrasing["many"]
    return template.format(count=count)


def render_steps(steps):
    """Joins a list of steps into one readable phrase."""
    if not steps:
        return ""
    phrases = [render_step(step) for step in steps]
    if len(phrases) == 1:
        return phrases[0]
    return ", then ".join(phrases)


def render_row(row, repeat_count):
    """
    Renders a full row (setup + repeat, worked repeat_count times) as
    plain-English instructions, e.g.:

      "Skip the next 5 stitches, then double crochet in the next stitch.
       Then repeat 7 times: chain 1, skip the next stitch, then double
       crochet in the next stitch."
    """
    setup_text = render_steps(row["setup"])
    repeat_text = render_steps(row["repeat"])

    if setup_text and repeat_text:
        return f"{setup_text.capitalize()}. Then repeat {repeat_count} times: {repeat_text}."
    elif repeat_text:
        return f"Repeat {repeat_count} times: {repeat_text}."
    elif setup_text:
        return f"{setup_text.capitalize()}."
    else:
        return ""
