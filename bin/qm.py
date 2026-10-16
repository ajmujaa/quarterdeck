#!/usr/bin/env python3
"""The Quartermaster's harness-side facts. Plain parsing and plain search; no model, no network, no install.

    qm.py bumps    --repo DIR --base REF --head REF [--files FILE]     what a pull request bumps, and what else arrived in the lockfile
    qm.py classify --stated TEXT --versions FILE --from X --to Y       is a stated patch really a patch, or a major hiding in a minor
    qm.py usage    --repo DIR --pkg NAME [--idents a,b]                where the repository imports the package, and uses named APIs
    qm.py idents   --notes FILE                                        the names a changelog says were removed or changed
    qm.py inject   --notes FILE                                        text in a changelog that talks to a reader (an instruction)
    qm.py releases --from X --to Y < releases.json                     the release notes between two versions

Files are read from git objects of the registered project (`git show REF:path`) or from the project's own worktree; nothing
outside the project is opened. Each command prints one JSON object. Stdlib only."""
import argparse
import json
import os
import re
import subprocess
import sys

SKIP = {"node_modules", ".git", "vendor", "dist", "build", ".next", "__pycache__", "coverage", ".venv", "venv"}
LOCKS = {"package-lock.json", "npm-shrinkwrap.json"}
SRC = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".py")


def show(repo, ref, path):
    r = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else None


def parse(v):
    """(major, minor, patch, prerelease?) of a version string, or None."""
    m = re.match(r"^[v=^~ ]*(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.-]+)?", str(v or ""))
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), bool(m.group(4))) if m else None


def kind(a, b):
    x, y = parse(a), parse(b)
    if not x or not y:
        return "unknown"
    if x[:3] == y[:3]:
        return "pre" if (x[3] or y[3]) and x[3] != y[3] else "same"
    if y[:3] < x[:3]:
        return "downgrade"
    if y[0] != x[0]:
        return "major"
    if y[1] != x[1]:
        return "minor"
    return "patch"


