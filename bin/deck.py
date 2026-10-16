#!/usr/bin/env python3
"""The Bosun's harness-side checks. Plain commands and plain search; no model, no network, no write to any repository.

Every command prints one JSON object {"findings": [{"kind","where","evidence","action"}]}.

    deck.py branches --repo R --base origin/main --days N --now EPOCH [--prs prs.json]
    deck.py envvars  --tree T
    deck.py docs     --tree T
    deck.py unused   --tree T
    deck.py issues   --issues issues.json --prs prs.json
    deck.py todos    --tree T --repo R --ref REF --days N --now EPOCH

R is the project's own git repository; T is a throwaway worktree of its base branch. Nothing outside them is opened. Real
environment files (.env, .env.local, .env.production ...) are never opened: only files named example, sample, template or dist.
Stdlib only."""
import argparse
import json
import os
import re
import subprocess
import sys

SKIP = {"node_modules", ".git", "vendor", "dist", "build", ".next", "__pycache__", "coverage", ".venv", "venv", "docs_build"}
CODE = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".py", ".sh", ".rb", ".go", ".rs", ".java", ".php")
EXAMPLE_ENV = re.compile(r"^\.?env(\.|_)?(example|sample|template|dist)$|^(example|sample)\.env$|^\.env\.(example|sample|template|dist)$", re.I)
REAL_ENV = re.compile(r"^\.env($|\.)", re.I)
BUILTIN_ENV = {"NODE_ENV", "CI", "HOME", "PATH", "PWD", "USER", "SHELL", "TERM", "LANG", "TZ", "PORT", "HOST", "DEBUG", "VERCEL", "VERCEL_ENV", "VERCEL_URL", "GITHUB_ACTIONS", "TMPDIR", "NODE_OPTIONS"}
LIFECYCLE = {"start", "test", "build", "dev", "lint", "prepare", "preinstall", "install", "postinstall", "prepublish", "prepublishOnly", "prepack", "postpack", "pretest", "posttest", "format", "typecheck", "check"}


def git(repo, *args, timeout=60):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ""


def files(tree, exts=None):
    for root, dirs, fs in os.walk(tree):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in fs:
            if REAL_ENV.match(f) and not EXAMPLE_ENV.match(f):
                continue                      # never open a file that may hold real values
            if exts is None or f.endswith(exts):
                yield os.path.join(root, f)


