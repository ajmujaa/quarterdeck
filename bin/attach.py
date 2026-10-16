#!/usr/bin/env python3
"""attach: scan a project folder, propose how the crew should work on it, and register it only when you say so.

    bin/attach.py PATH [--name NAME]            show the profile and the proposal; changes nothing
    bin/attach.py PATH [--name NAME] --apply    register it in your registry and keep the profile and a record of what was proposed

The proposal is what the scan supports and no more: the read-only duties first, the verify command only if the project has one, the
paths the crew may not touch taken from the sensitive folders and secret files found. Nothing is written into the project itself.
The registry, the profile and the record all live in your data folder. Standard library only; reads files, never the network.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home
import scan as _scan
import packs as _packs

READ_ONLY_DUTIES = ["surveyor", "foreman", "inspector"]
GUARDRAILS = ["Never merge a pull request.", "Never push to the default branch; every change goes on its own branch.",
              "Never touch .env files or anything that holds a secret.", "Follow the repository's own AGENTS.md or CLAUDE.md where it has one."]


def default_branch(root, prof):
    ref = Path(root) / ".git" / "refs" / "remotes" / "origin" / "HEAD"
    try:
        m = re.search(r"refs/remotes/origin/(\S+)", ref.read_text())
        if m:
            return m.group(1)
    except OSError:
        pass
    for b in ("main", "master"):
        if (Path(root) / ".git" / "refs" / "heads" / b).exists():
            return b
    return prof["git"].get("branch") or "main"


def repo_of(prof):
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", prof["git"].get("origin", ""))
    return m.group(1) if m else ""


def propose(prof, name=None):
    """The registry entry the scan supports, with a reason for each part. A dict: entry, reasons."""
    root = Path(prof["path"])
    tests = [c for c in prof["commands"] if c["name"].startswith("test:")]
    verify = tests[0]["name"].split(": ", 1)[1] if tests else ""
    forbidden = [d["evidence"][0] for d in prof["sensitive"] if d["name"] in ("database migrations", "secrets", "encryption", "payments")]
    forbidden += [s["evidence"][0] for s in prof["secret_files"]] + [i["evidence"][0].rsplit("/", 1)[0] + "/" for i in prof["infrastructure"] if "/" in i["evidence"][0] and "prod" in i["evidence"][0].lower()]
    duties = list(READ_ONLY_DUTIES) + (["shipwright"] if verify else [])
    why = {"duties": "read-only duties first" + ("; the Shipwright too, since there is a command to prove its work" if verify else "; no Shipwright until a verify command is set"),
           "verify": tests[0]["evidence"][0] if tests else "no test command was found",
           "forbidden_paths": "sensitive folders and secret files found by the scan" if forbidden else "nothing sensitive was found"}
    fit = _packs.select(prof)
    why["packs"] = ("stack notes for " + ", ".join(p["label"] for p, _ in fit) + ": " + "; ".join(h[0] for _, h in fit)) if fit else "no stack pack fits this project"
    entry = {"repo": repo_of(prof), "path": str(root).replace(str(Path.home()), "~", 1), "summary": "", "default_branch": default_branch(root, prof),
             "duties": duties, "guardrails": list(GUARDRAILS), "verify": verify, "forbidden_paths": sorted(dict.fromkeys(forbidden)),
             "packs": [p["id"] for p, _ in fit]}
    return {"name": (name or prof["name"]).lower(), "entry": entry, "reasons": why}


def registry_path():
    return _home.resolve() / "config" / "projects.json"


def load_registry(p):
    try:
        j = json.loads(Path(p).read_text())
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def apply(prop, prof, reg=None):
    """Register the proposal and keep the profile and the record. Refuses a name already registered. Returns the registry path."""
    name = prop["name"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,60}", name):
        raise ValueError("the name may hold lowercase letters, digits, dot, dash and underscore")
    reg = Path(reg or registry_path())
    cur = load_registry(reg)
    if name in cur:
        raise ValueError(f"'{name}' is already registered")
    cur[name] = prop["entry"]
    reg.parent.mkdir(parents=True, exist_ok=True)
    tmp = reg.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=2) + "\n")
    os.replace(tmp, reg)
    _scan.save(prof, name)
    rec = _scan.profile_dir() / f"{name}.attach.json"
    rec.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "proposed": prop["entry"], "reasons": prop["reasons"], "approved": prop["entry"], "approved_by": "owner, with --apply"}, indent=2) + "\n")
    return reg


def say(prop):
    e = prop["entry"]
    print(f"  proposal for '{prop['name']}'")
    print(f"    repo            {e['repo'] or '(no GitHub remote found; set it by hand)'}")
    print(f"    default branch  {e['default_branch']}")
    print(f"    duties          {', '.join(e['duties'])}   ({prop['reasons']['duties']})")
    print(f"    verify          {e['verify'] or '(none)'}   ({prop['reasons']['verify']})")
    print(f"    forbidden       {', '.join(e['forbidden_paths']) or '(none)'}   ({prop['reasons']['forbidden_paths']})")
    print(f"    stack notes     {', '.join(e['packs']) or '(none)'}   ({prop['reasons']['packs']})")
    print(f"    guardrails      {len(e['guardrails'])} standing rules, including never merge and never push to the default branch")


def main(argv):
    args, path, name, do = list(argv), None, None, False
    while args:
        a = args.pop(0)
        if a == "--name" and args:
            name = args.pop(0)
        elif a == "--apply":
            do = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif path is None:
            path = a
        else:
            print(__doc__)
            return 2
    if not path:
        print(__doc__)
        return 2
    try:
        prof = _scan.scan(path)
        _scan.say(prof)
        prop = propose(prof, name)
        say(prop)
        if do:
            print(f"  registered in {apply(prop, prof)}; the profile and a record of this proposal are in {_scan.profile_dir()}")
        else:
            print("  nothing was changed. Add --apply to register it.")
    except ValueError as e:
        print(f"  {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