def lock_packages(text):
    """{name: {version, license, install, key}} from an npm lockfile, any version of the format."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    out = {}
    for key, p in (data.get("packages") or {}).items():
        if not key or "node_modules/" not in key or not isinstance(p, dict) or p.get("link"):
            continue
        name = p.get("name") or key.rsplit("node_modules/", 1)[1]
        out[name] = {"version": p.get("version", ""), "license": str(p.get("license", "")), "install": bool(p.get("hasInstallScript")), "key": key}
    for name, p in (data.get("dependencies") or {}).items():
        if isinstance(p, dict) and name not in out:
            out[name] = {"version": p.get("version", ""), "license": "", "install": False, "key": name}
    return out


def manifest_deps(text):
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    out = {}
    for sec in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        out.update({k: str(v) for k, v in (data.get(sec) or {}).items()})
    return out


def requirements(text):
    out = {}
    for ln in (text or "").splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([0-9A-Za-z.+-]+)", ln)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def bumps(repo, base, head, files):
    res, seen = [], set()
    newdeps, scripts, licences = [], [], []
    dirs = sorted({os.path.dirname(f) for f in files if os.path.basename(f) in LOCKS | {"package.json"} or re.match(r"requirements.*\.txt$", os.path.basename(f))})
    for d in dirs:
        join = lambda n: (d + "/" + n) if d else n
        mb, mh = show(repo, base, join("package.json")), show(repo, head, join("package.json"))
        db, dh = manifest_deps(mb), manifest_deps(mh)
        lb, lh = lock_packages(show(repo, base, join("package-lock.json")) or show(repo, base, join("npm-shrinkwrap.json"))), \
                 lock_packages(show(repo, head, join("package-lock.json")) or show(repo, head, join("npm-shrinkwrap.json")))
        if lb or lh:
            for name, p in sorted(lh.items()):
                b = lb.get(name)
                if b and b["version"] != p["version"]:
                    k = (name, b["version"], p["version"])
                    if k not in seen:
                        seen.add(k); res.append({"name": name, "from": b["version"], "to": p["version"], "eco": "npm", "direct": name in dh or name in db, "dir": d})
                elif not b:
                    newdeps.append({"name": name, "version": p["version"], "direct": name in dh})
                if p["install"] and not (b and b["install"] and b["version"] == p["version"]):
                    scripts.append({"name": name, "version": p["version"]})
                if b and b["license"] and p["license"] and b["license"] != p["license"]:
                    licences.append({"name": name, "from": b["license"], "to": p["license"]})
        else:
            for name, v in sorted(dh.items()):
                if name in db and db[name] != v and parse(db[name]) and parse(v):
                    k = (name, db[name], v)
                    if k not in seen:
                        seen.add(k); res.append({"name": name, "from": db[name].lstrip("^~="), "to": v.lstrip("^~="), "eco": "npm", "direct": True, "dir": d})
        for f in files:
            if os.path.dirname(f) == d and re.match(r"requirements.*\.txt$", os.path.basename(f)):
                rb, rh = requirements(show(repo, base, f)), requirements(show(repo, head, f))
                for name, v in sorted(rh.items()):
                    if name in rb and rb[name] != v:
                        k = (name, rb[name], v)
                        if k not in seen:
                            seen.add(k); res.append({"name": name, "from": rb[name], "to": v, "eco": "pypi", "direct": True, "dir": d})
                    elif name not in rb:
                        newdeps.append({"name": name, "version": v, "direct": True})
    return {"bumps": res, "new_dependencies": newdeps, "new_install_scripts": scripts, "licence_changes": licences}


def classify(stated, versions, a, b):
    actual = kind(a, b)
    s = re.search(r"\b(major|minor|patch)\b", stated or "", re.I)
    stated_kind = s.group(1).lower() if s else ""
    order = {"patch": 0, "minor": 1, "major": 2}
    x, y = parse(a), parse(b)
    crossed = []
    if x and y:
        for v in versions or []:
            p = parse(v)
            if p and not p[3] and x[:3] < p[:3] <= y[:3] and p[0] > x[0] and p[1] == 0 and p[2] == 0:
                crossed.append(v)
    hidden = bool(stated_kind and actual in order and order[actual] > order[stated_kind]) or (actual in ("patch", "minor") and bool(crossed))
    note = []
    if stated_kind and actual in order and order[actual] > order[stated_kind]:
        note.append(f"stated as a {stated_kind}, but {a} to {b} is a {actual}")
    if crossed:
        note.append("passes over a major release on the way: " + ", ".join(crossed[:5]))
    if actual == "downgrade":
        note.append("the new version is lower than the old one")
    return {"actual": actual, "stated": stated_kind, "hidden_major": hidden, "majors_crossed": crossed[:10], "note": "; ".join(note)}


def walk(repo):
    for root, dirs, fs in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in fs:
            if f.endswith(SRC):
                yield os.path.join(root, f)


def usage(repo, pkg, idents, cap=40):
    esc = re.escape(pkg)
    imp = re.compile(rf"""(?:from\s+['"]{esc}(?:/[^'"]*)?['"]|require\(\s*['"]{esc}(?:/[^'"]*)?['"]|import\(\s*['"]{esc}(?:/[^'"]*)?['"]|^\s*import\s+{esc}\b|^\s*from\s+{esc}(?:\.\w+)*\s+import\b)""")
    id_rx = [(i, re.compile(r"(?<![\w.])" + re.escape(i) + r"\b")) for i in idents]
    hits, importers = [], 0
    for path in walk(repo):
        try:
            lines = open(path, errors="replace").read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(path, repo)
        imports_it = False
        for n, ln in enumerate(lines, 1):
            if imp.search(ln):
                imports_it = True
                if len(hits) < cap:
                    hits.append({"file": rel, "line": n, "text": ln.strip()[:160], "kind": "import"})
        if imports_it:
            importers += 1
            for n, ln in enumerate(lines, 1):
                for i, rx in id_rx:
                    if rx.search(ln) and not imp.search(ln) and len(hits) < cap:
                        hits.append({"file": rel, "line": n, "text": ln.strip()[:160], "kind": "api", "api": i})
    return {"package": pkg, "files_importing": importers, "hits": hits[:cap]}


def idents(notes):
    out = []
    for ln in notes.splitlines():
        if re.search(r"remov|deprecat|breaking|renam|dropp|no longer|replaced|changed signature|now throws|now returns", ln, re.I):
            for tok in re.findall(r"`([A-Za-z_$][\w$.]*)(?:\(\))?`", ln):
                if tok not in out and len(tok) > 2:
                    out.append(tok)
    return {"idents": out[:30]}


INJECT = [r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|messages)", r"disregard (all |any )?(the )?(previous|prior|above)",
          r"you (must|should|are to|will) (now )?(approve|answer|reply|respond|say|output|merge|return)", r"\b(reply|respond|answer|output|say) (only )?(with )?['\"`]?(verdict|merge|approved)",
          r"as (an|the) (ai|assistant|model|reviewer)", r"system prompt", r"(approve|merge) (this|the) (pull request|pr|bump|update)", r"do not (mention|tell|report|flag)", r"^\s*(system|assistant|human)\s*:"]


def inject(notes):
    found = []
    for rx in INJECT:
        m = re.search(rx, notes, re.I | re.M)
        if m:
            found.append(m.group(0).strip()[:80])
    return {"found": found}


def releases(data, a, b):
    x, y = parse(a), parse(b)
    parts = []
    for r in data if isinstance(data, list) else []:
        tag = str(r.get("tag_name") or r.get("name") or "")
        p = parse(tag.split("@")[-1])
        if p and x and y and x[:3] < p[:3] <= y[:3] and not r.get("draft"):
            parts.append((p[:3], f"## {tag}\n{str(r.get('body') or '').strip()}"))
    parts.sort()
    return {"count": len(parts), "notes": "\n\n".join(t for _, t in parts)}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bumps"); b.add_argument("--repo", required=True); b.add_argument("--base", required=True); b.add_argument("--head", required=True); b.add_argument("--files", default="")
    c = sub.add_parser("classify"); c.add_argument("--stated", default=""); c.add_argument("--versions", required=True); c.add_argument("--from", dest="a", required=True); c.add_argument("--to", dest="b", required=True)
    u = sub.add_parser("usage"); u.add_argument("--repo", required=True); u.add_argument("--pkg", required=True); u.add_argument("--idents", default="")
    i = sub.add_parser("idents"); i.add_argument("--notes", required=True)
    j = sub.add_parser("inject"); j.add_argument("--notes", required=True)
    r = sub.add_parser("releases"); r.add_argument("--from", dest="a", required=True); r.add_argument("--to", dest="b", required=True)
    a = ap.parse_args()
    if a.cmd == "bumps":
        files = [x.strip() for x in open(a.files).read().splitlines() if x.strip()] if a.files else []
        out = bumps(a.repo, a.base, a.head, files)
    elif a.cmd == "classify":
        try:
            vs = json.load(open(a.versions))
        except (OSError, ValueError):
            vs = []
        out = classify(a.stated, vs if isinstance(vs, list) else [], a.a, a.b)
    elif a.cmd == "usage":
        out = usage(a.repo, a.pkg, [x for x in a.idents.split(",") if x])
    elif a.cmd == "idents":
        out = idents(open(a.notes, errors="replace").read())
    elif a.cmd == "inject":
        out = inject(open(a.notes, errors="replace").read())
    else:
        try:
            data = json.load(sys.stdin)
        except ValueError:
            data = []
        out = releases(data, a.a, a.b)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
