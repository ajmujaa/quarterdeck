#!/usr/bin/env python3
"""The Logkeeper's injector: which records of decisions a review is shown. Chosen by this program, never by a model.

Records live in the project's own repository, in a folder named decisions, adr or adrs (docs/decisions/ by default; docs/architecture/decisions/
and docs/adr/ are found too), as NNNN-slug.md, and are read from git objects of the base branch (nothing outside the registered project is
read). A record may carry two header lines the harness matches on:

    Paths: src/crypto/, lib/keys.ts          a changed file starting with one of these matches
    Keywords: encryption, key rotation       a keyword found in the diff's files, title or issue text matches

A record without those lines still matches: the harness reads the paths it names in backticks (kept only when they exist in the repository), and
the words of its file name (two of them must appear). Its status may be a "Status:" line or a "## Status" section.

    adr.py select --repo DIR --base BRANCH --files FILE --context FILE [--max N] [--chars N]
        prints one JSON object: {"searched": ["0001", ...], "records": [{"n","title","score","text"}], "cut": int}
    adr.py next   --repo DIR --base BRANCH           prints the next free number, zero padded
    adr.py dir    --repo DIR --base BRANCH           prints {"dir", "count"}: where the records are (dir is "" when there are none)
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

DIR = "docs/decisions"       # where a new record goes when the project has none yet
NAME = re.compile(r"^(?:.+/)?(?:decisions|adrs?)/(\d{4})-[a-z0-9-]+\.md$")
_SKIP = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.git|\.venv)(/|$)")


def locate(paths):
    """(folder, [record paths]) from a list of repository paths: the folder named decisions, adr or adrs with the most NNNN-slug.md records in it,
    docs/decisions first on a tie. ("", []) when there are none."""
    found = {}
    for p in paths:
        m = NAME.match(p)
        if m and not _SKIP.search(p):
            found.setdefault(p.rsplit("/", 1)[0], []).append(p)
    if not found:
        return "", []
    best = sorted(found, key=lambda d: (-len(found[d]), d != DIR, d))[0]
    return best, sorted(found[best])


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


def tree(repo, ref):
    return (git(repo, "ls-tree", "-r", "--name-only", ref) or "").splitlines() if ref else []


def files(repo, base):
    """{number: path} of the records on the base branch, wherever the project keeps them."""
    found = {}
    for path in locate(tree(repo, base_ref(repo, base)))[1]:
        found[NAME.match(path).group(1)] = path
    return found


def parse(text):
    """Title, status, paths, keywords from a record's text. Tolerant: a record without the lines matches nothing."""
    title = next((re.sub(r"^#\s*(?:ADR\s+)?\d*[.:\- ]*", "", ln).strip() for ln in text.splitlines() if ln.startswith("#")), "")
    def line(key):
        m = re.search(rf"^{key}:[ \t]*(.*)$", text, re.I | re.M)
        return m.group(1).strip() if m else ""
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    status = line("Status")
    if not status:   # a "## Status" section: its first line of text
        m = re.search(r"^#{1,6}[ \t]*Status[ \t]*$\s*(.*)$", text, re.I | re.M)
        status = m.group(1).strip() if m else ""
    return {"title": title, "status": re.sub(r"[*_`]", "", status).lower(), "paths": split(line("Paths")), "keywords": split(line("Keywords"))}


STOP = {"about", "after", "before", "between", "first", "other", "their", "there", "which", "while", "with", "without", "using", "every", "shared", "runs", "that", "this", "from", "into"}


def infer(text, slug, known, skip_dir):
    """Matching for a record that carries no Paths: or Keywords: lines. Paths: what the text names in backticks, kept only when it exists in the
    repository (known = every file and folder), is not another record and is not a document. Keywords: the words of the file name."""
    paths = []
    for tok in re.findall(r"`([A-Za-z0-9_./@-]+)`", text):
        tok = tok.lstrip("./").rstrip("/")
        if tok.count("/") < 1 or tok.endswith(".md") or tok.startswith(skip_dir) or tok in paths:
            continue
        if tok in known or (tok + "/") in known:
            paths.append(tok + "/" if (tok + "/") in known else tok)
    words = [w for w in slug.split("-") if len(w) >= 5 and w not in STOP]
    return paths[:10], words[:8]


