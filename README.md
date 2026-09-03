# StitchScope

Read a crochet pattern, check the math, size it to fit.

StitchScope parses crochet rows written in a simple text format, checks that each row's stitch counts actually work against the stitches available (foundation chain or prior row), and solves for the stitch count closest to a target measurement without breaking a pattern's repeat. It also validates stitch proposals from a vision-model stand-in against the same rules.

## Tech Stack
- Python 3 (standard library only, no external dependencies)

## Features
- 🧶 Reads rows written as setup + repeat steps (e.g. `CH 1, SKIP 1, DC 1`)
- ✅ Validates stitches consumed/produced against a foundation chain or the previous row
- 📏 Solves for the stitch count closest to a target width without breaking the repeat
- 🤖 Checks AI-proposed stitch rows against the same validation rules
- 🚫 Catches rows that don't add up

## Local Development
Requirements: Python 3.8+

```
git clone https://github.com/gharteykeziah/StitchScope.git
cd StitchScope
python3 main.py
```
