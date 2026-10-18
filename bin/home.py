#!/usr/bin/env python3
"""Where Quarterdeck keeps YOUR data, apart from the program.

The program (bin/, duties/, crew/, dashboard/) lives where it was cloned. Everything that is yours lives in the Quarterdeck home: your registered projects
and overrides (config/), your runs, notes and connection state (state/), logs and working folders (logs/, workspace/). The two never mix, so the
program can be published or updated without touching your data, and a stranger starts with an empty home.

Which folder is the home, in this order (bin/lib.sh follows the same four rules):
  1. QUARTERDECK_HOME, if set;
  2. QUARTERDECK_DIR, if set: a throwaway Quarterdeck (the tests) keeps its data with its code;
  3. ~/.quarterdeck, once it carries the marker file .quarterdeck-home (made by `qtdeck home init`);
  4. on a first run, ~/.quarterdeck is made (first_run); the program folder itself only when your data already lives there (the older layout,
     moved by `home migrate`) or ~/.quarterdeck cannot be made.
"""
import json
import os
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
MARKER = ".quarterdeck-home"
SUBDIRS = ("config", "state", "logs", "workspace")

# remove after migration: an install made under the old name keeps its data folder until it is migrated (bin/legacy_home.py, never published)
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("legacy_home", Path(__file__).with_name("legacy_home.py"))
    _legacy = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_legacy)
except (OSError, ImportError, AttributeError):
    _legacy = None


def resolve(env=None, user_home=None, code=CODE):
    env = os.environ if env is None else env
    if env.get("QUARTERDECK_HOME"):
        return Path(env["QUARTERDECK_HOME"]).expanduser()
    if env.get("QUARTERDECK_DIR"):
        return Path(env["QUARTERDECK_DIR"])
    default = Path(user_home or Path.home()) / ".quarterdeck"
    if (default / MARKER).is_file():
        return default
    old = _legacy and _legacy.old_home(env, user_home)          # remove after migration
    return old or Path(code)


def why(env=None, user_home=None, code=CODE):
    """The rule that chose the home, for `qtdeck home`."""
    env = os.environ if env is None else env
    if env.get("QUARTERDECK_HOME"):
        return "QUARTERDECK_HOME is set"
    if env.get("QUARTERDECK_DIR"):
        return "QUARTERDECK_DIR is set (a throwaway Quarterdeck keeps its data with its code)"
    if ((Path(user_home or Path.home()) / ".quarterdeck") / MARKER).is_file():
        return "~/.quarterdeck has the marker file"
    if _legacy and _legacy.old_home(env, user_home):                # remove after migration
        return _legacy.WHY
    return "no data folder set up yet: data stays inside the program folder, as before"


def init(path):
    """Create an empty home: the folders and the marker. Never overwrites anything."""
    path = Path(path).expanduser()
    for d in SUBDIRS:
        (path / d).mkdir(parents=True, exist_ok=True)
        os.chmod(path / d, 0o700)
    os.chmod(path, 0o700)
    registry = path / "config" / "projects.json"
    if not registry.exists() and not registry.is_symlink():          # round 8 (L15): never written through a link, even a dangling one
        registry.write_text("{}\n")           # no projects yet: an empty registry, ready for `add`
    marker = path / MARKER
    if not marker.exists() and not marker.is_symlink():
        marker.write_text("This folder is a Quarterdeck home: your projects, state and logs live here, apart from the program.\n")
    return path


def program_has_data(code=CODE):
    """Whether someone's data already lives in the program folder (the older layout): a run on record, or a registry with a project in it.
    A registry that does not parse counts as data: it is not ours to ignore."""
    code = Path(code)
    if (code / "state" / "runs.json").exists():
        return True
    reg = code / "config" / "projects.json"
    if not reg.is_file():
        return False
    try:
        return json.loads(reg.read_text()) != {}
    except (OSError, ValueError):
        return True


def first_run(user_home=None, code=CODE):
    """Rule 4, when nothing is set up yet: (home, why, made). Makes ~/.quarterdeck (0700, the marker, an empty registry) so nothing of yours is
    written into the program folder. It does not when your data is already in the program folder (moving it is `home migrate`, a checked step),
    when ~/.quarterdeck exists without the marker (`home rollback` switched it off on purpose), or when it cannot be made."""
    default = Path(user_home or Path.home()) / ".quarterdeck"
    if program_has_data(code):
        return Path(code), "your data is still inside the program folder: `qtdeck home migrate` copies it to ~/.quarterdeck, checked", False
    if default.exists() or default.is_symlink():
        return Path(code), "~/.quarterdeck is there without its marker (switched off?): data stays inside the program folder", False
    try:
        init(default)
    except OSError:
        return Path(code), "~/.quarterdeck could not be made: data stays inside the program folder", False
    return default, "~/.quarterdeck has the marker file", True


