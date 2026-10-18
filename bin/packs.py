#!/usr/bin/env python3
"""packs: stack knowledge, plugged in without touching the core.

A pack is a folder: packs/<id>/pack.json says which projects it fits, packs/<id>/knowledge.md holds a short, concrete note the crew reads
before it works on such a project. Built-in packs live in the program's packs/ folder; yours live in your data folder under packs/ and
replace a built-in with the same id. Packs are instructions the agents will follow: read one before you install it.

    bin/packs.py list                    the packs found
    bin/packs.py match PATH              which packs fit the project folder at PATH (uses the project scan)
    bin/packs.py text ID [ID ...]        the knowledge of those packs, as the crew would read it
    bin/packs.py notice ID [ID ...]      the experimental sentence if any of those packs is experimental

pack.json: {"id", "label", "about", "tested" (optional: what was and was not verified), "status" (optional: "experimental" shows a tag everywhere the pack appears), "match": {"languages": [], "frameworks": [], "package_managers": [], "deploy_targets": [], "infrastructure": []}}
A pack fits when any one of its match names appears in the project's profile; more matches rank it higher. Standard library only.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home

ROOT = Path(__file__).resolve().parent.parent
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
KEYS = ("languages", "frameworks", "package_managers", "deploy_targets", "infrastructure")
EXPERIMENTAL_NOTE = "Tested on small examples only. Read the report as a second opinion, not a verdict."
MAX_KNOWLEDGE = 8000          # characters per pack: a note, not a manual


def dirs():
    return [ROOT / "packs", _home.resolve() / "packs"]


def _clean(raw, folder):
    if not isinstance(raw, dict) or raw.get("id") != folder.name or not SAFE_ID.match(str(raw.get("id", ""))):
        return None
    match = raw.get("match") if isinstance(raw.get("match"), dict) else {}
    m = {k: [str(x) for x in match.get(k, []) if isinstance(x, str)][:30] for k in KEYS}
    if not any(m.values()):
        return None
    try:
        text = (folder / "knowledge.md").read_text()[:MAX_KNOWLEDGE]
    except OSError:
        return None
    return {"id": raw["id"], "label": str(raw.get("label") or raw["id"])[:60], "about": str(raw.get("about") or "")[:200], "tested": str(raw.get("tested") or "")[:1200], "status": "experimental" if raw.get("status") == "experimental" else "", "match": m, "knowledge": text.strip(), "source": str(folder)}


def load(extra=None):
    """Built-in packs, then yours; yours replace a built-in with the same id. A broken pack is skipped, never fatal."""
    out = {}
    for d in ([Path(extra)] if extra else dirs()):
        for f in sorted(d.iterdir()) if d.is_dir() else []:
            try:
                p = _clean(json.loads((f / "pack.json").read_text()), f) if f.is_dir() else None
            except (OSError, ValueError):
                p = None
            if p:
                out[p["id"]] = p
    return list(out.values())


def select(profile, packs=None):
    """Packs that fit a project profile (from scan.py), best fit first: [(pack, [what matched])]."""
    packs = load() if packs is None else packs
    have = {k: {i["name"].lower() for i in profile.get(k, [])} for k in KEYS}
    out = []
    for p in packs:
        hit = [f"{k}: {n}" for k in KEYS for n in p["match"][k] if n.lower() in have[k]]
        if hit:
            out.append((p, hit))
    return sorted(out, key=lambda x: (-len(x[1]), x[0]["id"]))


def text(ids, packs=None):
    """The knowledge of the named packs, ready to put in front of the crew. Unknown ids are skipped."""
    by = {p["id"]: p for p in (load() if packs is None else packs)}
    return "\n\n".join(f"## Stack notes: {by[i]['label']}\n{by[i]['knowledge']}" for i in ids if i in by)


def notice(ids, packs=None):
    """The experimental sentence when any named pack is experimental, else an empty string (the infra report footer)."""
    by = {p["id"]: p for p in (load() if packs is None else packs)}
    return EXPERIMENTAL_NOTE if any(by.get(i, {}).get("status") == "experimental" for i in ids) else ""


def main(argv):
    cmd, rest = (argv[0] if argv else ""), argv[1:]
    if cmd == "list":
        for p in load():
            print(f"  {p['id']:<20} {p['label']}{'  [' + p['status'] + ']' if p['status'] else ''}  ({p['about']})")
            if p["tested"]:
                print(f"  {'':<20} tested: {p['tested']}")
        return 0
    if cmd == "match" and rest:
        import scan as _scan
        try:
            prof = _scan.scan(rest[0])
        except ValueError as e:
            print(f"  {e}")
            return 2
        got = select(prof)
        for p, hit in got:
            print(f"  {p['id']:<20} {', '.join(hit)}")
        if not got:
            print("  no pack fits this project")
        return 0
    if cmd == "notice" and rest:
        print(notice(rest))
        return 0
    if cmd == "text" and rest:
        print(text(rest))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
