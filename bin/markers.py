#!/usr/bin/env python3
"""The marks Quarterdeck writes into GitHub bodies, and the one place that reads them.

    REQ_OPEN ... REQ_CLOSE   the purser's requirements block in an issue body
    PR_SIGNS                 a pull request body Quarterdeck wrote carries one of these

Everything that WRITES uses REQ_OPEN, REQ_CLOSE and "<!-- quarterdeck:v1 ... -->". Everything that READS goes through
the functions below, which also accept the older forms listed in bin/legacy_markers.py when that file is present.

    markers.py checks < body    the requirements block's text, or the whole body when there is none
    markers.py strip < body     the body with every requirements block taken out (a block missing one mark is left as it is)
"""
import re
import sys
from pathlib import Path

REQ_OPEN, REQ_CLOSE = "<!-- quarterdeck:requirements -->", "<!-- /quarterdeck:requirements -->"
PR_SIGNS = ("<!-- quarterdeck:", "Checked locally before this branch was pushed")
REQ_PAIRS = [(REQ_OPEN, REQ_CLOSE)]

# remove after migration, and only once issues and pull requests written before the rename no longer matter: their older marks
_old = Path(__file__).with_name("legacy_markers.py")
if _old.is_file():
    _ns = {}
    exec(compile(_old.read_text(), str(_old), "exec"), _ns)
    REQ_PAIRS += list(_ns.get("REQ_PAIRS", ()))
    PR_SIGNS += tuple(_ns.get("PR_SIGNS", ()))


def _find(body):
    """(start, end, open, close) of the first complete block, or None."""
    best = None
    for o, c in REQ_PAIRS:
        i = body.find(o)
        j = body.find(c, i + len(o)) if i >= 0 else -1
        if i >= 0 and j >= 0 and (best is None or i < best[0]):
            best = (i, j, o, c)
    return best


def has_requirements(body):
    return _find(body or "") is not None


def requirements(body):
    """The text inside the requirements block, or None."""
    f = _find(body or "")
    return body[f[0] + len(f[2]):f[1]].strip() if f else None


def strip(body):
    """The body with every complete requirements block (any form) taken out, and nothing else touched."""
    for o, c in REQ_PAIRS:
        body = re.sub(r"\n*" + re.escape(o) + r".*?" + re.escape(c) + r"\n*", "\n", body, flags=re.S)
    return body.strip()


def normalise(body):
    """The body with an older block's marks written as the current ones, so the page needs to know only one form."""
    if not isinstance(body, str):
        return body
    for o, c in REQ_PAIRS[1:]:
        if o in body and c in body:
            body = body.replace(o, REQ_OPEN).replace(c, REQ_CLOSE)
    return body


def signed(body):
    """Whether a pull request body carries a Quarterdeck signature (any form)."""
    return any(s in (body or "") for s in PR_SIGNS)


if __name__ == "__main__":
    text = sys.stdin.read()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "checks":
        r = requirements(text)
        print(r if r is not None else text.strip())
    elif cmd == "strip":
        print(strip(text))
    else:
        sys.exit("usage: markers.py checks|strip < body")
