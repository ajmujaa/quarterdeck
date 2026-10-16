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

Stdlib only. Read only."""
import argparse
import json
import re
import subprocess
import sys

DIR = "docs/decisions"
NAME = re.compile(r"^docs/decisions/(\d{4})-[a-z0-9-]+\.md$")


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=60)
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
    a = ap.parse_args(argv)
    if a.cmd == "select":
        changed = [x.strip() for x in open(a.files).read().splitlines() if x.strip()]
        print(json.dumps(select(a.repo, a.base, changed, open(a.context).read(), a.max, a.chars)))
    elif a.cmd == "next":
        print(next_number(a.repo, a.base))
    else:
        print(json.dumps(parse(open(a.file).read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
