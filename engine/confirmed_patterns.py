"""
A growing library of confirmed stitch patterns
(data/confirmed_stitch_patterns.json) and the comparison logic that
checks a fresh AI proposal against it.

This is the other half of engine/plausibility.py: that module catches
an obviously wrong proposal the FIRST time a stitch is seen, with no
history at all. This module is what happens once a human has actually
confirmed a stitch family's real setup/repeat/turning_chain (by
hand-swatching it -- see confirm_stitch.py at the repo root): every
future AI proposal for that same stitch family gets checked against
that ground truth instead of trusted fresh each time.

Each entry is keyed by a normalized stitch family name and holds:
  setup           -- confirmed step list, or None if not yet confirmed
  repeat          -- confirmed step list, or None if not yet confirmed
  turning_chain   -- confirmed step list (like setup/repeat -- the
                      turning-chain steps for rows after the first), or
                      None if not yet confirmed
  confirmations   -- list of {"photo", "date", "note"}; empty until
                      confirm_pattern() is called at least once
  last_ai_proposal -- the most recent {"setup", "repeat",
                      "turning_chain"} this stitch family was proposed
                      as, updated every time check_against_confirmed()
                      runs, regardless of outcome -- so drift between
                      repeated AI guesses (and, once there is one,
                      confirmed ground truth) stays visible over time

An entry existing in the file does NOT mean the stitch family is
confirmed -- entries are created the first time a stitch family is
proposed at all, purely to hold last_ai_proposal so confirm_stitch.py
has something to pull from later. "Confirmed" specifically means
confirmations is non-empty.
"""

import datetime
import json
import re
from pathlib import Path

_PATTERNS_PATH = Path(__file__).resolve().parent.parent / "data" / "confirmed_stitch_patterns.json"

NO_CONFIRMED_ENTRY = "no_confirmed_entry"
MATCHES_CONFIRMED = "matches_confirmed"
CONFLICTS_WITH_CONFIRMED = "conflicts_with_confirmed"


class ConfirmationConflictError(Exception):
    """Raised when a new confirmation disagrees with an already-confirmed entry."""


def normalize_stitch_family(name):
    """Lowercase, whitespace-collapsed key so 'Filet Mesh' and 'filet  mesh' land on the same entry."""
    return re.sub(r"\s+", " ", name.strip().lower())


def load_patterns():
    with open(_PATTERNS_PATH) as f:
        return json.load(f)


