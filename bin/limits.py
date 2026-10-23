#!/usr/bin/env python3
"""Your own spend limits: the three dollar amounts in config/quarterdeck.env that the Settings page can change.

  call   QUARTERDECK_CALL_BUDGET    the most one model call may spend
  cycle  QUARTERDECK_CYCLE_BUDGET   the most one `qtdeck cycle` may spend
  day    QUARTERDECK_DAILY_BUDGET   where queued and scheduled work stops for the day

A value you set is written to YOUR copy of the file, in the data folder, as a plain line (NAME="12.5"). The shipped file is never touched, and the
shell sources yours after it, so yours wins. Resetting removes the line. Only a plain dollar amount is ever written: that is what keeps the file safe to source.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from integrations import common                                       # noqa: E402

NAMES = {"call": "QUARTERDECK_CALL_BUDGET", "cycle": "QUARTERDECK_CYCLE_BUDGET", "day": "QUARTERDECK_DAILY_BUDGET"}
AMOUNT = re.compile(r"\d{1,6}(\.\d{1,2})?")


def amount(v):
    """The dollar amount as text ('12.5'), or None if it is not a plain amount above zero (below a million, cents allowed)."""
    s = str(v).strip() if isinstance(v, (int, float, str)) and not isinstance(v, bool) else ""
    return s if AMOUNT.fullmatch(s) and float(s) > 0 else None


def check(values):
    """values: {call, cycle, day} as they would be after the change (text or None). A sentence for the first problem, else ''."""
    for k, v in values.items():
        if v is not None and amount(v) is None:
            return f"The {k} limit is an amount in dollars, like 12.50: above zero, below one million, cents at most."
    c, y = values.get("call"), values.get("cycle")
    if c is not None and y is not None and float(c) > float(y):
        return "The per-call limit cannot be more than the per-cycle limit: a cycle would never start a stage."
    return ""


def write(home, updates):
    """updates: {call|cycle|day: text, or None to go back to the default}. Rewrites only those lines of <home>/config/quarterdeck.env."""
    p = Path(home) / "config" / "quarterdeck.env"
    try:
        text = p.read_text()
    except FileNotFoundError:
        text = "# Your own settings. These win over the shipped config/quarterdeck.env.\n"
    for k, v in updates.items():
        name = NAMES[k]
        text = re.sub(rf"^{name}=.*\n?", "", text, flags=re.M)
        if v is not None:
            text = text.rstrip("\n") + "\n" + f'{name}="{amount(v)}"\n'
    common.write_private(p, text)
