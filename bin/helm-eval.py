#!/usr/bin/env python3
"""How well does Helm's local model understand free-form requests? Runs a labelled
set through the real /api/understand and prints what it got wrong. Needs the
dashboard running and the model installed; not part of selftest because it loads
a 2 GB model."""
import json, re, runpy, sys, urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
tok = (root / "state" / "dashboard.token").read_text().strip()
VIEWS = [("overview", "Home"), ("brain", "Brain"), ("missions", "Missions"), ("inbox", "Needs you"), ("operations", "Operations"),
         ("panels", "Panels"), ("documents", "Documents"), ("board", "Board"), ("prs", "Pull requests"), ("spend", "Spend"),
         ("crew", "Crew"), ("ledger", "Ledger"), ("log", "Log")]
CASES = [  # phrase, expected intent, expected extras
    ("how's the crew doing", "running", {}),
    ("what are the agents up to right now", "running", {}),
    ("is anything running", "running", {}),
    ("what did the agents get up to overnight", "brief", {}),
    ("catch me up on what happened", "brief", {}),
    ("what should I do next", "next", {}),
    ("what needs my attention", "next", {}),
    ("what's on my calendar", "agenda", {}),
    ("do I have any meetings today", "agenda", {}),
    ("what do I need to remember", "reminders", {}),
    ("take me to the board for wayfarer web", "go", {"view": "board", "project": "wayfarer-web"}),
    ("show me the pull requests", "go", {"view": "prs"}),
    ("open the ledger for wayfarer mobile", "go", {"view": "ledger", "project": "wayfarer-mobile"}),
    ("how much has this cost me", "go", {"view": "spend"}),
    ("show me the second brain", "go", {"view": "brain"}),
    ("switch to saltpan-blog", "project", {"project": "saltpan-blog"}),
    ("let's look at brand", "project", {"project": "brand-site"}),
    ("jot down that I should call the dentist", "capture", {}),
    ("remind me to buy milk", "capture", {}),
    ("where did I put the notes about brand", "find", {}),
    ("find my memory about the telephony bug", "find", {}),
    ("start work on issue thirteen for no me mobile", "work", {"issue": 13, "project": "wayfarer-mobile"}),
    ("analyse issue twenty one on wayfarer web", "work", {"issue": 21, "action": "analyse"}),
    ("what's the weather like", "none", {}),
    ("tell me a joke", "none", {}),
    ("hello", ("none", "clarify"), {}),
    ("run the surveyor on wayfarer mobile", "run", {"duty": "surveyor", "project": "wayfarer-mobile"}),
    ("can you have the surveyor look at wayfarer web", "run", {"duty": "surveyor", "project": "wayfarer-web"}),
    ("review pull request twelve on saltpan-blog and apply it", "run", {"duty": "surveyor", "project": "saltpan-blog", "apply": True, "pr": 12}),
    ("stop the shipwright on wayfarer mobile", "halt", {"duty": "shipwright", "project": "wayfarer-mobile"}),
    ("dismiss the surveyor signal", "ack", {}),
    ("plan offline mode for wayfarer mobile", "plan", {"project": "wayfarer-mobile", "panel": False}),
    ("plan a dark theme for wayfarer web and get the panel to look at it", "plan", {"project": "wayfarer-web", "panel": True}),
    ("what did the panel say about onboarding", "panelsay", {}),
    ("what are my open missions", "missions", {}),
]

# An add-on's own cases sit beside this file as helm-eval-ext-<name>.py, each defining VIEWS and CASES.
for _f in sorted(Path(__file__).resolve().parent.glob("helm-eval-ext-*.py")):
    _x = runpy.run_path(str(_f))
    VIEWS += _x["VIEWS"]
    CASES += _x["CASES"]

def ask(text):
    req = urllib.request.Request("http://127.0.0.1:7878/api/understand",
        json.dumps({"text": text, "views": [{"id": i, "label": l} for i, l in VIEWS]}).encode(),
        {"Content-Type": "application/json", "X-Quarterdeck-Token": tok})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())

ok = 0
for text, intent, extra in CASES:
    got = ask(text)
    good = (got.get("intent") in intent if isinstance(intent, tuple) else got.get("intent") == intent) and all(got.get(k) == v for k, v in extra.items())
    ok += good
    if not good or "-v" in sys.argv:
        print(("ok   " if good else "MISS ") + f"{text!r}\n       got {got}  want {intent} {extra}")
print(f"{ok}/{len(CASES)} understood")
sys.exit(0 if ok >= len(CASES) * 0.85 else 1)
