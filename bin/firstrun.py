#!/usr/bin/env python3
"""The first-run checklist: what this machine has and lacks, as data. The same facts as `qtdeck doctor` and `qtdeck setup`, in one list.

facts() returns [{key, label, state: have|lack|unknown, detail, fix: {command, note}|null}]. It runs only the tools' own sign-in checks
(the same two commands `qtdeck setup` runs), installs nothing, and never reads or prints a secret: an API key is reported as present or not.
The first-run state (dismissed or not) is one small file in the data folder: state/first-run.json, mode 0600, written atomically.

    python3 bin/firstrun.py [--json]
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup as _setup

FILE = "first-run.json"


def _managers():
    return {m for m in ("brew", "apt-get", "dnf") if shutil.which(m)}


def _install(tool, system=None):
    """The one install line setup prints for a tool (bin/setup.py install_cmd); for claude, the line that says where to get it."""
    return _setup.install_cmd([tool], system or platform.system(), _managers())


def _auth(argv, timeout=10):
    """True signed in, False not signed in, None could not tell (the tool did not answer in time or could not start)."""
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout).returncode == 0
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None


def _key_present():
    try:
        import billing
        return bool(billing.key_present())
    except Exception:
        return None


def facts(py=None, key=None, timeout=10):
    """The checklist. py: (major, minor), key: True/False/None and timeout: seconds for a sign-in check; overrides for tests."""
    system = platform.system()
    item = lambda k, label, state, detail, fix=None: {"key": k, "label": label, "state": state, "detail": detail, "fix": fix}
    out = []
    claude_cmd = os.environ.get("CLAUDE_BIN") or "claude"
    gh_cmd = os.environ.get("QUARTERDECK_GH") or "gh"
    claude_at, gh_at = shutil.which(claude_cmd), shutil.which(gh_cmd)

    if claude_at:
        out.append(item("claude", "claude", "have", claude_at))
    else:
        out.append(item("claude", "claude", "lack", "not found", {"command": "qtdeck setup", "note": _install("claude")}))
    if gh_at:
        out.append(item("gh", "gh", "have", gh_at))
    else:
        out.append(item("gh", "gh", "lack", "not found", {"command": _install("gh", system), "note": _setup.TOOLS["gh"][0]}))
    git_at = shutil.which("git")
    out.append(item("git", "git", "have", git_at) if git_at else item("git", "git", "lack", "not found", {"command": _install("git", system), "note": _setup.TOOLS["git"][0]}))
    node_at = shutil.which("node")
    out.append(item("node", "node", "have", node_at) if node_at else
               item("node", "node", "lack", "not found (optional, only some tests use it)", {"command": _install("node", system), "note": _setup.TOOLS["node"][0]}))
    v = py or (sys.version_info[0], sys.version_info[1])
    ver = f"{v[0]}.{v[1]}" if py else platform.python_version()
    if v >= (3, 10):
        out.append(item("python3", "python3", "have", f"python3 {ver}"))
    else:
        pip = "brew install python@3.12" if system == "Darwin" else "sudo apt-get update && sudo apt-get install -y python3"
        out.append(item("python3", "python3", "lack", f"python3 {ver} (3.10 or newer is needed)", {"command": pip, "note": "Python 3.10 or newer"}))

    signed = _auth([claude_cmd, "auth", "status"], timeout) if claude_at else None
    if not claude_at:
        out.append(item("claude_auth", "claude signed in", "unknown", "checked once claude is installed"))
    elif signed is None:
        out.append(item("claude_auth", "claude signed in", "unknown", "claude did not answer"))
    elif signed:
        out.append(item("claude_auth", "claude signed in", "have", "yes"))
    else:
        out.append(item("claude_auth", "claude signed in", "lack", "not signed in", {"command": "claude", "note": "run it once and sign in"}))
    gsigned = _auth([gh_cmd, "auth", "status"], timeout) if gh_at else None
    if not gh_at:
        out.append(item("gh_auth", "gh signed in", "unknown", "checked once gh is installed"))
    elif gsigned is None:
        out.append(item("gh_auth", "gh signed in", "unknown", "gh did not answer"))
    elif gsigned:
        out.append(item("gh_auth", "gh signed in", "have", "yes"))
    else:
        out.append(item("gh_auth", "gh signed in", "lack", "not signed in", {"command": "gh auth login", "note": "only needed to read or open pull requests"}))
    kp = _key_present() if key is None else key
    if kp is None:
        out.append(item("api_key", "API key stored", "unknown", "could not tell"))
    elif kp:
        out.append(item("api_key", "API key stored", "have", "present (the key is never shown)"))
    elif signed:
        out.append(item("api_key", "API key stored", "lack", "not stored (optional while claude is signed in)"))
    else:
        out.append(item("api_key", "API key stored", "lack", "not stored (optional if you sign in to claude)",
                        {"command": "qtdeck keys set anthropic", "note": "an alternative to signing in; the key is stored privately and never shown again"}))
    return out


# ---- the one small state file ---------------------------------------------------------------------------------------------------------
def _path(home):
    return Path(home) / "state" / FILE


def read_state(home):
    try:
        d = json.loads(_path(home).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record(home, action):
    """Write {done_at, how} to state/first-run.json (0600, atomic, in the data folder only). action: demo | dismiss."""
    if action not in ("demo", "dismiss"):
        raise ValueError("action must be demo or dismiss")
    p = _path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"done_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "how": action}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return read_state(home)


def is_first(home, projects):
    """True until the owner dismisses the screen or registers a project."""
    return not read_state(home).get("done_at") and not projects


def status(home, projects):
    return {"first": is_first(home, projects), "done_at": read_state(home).get("done_at"), "items": facts()}


if __name__ == "__main__":
    rows = facts()
    if "--json" in sys.argv[1:]:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"  {r['state']:<7} {r['label']:<18} {r['detail']}" + (f"   fix: {r['fix']['command']}" if r["fix"] else ""))
