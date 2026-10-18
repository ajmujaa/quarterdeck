#!/usr/bin/env python3
"""qtdeck setup: check the tools Quarterdeck needs, print the install command for anything missing, make the data folder, offer attach.

It installs nothing and runs no package manager: every install line is printed for you to read and run yourself. Standard library only.
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home

# tool -> (what it is for, package name per manager). None: not a package; the line says where to get it.
TOOLS = {
    "git": ("version control", {"brew": "git", "apt-get": "git", "dnf": "git"}),
    "jq": ("reads JSON in the scripts", {"brew": "jq", "apt-get": "jq", "dnf": "jq"}),
    "gh": ("the GitHub command line", {"brew": "gh", "apt-get": "gh", "dnf": "gh"}),
    "claude": ("Claude Code, which runs the agents", None),
    "bwrap": ("bubblewrap, the Linux sandbox project commands run in", {"apt-get": "bubblewrap", "dnf": "bubblewrap"}),
    "node": ("Node 20 or newer, only for some tests (optional)", {"brew": "node", "apt-get": "nodejs", "dnf": "nodejs"}),
}


def install_cmd(tools, system, managers):
    """One line a person can run to install `tools` on this platform. Pure: `managers` is the set of package managers found."""
    lines, pkgs = [], []
    for t in tools:
        names = TOOLS[t][1]
        if names is None:
            lines.append("Claude Code: see https://claude.com/claude-code, then run claude once and sign in")
        else:
            pkgs.append(t if not names else next((names[m] for m in ("brew", "apt-get", "dnf") if m in managers and m in names), t))
    if pkgs:
        if system == "Darwin" and "brew" in managers:
            lines.insert(0, "brew install " + " ".join(pkgs))
        elif "apt-get" in managers:
            lines.insert(0, "sudo apt-get update && sudo apt-get install -y " + " ".join(pkgs))   # without the update an image's stale index answers 404
        elif "dnf" in managers:
            lines.insert(0, "sudo dnf install -y " + " ".join(pkgs))
        elif system == "Darwin":
            lines.insert(0, "install Homebrew (https://brew.sh), then: brew install " + " ".join(pkgs))
        else:
            lines.insert(0, "install with your package manager: " + " ".join(pkgs))
    return "\n".join(lines)


def signed_in(argv):
    try:
        return subprocess.run(argv, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    system = platform.system()
    managers = {m for m in ("brew", "apt-get", "dnf") if shutil.which(m)}
    print("── Quarterdeck setup ──\n")
    ok = sys.version_info >= (3, 10)
    print(f"  {'ok ' if ok else 'old'}  python3 {platform.python_version()}" + ("" if ok else "  (3.10 or newer is needed)"))
    need = ["git", "jq", "gh", "claude"] + (["bwrap"] if system == "Linux" else [])
    missing, optional = [t for t in need if not shutil.which(t)], [t for t in ("node",) if not shutil.which(t)]
    for t in need + ["node"]:
        print(f"  {'ok ' if shutil.which(t) else '---'}  {t:<7} {TOOLS[t][0]}" + ("" if shutil.which(t) else "  (missing)"))
    gh = os.environ.get("QUARTERDECK_GH") or "gh"
    claude = os.environ.get("CLAUDE_BIN") or "claude"
    todo = []
    if missing or optional:
        print("\n  to install what is missing (setup installs nothing; read the line, then run it yourself):")
        if missing:
            print("    " + install_cmd(missing, system, managers).replace("\n", "\n    "))
        if optional:
            print("    optional: " + install_cmd(optional, system, managers))
    if shutil.which(gh) and not signed_in([gh, "auth", "status"]):
        todo.append("gh auth login")
    if shutil.which(claude) and not signed_in([claude, "auth", "status"]):
        todo.append("claude   (run it once and sign in)")
    if todo:
        print("\n  then sign in:\n" + "".join(f"    {t}\n" for t in todo), end="")
    # the data folder: the one in use if there is one, else a first run makes ~/.quarterdeck (bin/home.py first_run)
    home = _home.resolve()
    if home == _home.CODE and not os.environ.get("QUARTERDECK_HOME") and not os.environ.get("QUARTERDECK_DIR"):
        home, why, made = _home.first_run()
        print(f"\n  data folder  {home}" + ("  (made now)" if made else f"  ({why})"))
    else:
        if os.environ.get("QUARTERDECK_HOME") and not (home / _home.MARKER).exists() and not home.exists():
            _home.init(home)
        print(f"\n  data folder  {home}")
    if missing:
        print("\n  next: install what is missing, then run qtdeck setup again")
        return 1
    if sys.stdin.isatty():
        try:
            folder = input("\n  attach a project now? its folder (empty to skip): ").strip()
        except EOFError:
            folder = ""
        if folder:
            qtdeck = str(Path(__file__).resolve().parent / "qtdeck")
            return subprocess.call(["bash", qtdeck, "attach", os.path.expanduser(folder)])
    print("\n  next: qtdeck attach <your project folder>   (shows what it found; --apply registers it)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
