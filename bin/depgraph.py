#!/usr/bin/env python3
"""The dependency graph: which parts of a project call which, and what a change could break elsewhere. Built by this program, never by a model.

The graph is not a file that can go stale. It is worked out each time from the project's base branch (git objects, nothing else is read):

  scanned   every folder with a package.json is a unit; unit A depends on unit B when B's package name is in A's dependencies
  declared  docs/architecture/dependencies.json, optional, for what a scan cannot see (queues, HTTP calls, other languages):
              {"services": {"billing": {"path": "services/billing/", "calls": {"users": "http /v1/users", "ledger-queue": "sqs"}}}}

    depgraph.py graph  --repo DIR --base BRANCH                       the units and edges, and where each came from
    depgraph.py impact --repo DIR --base BRANCH --files FILE          who depends on the units a change touches
    depgraph.py check  --repo DIR --base BRANCH                       where the declared graph and the code disagree (exit 1 when they do)
    depgraph.py suggest --repo DIR --base BRANCH                      the calls the declared graph is missing, as lines to add to it
    depgraph.py newproblems --repo DIR --base BRANCH --head REF       what a change adds to check's problems (exit 1 when it adds any)

Stdlib only. Read only."""
import argparse
import json
import re
import sys

import adr as _adr   # the same safe, base-branch-only git reader the records of decisions use

DECLARED = "docs/architecture/dependencies.json"
MAX_UNITS = 300        # package.json files read; a bigger tree is a repository of repositories, not one project
MAX_BYTES = 200_000    # one manifest
SKIP = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.git|\.venv)(/|$)")
KINDS = ("dependencies", "peerDependencies", "optionalDependencies", "devDependencies")
DEPTH = 3
MAX_LINES = 14         # what a review is shown; the rest is counted


def _json(repo, ref, path):
    out = _adr.git(repo, "show", f"{ref}:{path}")
    if out is None or len(out) > MAX_BYTES:
        return None
    try:
        v = json.loads(out)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def build(repo, base):
    """{"units": {name: path}, "edges": [{"from","to","how","source"}], "declared": bool, "cut": int}; units is empty when the base cannot be read."""
    ref = _adr.base_ref(repo, base)
    out = _adr.git(repo, "ls-tree", "-r", "--name-only", ref) if ref else None
    if not out:
        return {"units": {}, "edges": [], "declared": False, "listed": [], "cut": 0}
    manifests = [p for p in out.splitlines() if p.rsplit("/", 1)[-1] == "package.json" and not SKIP.search(p)]
    cut = max(0, len(manifests) - MAX_UNITS)
    scanned = {}   # package name -> {path, deps: {name: kind}}
    for p in manifests[:MAX_UNITS]:
        d = _json(repo, ref, p)
        name = d.get("name") if d else None
        folder = p[: -len("package.json")]
        if not isinstance(name, str) or not folder:   # the root package.json names the repository, not a part of it
            continue
        deps = {}
        for kind in reversed(KINDS):   # a runtime kind wins over dev when both list the name
            if isinstance(d.get(kind), dict):
                deps.update({k: kind for k in d[kind]})
        scanned[name] = {"path": folder, "deps": deps}
    units = {n: u["path"] for n, u in scanned.items()}
    edges = []
    for n, u in scanned.items():
        for dep, kind in sorted(u["deps"].items()):
            if dep in scanned and dep != n:
                edges.append({"from": n, "to": dep, "how": "dev dependency" if kind == "devDependencies" else "package dependency", "source": "scanned"})
    decl = _json(repo, ref, DECLARED) if _adr.git(repo, "cat-file", "-e", f"{ref}:{DECLARED}") is not None else None
    services = decl.get("services") if decl else None
    listed = []
    if isinstance(services, dict):
        for n, s in services.items():
            if not isinstance(s, dict):
                continue
            listed.append(n)
            if isinstance(s.get("path"), str):
                units.setdefault(n, s["path"].lstrip("/").rstrip("/") + "/")
            calls = s.get("calls")
            for to, how in (calls.items() if isinstance(calls, dict) else []):
                edges.append({"from": n, "to": to, "how": str(how)[:80], "source": "declared"})
    return {"units": units, "edges": edges, "declared": isinstance(services, dict), "listed": listed, "cut": cut}


