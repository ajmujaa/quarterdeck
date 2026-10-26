#!/usr/bin/env python3
"""The Logkeeper's injector: which records of decisions a review is shown. Chosen by this program, never by a model.

Records live in the project's own repository, docs/decisions/NNNN-slug.md, and are read from git objects of the base
branch (nothing outside the registered project is read). Each record carries two header lines the harness matches on:

    Paths: src/crypto/, lib/keys.ts          a changed file starting with one of these matches
    Keywords: encryption, key rotation       a keyword found in the diff's files, title or issue text matches

    adr.py select --repo DIR --base BRANCH --files FILE --context FILE [--max N] [--chars N]
        prints one JSON object: {"searched": ["0001", ...], "records": [{"n","title","score","text"}], "cut": int}
    adr.py next   --repo DIR --base BRANCH           prints the next free number, zero padded
    adr.py parse  FILE                               prints the parsed header of one record (for the checks)
    adr.py check  --repo DIR --ref REF               what is wrong with the records themselves: two with one number, a name or heading that does
                                                     not carry its number (exit 1 when any). Reads names and headings only.
    adr.py stale  --repo DIR --base BRANCH           leads, not verdicts: records whose Paths are gone or have moved on since the record was written

Stdlib only. Read only."""
import argparse
import json
import re
import subprocess
import sys

import safegit as _safegit

DIR = "docs/decisions"
NAME = re.compile(r"^docs/decisions/(\d{4})-[a-z0-9-]+\.md$")


