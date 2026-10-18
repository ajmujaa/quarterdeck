#!/usr/bin/env python3
"""protect: paths a model-made change may not touch, and the files a project's verify command is built from.

    bin/protect.py list                         the default protected paths, one per line
    bin/protect.py check [--allow P]... [--plan FILE] [--extra GLOB]... [--root WORKTREE]
                                                changed paths on stdin; prints each protected one that is not allowed, exits 1 if any;
                                                with --root, also each one that is a symlink out of the worktree or to a protected place
    bin/protect.py folders --plan FILE [--root WORKTREE]
                                                the Terraform folders the plan's Where fields name, one per line; with --root, only those that
                                                pass the folder rules (inside the worktree, no link, present), else every folder-form Where
    bin/protect.py inputs WORKTREE              a digest of what the verify/test/build commands are made of: every package.json
                                                "scripts" block and every Makefile; print it before the model runs and after

Why: the harness runs the project's verify, test and build commands after a model has edited the worktree. A model (steered by a hostile
issue or pull request) that can change package.json scripts, a lockfile, a test-runner config or a CI workflow turns that run into code
execution on this machine, or into a workflow that runs with the repository's secrets once pushed. So such a change is refused BEFORE any
check runs. A path is allowed only when the project's registry lists it in "protected_allow" or the plan the duty was given (a dev panel's
ruling, not the issue text anyone can write) names it. Even then, a changed scripts block or Makefile is refused (see `inputs`).
A pattern with no slash matches the file name at any depth; a pattern with a slash matches from the repository root; ** crosses folders.
A trailing /** also matches the bare name: `.claude/**` matches `.claude`, which is what git records for a folder replaced by a symlink (audit 7, M2).
Terraform (ticket #101): a Where that is one folder in backticks (`infra/net/`) unlocks only the *.tf files under it and the *.tfvars files under it
that hold no secret-looking value, and only when the folder is in the worktree (--root); state, the provider cache, the CLI config and its credentials
and the lock file are never unlocked by a plan.
Standard library only.
"""
import fnmatch
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT = [
    ".github/**", ".gitlab-ci.yml", ".circleci/**", "Jenkinsfile", "azure-pipelines.yml", ".travis.yml",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum",
    ".npmrc", ".yarnrc*", "*.config.*", "tsconfig*", "Makefile", "GNUmakefile", "makefile", ".husky/**", "scripts/**", "**/scripts/**",
    "Dockerfile*", "docker-compose*", "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "tox.ini", "noxfile.py",
    "Cargo.toml", "build.rs", "go.mod", "Gemfile", "Rakefile", "justfile", ".pre-commit-config.yaml", ".gitmodules", ".gitattributes",
    ".claude/**", ".mcp.json",
    # test-runner, linter, formatter and loader files that a check picks up by name (round-2 audit R3 D)
    "conftest.py", "pytest.ini", "pytest.cfg", ".babelrc*", ".mocharc*", "jest.setup.*", "*.setup.*", "setupTests.*", "setup-tests.*", ".eslintrc*", ".prettierrc*",
    ".flake8", "mypy.ini", ".mypy.ini", ".pylintrc", "ruff.toml", ".ruff.toml", ".nycrc*", "karma.conf.*", "vitest.workspace.*", ".swcrc", "sitecustomize.py",
    "usercustomize.py", ".lintstagedrc*", "lefthook.yml", ".tool-versions",
    # round-3 LOW: environment files (secrets; .envrc is run by direnv), cargo and yarn/pnpm project hooks, deploy config, code owners and infrastructure as code
    ".env*", "*.env", ".cargo/**", "**/.cargo/**", ".yarn/**", "**/.yarn/**", "vercel.json", "netlify.toml", "CODEOWNERS",
    "*.tf", "*.tfvars", "*.tf.json", ".terraform/**",
    # round 6: package-manager files that run code or fetch it (pnpm 10 reads its settings, pnpmfile among them, from pnpm-workspace.yaml)
    ".pnpmfile.*", "pnpm-workspace.yaml", "bunfig.toml",
    # ticket #101: Terraform state, the provider and module cache at any depth, the CLI config and its credentials, and the provider lock file
    "*.tfstate", "*.tfstate.backup", "**/.terraform/**", ".terraformrc", "terraform.rc", "credentials.tfrc.json", ".terraform.lock.hcl",
]