def read(path, limit=400_000):
    try:
        with open(path, errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def rel(tree, path):
    return os.path.relpath(path, tree)


def F(kind, where, evidence, action):
    return {"kind": kind, "where": where, "evidence": evidence, "action": action}


# ---- stale branches --------------------------------------------------------------------------------------------------------
def branches(repo, base, days, now, prs):
    out = []
    merged = {b.strip() for b in git(repo, "branch", "-r", "--merged", base).splitlines()}
    byhead = {}
    for p in prs if isinstance(prs, list) else []:
        byhead.setdefault(p.get("headRefName"), []).append(p)
    base_short = base.split("/", 1)[-1]
    rows = git(repo, "for-each-ref", "--format=%(refname:short)\t%(committerdate:unix)", "refs/remotes/origin").splitlines()
    for row in rows:
        name, _, ts = row.partition("\t")
        short = name.split("/", 1)[-1]
        if short in ("HEAD", base_short) or not ts.isdigit():
            continue
        age = (now - int(ts)) // 86400
        pulls = byhead.get(short, [])
        open_pr = any(p.get("state") == "OPEN" for p in pulls)
        why = []
        if name in merged:
            why.append("already merged into " + base_short)
        closed = [p for p in pulls if p.get("state") == "CLOSED"]
        if closed and not open_pr:
            why.append(f"its pull request #{closed[0].get('number')} was closed without merging")
        if any(p.get("state") == "MERGED" for p in pulls) and not open_pr:
            why.append("its pull request was merged")
        if age >= days and not open_pr and not why:
            why.append(f"no commit for {age} days and no open pull request")
        if why:
            out.append(F("stale branch", name, f"last commit {age} days ago; " + "; ".join(why),
                         f"If nobody needs it, delete the branch {short} (the owner decides; the bosun never does)."))
    return out


# ---- environment variables ------------------------------------------------------------------------------------------------------------
READ_RX = [re.compile(p) for p in (r"process\.env\.([A-Z][A-Z0-9_]+)", r"process\.env\[['\"]([A-Z][A-Z0-9_]+)['\"]\]", r"import\.meta\.env\.([A-Z][A-Z0-9_]+)",
                                    r"os\.environ(?:\.get)?\(?\[?['\"]([A-Z][A-Z0-9_]+)['\"]", r"os\.getenv\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]", r"\bgetenv\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
                                    r"\$\{?([A-Z][A-Z0-9_]{3,})\}?(?::-|:\?|\})")]
DEFINE_FILES = re.compile(r"(Dockerfile|docker-compose.*\.ya?ml|\.github/workflows/.*\.ya?ml|vercel\.json|fly\.toml|render\.ya?ml|netlify\.toml|app\.json|Procfile|\.gitlab-ci\.yml)$")


def envvars(tree):
    reads, example, defined = {}, {}, set()
    for path in files(tree):
        r = rel(tree, path); name = os.path.basename(path)
        text = read(path)
        if EXAMPLE_ENV.match(name):
            for ln_no, ln in enumerate(text.splitlines(), 1):
                m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]+)\s*=", ln)
                if m:
                    example.setdefault(m.group(1), f"{r}:{ln_no}")
                    defined.add(m.group(1))
        elif DEFINE_FILES.search(r.replace(os.sep, "/")) or name in ("Dockerfile", "Procfile"):
            for tok in re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b\s*[:=]", text):
                defined.add(tok)
            for tok in re.findall(r"^\s*(?:ENV|ARG)\s+([A-Z][A-Z0-9_]+)", text, re.M):
                defined.add(tok)
        if path.endswith(CODE):
            for ln_no, ln in enumerate(text.splitlines(), 1):
                for rx in READ_RX:
                    for m in rx.finditer(ln):
                        reads.setdefault(m.group(1), f"{r}:{ln_no}")
    out = []
    for name, where in sorted(reads.items()):
        if name not in defined and name not in BUILTIN_ENV and len(name) > 3 and not name.startswith("npm_"):
            out.append(F("dead environment variable", name, f"read at {where}, and no example env file, Dockerfile, workflow or platform file in the repository defines it",
                         f"Add {name} to the example env file, or remove the read if nothing needs it. It may be set by a platform this repository cannot see."))
    for name, where in sorted(example.items()):
        if name not in reads and name not in BUILTIN_ENV:
            out.append(F("dead environment variable", name, f"defined in {where} but nothing in the code reads it",
                         f"Remove {name} from the example env file, or find what should be reading it."))
    return out