def score(rec, changed, context):
    low = context.lower()
    hits = sum(1 for p in rec["paths"] if any(f.startswith(p) for f in changed)) * 2
    hits += sum(1 for k in rec["keywords"] if k.lower() in low) * (0.5 if rec.get("inferred") else 1)
    return hits


def select(repo, base, changed, context, max_n=5, chars=6000):
    ref = base_ref(repo, base)
    all_paths = tree(repo, ref)
    folder = locate(all_paths)[0]
    recs = files(repo, base)
    out, searched = [], sorted(recs)
    low = (context + "\n" + "\n".join(changed))
    known = None
    for n, path in sorted(recs.items()):
        text = git(repo, "show", f"{ref}:{path}") or ""
        h = parse(text)
        if h["status"].startswith(("superseded", "rejected", "deprecated")):
            continue
        if not h["paths"] and not h["keywords"]:
            if known is None:
                known = set(all_paths) | {p.rsplit("/", i)[0] + "/" for p in all_paths for i in range(1, p.count("/") + 1)}
            h["paths"], h["keywords"] = infer(text, path.rsplit("/", 1)[-1][5:-3], known, folder)
            h["inferred"] = True
        s = score(h, changed, low)
        if s >= (1 if h.get("inferred") else 0.5):
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
    folder = locate(tree(repo, ref))[0] or DIR
    out = git(repo, "ls-tree", "-r", "--name-only", ref, folder + "/")
    defects, by_number = [], {}
    for path in sorted((out or "").splitlines()):
        name = path.rsplit("/", 1)[-1]
        if not name.endswith(".md") or name.lower() == "readme.md" or path.count("/") != folder.count("/") + 1:
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
    all_paths = tree(repo, ref)
    folder = locate(all_paths)[0]
    leads, known = [], None
    for n, path in sorted(files(repo, base).items()):
        text = git(repo, "show", f"{ref}:{path}") or ""
        h = parse(text)
        if h["status"].startswith(("superseded", "rejected", "deprecated")):
            continue
        if not h["paths"] and not h["keywords"]:   # matched by what it names, as select() does: only a record that names nothing real is a lead
            if known is None:
                known = set(all_paths) | {q.rsplit("/", i)[0] + "/" for q in all_paths for i in range(1, q.count("/") + 1)}
            h["paths"], h["keywords"] = infer(text, path.rsplit("/", 1)[-1][5:-3], known, folder)
            h["inferred"] = True
            if not h["paths"]:
                if not h["keywords"]:
                    leads.append({"n": n, "title": h["title"], "why": "it names no Paths or Keywords and no real path in the text, so no review is ever shown it"})
                continue   # only its file name's words: too loose to call out as moved on
        if not h["paths"]:
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
            leads.append({"n": n, "title": h["title"], "why": f"{busy} commits touched its Paths since the record last changed", "busy": int(busy)})
    # the most likely to be out of date first: paths gone, then the busiest
    return sorted(leads, key=lambda l: (l.get("busy") is not None, -(l.get("busy") or 0), l["n"]))


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
    dd = sub.add_parser("dir"); dd.add_argument("--repo", required=True); dd.add_argument("--base", required=True)
    c = sub.add_parser("check"); c.add_argument("--repo", required=True); c.add_argument("--ref", required=True)
    st = sub.add_parser("stale"); st.add_argument("--repo", required=True); st.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "select":
        changed = [x.strip() for x in open(a.files).read().splitlines() if x.strip()]
        print(json.dumps(select(a.repo, a.base, changed, open(a.context).read(), a.max, a.chars)))
    elif a.cmd == "next":
        print(next_number(a.repo, a.base))
    elif a.cmd == "dir":
        folder, recs = locate(tree(a.repo, base_ref(a.repo, a.base)))
        print(json.dumps({"dir": folder, "count": len(recs)}))
    elif a.cmd == "check":
        d = check(a.repo, a.ref)
        folder, recs = locate(tree(a.repo, a.ref))
        print(json.dumps({"problems": d, "records": len(recs), "dir": folder}))
        return 1 if d else 0
    elif a.cmd == "stale":
        print(json.dumps(stale(a.repo, a.base)))
    else:
        print(json.dumps(parse(open(a.file).read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
