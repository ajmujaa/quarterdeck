#!/usr/bin/env python3
"""ready: the one checklist that says whether a project is ready for the crew, and the one thing to do next.

    bin/ready.py show PROJECT [--details]       the checklist and one "next:" line (this is `qtdeck ready PROJECT`); changes nothing
    bin/ready.py json PROJECT                   the same as JSON (the dashboard's GET /api/ready)
    bin/ready.py record-verify PROJECT CMD EXIT SECONDS SANDBOX [FIRST-LINE]     keep the result of one real run (bin/prove writes it)

The items, in order: scan, verify, repo, docs, agents, cycle. Each is {key, label, state, detail, action}; state is done, todo, unknown or blocked.
Only the verify command can block anything. The repo, the docs and the agents are offers, said calmly: a project with none of them is still ready for
a first ticket. Everything here comes from files in your data folder (the registry, the survey, the attach record, verify.json, a waiting docs draft,
the ticket list). Nothing is run and nothing is written, except by `record-verify`, which only keeps what `qtdeck ready PROJECT --prove` found.

state/projects/<project>/verify.json  {at, command, exit, seconds, sandbox, first_line}   one real run of the verify command in the sandbox
Standard library only; no model, no network.
"""
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import survey as _survey

NODE_RUNNERS = ("npm", "pnpm", "yarn", "bun", "npx")
EXPLAIN_127 = ("the command was not found; the crew never installs dependencies: run npm install (or your install step) in the project first, "
               "or set a command that runs without one")
STATES = ("done", "todo", "unknown", "blocked")


def _clip(s, n=160):
    return " ".join(str(s).split())[:n]


def _plain_dashes(s):
    return str(s).replace("—", ", ").replace("–", "-")


# ---- reading what is kept ------------------------------------------------------------------------------------------------------
def _folder(project):
    return _survey.folder(project)


def read_json(path, default=None):
    try:
        j = json.loads(Path(path).read_text())
        return j
    except (OSError, ValueError):
        return default


def registry_entry(project):
    import attach as _attach
    e = _attach.load_registry(_attach.registry_path()).get(project)
    return e if isinstance(e, dict) else None


def verify_record(project):
    j = read_json(_folder(project) / "verify.json", None)
    return j if isinstance(j, dict) else None


def docs_draft(project):
    j = read_json(_folder(project) / "docs-draft.json", None)
    return j if isinstance(j, dict) and isinstance(j.get("files"), list) else None


def attach_record(project):
    import scan as _scan
    j = read_json(_scan.profile_dir() / f"{project}.attach.json", None)
    return j if isinstance(j, dict) else None


def tickets_of(project):
    import tickets as _tk
    try:
        return _tk.load(project)
    except Exception:
        return {"tickets": [], "drafts": []}


def expand(path):
    return Path(os.path.expanduser(str(path or "")))


# ---- the pieces -----------------------------------------------------------------------------------------------------------------
def install_hint(path, verify, sv=None):
    """For a Node project whose verify command is the project's own tool and whose node_modules is absent: the sentence that says what to do. Else ''."""
    cmd = (verify or "").split()
    if not cmd or cmd[0] not in NODE_RUNNERS or not path:
        return ""
    root = expand(path)
    if not (root / "package.json").is_file() or (root / "node_modules").exists():
        return ""
    pm = next((p for p in (sv or {}).get("package_managers", []) if p in ("npm", "pnpm", "yarn", "bun")), "npm")
    return (f"{pm} has not installed this project's tools yet (no node_modules), and the crew never installs: run {pm} install first, "
            "or set a verify command that needs no install, for example --verify \"node --test\"")


def manifest_mtime(path):
    root = expand(path)
    best = 0
    for m in _survey.MANIFESTS:
        try:
            best = max(best, int((root / m).stat().st_mtime))
        except OSError:
            continue
    return best


