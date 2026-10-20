#!/usr/bin/env python3
"""A project's guardrails: the rules every agent is given for it. Three are locked (never merge, never push to the default branch, never touch secrets)
and cannot be removed, edited or moved by the page, the command line or the API. The rest are the owner's own text, up to 20 of 300 characters each.

Every change goes through attach.edit and the registry's atomic 0600 write, and appends one line to logs/guardrails.log. A rule is text that reaches
the model as the project's rules, so it is scanned for credentials (outscan) and may not forge a prompt marker.

  qtdeck guardrail <project> list [--effective] | add "<text>" | remove <number|text> | move <number> up|down

The text the crew receives is effective_text(): "- rule" per line, the same bytes bin/lib.sh's project_guardrails prints into every prompt (the test
compares the two)."""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attach as _attach
import home as _home
import outscan as _outscan

LOCKED = [{"text": t, "reason": r} for t, r in _attach.LOCKED]
LOCKED_TEXTS = [x["text"] for x in LOCKED]
MAX_RULES = 20
MAX_CHARS = 300
MARKER = re.compile(r"(BEGIN|END)\s+UNTRUSTED", re.I)


def check_rule(text):
    """The text of one custom rule, trimmed, or ValueError saying in plain words what is wrong."""
    if not isinstance(text, str):
        raise ValueError("a guardrail is text")
    t = text.strip()
    shown = t[:40]
    if not t:
        raise ValueError("a guardrail cannot be empty")
    if "\n" in t or "\r" in t or " " in t or " " in t:
        raise ValueError(f"'{shown}' has a line break: a guardrail is one line")
    if _attach.CONTROL.search(t):
        raise ValueError(f"'{shown}' has a control character")
    if len(t) > MAX_CHARS:
        raise ValueError(f"'{shown}' is {len(t)} characters: a guardrail may hold at most {MAX_CHARS}")
    if "<!--" in t:
        raise ValueError(f"'{shown}' holds a comment marker, which the crew's prompts do not allow")
    if MARKER.search(t):
        raise ValueError(f"'{shown}' looks like a marker the prompts use for text from other people; reword it")
    if _outscan.scan_text(t):
        raise ValueError(f"This guardrail looks like a password, key or token. A guardrail is given to the model and written to a log; leave secrets out")
    return t


def normalise(items):
    """The full ordered list checked and arranged: the locked rules first and in their order, then the custom ones as written (trimmed). ValueError names
    the first locked rule that is missing or changed, with its reason, or the first custom rule that is not allowed."""
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        raise ValueError("guardrails must be a list of rules")
    for x in LOCKED:
        if x["text"] not in items:
            raise ValueError(f"'{x['text']}' is locked and stays as it is: {x['reason']}")
    custom, seen = [], set()
    for it in items:
        if it in LOCKED_TEXTS:
            if items.count(it) > 1:
                raise ValueError(f"'{it}' is listed twice")
            continue
        t = check_rule(it)
        k = " ".join(t.split()).casefold()
        if k in seen or k in (" ".join(x.split()).casefold() for x in LOCKED_TEXTS):
            raise ValueError(f"'{t[:40]}' is already a guardrail")
        seen.add(k)
        custom.append(t)
    if len(custom) > MAX_RULES:
        raise ValueError(f"a project may have at most {MAX_RULES} guardrails of its own; this list has {len(custom)}")
    return LOCKED_TEXTS + custom


def _stored(project, reg=None):
    cur = _attach.load_registry(reg or _attach.registry_path())
    ent = cur.get(project) if isinstance(project, str) else None
    if not isinstance(ent, dict):
        raise ValueError(f"'{str(project)[:60]}' is not registered (see: qtdeck projects)")
    g = ent.get("guardrails")
    return cur, [x for x in g if isinstance(x, str)] if isinstance(g, list) else []


def effective_of(items):
    """The text the crew receives for a list: one "- rule" per line (what lib.sh's project_guardrails prints)."""
    return "\n".join("- " + x for x in items)


def listing_of(items):
    items = [x for x in items if isinstance(x, str)]
    return {"locked": [dict(x) for x in LOCKED], "custom": [x for x in items if x not in LOCKED_TEXTS], "effective": effective_of(items),
            "missing_locked": [x for x in LOCKED_TEXTS if x not in items], "limit": MAX_RULES, "max_chars": MAX_CHARS}


def listing(project):
    return listing_of(_stored(project)[1])


def effective_text(project):
    return effective_of(_stored(project)[1])


def _clip(t):
    return " ".join(str(t).split())[:120]


def _log(project, action, text, count):
    try:
        d = _home.resolve() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "guardrails.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {project} {action} {count} {_clip(text)}\n")
    except OSError:
        pass                                           # a note that could not be written never undoes the change


