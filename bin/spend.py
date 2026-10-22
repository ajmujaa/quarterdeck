#!/usr/bin/env python3
"""Where the tokens went. Reads state/spend.jsonl (one row per model call, written by bin/lib.sh record_spend from the call's envelope).

    spend.py [--days N] [DATA-FOLDER]     per duty and per seat: calls, turns, output, new input, cache reads, cost; and the top three sinks

The dashboard's Spend view uses the same functions (group, sinks), so the two never disagree.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIELDS = ("cost", "turns", "out", "in", "cache_read", "cache_write")
TEXT = ("at", "project", "duty", "seat", "model", "run", "fix", "effort", "billing", "provider", "key")


def rows(path):
    out = []
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                # review r9 D4: one malformed row cannot break the view of the rest: a time or name field
                # that is not text is dropped, a figure that is not a number counts 0
                if isinstance(r, dict):
                    out.append({k: (None if k in TEXT and not isinstance(v, str) else _num(v) if k in FIELDS else v) for k, v in r.items()})
    except FileNotFoundError:
        pass
    return out


def since(rows_, days):
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [r for r in rows_ if (r.get("at") or "") >= cut]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def group(rows_, key):
    """{name: {calls, reused, cost, turns, out, in, cache_read, cache_write}}, the dearest first. key is a field name or a function of a row."""
    g = {}
    for r in rows_:
        k = key(r) if callable(key) else r.get(key)
        if not k:
            continue
        a = g.setdefault(k, dict({f: 0 for f in FIELDS}, calls=0, reused=0))
        if r.get("reused"):
            a["reused"] += 1
        else:
            a["calls"] += 1
        for f in FIELDS:
            a[f] += _num(r.get(f))
    return dict(sorted(g.items(), key=lambda kv: -kv[1]["cost"]))


def sinks(rows_, n=3):
    """The n dearest project/duty pairs, each with what it cost per call: where a saving would show first."""
    g = group(rows_, lambda r: f"{r.get('project') or '-'}/{r.get('duty') or 'unknown'}")
    return [dict(v, what=k, per_call=v["cost"] / max(1, v["calls"]), turns_per_call=v["turns"] / max(1, v["calls"]))
            for k, v in list(g.items())[:n]]


def _table(title, g):
    print(f"\n{title}")
    print(f"  {'':24} {'calls':>5} {'turns/call':>10} {'output':>9} {'new in':>8} {'cache read':>11} {'cost':>9}")
    for k, v in g.items():
        c = max(1, v["calls"])
        extra = f"  ({v['reused']} reused)" if v["reused"] else ""
        print(f"  {k[:24]:24} {v['calls']:>5} {v['turns'] / c:>10.1f} {v['out']:>9,} {v['in']:>8,} {v['cache_read']:>11,} {'$%.2f' % v['cost']:>9}{extra}")


def main(argv):
    days, home = 7, None
    i = 0
    while i < len(argv):
        if argv[i] == "--days":
            if i + 1 >= len(argv) or not argv[i + 1].isdigit():
                print("usage: qtdeck spend [--days N]   (N is a number)", file=sys.stderr)
                return 2
            days = int(argv[i + 1]); i += 2
        else:
            home = argv[i]; i += 1
    if not home:
        print("usage: spend.py [--days N] <data-folder>", file=sys.stderr)
        return 2
    rs = since(rows(Path(home) / "state" / "spend.jsonl"), days)
    if not rs:
        print(f"no model calls recorded in the last {days} day(s)")
        return 0
    total = sum(_num(r.get("cost")) for r in rs)
    print(f"last {days} day(s): {sum(1 for r in rs if not r.get('reused'))} model call(s), ${total:.2f} (API-equivalent)")
    print("\ntop sinks")
    for s in sinks(rs):
        print(f"  {s['what'][:30]:30} ${s['cost']:.2f} over {s['calls']} call(s): ${s['per_call']:.2f} and {s['turns_per_call']:.0f} turns per call")
    _table("by duty", group(rs, "duty"))
    seats = group(rs, "seat")
    if seats:
        _table("by panel seat", seats)
    _table("by model", group(rs, "model"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
