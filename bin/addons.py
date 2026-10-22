#!/usr/bin/env python3
"""Add-ons in the data folder: which files may be loaded, and `qtdeck addon new|list`.

An add-on is one file, ext_<name>.py, with one function, install(core) (see ADDONS.md). Besides bin/ext_*.py the dashboard
imports <data folder>/addons/ext_*.py, but only when it is safe to trust what is there:

  * the folder is a real directory (not a link), owned by you, mode 0700;
  * each file is a regular file (not a link), owned by you, and not writable by group or others;
  * QUARTERDECK_ADDONS=off loads none of them.

Anything else is skipped with the reason, never fatal. No model and no project command can write to this folder (bin/lib.sh
protected_write_paths). This module reads file modes and names only; `list` never runs an add-on.

    python3 bin/addons.py new <name>      scaffold addons/ext_<name>.py and addons/test_<name>.py, never over an existing file
    python3 bin/addons.py list            loaded and skipped add-ons, with the reason
"""
import json
import os
import re
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home

NAME = re.compile(r"[a-z0-9][a-z0-9_]{0,31}")        # becomes ext_<name>.py and the module name, so no dash
STATUS_FILE = "addons-status.json"


def off(env=None):
    return (env if env is not None else os.environ).get("QUARTERDECK_ADDONS", "").strip().lower() == "off"


def folder(home):
    return Path(home) / "addons"


def check_folder(path):
    """None when the add-on folder may be used, else the reason it is skipped. A missing folder is not a problem: it returns "absent"."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "absent"
    except OSError as e:
        return f"cannot look at it ({type(e).__name__})"
    if stat.S_ISLNK(st.st_mode):
        return "the addons folder is a link"
    if not stat.S_ISDIR(st.st_mode):
        return "the addons path is not a folder"
    if st.st_uid != os.getuid():
        return "the addons folder is not owned by you"
    if stat.S_IMODE(st.st_mode) != 0o700:
        return "the addons folder is not mode 0700 (run: chmod 700 %s)" % path
    return None


def _file_problem(st):
    if stat.S_ISLNK(st.st_mode):
        return "it is a link"
    if not stat.S_ISREG(st.st_mode):
        return "it is not a regular file"
    if st.st_uid != os.getuid():
        return "it is not owned by you"
    if st.st_mode & 0o022:
        return "it is writable by group or others (run: chmod go-w <file>)"
    return None


def check_file(path):
    """None when the file may be loaded, else the reason."""
    try:
        return _file_problem(os.lstat(path))
    except OSError as e:
        return f"cannot look at it ({type(e).__name__})"


def read_source(path):
    """The file's text, checked on the very descriptor that is read (a file swapped for a link after the listing is refused). Raises ValueError."""
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        raise ValueError(f"cannot open it ({type(e).__name__})")
    with os.fdopen(fd, "rb") as f:
        why = _file_problem(os.fstat(f.fileno()))
        if why:
            raise ValueError(why)
        return f.read()


def candidates(home, env=None):
    """([(path, name)] that passed the checks, [(name, reason)] skipped). Names are the file's stem, ext_<name>."""
    d = folder(home)
    if off(env):
        return [], ([("addons folder", "turned off by QUARTERDECK_ADDONS=off")] if d.exists() else [])
    why = check_folder(d)
    if why == "absent":
        return [], []
    if why:
        return [], [("addons folder", why)]
    ok, skipped = [], []
    try:
        names = sorted(os.listdir(d))
    except OSError as e:
        return [], [("addons folder", f"cannot be read ({type(e).__name__})")]
    for n in names:
        if not (n.startswith("ext_") and n.endswith(".py")):
            continue
        stem = n[:-3]
        if not NAME.fullmatch(stem[4:]):
            skipped.append((stem, "the name is not lower case letters, digits and _"))
            continue
        why = check_file(d / n)
        (skipped.append((stem, why)) if why else ok.append((d / n, stem)))
    return ok, skipped


