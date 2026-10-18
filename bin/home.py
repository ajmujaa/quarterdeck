#!/usr/bin/env python3
"""Where Quarterdeck keeps YOUR data, apart from the program.

The program (bin/, duties/, crew/, dashboard/) lives where it was cloned. Everything that is yours lives in the Quarterdeck home: your registered projects
and overrides (config/), your runs, notes and connection state (state/), logs and working folders (logs/, workspace/). The two never mix, so the
program can be published or updated without touching your data, and a stranger starts with an empty home.

Which folder is the home, in this order (bin/lib.sh follows the same four rules):
  1. QUARTERDECK_HOME, if set;
  2. QUARTERDECK_DIR, if set: a throwaway Quarterdeck (the tests) keeps its data with its code;
  3. ~/.quarterdeck, once it carries the marker file .quarterdeck-home (made by `qtdeck home init`);
  4. the program folder itself: the layout every earlier version had, so nothing moves until you say so.
"""
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
    if not registry.exists():
        registry.write_text("{}\n")           # no projects yet: an empty registry, ready for `add`
    marker = path / MARKER
    if not marker.exists():
        marker.write_text("This folder is a Quarterdeck home: your projects, state and logs live here, apart from the program.\n")
    return path


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
        if p.is_dir():
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


def _copy_tree(a, b):
    import shutil
    for root, dirs, files in os.walk(a):
        rel = Path(root).relative_to(a)
        (b / rel).mkdir(parents=True, exist_ok=True)
        os.chmod(b / rel, 0o700)                       # private whatever the old modes were
        for f in files:
            t = b / rel / f
            if os.path.islink(Path(root) / f):
                continue                               # a link could point at a secret anywhere on the disk: never followed, never copied
            if not t.exists():
                shutil.copy2(Path(root) / f, t)
                os.chmod(t, 0o600)


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
    live = live_processes(src)
    if live and not force:
        return False, out + ["  not safe to copy now: " + "; ".join(live), "  stop it, or add --force if you accept a copy of live files"]
    if not apply:
        return True, out + ["", "  dry run: nothing was copied. Add --apply to copy, check, and switch over (the originals stay where they are)."]
    init(dst)
    marker = dst / MARKER
    if marker.exists():
        marker.unlink()                               # switched off while copying: an interrupted copy changes nothing
    try:
        for d in MOVE_DIRS:
            if (src / d).is_dir():
                _copy_tree(src / d, dst / d)
        for f in MOVE_FILES:
            if (src / f).is_file() and not (src / f).is_symlink():
                t = dst / f
                t.parent.mkdir(parents=True, exist_ok=True)
                if t.exists() and t.name == "projects.json" and t.read_text().strip() == "{}":
                    t.unlink()                                  # the empty registry `init` makes is a placeholder, not something of yours
                if t.exists() and _digest(t) != _digest(src / f):
                    shutil.copy2(src / f, str(t) + ".from-program")
                elif not t.exists():
                    shutil.copy2(src / f, t)
                for q in (t, Path(str(t) + ".from-program")):
                    if q.exists():
                        os.chmod(q, 0o600)
    except OSError as e:
        return False, out + [f"  copy failed ({e}); nothing was switched and the originals are untouched"]
    bad = []
    for item, kind, n, size, note in rows:
        if kind == "folder":
            for root, _d, files in os.walk(src / item.rstrip("/")):
                for f in files:
                    a = Path(root) / f
                    if a.is_symlink():
                        continue
                    b = dst / a.relative_to(src)
                    if not b.exists() or b.stat().st_size != a.stat().st_size:
                        bad.append(str(a.relative_to(src)))
        else:
            b = dst / item
            a = src / item
            if not b.exists() and not Path(str(b) + ".from-program").exists():
                bad.append(item)
            elif b.exists() and _digest(a) != _digest(b) and not Path(str(b) + ".from-program").exists():
                bad.append(item)
    if bad:
        return False, out + [f"  the copy did not verify ({len(bad)} file(s), for example {bad[0]}); nothing was switched"]
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