# What a plan can never unlock, only the project's protected_allow (round 6, H2). A plan's Where line is written by a model, from an issue anyone can
# file: CI runs with the repository's secrets once a branch is pushed, lockfiles and package-manager config choose what is fetched and run at install,
# hooks run on the next commit, CODEOWNERS decides who must review, and agent settings decide what the next model may do.
PLAN_NEVER = [
    ".github/**", ".gitlab-ci.yml", ".circleci/**", "Jenkinsfile", "azure-pipelines.yml", ".travis.yml",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum",
    ".npmrc", ".yarnrc*", ".pnpmfile.*", "pnpm-workspace.yaml", "bunfig.toml", ".yarn/**", "**/.yarn/**", ".cargo/**", "**/.cargo/**",
    ".husky/**", ".pre-commit-config.yaml", "lefthook.yml", ".lintstagedrc*", "CODEOWNERS", ".claude/**", ".mcp.json", ".env*", "*.env",
    ".gitattributes", ".gitmodules",
    # ticket #101: state holds live values and secrets, the cache holds provider code that runs, the CLI config and credentials reach a registry
    # or a backend, and the lock file chooses which provider code CI downloads. A person changes these.
    "*.tfstate", "*.tfstate.backup", ".terraform/**", "**/.terraform/**", ".terraformrc", "terraform.rc", "credentials.tfrc.json", ".terraform.lock.hcl",
]

# What a folder Where unlocks, and nothing else: Terraform source and variable files (a variable file only without a secret-looking value).
TF_UNLOCK = ["*.tf", "*.tfvars"]


def _rx(pat):
    """A glob with ** crossing folders and * / ? staying inside one."""
    out, i = "", 0
    while i < len(pat):
        c = pat[i]
        if pat[i:] == "/**":
            out += "(?:/.*)?"; break
        if pat[i:i + 3] == "**/":
            out += "(?:.*/)?"; i += 3; continue
        if pat[i:i + 2] == "**":
            out += ".*"; i += 2; continue
        out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
        i += 1
    return re.compile(out + r"\Z")


def prefixes():
    """The default list as the literal path prefixes a registry's forbidden_paths understands (root-level only; a pattern that starts
    with a * cannot be a prefix and is covered by the harness's own check instead)."""
    out = []
    for pat in DEFAULT:
        if pat.startswith("*"):
            continue
        out.append(pat[:-2] if pat.endswith("/**") else pat.split("*", 1)[0])
    return list(dict.fromkeys(o for o in out if o))


