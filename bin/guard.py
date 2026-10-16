#!/usr/bin/env python3
"""guard: nothing private or secret may be committed.

    bin/guard.py                    secrets only, in every tracked file (this is what `check` runs)
    bin/guard.py --names            also the names in your denylist, and any e-mail address that is not an obvious placeholder
    bin/guard.py --staged           only what is staged for the next commit (for a pre-commit hook)
    bin/guard.py --history          every line ever added in any commit, secrets (and names with --names)
    bin/guard.py install-hook       a pre-commit hook that runs `guard.py --staged --names` and refuses the commit on a hit

The denylist is a plain text file in YOUR data folder (guard-denylist.txt, one term per line, # for comments, matched whole word, ignoring case),
never in the repository: a list of private names kept in the repo would itself leak them. Point at another with --denylist.
A hit prints file:line and the kind of thing, with any secret masked, and exits 1. Standard library only; reads git's own file list.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home

SECRETS = [
    ("an Anthropic API key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("an API key (sk-)", r"\bsk-[A-Za-z0-9]{32,}"),
    ("a GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("a GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("a Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("a Slack webhook", r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    ("an AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("a Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
    ("a Stripe live key", r"\b[sr]k_live_[0-9a-zA-Z]{20,}"),
    ("a private key", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY"),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
OK_MAIL_DOMAINS = ("example.com", "example.org", "example.net", "example", "test", "invalid", "localhost", "anthropic.com", "users.noreply.github.com", "noreply.github.com")
SKIP_DIRS = ("dashboard/assets/vendor/", ".git/", "node_modules/")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".pdf", ".zip", ".onnx", ".bin", ".gguf", ".mp3", ".wav")
MAX_BYTES = 1_000_000
HOOK = "#!/bin/sh\n# installed by bin/guard.py: refuse a commit that holds a secret or a private name\nexec python3 \"%s\" --staged --names\n"


def mask(s):
    return s[:4] + "…" + f"({len(s)} chars)"


def load_denylist(path):
    terms = []
    try:
        for line in Path(path).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                terms.append(line)
    except OSError:
        pass
    return terms


def compile_names(terms):
    return [(t, re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", re.I)) for t in terms]


def scan_line(line, names, check_mail):
    """[(kind, shown)] for one line of text."""
    hits = []
    for label, pat in SECRETS:
        m = re.search(pat, line)
        if m:
            hits.append((label, mask(m.group(0))))
    for term, rx in names:
        if rx.search(line):
            hits.append(("a private name", term))
    if check_mail:
        for m in EMAIL.finditer(line):
            d = m.group(1).lower()
            if not any(d == ok or d.endswith("." + ok) for ok in OK_MAIL_DOMAINS):
                hits.append(("an e-mail address", m.group(0)[:3] + "…@" + d))
    return hits


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def tracked_files(root, staged=False):
    out = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACM") if staged else git(root, "ls-files")
    return [f for f in out.splitlines() if f and not f.startswith(SKIP_DIRS) and not f.lower().endswith(SKIP_EXT)]


def file_text(root, rel, staged):
    if staged:
        return git(root, "show", f":{rel}")
    p = Path(root) / rel
    try:
        if not p.is_file() or p.stat().st_size > MAX_BYTES:
            return ""
        return p.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def scan(root, names=(), check_mail=False, staged=False):
    out = []
    for rel in tracked_files(root, staged):
        for n, line in enumerate(file_text(root, rel, staged).splitlines(), 1):
            for kind, shown in scan_line(line, names, check_mail):
                out.append((rel, n, kind, shown))
    return out


def scan_history(root, names=(), check_mail=False, limit=3_000_000):
    out, commit, path, seen = [], "", "", 0
    log = subprocess.Popen(["git", "-C", str(root), "log", "--all", "-p", "--no-color", "-U0", "--format=@@COMMIT %h"], stdout=subprocess.PIPE, text=True, errors="replace")
    for line in log.stdout:
        seen += 1
        if seen > limit:
            break
        if line.startswith("@@COMMIT "):
            commit = line.split()[1]
        elif line.startswith("+++ b/"):
            path = line[6:].strip()
        elif line.startswith("+") and not line.startswith("+++") and not path.startswith(SKIP_DIRS) and not path.lower().endswith(SKIP_EXT):
            for kind, shown in scan_line(line[1:], names, check_mail):
                out.append((f"{path} @{commit}", 0, kind, shown))
    log.terminate()
    return out


def report(hits):
    for rel, n, kind, shown in hits[:200]:
        print(f"  {rel}{':' + str(n) if n else ''}  {kind}: {shown}")
    if len(hits) > 200:
        print(f"  ... and {len(hits) - 200} more")
    print(f"{len(hits)} hit(s)" if hits else "  ok    nothing private or secret is tracked")


def main(argv):
    root, names_mode, staged, history, deny = ROOT, False, False, False, None
    args = list(argv)
    if args[:1] == ["install-hook"]:
        # into the repository you are standing in (or the folder you name), never into the guard's own
        target = Path(args[1]) if len(args) > 1 else Path.cwd()
        top = git(target, "rev-parse", "--show-toplevel").strip()
        if not top:
            print(f"  {target} is not inside a git repository")
            return 2
        hook = Path(git(top, "rev-parse", "--git-path", "hooks/pre-commit").strip())
        hook = hook if hook.is_absolute() else Path(top) / hook
        hook.parent.mkdir(parents=True, exist_ok=True)
        if hook.exists() and "bin/guard.py" not in hook.read_text(errors="replace") and "guard.py" not in hook.read_text(errors="replace"):
            print(f"  {hook} already holds another hook; not overwriting it")
            return 2
        hook.write_text(HOOK % Path(__file__).resolve())
        hook.chmod(0o755)
        print(f"installed {hook}")
        return 0
    while args:
        a = args.pop(0)
        if a == "--names":
            names_mode = True
        elif a == "--staged":
            staged = True
        elif a == "--history":
            history = True
        elif a == "--denylist" and args:
            deny = args.pop(0)
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            root = Path(a)
    names = []
    if names_mode:
        deny = deny or str(_home.resolve() / "guard-denylist.txt")
        terms = load_denylist(deny)
        names = compile_names(terms)
        if not terms:
            print(f"  note  --names without a denylist at {deny}: only e-mail addresses are checked")
    hits = scan_history(root, names, names_mode) if history else scan(root, names, names_mode, staged)
    report(hits)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