def save_patterns(data):
    with open(_PATTERNS_PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def get_confirmed_recipe(stitch_family):
    """
    Returns the confirmed {"setup", "repeat", "turning_chain"} for
    stitch_family, or None if nothing's confirmed yet -- whether this
    stitch family has never been seen at all, or has only ever been
    proposed (an entry exists, but confirmations is empty).

    A pure read: doesn't touch last_ai_proposal or write anything. Meant
    for callers deciding whether they even need to ask for a fresh
    recipe at all (see run_real_photo.py's resolve_recipe()) -- no
    need to call get_stitch_recipe() again once something's proven.
    """
    key = normalize_stitch_family(stitch_family)
    data = load_patterns()
    entry = data.get(key)
    if entry is None or not entry["confirmations"]:
        return None
    return {"setup": entry["setup"], "repeat": entry["repeat"], "turning_chain": entry["turning_chain"]}


def check_against_confirmed(stitch_family, proposed_setup, proposed_repeat, proposed_turning_chain):
    """
    Compares a fresh AI proposal for stitch_family against whatever's
    confirmed for it in data/confirmed_stitch_patterns.json.

    Always updates the entry's last_ai_proposal as a side effect --
    creating the entry if this stitch family has never been proposed
    before -- regardless of whether the comparison matches, conflicts,
    or there's nothing confirmed yet to compare against.

    Returns:
      {"status": NO_CONFIRMED_ENTRY | MATCHES_CONFIRMED | CONFLICTS_WITH_CONFIRMED,
       "confirmed_entry": <entry dict, or None if not yet confirmed>,
       "disagreements": [<human-readable strings naming exactly which
                           part(s) disagreed>]}  -- only non-empty when
                          status is CONFLICTS_WITH_CONFIRMED
    """
    key = normalize_stitch_family(stitch_family)
    data = load_patterns()
    entry = data.get(key)

    proposal_record = {
        "setup": proposed_setup,
        "repeat": proposed_repeat,
        "turning_chain": proposed_turning_chain,
    }

    if entry is None:
        entry = {
            "setup": None,
            "repeat": None,
            "turning_chain": None,
            "confirmations": [],
            "last_ai_proposal": proposal_record,
        }
        data[key] = entry
        save_patterns(data)
        return {"status": NO_CONFIRMED_ENTRY, "confirmed_entry": None, "disagreements": []}

    entry["last_ai_proposal"] = proposal_record
    save_patterns(data)

    if not entry["confirmations"]:
        return {"status": NO_CONFIRMED_ENTRY, "confirmed_entry": None, "disagreements": []}

    disagreements = []
    if entry["setup"] != proposed_setup:
        disagreements.append(f"setup differs: confirmed {entry['setup']!r} vs proposed {proposed_setup!r}")
    if entry["repeat"] != proposed_repeat:
        disagreements.append(f"repeat differs: confirmed {entry['repeat']!r} vs proposed {proposed_repeat!r}")
    if entry["turning_chain"] != proposed_turning_chain:
        disagreements.append(
            f"turning_chain differs: confirmed {entry['turning_chain']} vs proposed {proposed_turning_chain}"
        )

    if disagreements:
        return {"status": CONFLICTS_WITH_CONFIRMED, "confirmed_entry": entry, "disagreements": disagreements}
    return {"status": MATCHES_CONFIRMED, "confirmed_entry": entry, "disagreements": []}


def confirm_pattern(stitch_family, setup, repeat, turning_chain, photo_filename, note, date=None):
    """
    Records a human-confirmed ground truth for stitch_family -- the
    real setup/repeat/turning_chain, backed by an actual hand-swatch.

    If this stitch family already has a CONFIRMED entry (confirmations
    non-empty) whose setup/repeat/turning_chain disagrees with this new
    confirmation, this does NOT silently overwrite established ground
    truth -- it raises ConfirmationConflictError naming exactly what
    disagreed, so a human decides (fix data/confirmed_stitch_patterns.json
    by hand, or realize this is actually a different stitch that
    happens to share a name).

    If the entry exists but was only ever proposed (never confirmed),
    or doesn't exist at all, this fills it in / creates it. Either way,
    appends a new {"photo", "date", "note"} confirmation record.
    """
    key = normalize_stitch_family(stitch_family)
    data = load_patterns()
    entry = data.get(key)

    confirmation = {
        "photo": photo_filename,
        "date": date or datetime.date.today().isoformat(),
        "note": note,
    }

    if entry is not None and entry["confirmations"]:
        conflicts = []
        if entry["setup"] != setup:
            conflicts.append(f"setup differs: existing confirmed {entry['setup']!r} vs new {setup!r}")
        if entry["repeat"] != repeat:
            conflicts.append(f"repeat differs: existing confirmed {entry['repeat']!r} vs new {repeat!r}")
        if entry["turning_chain"] != turning_chain:
            conflicts.append(
                f"turning_chain differs: existing confirmed {entry['turning_chain']} vs new {turning_chain}"
            )
        if conflicts:
            raise ConfirmationConflictError(
                f"New confirmation for '{stitch_family}' conflicts with the already-confirmed entry:\n"
                + "\n".join(f"  - {c}" for c in conflicts)
            )
        entry["confirmations"].append(confirmation)
    elif entry is not None:
        # Entry exists but was never confirmed (only ever proposed) --
        # fill it in now.
        entry["setup"] = setup
        entry["repeat"] = repeat
        entry["turning_chain"] = turning_chain
        entry["confirmations"] = [confirmation]
    else:
        entry = {
            "setup": setup,
            "repeat": repeat,
            "turning_chain": turning_chain,
            "confirmations": [confirmation],
            "last_ai_proposal": None,
        }
        data[key] = entry

    save_patterns(data)
    return entry