# ---- docs that have drifted from the code -----------------------------------------------------------------------------------------------
def docs(tree):
    out, seen = [], set()
    docfiles = [p for p in files(tree, (".md",)) if rel(tree, p).count(os.sep) <= 2 or "docs" in rel(tree, p).split(os.sep)]
    allfiles = {rel(tree, p).replace(os.sep, "/") for p in files(tree)}
    basenames = {os.path.basename(f) for f in allfiles}
    pkg = {}
    try:
        pkg = json.loads(read(os.path.join(tree, "package.json")) or "{}")
    except ValueError:
        pass
    scripts = set((pkg.get("scripts") or {}).keys())
    makefile = read(os.path.join(tree, "Makefile"))
    targets = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:", makefile, re.M))
    code_text = None
    def code():
        nonlocal code_text
        if code_text is None:
            code_text = "\n".join(read(p, 200_000) for p in files(tree) if p.endswith(CODE + (".json", ".yml", ".yaml", ".toml")))
        return code_text
    def add(kind, where, ev, action):
        k = (kind, where, ev)
        if k not in seen:
            seen.add(k); out.append(F(kind, where, ev, action))
    for path in sorted(docfiles):
        r = rel(tree, path).replace(os.sep, "/")
        for ln_no, ln in enumerate(read(path).splitlines(), 1):
            for tok in re.findall(r"`([^`\n]{2,120})`", ln):
                t = tok.strip()
                m = re.match(r"^npm (?:run )?([A-Za-z0-9:_-]+)", t)
                if m and scripts is not None and (pkg.get("scripts") is not None) and m.group(1) not in scripts and m.group(1) not in ("install", "ci", "test", "start", "init", "publish", "audit", "i", "update", "outdated", "pack", "link"):
                    add("doc drift", f"{r}:{ln_no}", f"names `{t}` but package.json has no script called {m.group(1)}", f"Fix or remove the line in {r}.")
                    continue
                m = re.match(r"^make ([A-Za-z0-9_.-]+)", t)
                if m and makefile and m.group(1) not in targets:
                    add("doc drift", f"{r}:{ln_no}", f"names `{t}` but the Makefile has no target {m.group(1)}", f"Fix or remove the line in {r}.")
                    continue
                if re.match(r"^[A-Za-z0-9_./@-]+\.[A-Za-z0-9]{1,5}$", t) and ("/" in t or "." in t) and not t.startswith(("http", "www.", "@")) and not re.match(r"^\d", t):
                    ext = t.rsplit(".", 1)[-1].lower()
                    if ext in ("js", "ts", "tsx", "jsx", "py", "sh", "json", "md", "yml", "yaml", "toml", "mjs", "cjs", "html", "css", "txt", "env", "sql", "swift"):
                        p = t.lstrip("./")
                        here = os.path.normpath(os.path.join(os.path.dirname(r), p)).replace(os.sep, "/")
                        if p not in allfiles and here not in allfiles and not any(f.endswith("/" + p) for f in allfiles) and os.path.basename(p) not in basenames:
                            add("doc drift", f"{r}:{ln_no}", f"names the file `{t}`, which is not in the repository", f"Fix the path or remove the mention in {r}.")
                        continue
                flags = re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]{2,})", t)
                if flags:
                    for fl in flags:
                        if fl not in code():
                            add("doc drift", f"{r}:{ln_no}", f"names the flag `{fl}`, which appears nowhere in the code or config", f"Fix or remove the mention in {r}.")
                    continue
                if re.match(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]{2,}$", t) and t not in BUILTIN_ENV and t not in code() and not re.search(r"\b" + re.escape(t) + r"\b", "\n".join(read(p, 100_000) for p in files(tree) if EXAMPLE_ENV.match(os.path.basename(p)))):
                    add("doc drift", f"{r}:{ln_no}", f"names the variable `{t}`, which nothing in the repository reads or defines", f"Fix or remove the mention in {r}.")
    return out


# ---- unused scripts and config keys ---------------------------------------------------------------------------------------------------------
def unused(tree):
    out = []
    corpus = {}
    for p in files(tree):
        if os.path.getsize(p) < 600_000:
            corpus[rel(tree, p).replace(os.sep, "/")] = read(p)
    pkg = {}
    try:
        pkg = json.loads(corpus.get("package.json", "{}") or "{}")
    except ValueError:
        pass
    scripts = pkg.get("scripts") or {}
    for name in sorted(scripts):
        if name in LIFECYCLE or re.match(r"^(pre|post)", name) and name[3 if name.startswith("pre") else 4:] in scripts:
            continue
        rx = re.compile(r"(npm|yarn|pnpm)( run)? " + re.escape(name) + r"\b|" + r"\b" + re.escape(name) + r"\b")
        used = any(rx.search(t) for f, t in corpus.items() if f != "package.json") or any(rx.search(v) for k, v in scripts.items() if k != name)
        if not used:
            out.append(F("unused script", f"package.json: scripts.{name}", f"nothing in the repository's scripts, workflows, docs or code mentions `{name}`", f"If nobody runs it by hand, remove scripts.{name}."))
    for f in sorted(corpus):
        if re.match(r"^(scripts|bin|tools)/[^/]+\.(sh|py|js|mjs)$", f):
            base = os.path.basename(f)
            if not any(base in t for g, t in corpus.items() if g != f):
                out.append(F("unused script", f, f"no other file in the repository mentions {base}", f"If it is dead, remove {f}; if it is run by hand, mention it in the README."))
    for f in sorted(corpus):
        if re.match(r"^config/[^/]+\.json$", f):
            try:
                data = json.loads(corpus[f])
            except ValueError:
                continue
            if isinstance(data, dict):
                others = "\n".join(t for g, t in corpus.items() if g != f and g.endswith(CODE))
                for key in sorted(data):
                    if len(key) > 2 and not re.search(r"\b" + re.escape(key) + r"\b", others):
                        out.append(F("unused config key", f"{f}: {key}", f"no code in the repository mentions the key {key}", f"If nothing reads {key}, remove it from {f}."))
    return out