def norm(text):
    """The way a Mac's volume (APFS) compares names: letter case does not matter (casefold, not lower: ẞ is ss, the Kelvin sign is k) and neither does
    how an accent is spelled (é as one character or as e plus a combining mark), so both are compared in one form."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


def matches(path, patterns):
    """Case and normalisation do not matter: JEST.CONFIG.JS is jest.config.js on a Mac, and so is an é spelled either way."""
    path = norm(path.strip())
    path = path[2:] if path.startswith("./") else path
    base = path.rsplit("/", 1)[-1]
    for pat in patterns:
        pat = norm(pat)
        if "/" in pat:
            if _rx(pat).match(path):
                return True
        elif _rx(pat).match(base):
            return True
    return False


WHERE = re.compile(r"\s*\*\*Where\.\*\*")
WHERE_PATH = re.compile(r"\s*\*\*Where\.\*\*\s*`(?:\./)?([A-Za-z0-9._@+/-]+?)(?::\d+(?:[-:]\d+)*)?`\s*$")


def plan_paths(plan_text):
    """The paths a plan names in its structured field: the `**Where.** `path`` line of a ruling item (bin/panel, bin/fix and the joiner write exactly
    one per item, the value in backticks). Only a field that is ONE path and nothing else counts: prose (even a sentence that says not to touch a file),
    a list, a bare unquoted value, or an item with a second Where line (text a model put in another field) unlocks nothing. A `:12` suffix is dropped."""
    out, items, cur = set(), [], []
    for line in plan_text.splitlines():
        if line.startswith("#"):
            items.append(cur); cur = []
        elif WHERE.match(line):
            cur.append(line)
    items.append(cur)
    for where in items:
        m = WHERE_PATH.match(where[0]) if len(where) == 1 else None
        if m and ".." not in m.group(1).split("/"):
            out.add(norm(m.group(1)))
    return out


def plan_folders(plan_text):
    """The folder-form Where values of a plan (`infra/net/`, a trailing slash), as written, by the same strict rule as plan_paths."""
    out = []
    for line in plan_text.splitlines():
        m = WHERE_PATH.match(line)
        if m and m.group(1).endswith("/") and norm(m.group(1)) in plan_paths(plan_text):
            out.append(m.group(1))
    return list(dict.fromkeys(out))


def folder_ok(folder, root):
    """A folder Where is used only when it is inside the worktree, spelled without `..`, not absolute, not the root itself, is a real folder in the
    checkout, and no part of it is a link (a link could point out of the worktree or at another folder the plan did not name)."""
    if not root or not folder.endswith("/") or folder.startswith("/") or folder in ("/", "./"):
        return False
    parts = folder.rstrip("/").split("/")
    if not parts or any(x in ("", ".", "..") for x in parts):
        return False
    cur = os.path.realpath(root)
    for x in parts:
        cur = os.path.join(cur, x)
        if os.path.islink(cur) or not os.path.isdir(cur):
            return False
    return os.path.realpath(cur).startswith(os.path.realpath(root) + os.sep)


def tf_folders(plan_text, root):
    """The folder Where values of the plan that pass folder_ok, as written: the folders the harness runs terraform fmt and validate on."""
    return [f for f in plan_folders(plan_text) if folder_ok(f, root)]


SECRET_NAME = re.compile(r"(?i)(passw|secret|token|api_?key|private_?key|access_?key|credential|auth|cert|\bkey\b|_key\b|pem\b|connection_?string|dsn)")
ASSIGN = re.compile(r"^\s*\"?([A-Za-z0-9_.-]+)\"?\s*=\s*(.*)$")


def tfvars_secret(text):
    """A short reason when a variable file looks like it holds a secret, else "". Fail closed: a credential pattern or high-entropy run anywhere
    (bin/outscan.py), a private key block, or a variable whose name sounds like a secret with any value but an empty string or null."""
    if "-----BEGIN" in text:
        return "a key block"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import outscan
        hits = outscan.scan_text(text) or (["a random-looking value"] if outscan.entropy_runs(text) else [])
    except Exception:          # the scanner itself could not run: nothing is trusted
        return "the secret scan could not run"
    if hits:
        return hits[0]
    for line in text.splitlines():
        m = ASSIGN.match(line)
        if m and SECRET_NAME.search(m.group(1)) and m.group(2).strip().rstrip(",") not in ('""', "null", "''"):
            return "a value for " + m.group(1)
    return ""


def tf_allowed(path, raw, plan_text, root):
    """Unlocked by a folder Where: a *.tf, or a clean *.tfvars, under a folder the plan names (one per item) that passes folder_ok. Never a path
    on PLAN_NEVER. `path` is the compared form, `raw` the spelling on disk. A *.tfvars is read from the worktree: a link, something that is not a file, or a secret-looking value keeps it protected."""
    if not plan_text or not root or matches(path, PLAN_NEVER) or not matches(path, TF_UNLOCK):
        return False
    if ".." in path.split("/"):
        return False
    if not any(path.startswith(norm(f)) for f in tf_folders(plan_text, root)):
        return False
    return tfvars_clean(raw, root) if matches(path, ["*.tfvars"]) else True


def tfvars_clean(path, root):
    full = os.path.join(root, path)
    if os.path.islink(full):
        return False
    if not os.path.lexists(full):
        return True            # deleted: nothing is written
    if not os.path.isfile(full):
        return False
    try:
        text = Path(full).read_text(errors="replace")
    except OSError:
        return False
    return not tfvars_secret(text)


def allowed_by(path, allow, plan_text, root=""):
    """Listed by the registry (an exact path or a glob) or named, as a whole path, in the Where field of an item of the plan the duty was handed,
    or (Terraform) a *.tf or clean *.tfvars under a folder a Where field names. A *.tfvars a plan unlocks must hold no secret-looking value."""
    if matches(path, [a for a in allow if a]):
        return True
    p = norm(path.strip())
    p = p[2:] if p.startswith("./") else p
    if not plan_text or matches(p, PLAN_NEVER):
        return False
    if p in plan_paths(plan_text):
        if matches(p, ["*.tfvars"]):
            return bool(root) and tfvars_clean(_on_disk(path), root)
        return True
    return tf_allowed(p, _on_disk(path), plan_text, root)


def _on_disk(path):
    path = path.strip()
    return path[2:] if path.startswith("./") else path


def violations(paths, allow=(), plan_text="", extra=(), root=""):
    return [p for p in paths if p.strip() and matches(p, list(DEFAULT) + list(extra)) and not allowed_by(p.strip(), allow, plan_text, root)]


def link_violations(paths, root, allow=(), extra=()):
    """The changed paths that are symlinks and resolve outside the worktree, to the worktree itself, into its .git, or to a protected place
    (audit 7, M2: `.claude -> docs/agent` made an unprotected folder the agent settings). A link the project's protected_allow names is let through."""
    rootr = os.path.realpath(root)
    pats = list(DEFAULT) + list(extra)
    out = []
    for p in paths:
        p = p.strip()
        full = os.path.join(root, p)
        if not p or not os.path.islink(full) or matches(p, [a for a in allow if a]):
            continue
        rel = os.path.relpath(os.path.realpath(full), rootr)
        if rel in (".", "..") or rel.startswith("../") or rel.split("/")[0] == ".git" or matches(rel, pats):
            out.append(p + " (a symlink out of the worktree or to a protected place)")
    return out


