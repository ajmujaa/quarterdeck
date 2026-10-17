#!/usr/bin/env python3
"""Verify the vendored third-party files against pinned sha256 hashes.

    python3 bin/vendor-verify.py --write   regenerate HASHES.json
    python3 bin/vendor-verify.py           verify; exit 1 and list what changed

Only files under dashboard/assets/vendor/ are read. Symlinks are refused, never followed.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "dashboard" / "assets" / "vendor"
SKIP = {"HASHES.json", "VENDOR.md"}


def scan(vendor):
    """Return {relative path: sha256 hex}. Raises ValueError on a symlink."""
    out = {}
    base = os.path.realpath(vendor)
    for dirpath, dirnames, filenames in os.walk(vendor, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                raise ValueError(f"symlink refused: {os.path.relpath(p, vendor)}")
        for name in filenames:
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, vendor).replace(os.sep, "/")
            if rel in SKIP:
                continue
            if not os.path.realpath(p).startswith(base + os.sep):
                raise ValueError(f"outside the vendor folder: {rel}")
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = h.hexdigest()
    return dict(sorted(out.items()))


def compare(vendor):
    """Return (changed, added, removed, count) against HASHES.json."""
    pinned = json.loads((Path(vendor) / "HASHES.json").read_text())
    now = scan(vendor)
    changed = sorted(k for k in now if k in pinned and now[k] != pinned[k])
    added = sorted(k for k in now if k not in pinned)
    removed = sorted(k for k in pinned if k not in now)
    return changed, added, removed, len(now)


def main(argv):
    if argv not in ([], ["--write"]):
        print("usage: vendor-verify.py [--write]", file=sys.stderr)
        return 2
    try:
        if argv:
            hashes = scan(VENDOR)
            (VENDOR / "HASHES.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
            print(f"wrote HASHES.json with {len(hashes)} files")
            return 0
        changed, added, removed, n = compare(VENDOR)
    except (ValueError, OSError) as e:
        print(f"vendor check failed: {e}", file=sys.stderr)
        return 1
    if changed or added or removed:
        for label, names in (("changed", changed), ("added", added), ("removed", removed)):
            for name in names:
                print(f"{label}: {name}")
        return 1
    print(f"vendor files match HASHES.json ({n} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
