"""Where a project folder may live, for the dashboard and the command line alike: one rule, one message.

A project folder must sit under an allowed root (your home folder, or a folder named in QUARTERDECK_PROJECT_ROOTS, colon-separated,
in config/quarterdeck.env or the environment), and no part of the path below that root may be a hidden (dot) folder. The dashboard
(bin/dashboard.py) and `qtdeck attach` (bin/attach.py) both call check_project_folder. Standard library plus bin/home.py only.
"""
import os
import re
from pathlib import Path

import home as _home

ROOT = Path(__file__).resolve().parent.parent           # the program: bin/, duties/, crew/, dashboard/


def env_flag(name, default="", bases=None):
    """Read a value out of config/quarterdeck.env without sourcing it. Your own file in your data folder wins over the shipped defaults."""
    for base in dict.fromkeys(bases or (_home.resolve(), ROOT)):
        try:
            text = (base / "config" / "quarterdeck.env").read_text()
            m = re.search(rf'^{name}="\$\{{{name}:-([^}}]*)\}}"', text, re.M)
            if m:
                return os.environ.get(name, m.group(1))
        except Exception:
            continue
    return os.environ.get(name, default)


def project_roots(read=None):
    """The folders a project may live under: QUARTERDECK_PROJECT_ROOTS (colon-separated), else your home directory."""
    raw = (read or env_flag)("QUARTERDECK_PROJECT_ROOTS", "")
    out = []
    for part in [x for x in raw.split(":") if x.strip()] or [str(Path.home())]:
        try:
            out.append(Path(part.strip()).expanduser().resolve())
        except OSError:
            pass
    return out


def check_project_folder(raw, what="a project", whole=True, read=None, program=None):
    """The real folder `raw` names, or ValueError saying where projects may live. It must sit under an allowed root and no part of
    the path below that root may be a dot folder (.ssh, .aws, .config ...). Symlinks are followed first, so a link cannot lead out.
    With whole (the project folder itself, not the folder a new one goes in): not an allowed root, not the home folder, and neither
    the program folder, the data folder, nor a folder that holds either of them. `read` and `program` let the dashboard pass its own
    settings reader and (program folder, data folder); the command line uses the defaults."""
    roots = project_roots(read)
    prog = program or (ROOT, _home.resolve())
    try:
        real = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise ValueError(f"{raw} is not a usable folder name")
    for r in roots:
        try:
            rel = real.relative_to(r)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            raise ValueError(f"{raw} is inside a hidden folder, which {what} may not be")
        if whole and (real == r or real == Path.home().resolve()):
            raise ValueError(f"{raw} is a whole folder of projects, not one project. Choose the project's own folder inside it")
        if any(real == x or x in real.parents or (whole and real in x.parents) for x in (p.resolve() for p in prog)):
            raise ValueError(f"{raw} is, holds or sits inside Quarterdeck's own program or data folder, which {what} may not be")
        return real
    where = ", ".join(str(r) for r in roots)
    raise ValueError(f"{raw} is outside the places {what} may live ({where}). To allow another, set QUARTERDECK_PROJECT_ROOTS in your config/quarterdeck.env (folders separated by a colon)")


if __name__ == "__main__":      # for shell callers: projectroots.py check <folder> [--parent]  (exit 2 and the sentence on a refusal)
    import sys
    if len(sys.argv) in (3, 4) and sys.argv[1] == "check":
        try:
            check_project_folder(sys.argv[2], whole=sys.argv[3:] != ["--parent"])
        except ValueError as e:
            print(f"  {e}")
            sys.exit(2)
        sys.exit(0)
    print("usage: projectroots.py check <folder> [--parent]")
    sys.exit(2)