# ---- moving an existing setup across: copy, check, switch, never delete -------------------------------------------------------------

MOVE_DIRS = ("state", "logs", "workspace")
MOVE_FILES = ("config/projects.json", "config/integrations.json", "config/fleet.local.json", "guard-denylist.txt")
LIVE_NOTE = "its owner is still running (stop it first, then run this again)"


def _count(path):
    n = size = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, size


def plan(src, dst):
    """[(item, kind, files, bytes, note)] for what would be copied from the program folder `src` into `dst`."""
    src, dst, rows = Path(src), Path(dst), []
    for d in MOVE_DIRS:
        p = src / d
        if p.is_dir() and not p.is_symlink():          # round 8 (L15): a program-folder item that is itself a link is not followed
            n, size = _count(p)
            rows.append((d + "/", "folder", n, size, "target already has files, they are kept and only missing ones are added" if (dst / d).is_dir() and any((dst / d).iterdir()) else ""))
    for f in MOVE_FILES:
        p = src / f
        if p.is_file() and not p.is_symlink():
            clash = (dst / f).exists() and not ((dst / f).name == "projects.json" and (dst / f).read_text().strip() == "{}")
            rows.append((f, "file", 1, p.stat().st_size, "target already has this file: the copy is kept beside it as .from-program" if clash else ""))
    return rows


def live_processes(src):
    """Reasons it is unsafe to copy now: a dashboard whose pid file points at a live process, or a duty lock."""
    why = []
    pid = Path(src) / "state" / "dashboard.pid"
    try:
        n = int(pid.read_text().strip())
        os.kill(n, 0)
        why.append(f"the dashboard (process {n}) is running")
    except (OSError, ValueError):
        pass
    for lock in sorted((Path(src) / "state").glob("*.lock")):
        try:
            n = int((lock / "pid" if lock.is_dir() else lock).read_text().strip().split()[0])
            os.kill(n, 0)
            why.append(f"a duty is running ({lock.name}, process {n})")
        except (OSError, ValueError, IndexError):
            continue                                   # a lock whose process is gone is a leftover, not a reason to wait
    return why[:6]