# ---- open issues whose pull request has merged -----------------------------------------------------------------------------------------------
def issues(open_issues, prs):
    out = []
    byissue = {}
    for p in prs if isinstance(prs, list) else []:
        if p.get("state") == "MERGED" or p.get("mergedAt"):
            for ref in p.get("closingIssuesReferences") or []:
                if isinstance(ref, dict) and isinstance(ref.get("number"), int):
                    byissue.setdefault(ref["number"], p.get("number"))
    for i in open_issues if isinstance(open_issues, list) else []:
        n = i.get("number")
        if n in byissue:
            out.append(F("open issue already fixed", f"issue #{n}", f"{str(i.get('title', ''))[:100]}: pull request #{byissue[n]}, which closes it, has merged", f"Check that #{n} is done and close it."))
    return out


# ---- TODO and FIXME older than a season -----------------------------------------------------------------------------------------------------
def todos(tree, repo, ref, days, now, cap=60):
    out, n = [], 0
    r = subprocess.run(["git", "-C", repo, "grep", "-nIw", "-e", "TODO", "-e", "FIXME", ref, "--", "."], capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        m = re.match(r"^[^:]+:(.+?):(\d+):(.*)$", line)
        if not m:
            continue
        path, ln, text = m.group(1), int(m.group(2)), m.group(3).strip()
        if path.endswith((".md", ".lock", ".json", ".svg")) or any(part in SKIP for part in path.split("/")):
            continue
        if n >= cap:
            break
        n += 1
        b = subprocess.run(["git", "-C", repo, "blame", "--line-porcelain", "-L", f"{ln},{ln}", ref, "--", path], capture_output=True, text=True, timeout=60)
        mt = re.search(r"^author-time (\d+)", b.stdout, re.M)
        if not mt:
            continue
        age = (now - int(mt.group(1))) // 86400
        if age >= days:
            out.append(F("old TODO", f"{path}:{ln}", f"{text[:120]} (written {age} days ago)", "Do it, file it as an issue, or delete the comment."))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("branches"); b.add_argument("--repo", required=True); b.add_argument("--base", required=True); b.add_argument("--days", type=int, default=60); b.add_argument("--now", type=int, required=True); b.add_argument("--prs", default="")
    e = sub.add_parser("envvars"); e.add_argument("--tree", required=True)
    d = sub.add_parser("docs"); d.add_argument("--tree", required=True)
    u = sub.add_parser("unused"); u.add_argument("--tree", required=True)
    i = sub.add_parser("issues"); i.add_argument("--issues", required=True); i.add_argument("--prs", required=True)
    t = sub.add_parser("todos"); t.add_argument("--tree", required=True); t.add_argument("--repo", required=True); t.add_argument("--ref", required=True); t.add_argument("--days", type=int, default=90); t.add_argument("--now", type=int, required=True)
    a = ap.parse_args()
    def load(path):
        try:
            return json.load(open(path))
        except (OSError, ValueError):
            return []
    if a.cmd == "branches":
        out = branches(a.repo, a.base, a.days, a.now, load(a.prs) if a.prs else [])
    elif a.cmd == "envvars":
        out = envvars(a.tree)
    elif a.cmd == "docs":
        out = docs(a.tree)
    elif a.cmd == "unused":
        out = unused(a.tree)
    elif a.cmd == "issues":
        out = issues(load(a.issues), load(a.prs))
    else:
        out = todos(a.tree, a.repo, a.ref, a.days, a.now)
    print(json.dumps({"findings": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