def replace(project, items, action=None, detail=None):
    """Save the full ordered list the page shows. Returns the new listing. ValueError (nothing written) when a locked rule is missing or a rule is not allowed."""
    cur, old = _stored(project)
    new = _attach.edit({"entry": {"duties": [], "verify": "", "guardrails": old}}, {"guardrails": items})["entry"]["guardrails"]
    if new == old:
        return listing_of(new)
    cur[project]["guardrails"] = new
    _attach.write_registry(cur)
    n = len(new) - len(LOCKED_TEXTS)
    if action:
        _log(project, action, detail if detail is not None else "", n)
    else:
        gone, came = [x for x in old if x not in new], [x for x in new if x not in old]
        for x in gone:
            _log(project, "remove", x, n)
        for x in came:
            _log(project, "add", x, n)
        if not gone and not came:
            _log(project, "reorder", "", n)
    return listing_of(new)


def _custom(project):
    return listing(project)["custom"]


def add(project, text):
    t = check_rule(text)
    cur = _custom(project)
    return replace(project, LOCKED_TEXTS + cur + [t], "add", t)


def _find(project, ref):
    """(index in the custom list, its text) for a 1-based number or the exact text; ValueError for a locked rule or no match."""
    cur = _custom(project)
    r = str(ref).strip()
    for x in LOCKED:
        if r == x["text"]:
            raise ValueError(f"'{x['text']}' is locked and stays as it is: {x['reason']}")
    if r.isdigit():
        n = int(r)
        if 1 <= n <= len(cur):
            return cur, n - 1
        raise ValueError(f"there is no guardrail number {n}: this project has {len(cur)} of its own")
    if r in cur:
        return cur, cur.index(r)
    raise ValueError(f"no guardrail says '{r[:40]}' (see: qtdeck guardrail {project} list)")


def remove(project, ref):
    cur, i = _find(project, ref)
    gone = cur.pop(i)
    return replace(project, LOCKED_TEXTS + cur, "remove", gone)


def move(project, ref, direction):
    if direction not in ("up", "down"):
        raise ValueError("move it up or down")
    cur, i = _find(project, ref)
    j = i - 1 if direction == "up" else i + 1
    if not 0 <= j < len(cur):
        raise ValueError(f"it is already the {'first' if direction == 'up' else 'last'} guardrail of the project's own")
    cur[i], cur[j] = cur[j], cur[i]
    return replace(project, LOCKED_TEXTS + cur, "move", cur[j])


def _n(p):
    n = len(listing(p)["custom"])
    return f"{n} guardrail{'' if n == 1 else 's'} of its own"


def main(argv):
    usage = ('usage: qtdeck guardrail <project> list [--effective]\n       qtdeck guardrail <project> add "<text>"\n'
             '       qtdeck guardrail <project> remove <number|text>\n       qtdeck guardrail <project> move <number> up|down')
    if len(argv) >= 2 and argv[0] == "effective":           # for tests and scripts: the exact text, nothing else
        try:
            print(effective_text(argv[1]))
        except ValueError as e:
            print("qtdeck: " + str(e), file=sys.stderr)
            return 2
        return 0
    if len(argv) < 2 or argv[1] not in ("list", "add", "remove", "move"):
        print(usage, file=sys.stderr)
        return 2
    p, sub, rest = argv[0], argv[1], argv[2:]
    try:
        if sub == "list":
            if rest not in ([], ["--effective"]):
                print(usage, file=sys.stderr)
                return 2
            ls = listing(p)
            if rest:
                print(ls["effective"])
                return 0
            print(f"Guardrails for {p}:")
            for x in ls["locked"]:
                print(f"  locked  {x['text']}\n          {x['reason']}")
            for i, x in enumerate(ls["custom"], 1):
                print(f"  {i:>2}.    {x}")
            if not ls["custom"]:
                print("  (no guardrails of your own yet: qtdeck guardrail " + p + ' add "<text>")')
            print(f"This is what the crew receives. The exact text: qtdeck guardrail {p} list --effective")
            return 0
        if sub == "add" and len(rest) == 1:
            add(p, rest[0])
            print(f"Added. {p} now has {_n(p)}.")
        elif sub == "remove" and len(rest) == 1:
            remove(p, rest[0])
            print(f"Removed. {p} now has {_n(p)}.")
        elif sub == "move" and len(rest) == 2:
            move(p, rest[0], rest[1])
            print(f"Moved {rest[1]}.")
        else:
            print(usage, file=sys.stderr)
            return 2
    except ValueError as e:
        print("qtdeck: " + str(e), file=sys.stderr)
        return 2
    except OSError as e:
        print("qtdeck: could not write the registry: " + type(e).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
