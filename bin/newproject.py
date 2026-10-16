#!/usr/bin/env python3
"""newproject: start something new. Makes a folder with a git repository, a README that says what it is for and a .gitignore, and stops there.

    bin/newproject.py NAME [--in DIR] [--about "one sentence"]     DIR defaults to ~/Projects

It refuses a folder that already exists with anything in it, writes only inside the new folder, and does not register anything or contact
any service: the next step, `bin/quarterdeck attach <folder> --apply`, is yours. Standard library only (git must be installed).
"""
import re
import subprocess
import sys
from pathlib import Path

GITIGNORE = ".env\n.env.*\n!.env.example\n*.pem\nnode_modules/\n__pycache__/\n.venv/\ndist/\nbuild/\n.DS_Store\n"


def create(name, parent=None, about=""):
    """Make the project and return its folder. Raises ValueError with a sentence the owner can act on."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", name or ""):
        raise ValueError("the name may hold letters, digits, dot, dash and underscore, and must start with a letter or digit")
    base = Path(parent).expanduser() if parent else Path.home() / "Projects"
    dest = base / name
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError(f"{dest} already exists and is not empty")
    about = " ".join(str(about or "").split())[:300]
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError("git could not start a repository: " + (r.stderr.strip() or "unknown error")[:160])
    (dest / "README.md").write_text(f"# {name}\n\n{about or 'Say here, in a sentence, what this is for.'}\n")
    (dest / ".gitignore").write_text(GITIGNORE)
    return dest


def main(argv):
    args, name, parent, about = list(argv), None, None, ""
    while args:
        a = args.pop(0)
        if a == "--in" and args:
            parent = args.pop(0)
        elif a == "--about" and args:
            about = args.pop(0)
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif name is None:
            name = a
        else:
            print(__doc__)
            return 2
    if not name:
        print(__doc__)
        return 2
    try:
        dest = create(name, parent, about)
    except ValueError as e:
        print(f"  {e}")
        return 2
    print(f"  created {dest}  (a git repository with a README and a .gitignore)")
    print(f"  next: bin/quarterdeck attach {dest}    to see what the crew would do, then add --apply to register it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