def _new_file(src, t):
    """Copies src to a NEW file t, owner-only, never through a link (round 8, L15): O_EXCL and O_NOFOLLOW, so a link (even a dangling one) planted at t
    makes this fail instead of writing outside the data folder."""
    import shutil
    fd = os.open(t, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as o, open(src, "rb") as i:
        shutil.copyfileobj(i, o)
    shutil.copystat(src, t, follow_symlinks=False)
    os.chmod(t, 0o600)


def _copy_tree(a, b):
    """Copies what is missing in b; returns the (source, copy) pairs it copied, which is what the verify step checks. Round 8 (L15): a folder in the
    destination that is a link is not entered (nothing under it is written), a destination file that is a link is skipped, and new files are
    made with _new_file."""
    copied = []
    for root, dirs, files in os.walk(a):               # followlinks=False: a source folder that is a link is never walked
        rel = Path(root).relative_to(a)
        if (b / rel).is_symlink() or (rel == Path(".") and b.is_symlink()):
            dirs[:] = []
            continue
        (b / rel).mkdir(parents=True, exist_ok=True)
        os.chmod(b / rel, 0o700, follow_symlinks=False)  # private whatever the old modes were
        for f in files:
            t = b / rel / f
            if os.path.islink(Path(root) / f) or t.is_symlink():
                continue                               # a link could point at a secret anywhere on the disk: never followed, never copied
            if not t.exists():
                _new_file(Path(root) / f, t)
                copied.append((Path(root) / f, t))
    return copied


def _digest(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def migrate(src, dst, apply=False, force=False):
    """Copy the data in the program folder into the data folder, verify the copy, and only then add the marker that switches over.
    Originals are never touched. Returns (ok, lines)."""
    import shutil
    src, dst, out = Path(src), Path(dst).expanduser(), []
    if src.resolve() == dst.resolve():
        return False, ["  the data folder is the program folder: there is nothing to move"]
    rows = plan(src, dst)
    out.append(f"  from {src}\n  to   {dst}")
    for item, kind, n, size, note in rows:
        out.append(f"    {item:<26} {n:>6} file(s) {size / 1024:>9.0f} KB  {note}")
    if not rows:
        return True, out + ["  nothing to move"]
    live = live_processes(src) + live_processes(dst)          # round 8 (M9): a live data folder is not copied into either
    if live and not force:
        return False, out + ["  not safe to copy now: " + "; ".join(live), "  stop it, or add --force if you accept a copy of live files"]
    if not apply:
        return True, out + ["", "  dry run: nothing was copied. Add --apply to copy, check, and switch over (the originals stay where they are)."]
    if dst.is_symlink() or any((dst / d).is_symlink() for d in SUBDIRS):
        return False, out + ["  the data folder, or one of its folders, is a link: nothing is copied into it (copy into a real folder)"]
    marker = dst / MARKER
    was_active = marker.is_file()                     # round 8 (M9): an active data folder stays active whatever happens below
    init(dst)
    if not was_active and marker.exists():
        marker.unlink()                               # a fresh folder is switched off while copying: an interrupted copy changes nothing
    copied = []
    try:
        for d in MOVE_DIRS:
            if (src / d).is_dir() and not (src / d).is_symlink():
                copied += _copy_tree(src / d, dst / d)
        for f in MOVE_FILES:
            if (src / f).is_file() and not (src / f).is_symlink():
                t = dst / f
                if t.is_symlink() or Path(str(t) + ".from-program").is_symlink() or t.parent.is_symlink():
                    continue                                    # round 8 (L15): never written through a link
                t.parent.mkdir(parents=True, exist_ok=True)
                if t.exists() and t.name == "projects.json" and t.read_text().strip() == "{}":
                    t.unlink()                                  # the empty registry `init` makes is a placeholder, not something of yours
                if t.exists() and _digest(t) != _digest(src / f):
                    if not Path(str(t) + ".from-program").exists():
                        _new_file(src / f, Path(str(t) + ".from-program"))
                elif not t.exists():
                    _new_file(src / f, t)
                for q in (t, Path(str(t) + ".from-program")):
                    if q.exists():
                        os.chmod(q, 0o600)
    except OSError as e:
        return False, out + [f"  copy failed ({e}); nothing was switched and the originals are untouched"
                             + (" (this folder was already the active one and stays so)" if was_active else "")]
    bad = []
    for item, kind, n, size, note in rows:
        if kind == "folder":
            continue                                  # the folders: only the files this run copied are checked, just below
        else:
            b = dst / item
            a = src / item
            if not b.exists() and not Path(str(b) + ".from-program").exists():
                bad.append(item)
            elif b.exists() and _digest(a) != _digest(b) and not Path(str(b) + ".from-program").exists():
                bad.append(item)
    for a, b in copied:                               # round 8 (M9): a file kept from an earlier run may have grown since, as the plan says it is kept
        if not b.is_file() or b.is_symlink() or b.stat().st_size != a.stat().st_size:
            bad.append(str(a.relative_to(src)))
    if bad:
        return False, out + [f"  the copy did not verify ({len(bad)} file(s), for example {bad[0]}); nothing was switched"
                             + (" (this folder was already the active one and stays so)" if was_active else "")]
    if marker.is_symlink() or (dst / "MIGRATED-FROM").is_symlink():
        return False, out + ["  the marker or MIGRATED-FROM in the data folder is a link: nothing was switched"]
    marker.write_text("This folder is a Quarterdeck home: your projects, state and logs live here, apart from the program.\n")
    (dst / "MIGRATED-FROM").write_text(f"{src}\ncopied {len(rows)} item(s); the originals were left in place and can be deleted once you are happy.\n")
    return True, out + ["", "  copied and verified. The marker is in place, so the next start uses this folder.", f"  to go back: qtdeck home rollback   (the originals in {src} were not touched)"]


def rollback(dst):
    marker = Path(dst).expanduser() / MARKER
    if not marker.exists():
        return False, "  there is no marker here: this folder is not the active data folder"
    marker.rename(marker.with_name(MARKER + ".off"))
    return True, f"  switched back: {marker.parent} is no longer used, the program folder is again. Nothing was deleted."


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        print(resolve())
    elif cmd == "why":
        print(why())
    elif cmd == "init":
        print(init(sys.argv[2] if len(sys.argv) > 2 else Path.home() / ".quarterdeck"))
        print("  next: qtdeck attach <your project folder>")
    elif cmd == "first-run":                      # bin/lib.sh, rule 4: three lines, the home, why, and 1 if it was just made
        h, w, made = first_run()
        print(f"{h}\n{w}\n{int(made)}")
    elif cmd == "migrate":
        a = sys.argv[2:]
        dst = a[a.index("--to") + 1] if "--to" in a else str(Path.home() / ".quarterdeck")
        ok, lines = migrate(CODE, dst, apply="--apply" in a, force="--force" in a)
        print("\n".join(lines))
        sys.exit(0 if ok else 1)
    elif cmd == "rollback":
        ok, line = rollback(sys.argv[2] if len(sys.argv) > 2 else Path.home() / ".quarterdeck")
        print(line)
        sys.exit(0 if ok else 1)
    else:
        sys.exit("usage: home.py [show|why|init [path]|migrate [--to path] [--apply] [--force]|rollback [path]]")