def _scan_item(name, sv, path, preview):
    if not sv:
        return {"key": "scan", "label": "Scan", "state": "todo", "detail": "This project has not been surveyed yet.", "action": f"qtdeck attach {shlex.quote(path or '<dir>')} --apply"}
    summary = (sv.get("stack") or {}).get("summary") or "stack not recognised"
    if preview:
        return {"key": "scan", "label": "Scan", "state": "done", "detail": f"Surveyed just now: {summary}. It is saved when you apply.", "action": ""}
    if path and manifest_mtime(path) > int(sv.get("surveyed_epoch") or 0):
        return {"key": "scan", "label": "Scan", "state": "todo", "detail": f"The scan is old: a manifest changed since {sv.get('surveyed_at', 'the last survey')}.",
                "action": f"qtdeck attach {shlex.quote(path)}"}
    return {"key": "scan", "label": "Scan", "state": "done", "detail": f"{summary}. Surveyed {sv.get('surveyed_at', '')}.", "action": ""}


def _verify_item(name, entry, sv, vrec, path, preview):
    cmd = (entry or {}).get("verify", "")
    if not cmd:
        return {"key": "verify", "label": "Verify command", "state": "blocked",
                "detail": "No verify command is set, so there is nothing to prove a change with.",
                "action": f"qtdeck attach {shlex.quote(path or '<dir>')} --verify \"<command>\" --apply"}
    hint = install_hint(path, cmd, sv)
    if preview:
        return {"key": "verify", "label": "Verify command", "state": "todo", "detail": f"{cmd}. After attaching, run it once to prove it works in the sandbox." + (f" Note: {hint}." if hint else ""),
                "action": f"qtdeck ready {name} --prove"}
    if not vrec or vrec.get("command") != cmd:
        why = "It was changed since it was last proven." if vrec else "It has not been run yet."
        return {"key": "verify", "label": "Verify command", "state": "todo", "detail": f"{cmd} is set. {why}" + (f" Note: {hint}." if hint else ""),
                "action": f"Run it once to prove it: qtdeck ready {name} --prove"}
    rc, first = vrec.get("exit"), _clip(vrec.get("first_line") or "", 140)
    if rc == 0:
        return {"key": "verify", "label": "Verify command", "state": "done",
                "detail": f"{cmd} ran in the sandbox and passed (exit 0, {vrec.get('seconds', 0)} s, {str(vrec.get('at', ''))[:10]}).", "action": ""}
    why = EXPLAIN_127 if rc == 127 else (first or "it printed nothing")
    detail = f"{cmd} exited {rc} in the sandbox. " + (f"First line: {first}. " if first and rc != 127 else "") + ("" if rc != 127 else f"Exit 127: {EXPLAIN_127}.")
    if rc == 127 and hint:
        detail += f" {hint[0].upper() + hint[1:]}."
    return {"key": "verify", "label": "Verify command", "state": "blocked", "detail": detail.strip(),
            "action": f"Fix it, then prove it again: qtdeck ready {name} --prove", "failed": True, "hint": why}


def _repo_item(name, entry):
    import attach as _attach
    if entry.get("repo"):
        return {"key": "repo", "label": "GitHub repo", "state": "done", "detail": f"Linked: {entry['repo']}.", "action": ""}
    return {"key": "repo", "label": "GitHub repo", "state": "todo",
            "detail": "Optional: tickets work on this computer without it. " + _attach.no_repo_sentence(name), "action": f"qtdeck repo {name}"}


def _docs_item(name, sv, draft):
    if not sv:
        return {"key": "docs", "label": "Docs", "state": "unknown", "detail": "The project has not been surveyed, so its documents are not known.", "action": ""}
    miss = sv["docs"]["missing"]
    names = {"readme": "README", "architecture": "an architecture overview"}
    if draft:
        waiting = [f.get("path") for f in draft.get("files", []) if isinstance(f, dict) and f.get("path")]
        if waiting:
            return {"key": "docs", "label": "Docs", "state": "todo", "detail": f"A draft of {', '.join(waiting)} is waiting. Nothing was written to your project.",
                    "action": f"qtdeck docs {name} --apply", "draft": waiting, "missing": sorted(miss)}
    if not miss:
        return {"key": "docs", "label": "Docs", "state": "done", "detail": "A README and an architecture overview are there.", "action": "", "missing": []}
    return {"key": "docs", "label": "Docs", "state": "todo",
            "detail": "Missing: " + " and ".join(names[k] for k in ("readme", "architecture") if k in miss) + ". The scribe can draft " + ("it" if len(miss) == 1 else "them")
            + " from the survey; nothing is written to your project until you say so.",
            "action": f"qtdeck docs {name}", "missing": sorted(miss)}