def write_status(home, rows):
    """state/addons-status.json: [{id, where, status, reason}], written by the dashboard after it loads, read by `list`."""
    p = Path(home) / "state" / STATUS_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(rows, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        pass


def listing(home, env=None):
    """Rows for `addon list`: the files in the folder with what the dashboard last said about them, plus the safety verdict now."""
    ok, skipped = candidates(home, env)
    try:
        last = {r["id"]: r for r in json.loads((Path(home) / "state" / STATUS_FILE).read_text()) if isinstance(r, dict) and r.get("where") == "local"}
    except (OSError, ValueError, TypeError, KeyError):
        last = {}
    rows = []
    for path, stem in ok:
        r = last.get(stem[4:])
        if r:
            rows.append((stem[4:], r.get("status", "?"), r.get("reason", "")))
        else:
            rows.append((stem[4:], "ready", "passes the checks; the dashboard loads it when it starts"))
    rows += [(n, "skipped", why) for n, why in skipped]
    return rows


TEMPLATE = '''"""{label}: a local add-on. One function, install(core); the contract is in ADDONS.md.

It shows one alert on the Needs you list when the file state/{name}/alert.txt has a line in it. It reads and writes nothing else.
"""
from pathlib import Path

ADDON_NAME = "{label}"


def install(core):
    folder = Path(core.STATE) / "{name}"

    def alerts(ack):
        try:
            text = (folder / "alert.txt").read_text(errors="replace").strip().splitlines()[0][:200]
        except (OSError, IndexError):
            return []
        key = "{name}:alert"
        return [{{"id": key, "source": "{name}", "project": "", "severity": "warn", "text": text, "at": core.iso(core.now_utc()),
                 "stale": False, "acknowledged": key in ack}}]

    core.EXT["attention"].append(alerts)
'''

TEST_TEMPLATE = '''#!/usr/bin/env python3
"""Test for the {label} add-on: a fake HOME, a temp data folder, nothing real. Run: python3 test_{name}.py"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path


class Core:
    EXT = {{"attention": []}}
    iso = staticmethod(lambda t: "2026-01-01T00:00:00Z")
    now_utc = staticmethod(lambda: None)

    def __init__(self, state):
        self.STATE = state


def main():
    with tempfile.TemporaryDirectory() as t:
        os.environ["HOME"] = t
        spec = importlib.util.spec_from_file_location("ext_{name}", Path(__file__).with_name("ext_{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        core = Core(Path(t) / "state")
        mod.install(core)
        fn = core.EXT["attention"][0]
        assert fn({{}}) == [], "no alert file, no alert"
        (Path(t) / "state" / "{name}").mkdir(parents=True)
        (Path(t) / "state" / "{name}" / "alert.txt").write_text("Example alert\\n")
        got = fn({{}})
        assert got and got[0]["text"] == "Example alert", got
    print("ok")


if __name__ == "__main__":
    sys.exit(main())
'''


def scaffold(name, home):
    """Create addons/ext_<name>.py and test_<name>.py. Returns the paths; raises ValueError (nothing written) or FileExistsError."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("a name is lower case letters, digits and _, up to 32, starting with a letter or digit")
    d = folder(home)
    why = check_folder(d)
    if why == "absent":
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    elif why:
        raise ValueError(why)
    label = name.replace("_", " ").title()
    made = []
    for fname, body, mode in ((f"ext_{name}.py", TEMPLATE, 0o600), (f"test_{name}.py", TEST_TEMPLATE, 0o600)):
        if (d / fname).exists() or (d / fname).is_symlink():
            raise FileExistsError(f"{d / fname} already exists, not overwriting")
    for fname, body, mode in ((f"ext_{name}.py", TEMPLATE, 0o600), (f"test_{name}.py", TEST_TEMPLATE, 0o600)):
        fd = os.open(str(d / fname), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "w") as f:
            f.write(body.format(name=name, label=label))
        made.append(d / fname)
    return made


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    home = _home.resolve()
    if a[:1] == ["new"] and len(a) == 2:
        try:
            made = scaffold(a[1], home)
        except (ValueError, OSError) as e:
            print(f"qtdeck addon: {e}", file=sys.stderr)
            return 1
        for p in made:
            print(f"  wrote {p}")
        print(f"\n  next: edit {made[0].name}, run `python3 {made[1]}` to test it, then restart the dashboard (qtdeck dashboard).")
        print("  Add-ons from this folder can be turned off with QUARTERDECK_ADDONS=off. Guide: ADDONS.md")
        return 0
    if a == ["list"]:
        if off():
            print("  add-ons from the data folder are turned off (QUARTERDECK_ADDONS=off)")
        rows = listing(home)
        if not rows:
            print(f"  no add-ons in {folder(home)}")
        for n, st, why in rows:
            print(f"  {n:<24} {st:<8} {why}")
        return 0
    print("usage: qtdeck addon new <name> | qtdeck addon list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
