#!/usr/bin/env python3
"""repo: what a project with no GitHub repo can do, and the one command that makes a repo (only when you say yes).

    bin/repo.py options <project>                 the one sentence and the four ways forward, in order
    bin/repo.py sentence <project>                only the sentence (what attach, status, run and ticket new print, with a pointer to the options)
    bin/repo.py create <project> [--private | --public --i-mean-public] [--yes] [--push]

`qtdeck repo <project>` is `options`. `qtdeck repo <project> <owner/name>` (the repo you already have) is bin/attach.py set-repo and is unchanged.

`create` runs `gh repo create <login>/<name> --private --source <your folder> --remote origin`, and only
  * for a registered project whose folder is a git checkout and that has no origin yet,
  * when `gh auth status` says gh is signed in (otherwise it prints `gh auth login` and stops: exit 3, nothing created),
  * after a typed `yes` on a terminal (or --yes; with no terminal and no --yes it refuses),
  * with the owner taken from `gh api user --jq .login` and checked, and the name from the project name, checked with the same rule `qtdeck repo` uses.
Then it records the repo in the registry. Pushing the default branch once, so pull requests have a base, is a SECOND yes (or --push). Nothing else is pushed.
Quarterdeck never creates a GitHub account and never touches a password or a token: a person signs up at github.com and signs in with `gh auth login`.
Standard library only. The gh program is the one named by QUARTERDECK_GH (a test points it at a stand-in), else `gh`.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attach as _attach
import safegit as _safegit

LOGIN_OK = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")      # a GitHub user or organisation name


def _entry(project):
    reg = _attach.load_registry(_attach.registry_path())
    e = reg.get(project)
    if not isinstance(e, dict):
        raise ValueError(f"'{project}' is not registered (see: qtdeck projects)")
    return e


def sentence(project):
    return _attach.no_repo_sentence(project)


def pointer(project):
    return f"see your options: qtdeck repo {project}"


def has_repo(project):
    return bool(_entry(project).get("repo"))


def options(project):
    """The four ways forward, in order, for a page or a terminal: [{key, title, command, steps, note}]."""
    p = project
    return [
        {"key": "a", "title": "I already have a GitHub repo", "command": f"qtdeck repo {p} <owner/name>", "steps": [],
         "note": "connects this project to a repository you already made"},
        {"key": "b", "title": "I have a GitHub account", "command": f"qtdeck repo create {p} --private", "steps": [],
         "note": "asks you to type yes, then makes a private repository and connects it; it needs gh signed in, and if it is not it tells you to run: gh auth login"},
        {"key": "c", "title": "I have no GitHub account",
         "command": "",
         "steps": ["Go to https://github.com and choose Sign up.", "Use your email address.", "Choose a username.", "Verify your email when GitHub asks.",
                   "Sign in on this computer with: gh auth login", f"Come back here and continue with (b): qtdeck repo create {p} --private"],
         "note": "A person has to do this: Quarterdeck never creates an account and never touches a password."},
        {"key": "d", "title": "Not now", "command": f"qtdeck ticket new {p} \"<what you want>\"", "steps": [],
         "note": "keeps tickets on this computer and builds them on local branches you review; nothing goes to GitHub"},
    ]


def options_text(project):
    out = [f"  {sentence(project)}", "", "  Pick one:", ""]
    for o in options(project):
        out.append(f"  ({o['key']}) {o['title']}")
        if o["command"]:
            out.append(f"        {o['command']}")
        for i, s in enumerate(o["steps"], 1):
            out.append(f"        {i}. {s}")
        if o["note"]:
            out.append(f"      {o['note']}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def explain(project):
    try:
        e = _entry(project)
    except ValueError as err:
        print(f"  {err}")
        return 2
    if e.get("repo"):
        print(f"  {project} uses the GitHub repo {e['repo']}.")
        print(f"  To use another one: qtdeck repo {project} <owner/name>")
        return 0
    print(options_text(project), end="")
    return 0


# ---- gh, through the seam ---------------------------------------------------------------------------------------------------------
def _gh(*args, timeout=60):
    """(returncode, stdout, stderr) of gh; (127, '', why) when it cannot be run. No secret is ever an argument here."""
    exe = os.environ.get("QUARTERDECK_GH") or "gh"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "gh is not installed (run: qtdeck setup)"
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", f"gh could not be run: {type(e).__name__}"


def _tail(text, n=3):
    return "\n".join("    " + ln[:200] for ln in text.strip().splitlines()[-n:])


def _yes(ask, prompt):
    try:
        return ask(prompt).strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        return False


def create(project, public=False, i_mean_public=False, yes=False, push=False, ask=None, tty=None):
    """Make a GitHub repository for a project and connect it, after the owner says yes. Returns the exit code: 0 done, 1 declined or failed, 2 refused, 3 gh not
    signed in. `ask` and `tty` are for the tests (the answer to a prompt; whether there is a terminal)."""
    ask = ask or input
    tty = sys.stdin.isatty() if tty is None else tty
    try:
        e = _entry(project)
    except ValueError as err:
        print(f"  {err}")
        return 2
    if public and not i_mean_public:
        print("  --public would make the code visible to everyone. If you mean that, add --i-mean-public. Nothing was created.")
        return 2
    path = Path(os.path.expanduser(str(e.get("path") or "")))
    if not e.get("path") or not (path / ".git").exists():
        print(f"  {path} is not a git checkout, so there is nothing to connect a repository to. Nothing was created.")
        return 2
    if e.get("repo"):
        print(f"  {project} already uses the GitHub repo {e['repo']}. Nothing was created.")
        return 2
    try:
        r = _safegit.run(path, "remote", "get-url", "origin", timeout=20, text=True)
    except _safegit.Untrusted as err:
        print(f"  {err}")
        return 2
    except (OSError, ValueError) as err:
        print(f"  could not run git there: {type(err).__name__}")
        return 2
    if r.returncode == 0:
        print(f"  {path} already has a remote called origin. Connect that one with: qtdeck repo {project} <owner/name>. Nothing was created.")
        return 2
    rc, _, err = _gh("auth", "status", timeout=30)
    if rc != 0:
        print("  GitHub is not signed in on this computer, so nothing was created.")
        if rc == 127:
            print(f"  {err}")
        print("  Sign in first, in this terminal:   gh auth login")
        print(f"  then run this again:               qtdeck repo create {project} --private")
        return 3
    rc, out, err = _gh("api", "user", "--jq", ".login", timeout=30)
    login = out.strip()
    if rc != 0 or not LOGIN_OK.fullmatch(login):
        print("  gh did not give a plain GitHub user name, so nothing was created." + (f"\n{_tail(err)}" if rc != 0 else ""))
        return 2
    full = f"{login}/{project}"
    if not _attach.REPO_OK.fullmatch(full) or ".." in full or project.endswith((".git", ".lock")):
        print(f"  '{project}' cannot be a GitHub repository name (letters, digits, dash, dot and underscore only). Nothing was created.")
        return 2
    kind = "PUBLIC" if public else "PRIVATE"
    print(f"  This will:")
    print(f"    1. create a {kind} repository {full} on GitHub (gh repo create)")
    print(f"    2. connect it as the remote \"origin\" of {path}")
    print(f"    3. record {full} as the GitHub repo of {project}")
    print("  Nothing is pushed in this step.")
    if not yes:
        if not tty:
            print("  There is no terminal to type yes in. Run it in a terminal, or add --yes. Nothing was created.")
            return 2
        if not _yes(ask, "  Type yes to do this: "):
            print("  Nothing was created.")
            return 1
    rc, out, err = _gh("repo", "create", full, "--public" if public else "--private", "--source", str(path), "--remote", "origin", timeout=120)
    if rc != 0:
        print("  gh could not create the repository:")
        print(_tail(err or out))
        print("  Nothing was recorded.")
        return 1
    try:
        _attach.set_repo(project, full)
    except ValueError as err:
        print(f"  the repository {full} was created, but it could not be recorded: {err}")
        print(f"  record it with: qtdeck repo {project} {full}")
        return 1
    print(f"  created {kind.lower()} repository {full}, connected as origin, and recorded for {project}")
    branch = e.get("default_branch") or "main"
    ok = _safegit.valid_branch(branch)
    if ok:
        try:
            ok = _safegit.run(path, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", timeout=20).returncode == 0
        except (OSError, _safegit.Untrusted):
            ok = False
    if not ok:
        print(f"  There is no local branch {branch} to push, so nothing was pushed. Pull requests need one: push it yourself when it exists.")
        print(f"  next: qtdeck ticket new {project} \"<what you want>\"")
        return 0
    print()
    print(f"  Pull requests need the branch {branch} to be on GitHub too. I can push {branch} to {full} once.")
    print("  That is the only push this command makes, and Quarterdeck never pushes anything else on its own.")
    if not push:
        if not tty:
            print(f"  Not pushed (no terminal and no --push). When you want it: git -C {path} push -u origin {branch}")
            print(f"  next: qtdeck ticket new {project} \"<what you want>\"")
            return 0
        if not _yes(ask, f"  Type yes to push {branch}: "):
            print(f"  Not pushed. When you want it: git -C {path} push -u origin {branch}")
            print(f"  next: qtdeck ticket new {project} \"<what you want>\"")
            return 0
    try:
        r = _safegit.run(path, "push", "-u", "origin", branch, timeout=180, text=True)
    except (OSError, ValueError, _safegit.Untrusted, subprocess.SubprocessError) as err:
        print(f"  the push did not run: {type(err).__name__}")
        return 1
    if r.returncode != 0:
        print("  the push failed:")
        print(_tail(r.stderr or ""))
        print(f"  The repository exists and is recorded. Try again with: git -C {path} push -u origin {branch}")
        return 1
    print(f"  pushed {branch} to {full}")
    print(f"  next: qtdeck ticket new {project} \"<what you want>\"")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2 if not argv else 0
    cmd, a = argv[0], argv[1:]
    if cmd == "options" and len(a) == 1:
        return explain(a[0])
    if cmd == "sentence" and len(a) == 1:
        try:
            if _entry(a[0]).get("repo"):
                return 0
        except ValueError:
            return 0
        print(f"  {sentence(a[0])}")
        print(f"  {pointer(a[0])}")
        return 0
    if cmd == "create" and a:
        project, flags = a[0], a[1:]
        known = {"--private", "--public", "--i-mean-public", "--yes", "--push"}
        bad = [f for f in flags if f not in known]
        if bad:
            print(f"  unknown option {bad[0][:40]!r}. usage: qtdeck repo create <project> [--private | --public --i-mean-public] [--yes] [--push]")
            return 2
        if "--private" in flags and "--public" in flags:
            print("  choose --private or --public, not both. Nothing was created.")
            return 2
        return create(project, public="--public" in flags, i_mean_public="--i-mean-public" in flags, yes="--yes" in flags, push="--push" in flags)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