def inputs_digest(worktree):
    """sha256 over every package.json "scripts" block and every Makefile under the worktree (node_modules and .git left out)."""
    root = Path(worktree)
    parts = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if "node_modules/" in rel + "/" or rel.startswith(".git/") or not p.is_file() or p.is_symlink():
            continue
        if p.name == "package.json":
            try:
                scripts = json.loads(p.read_text(errors="replace")).get("scripts", {})
            except (ValueError, AttributeError):
                scripts = "unparseable"
            parts.append((rel, json.dumps(scripts, sort_keys=True)))
        elif p.name in ("Makefile", "makefile", "GNUmakefile"):
            parts.append((rel, p.read_text(errors="replace")))
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "list":
        print("\n".join(DEFAULT))
        return 0
    if cmd == "prefixes":
        print("\n".join(prefixes()))
        return 0
    if cmd == "inputs" and len(argv) == 2:
        print(inputs_digest(argv[1]))
        return 0
    if cmd == "folders" and len(argv) in (3, 5) and argv[1] == "--plan" and (len(argv) == 3 or argv[3] == "--root"):
        try:
            plan = Path(argv[2]).read_text(errors="replace")
        except OSError:
            return 1
        print("\n".join(tf_folders(plan, argv[4]) if len(argv) == 5 else plan_folders(plan)))
        return 0
    if cmd == "check":
        allow, extra, plan, root, a = [], [], "", "", argv[1:]
        while a:
            f = a.pop(0)
            if f == "--allow" and a:
                allow.append(a.pop(0))
            elif f == "--extra" and a:
                extra.append(a.pop(0))
            elif f == "--root" and a:
                root = a.pop(0)
            elif f == "--plan" and a:
                try:
                    plan = Path(a.pop(0)).read_text(errors="replace")
                except OSError:
                    plan = ""
            else:
                print(__doc__)
                return 2
        paths = sys.stdin.read().splitlines()
        bad = violations(paths, allow, plan, extra, root)
        if root:
            bad += [b for b in link_violations(paths, root, allow, extra) if b.split(" (", 1)[0] not in bad]
        print("\n".join(bad))
        return 1 if bad else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
