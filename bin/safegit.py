#!/usr/bin/env python3
"""safegit: the one way the Python tools run git against a folder that is not theirs.

A registered project, a worktree an agent made or a session's folder carries a .git/config and files (.gitattributes) that someone else may have written.
Git runs programs those name: a clean/smudge filter on `git add`, `status` and `worktree add`; a textconv on `diff`, `log -p` and `blame`; a signing
program on `commit`; a pager; an ssh command; a credential helper. bin/lib.sh does the same for the shell (SAFE_GIT, safe_git); this is the Python side,
with the same two controls:

  1. flags that switch off what a flag can switch off (hooks, fsmonitor, ssh command, ext:: transport, pager, signing, credential helpers of the repository)
  2. a refusal: a repository whose OWN configuration defines something git would run that no flag reaches (a filter, a textconv or external diff,
     a merge driver, a gpg program of any kind, url.<x>.insteadOf, include.path, a credential helper tied to a URL, a git proxy ...) is not touched at all.
     The registry opt-out for a folder you wrote yourself is "trusted_git_config": true.

    python3 bin/safegit.py check REPO      lists the risky keys (exit 1 if any); python3 bin/safegit.py branch NAME   exit 1 unless NAME is a plain branch name

Standard library only.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# A branch name that is safe in a command line and a path: no leading dash (it would pass for an option: --upload-pack=...), no "..", no control or
# shell characters. A name from an untrusted .git/HEAD or refs/remotes/origin/HEAD is checked with this before it goes anywhere.
BRANCH_OK = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}$")


def valid_branch(name):
    return (isinstance(name, str) and bool(BRANCH_OK.match(name)) and ".." not in name and "//" not in name
            and not name.endswith(("/", ".", ".lock")) and name != "@")


# Keys (lower-cased) that make git run something, which no -c flag of ours can switch off one by one. ONE list for both languages: bin/gitrisky.re is read
# here and by bin/lib.sh (an extended regular expression, matched against the lower-cased key).
RISKY = re.compile((Path(__file__).resolve().parent / "gitrisky.re").read_text().strip())
# Git LFS writes exactly these three into a repository's config with `git lfs install --local`; they are the one common, harmless use of a filter.
LFS_OK = {"filter.lfs.clean": "git-lfs clean -- %f", "filter.lfs.smudge": "git-lfs smudge -- %f", "filter.lfs.process": "git-lfs filter-process"}

_CRED = None


def _cred_args():
    """-c credential.helper= (drop the repository's), then the helpers of the owner's own global configuration put back."""
    global _CRED
    if _CRED is None:
        out = ["-c", "credential.helper="]
        try:
            r = subprocess.run(["git", "config", "--global", "--get-all", "credential.helper"], capture_output=True, text=True, timeout=10)
            for h in r.stdout.splitlines():
                if h.strip():
                    out += ["-c", "credential.helper=" + h]
        except (OSError, subprocess.SubprocessError):
            pass
        _CRED = out
    return _CRED


def flags():
    return ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.sshCommand=ssh", "-c", "protocol.ext.allow=never",
            "-c", "core.pager=cat", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "gpg.program=/usr/bin/false", "-c", "gc.auto=0"] + _cred_args()


def risky_config(repo):
    """The risky keys (with their values left out) the repository's own configuration defines, as a sorted list. Reading a config runs nothing."""
    found = set()
    for scope in ("--local", "--worktree"):
        try:
            r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), "config", scope, "-z", "--list"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode != 0:
            continue
        for ent in r.stdout.split("\0"):
            key, _, val = ent.partition("\n")
            k = key.lower()
            if k and RISKY.match(k) and LFS_OK.get(k) != val.strip():
                found.add(key)
    return sorted(found)


def trusted(repo):
    """True when the registry lists this folder with "trusted_git_config": true (a folder the owner wrote or has read)."""
    home = Path(os.environ.get("QUARTERDECK_HOME") or os.environ.get("QUARTERDECK_DIR") or (Path(__file__).resolve().parent.parent))
    try:
        reg = json.loads((home / "config" / "projects.json").read_text())
        want = Path(repo).resolve()
        return any(isinstance(p, dict) and p.get("trusted_git_config") is True and p.get("path")
                   and Path(os.path.expanduser(p["path"])).resolve() == want for p in reg.values())
    except (OSError, ValueError, AttributeError, RuntimeError):
        return False


class Untrusted(Exception):
    pass


_SEEN = {}


def refusal(repo):
    """None when git may be run in `repo`, else the sentence that says why not. Cached for a minute per folder."""
    if os.environ.get("QUARTERDECK_TRUSTED_GIT_CONFIG") == "1":      # set by bin/lib.sh for a registry entry with "trusted_git_config": true
        return None
    key = str(repo)
    hit = _SEEN.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    bad = [] if trusted(repo) else risky_config(repo)
    msg = None
    if bad:
        msg = (f"{repo} has git settings of its own that make git run programs ({', '.join(bad[:6])}); no git command was run there. "
               f"If you wrote that folder yourself, set \"trusted_git_config\": true for it in config/projects.json")
    _SEEN[key] = (time.time(), msg)
    return msg


def run(repo, *args, timeout=60, **kw):
    """subprocess.run of `git <flags> -C repo <args>`; raises Untrusted (touching nothing) for a repository that refusal() names."""
    msg = refusal(repo)
    if msg:
        raise Untrusted(msg)
    kw.setdefault("capture_output", True)
    return subprocess.run(["git", *flags(), "-C", str(repo), *args], timeout=timeout, **kw)


def main(argv):
    if len(argv) == 2 and argv[0] == "check":
        bad = [] if trusted(argv[1]) else risky_config(argv[1])
        print("\n".join(bad))
        return 1 if bad else 0
    if len(argv) == 2 and argv[0] == "branch":
        return 0 if valid_branch(argv[1]) else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