def _agents_item(name, entry, record):
    reasons = (record or {}).get("duty_reasons") or {}
    on = [d for d in entry.get("duties", [])]
    on_rows = [{"duty": d, "why": _clip((reasons.get(d) or {}).get("why") or "turned on in the registry", 200)} for d in on]
    sugg = [{"duty": d, "why": _clip(v.get("why", ""), 200), "command": f"qtdeck enable {name} {d}"} for d, v in sorted(reasons.items())
            if isinstance(v, dict) and v.get("suggested") and d not in on]
    detail = f"{len(on)} on: " + ", ".join(on) + "." + (f" {len(sugg)} more fit this project and are off: {', '.join(s['duty'] for s in sugg[:6])}{'...' if len(sugg) > 6 else ''}." if sugg else "")
    return {"key": "agents", "label": "Agents", "state": "done" if on else "todo", "detail": detail, "action": sugg[0]["command"] if sugg else "", "on": on_rows, "suggested": sugg}


def _cycle_item(name, entry):
    duties = entry.get("duties", [])
    ok = entry.get("cycle") is True and "purser" in duties and "panel" in duties
    if ok:
        return {"key": "cycle", "label": "Cycles", "state": "done", "detail": "Allowed: a ticket can go through the purser, the dev panel and the shipwright in one go. A cycle spends model money.", "action": ""}
    missing = [d for d in ("purser", "panel") if d not in duties]
    why = []
    if entry.get("cycle") is not True:
        why.append("it is not switched on")
    if missing:
        why.append("the " + " and ".join(missing) + " " + ("is" if len(missing) == 1 else "are") + " off")
    return {"key": "cycle", "label": "Cycles", "state": "todo", "detail": "Optional: a whole ticket in one go needs cycles (" + " and ".join(why) + "). A cycle spends model money, so it is never on by default.",
            "action": f"qtdeck enable {name} cycle"}


def build(name, entry, sv, record=None, vrec=None, draft=None, path=None, preview=False):
    """The items, in order. `entry` is the registry entry (or the proposal's entry for a preview); nothing here reads a file but through the arguments."""
    path = path or entry.get("path", "")
    return [_scan_item(name, sv, path, preview), _verify_item(name, entry, sv, vrec, path, preview), _repo_item(name, entry),
            _docs_item(name, sv, draft), _agents_item(name, entry, record), _cycle_item(name, entry)]


def next_action(name, entry, items, tk=None, path=None):
    """Exactly one: {kind, text, command}. In this order: no verify command, verify unproven, verify failed, then a first ticket (or a mission)."""
    by = {i["key"]: i for i in items}
    v = by["verify"]
    path = path or entry.get("path", "")
    if v["state"] == "blocked" and not v.get("failed"):
        cmd = f"qtdeck attach {shlex.quote(path or '<dir>')} --verify \"<command>\" --apply"
        return {"kind": "set-verify", "text": f"Set a verify command: {cmd}", "command": cmd}
    if v["state"] == "todo":
        cmd = f"qtdeck ready {name} --prove"
        return {"kind": "prove", "text": f"Run it once to prove it: {cmd}", "command": cmd}
    if v.get("failed"):
        return {"kind": "fix-verify", "text": f"Fix the verify command ({_clip(v['hint'], 150)}), then prove it again: qtdeck ready {name} --prove", "command": f"qtdeck ready {name} --prove"}
    open_t = sorted((t for t in (tk or {}).get("tickets", []) if t.get("status") == "open"), key=lambda t: t.get("id", 0))
    if open_t:
        t = open_t[0]
        if by["cycle"]["state"] != "done":
            cmd = f"qtdeck enable {name} cycle"
            return {"kind": "enable-cycle", "text": f"Allow cycles so ticket {t['id']} can be built: {cmd}", "command": cmd}
        cmd = f"qtdeck cycle {name} --ticket {t['id']}" if t.get("source") != "github" else f"qtdeck cycle {name} --issue {t.get('issue')}"
        return {"kind": "mission", "text": f"Start a mission from ticket {t['id']}: {cmd}", "command": cmd}
    cmd = f"qtdeck ticket new {name} \"<what you want built>\""
    return {"kind": "ticket", "text": f"File your first ticket: {cmd}", "command": cmd}