def owner(units, path):
    """The unit a file belongs to: the longest folder that contains it."""
    best = None
    for n, p in units.items():
        if path.startswith(p) and (best is None or len(p) > len(units[best])):
            best = n
    return best


def impact(g, changed):
    """The units a change touches, and who depends on them, nearest first. Transitive to DEPTH."""
    units = g["units"]
    touched, unmapped = {}, 0
    for f in changed:
        o = owner(units, f)
        if o:
            touched[o] = touched.get(o, 0) + 1
        else:
            unmapped += 1
    callers = {}
    for e in g["edges"]:
        callers.setdefault(e["to"], []).append(e)
    seen, rows, frontier = set(touched), [], list(touched)
    for depth in range(1, DEPTH + 1):
        nxt = []
        for t in frontier:
            for e in sorted(callers.get(t, []), key=lambda e: (e["how"] == "dev dependency", e["from"])):
                if e["from"] in seen:
                    continue
                seen.add(e["from"]); nxt.append(e["from"])
                rows.append({"unit": e["from"], "calls": t, "how": e["how"], "source": e["source"], "depth": depth})
        frontier = nxt
    return {"touched": [{"unit": u, "files": c} for u, c in sorted(touched.items())], "dependents": rows, "unmapped": unmapped}


def check(g):
    """Declared claims the code contradicts. Only meaningful when a declared graph exists."""
    problems = []
    if not g["declared"]:
        return problems
    scanned = {(e["from"], e["to"]) for e in g["edges"] if e["source"] == "scanned"}
    declared = {(e["from"], e["to"]) for e in g["edges"] if e["source"] == "declared"}
    for a, b in sorted(declared):
        if b not in g["units"]:
            problems.append(f"{a} is declared to call {b}, which is not a unit in the project")
    for a, b in sorted(scanned - declared):
        if a in g["listed"]:
            problems.append(f"{a} depends on {b} in its package.json, but {DECLARED} does not say so")
    return problems


def suggest(g):
    """The calls the declared graph is missing, as lines to add: {"unit", "calls", "how"}. Only for units the declared file lists."""
    have = {(e["from"], e["to"]) for e in g["edges"] if e["source"] == "declared"}
    return [{"unit": e["from"], "calls": e["to"], "how": e["how"]} for e in g["edges"]
            if e["source"] == "scanned" and e["from"] in g["listed"] and (e["from"], e["to"]) not in have]


def render(imp):
    """The text a review is shown; empty when the change touches nothing with a caller."""
    if not imp["dependents"]:
        return ""
    lines = ["This change touches: " + ", ".join(f"{t['unit']} ({t['files']} file{'s' * (t['files'] != 1)})" for t in imp["touched"])]
    lines.append("Parts of the project that depend on it, nearest first (each could break):")
    for r in imp["dependents"][:MAX_LINES]:
        lines.append(f"- {r['unit']} {'calls' if r['depth'] == 1 else 'reaches, through the above,'} {r['calls']}: {r['how']} ({r['source']})")
    if len(imp["dependents"]) > MAX_LINES:
        lines.append(f"- and {len(imp['dependents']) - MAX_LINES} more")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("graph", "impact", "check", "text", "suggest", "newproblems"):
        s = sub.add_parser(name); s.add_argument("--repo", required=True); s.add_argument("--base", required=True)
        if name in ("impact", "text"):
            s.add_argument("--files", required=True)
        if name == "newproblems":
            s.add_argument("--head", required=True)
    a = ap.parse_args(argv)
    g = build(a.repo, a.base)
    if a.cmd == "graph":
        print(json.dumps(g))
    elif a.cmd == "suggest":
        print(json.dumps(suggest(g)))
    elif a.cmd == "newproblems":
        before = set(check(g)); new = [p for p in check(build(a.repo, a.head)) if p not in before]
        print(json.dumps({"problems": new}))
        return 1 if new else 0
    elif a.cmd == "check":
        problems = check(g)
        print(json.dumps({"declared": g["declared"], "problems": problems}))
        return 1 if problems else 0
    else:
        imp = impact(g, [x.strip() for x in open(a.files).read().splitlines() if x.strip()])
        print(json.dumps(imp) if a.cmd == "impact" else render(imp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