def git(repo, *args):
    """git against the project's repository, through bin/safegit.py; None for any failure, including a repository it refuses to touch."""
    try:
        r = _safegit.run(repo, *args, text=True, timeout=60)
    except (_safegit.Untrusted, OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def base_ref(repo, base):
    for ref in (f"origin/{base}", base):
        if git(repo, "rev-parse", "--verify", "-q", ref) is not None:
            return ref
    return None


def files(repo, base):
    """{number: path} of the records on the base branch."""
    ref = base_ref(repo, base)
    out = git(repo, "ls-tree", "-r", "--name-only", ref, DIR + "/") if ref else None
    found = {}
    for line in (out or "").splitlines():
        m = NAME.match(line.strip())
        if m:
            found[m.group(1)] = line.strip()
    return found


def parse(text):
    """Title, status, paths, keywords from a record's text. Tolerant: a record without the lines matches nothing."""
    title = next((re.sub(r"^#\s*\d*[.:\- ]*", "", ln).strip() for ln in text.splitlines() if ln.startswith("#")), "")
    def line(key):
        m = re.search(rf"^{key}:[ \t]*(.*)$", text, re.I | re.M)
        return m.group(1).strip() if m else ""
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    return {"title": title, "status": line("Status").lower(), "paths": split(line("Paths")), "keywords": split(line("Keywords"))}


def score(rec, changed, context):
    low = context.lower()
    hits = sum(1 for p in rec["paths"] if any(f.startswith(p) for f in changed)) * 2
    hits += sum(1 for k in rec["keywords"] if k.lower() in low)
    return hits


def select(repo, base, changed, context, max_n=5, chars=6000):
    recs = files(repo, base)
    ref = base_ref(repo, base)
    out, searched = [], sorted(recs)
    low = (context + "\n" + "\n".join(changed))
    for n, path in sorted(recs.items()):
        text = git(repo, "show", f"{ref}:{path}") or ""
        h = parse(text)
        if h["status"].startswith(("superseded", "rejected", "deprecated")):
            continue
        s = score(h, changed, low)
        if s > 0:
            out.append({"n": n, "title": h["title"], "score": s, "text": text})
    out.sort(key=lambda r: (-r["score"], r["n"]))
    out, cut, used = out[:max_n], 0, 0
    kept = []
    for r in out:
        room = chars - used
        if room < 150:
            cut += 1
            continue
        if len(r["text"]) > room:
            r["text"] = r["text"][:room].rstrip() + "\n[record cut here to fit the size limit]"
        used += len(r["text"])
        kept.append(r)
    return {"searched": searched, "records": kept, "cut": cut + max(0, len(out) - len(kept) - cut)}


HEADING = re.compile(r"^#\s*(?:ADR\s+)?(\d{4})\b")
MOVED = 20     # commits on a record's Paths since the record last changed, before it is called out


def check(repo, ref):
    """What is wrong with the records themselves, as sentences. A record that is misnamed, or that shares its number, can be cited ambiguously
    (or never matched at all: files() skips a name it cannot read). Reads file names and first headings only, never what a record decides."""
    out = git(repo, "ls-tree", "-r", "--name-only", ref, DIR + "/")
    defects, by_number = [], {}
    for path in sorted((out or "").splitlines()):
        name = path.rsplit("/", 1)[-1]
        if not name.endswith(".md") or name.lower() == "readme.md" or path.count("/") != DIR.count("/") + 1:
            continue
        m = NAME.match(path)
        if not m:
            defects.append(f"{path}: not named NNNN-slug.md (lower case, digits, hyphens), so it is never matched and nothing can cite it by number")
            continue
        by_number.setdefault(m.group(1), []).append(path)
        head = next((ln for ln in (git(repo, "show", f"{ref}:{path}") or "").splitlines() if ln.startswith("#")), "")
        h = HEADING.match(head)
        if not h:
            defects.append(f"{path}: its first heading does not start with its number ({m.group(1)})")
        elif h.group(1) != m.group(1):
            defects.append(f"{path}: the heading says {h.group(1)} but the file name says {m.group(1)}")
    for n, paths in sorted(by_number.items()):
        if len(paths) > 1:
            defects.append(f"number {n} is used by {len(paths)} records: " + ", ".join(p.rsplit("/", 1)[-1] for p in paths))
    return defects


def stale(repo, base):
    """Records that may no longer describe the code: [{"n","title","why"}]. A lead for a person to read, never a verdict: a record about a rule
    can stay true while its folder is busy. Only records that are still in force (not superseded, rejected or deprecated)."""
    ref = base_ref(repo, base)
    leads = []
    for n, path in sorted(files(repo, base).items()):
        h = parse(git(repo, "show", f"{ref}:{path}") or "")
        if h["status"].startswith(("superseded", "rejected", "deprecated")):
            continue
        if not h["paths"]:
            if not h["keywords"]:
                leads.append({"n": n, "title": h["title"], "why": "it has no Paths: and no Keywords: line, so no review is ever shown it"})
            continue
        gone = [p for p in h["paths"] if not (git(repo, "ls-tree", "--name-only", ref, "--", p) or "").strip()]
        if len(gone) == len(h["paths"]):
            leads.append({"n": n, "title": h["title"], "why": "none of its Paths exist on " + base + " any more (" + ", ".join(gone) + "): moved, renamed or removed"})
            continue
        if gone:
            leads.append({"n": n, "title": h["title"], "why": "some of its Paths are gone: " + ", ".join(gone)})
        written = (git(repo, "log", "-1", "--format=%H", ref, "--", path) or "").strip()
        live = [p for p in h["paths"] if p not in gone]
        busy = (git(repo, "rev-list", "--count", f"{written}..{ref}", "--", *live) or "0").strip() if written else "0"
        if busy.isdigit() and int(busy) >= MOVED:
            leads.append({"n": n, "title": h["title"], "why": f"{busy} commits touched its Paths since the record last changed"})
    return leads


def next_number(repo, base):
    recs = files(repo, base)
    return "%04d" % (max([int(n) for n in recs] or [0]) + 1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select"); s.add_argument("--repo", required=True); s.add_argument("--base", required=True)
    s.add_argument("--files", required=True); s.add_argument("--context", required=True)
    s.add_argument("--max", type=int, default=5); s.add_argument("--chars", type=int, default=6000)
    n = sub.add_parser("next"); n.add_argument("--repo", required=True); n.add_argument("--base", required=True)
    p = sub.add_parser("parse"); p.add_argument("file")
    c = sub.add_parser("check"); c.add_argument("--repo", required=True); c.add_argument("--ref", required=True)
    st = sub.add_parser("stale"); st.add_argument("--repo", required=True); st.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "select":
        changed = [x.strip() for x in open(a.files).read().splitlines() if x.strip()]
        print(json.dumps(select(a.repo, a.base, changed, open(a.context).read(), a.max, a.chars)))
    elif a.cmd == "next":
        print(next_number(a.repo, a.base))
    elif a.cmd == "check":
        d = check(a.repo, a.ref)
        print(json.dumps({"problems": d}))
        return 1 if d else 0
    elif a.cmd == "stale":
        print(json.dumps(stale(a.repo, a.base)))
    else:
        print(json.dumps(parse(open(a.file).read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