def is_ready(items):
    by = {i["key"]: i for i in items}
    return by["verify"]["state"] == "done" and by["scan"]["state"] != "unknown"


def view(project):
    entry = registry_entry(project)
    if entry is None:
        raise ValueError(f"'{project}' is not registered (see: qtdeck projects)")
    sv = _survey.load(project)
    items = build(project, entry, sv, attach_record(project), verify_record(project), docs_draft(project))
    return {"project": project, "items": items, "next": next_action(project, entry, items, tickets_of(project)), "ready": is_ready(items), "preview": False}


# ---- saying it ------------------------------------------------------------------------------------------------------------------
MARKS_UNICODE = {"done": "✓", "todo": "-", "unknown": "?", "blocked": "!"}
MARKS_ASCII = {"done": "[x]", "todo": "[ ]", "unknown": "[?]", "blocked": "[!]"}


def marks(stream=None):
    mode = os.environ.get("QUARTERDECK_MARKS", "")
    if mode in ("unicode", "ascii"):
        return MARKS_UNICODE if mode == "unicode" else MARKS_ASCII
    s = stream or sys.stdout
    try:
        return MARKS_UNICODE if s.isatty() else MARKS_ASCII
    except (AttributeError, ValueError):
        return MARKS_ASCII


def first_sentence(text, n):
    """As many whole sentences of a detail as fit in n characters; cut at a word with "..." when not even the first does."""
    t = _clip(text, 600)
    if len(t) <= n:
        return t
    parts = re.split(r"(?<=[a-z0-9\)])\. ", t)
    out = ""
    for k, part in enumerate(parts):
        cand = (out + " " if out else "") + part + ("." if k < len(parts) - 1 and not part.endswith(".") else "")
        if len(cand) > n:
            break
        out = cand
    return out or t[:n - 4].rsplit(" ", 1)[0] + " ..."


def item_lines(items, details=False, width=118):
    m = marks()
    out = []
    for i in items:
        text = _plain_dashes(_clip(i["detail"], 400) if details else first_sentence(i["detail"], width - 22))
        out.append(f"  {m[i['state']]} {i['label']:<15} {text}")
        if details:
            if i.get("action"):
                out.append(f"      {_plain_dashes(i['action'])}")
            for r in i.get("on", []):
                out.append(f"      on   {r['duty']}: {_plain_dashes(r['why'])}")
            for r in i.get("suggested", []):
                out.append(f"      off  {r['duty']}: {_plain_dashes(r['why'])}   ({r['command']})")
    return out


def lines(items, nxt, details=False, width=118):
    return item_lines(items, details, width) + ["", f"  next: {_plain_dashes(nxt['text'])}"]


def say(project, details=False):
    v = view(project)
    print(f"  {project}: {'ready for a first ticket' if v['ready'] else 'not ready yet'}")
    print("\n".join(lines(v["items"], v["next"], details)))
    return 0


def record_verify(project, command, rc, seconds, sandbox, first_line=""):
    d = _folder(project)
    d.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(d.parent, 0o700)
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    try:
        import outscan as _os
        first_line = _os.redact(first_line)
    except Exception:
        first_line = "(hidden: the credential scan could not run)"
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "command": command, "exit": int(rc), "seconds": int(seconds), "sandbox": sandbox,
           "first_line": _clip(first_line, 200)}
    _survey._atomic(d / "verify.json", json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


def main(argv):
    a = list(argv)
    try:
        if a[:1] == ["show"] and len(a) >= 2:
            return say(a[1], details="--details" in a[2:])
        if a[:1] == ["json"] and len(a) == 2:
            print(json.dumps(view(a[1])))
            return 0
        if a[:1] == ["record-verify"] and len(a) in (6, 7):
            rec = record_verify(a[1], a[2], a[3], a[4], a[5], a[6] if len(a) == 7 else "")
            print(json.dumps(rec))
            return 0
    except ValueError as e:
        print(f"  {e}")
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
