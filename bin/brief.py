#!/usr/bin/env python3
"""Design-brief plumbing, kept out of the duty that uses it (duties/brief.sh).

Harness code, not model code. The model writes a brief in plain words as one JSON contract; everything here
checks it (required fields, bounded sizes, at most 8 screens, no code and no commands), renders it to a
document in the data folder and keeps the owner's answer: approved, or changes asked for with notes. Nothing
here touches a project folder, GitHub or the network.

  brief.py new-id
  brief.py check   [<project-or-idea-title>]   (the model's reply on stdin)  -> the checked brief JSON, or errors on stderr (exit 1)
  brief.py render  <record.json>               -> the document (markdown)
  brief.py save    <home> <record.json>        -> writes workspace/<slug>-brief-<id>.md and state/briefs/<id>.json; prints the document path
  brief.py stub    <home> <id> <source> <project> <issue|-> <idea-file|-> <audience-file|->      a "drafting" record while the duty works
  brief.py fail    <home> <id> <reason>
  brief.py approve <home> <id>
  brief.py changes <home> <id> <note>
  brief.py revise-context <home> <id>          -> the owner's notes and the earlier brief, as text for the next run
  brief.py list    <home>
"""
import json
import re
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ID_RE = re.compile(r"^b\d{8}-\d{6}-[0-9a-f]{4}\Z")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}\Z")
STATUSES = ("drafting", "proposed", "approved", "changes_requested", "superseded", "failed")
MAX_SCREENS = 8
NOTE_MAX = 1200
IDEA_MAX = 2000
LOCK = threading.Lock()

# name -> (max items, max chars per item); a scalar is (None, max chars)
LIMITS = {
    "title": (None, 80), "one_line": (None, 200), "audience": (None, 300), "content_notes": (None, 800), "accessibility": (None, 800),
    "goals": (6, 200), "not_goals": (6, 200), "assumptions": (8, 200), "open_questions": (6, 200), "success_checks": (8, 200),
}
SCREEN = {"name": 40, "purpose": 240, "content": (8, 120), "actions": (6, 100)}
FLOW = {"name": 60, "steps": (10, 160)}
REQUIRED = ("title", "one_line", "audience", "goals", "key_screens", "flows", "accessibility", "success_checks")

# A brief is words for a person. These are the shapes of code and of instructions to run something.
_CODE = [
    (re.compile(r"```|~~~"), "a code fence"),
    (re.compile(r"`"), "a backtick (code)"),
    (re.compile(r"<\s*/?\s*[A-Za-z!?][^>]*>"), "an HTML tag"),
    (re.compile(r"(?m)^\s*\$\s+\S"), "a shell prompt"),
    (re.compile(r"(?i)\b(rm\s+-[a-z]*r|sudo\s|curl\s+\S|wget\s+\S|chmod\s+[0-7+-]|npm\s+(install|i|run|publish)\b|npx\s|pip3?\s+install|git\s+(push|commit|clone|reset|checkout)\b|bash\s+-c|sh\s+-c|eval\s*\(|exec\s*\(|powershell|osascript)"), "a command to run"),
    (re.compile(r"(?:=>|\bfunction\s*\(|\bdef\s+\w+\(|\bconst\s+\w+\s*=|\bvar\s+\w+\s*=|;\s*\}|\bimport\s+\w+\s+from\b|#!/)"), "code"),
]


class BriefError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).strftime("%FT%TZ")


def new_id():
    return "b" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def id_ok(s):
    return isinstance(s, str) and bool(ID_RE.match(s))


def slug(text, fallback="brief"):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40].strip("-")
    return s or fallback


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=2))
    tmp.replace(path)


# ---- the contract ----------------------------------------------------------------------------------
def _text(v, what, cap, req=True):
    if not isinstance(v, str):
        raise BriefError(f"{what} must be text")
    v = " ".join(v.split())
    if req and not v:
        raise BriefError(f"{what} is empty")
    if len(v) > cap:
        raise BriefError(f"{what} is {len(v)} characters; the limit is {cap}")
    for rx, label in _CODE:
        if rx.search(v):
            raise BriefError(f"{what} contains {label}: a brief is plain words, not code or commands")
    return v


def _list(v, what, n, cap, req=False):
    if v is None:
        v = []
    if not isinstance(v, list):
        raise BriefError(f"{what} must be a list")
    if req and not v:
        raise BriefError(f"{what} needs at least one entry")
    if len(v) > n:
        raise BriefError(f"{what} has {len(v)} entries; the limit is {n}")
    return [_text(x, f"{what}[{i + 1}]", cap) for i, x in enumerate(v)]


def check(raw):
    """The model's brief (a JSON object, or its text) -> the cleaned brief. Raises BriefError with the first thing wrong."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw, strict=False)
        except ValueError as e:
            raise BriefError(f"the brief is not JSON: {e}")
    if not isinstance(raw, dict):
        raise BriefError("the brief must be one JSON object")
    for k in REQUIRED:
        if k not in raw or raw[k] in ("", None, []):
            raise BriefError(f"{k} is missing")
    out = {}
    for k, (n, cap) in LIMITS.items():
        if n is None:
            out[k] = _text(raw.get(k, ""), k, cap, req=k in REQUIRED)
        else:
            out[k] = _list(raw.get(k), k, n, cap, req=k in REQUIRED)
    a = out["accessibility"].lower()
    # the model may say "outlined" or "highlighted" for the focus; the words that matter are the keyboard and a place that stays visible
    if "keyboard" not in a or not any(w in a for w in ("focus", "outline", "highlight", "marked", "visible")):
        raise BriefError("accessibility must say how a person reaches everything by keyboard and that the focus is always visible")
    scr = raw["key_screens"]
    if not isinstance(scr, list) or not scr:
        raise BriefError("key_screens needs at least one screen")
    if len(scr) > MAX_SCREENS:
        raise BriefError(f"key_screens has {len(scr)} screens; the limit is {MAX_SCREENS}")
    out["key_screens"], seen = [], set()
    for i, s in enumerate(scr, 1):
        if not isinstance(s, dict):
            raise BriefError(f"key_screens[{i}] must be an object")
        name = _text(s.get("name", ""), f"key_screens[{i}].name", SCREEN["name"])
        sl = slug(name, "")
        if not SLUG_RE.match(sl) or sl in seen:
            raise BriefError(f"key_screens[{i}].name '{name}' is empty or repeats another screen's name")
        seen.add(sl)
        out["key_screens"].append({
            "name": name,
            "purpose": _text(s.get("purpose", ""), f"key_screens[{i}].purpose", SCREEN["purpose"]),
            "content": _list(s.get("content"), f"key_screens[{i}].content", *SCREEN["content"]),
            "actions": _list(s.get("actions"), f"key_screens[{i}].actions", *SCREEN["actions"])})
    fl = raw["flows"]
    if not isinstance(fl, list) or not fl or len(fl) > 6:
        raise BriefError("flows needs between 1 and 6 flows")
    out["flows"] = []
    for i, f in enumerate(fl, 1):
        if not isinstance(f, dict):
            raise BriefError(f"flows[{i}] must be an object")
        out["flows"].append({"name": _text(f.get("name", ""), f"flows[{i}].name", FLOW["name"]),
                             "steps": _list(f.get("steps"), f"flows[{i}].steps", *FLOW["steps"], req=True)})
    return out


def screen_slugs(b):
    return [slug(s["name"]) for s in b["key_screens"]]


# ---- the document ----------------------------------------------------------------------------------
def render(rec):
    b = rec["brief"]
    who = rec.get("project") or "a new idea"
    o = [f"# {b['title']}", "", b["one_line"], "",
         f"Design brief `{rec['id']}` for {who} · status **{rec['status'].replace('_', ' ')}**. Written by the draughtsman; "
         "it is a proposal until you approve it. Nothing was built and nothing in any project changed.", "",
         "## Who it is for", "", b["audience"], "", "## What it should do", ""]
    o += [f"- {x}" for x in b["goals"]] + [""]
    if b["not_goals"]:
        o += ["## What it will not do", ""] + [f"- {x}" for x in b["not_goals"]] + [""]
    o += ["## The screens", ""]
    for s in b["key_screens"]:
        o += [f"### {s['name']}", "", s["purpose"], ""]
        if s["content"]:
            o += ["What is on it:"] + [f"- {x}" for x in s["content"]] + [""]
        if s["actions"]:
            o += ["What a person can do:"] + [f"- {x}" for x in s["actions"]] + [""]
    o += ["## How a person moves through it", ""]
    for f in b["flows"]:
        o += [f"### {f['name']}", ""] + [f"{i}. {x}" for i, x in enumerate(f["steps"], 1)] + [""]
    if b["content_notes"]:
        o += ["## Words and pictures", "", b["content_notes"], ""]
    o += ["## Reaching everyone", "", b["accessibility"], ""]
    if b["assumptions"]:
        o += ["## What I assumed (tell me if any is wrong)", ""] + [f"- {x}" for x in b["assumptions"]] + [""]
    if b["open_questions"]:
        o += ["## Questions only you can answer", ""] + [f"- {x}" for x in b["open_questions"]] + [""]
    o += ["## How we will know it is right", ""] + [f"- {x}" for x in b["success_checks"]] + [""]
    if rec.get("notes"):
        o += ["## Your notes so far", ""] + [f"- {n['at'][:10]} ({n['action'].replace('_', ' ')}): {n['text']}" for n in rec["notes"] if n.get("text")] + [""]
    return "\n".join(o)


# ---- state -------------------------------------------------------------------------------------------
def _path(home, bid):
    if not id_ok(bid):
        raise BriefError("that is not a brief id")
    return Path(home) / "state" / "briefs" / f"{bid}.json"


def load(home, bid):
    f = _path(home, bid)
    try:
        rec = json.loads(f.read_text())
    except (OSError, ValueError):
        raise BriefError(f"no brief called {bid}")
    if not isinstance(rec, dict) or rec.get("id") != bid:
        raise BriefError(f"no brief called {bid}")
    return rec


def list_all(home):
    d = Path(home) / "state" / "briefs"
    out = []
    for f in sorted(d.glob("b*.json")) if d.is_dir() else []:
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and id_ok(r.get("id")):
            out.append(r)
    return out


def stub(home, bid, source, project="", issue=None, idea="", audience="", revises=""):
    rec = {"id": bid, "kind": "brief", "status": "drafting", "created": now(), "updated": now(), "source": source,
           "project": project or "", "issue": issue, "idea": " ".join(str(idea or "").split())[:IDEA_MAX],
           "audience_hint": " ".join(str(audience or "").split())[:300], "revises": revises or "", "brief": None,
           "notes": [], "doc": "", "mockups": {"state": "none"}}
    with LOCK:
        _write(_path(home, bid), rec)
    return rec


def fail(home, bid, reason):
    with LOCK:
        try:
            rec = load(home, bid)
        except BriefError:
            return
        if rec["status"] == "drafting":
            rec["status"], rec["error"], rec["updated"] = "failed", str(reason)[:300], now()
            _write(_path(home, bid), rec)


def save(home, rec):
    """Write the document and the record; a brief that revises another supersedes it."""
    b = rec["brief"]
    with LOCK:
        rec["status"], rec["updated"] = "proposed", now()
        rec.pop("error", None)
        doc = Path(home) / "workspace" / f"{slug(rec.get('project') or b['title'])}-brief-{rec['id']}.md"
        rec["doc"] = doc.name
        _write(doc, render(rec))
        _write(_path(home, rec["id"]), rec)
        old = rec.get("revises")
        if old and id_ok(old):
            try:
                o = load(home, old)
                if o["status"] in ("changes_requested", "proposed", "approved"):
                    o["status"], o["superseded_by"], o["updated"] = "superseded", rec["id"], now()
                    _write(_path(home, old), o)
            except BriefError:
                pass
    return doc


def _note(rec, action, text):
    text = " ".join(str(text or "").split())[:NOTE_MAX]
    rec.setdefault("notes", []).append({"at": now(), "action": action, "text": text})


def act(home, bid, action, note=""):
    """The owner's answer. approve: proposed -> approved. changes: proposed or approved -> changes_requested, with notes."""
    with LOCK:
        rec = load(home, bid)
        st = rec["status"]
        if action == "approve":
            if st != "proposed":
                raise BriefError(f"{bid} is {st.replace('_', ' ')}; only a proposed brief can be approved")
            rec["status"] = "approved"
            _note(rec, "approved", note)
        elif action == "changes":
            if st not in ("proposed", "approved"):
                raise BriefError(f"{bid} is {st.replace('_', ' ')}; changes can be asked for on a proposed or approved brief")
            if not " ".join(str(note or "").split()):
                raise BriefError("say what should change")
            rec["status"] = "changes_requested"
            _note(rec, "changes_requested", note)
        else:
            raise BriefError("unknown action")
        rec["updated"] = now()
        _write(_path(home, bid), rec)
        if rec.get("doc"):
            try:
                _write(Path(home) / "workspace" / rec["doc"], render(rec))
            except OSError:
                pass
        return rec


def revise_context(home, bid):
    rec = load(home, bid)
    if rec["status"] != "changes_requested":
        raise BriefError(f"{bid} is {rec['status'].replace('_', ' ')}: only a brief the owner asked changes on can be revised")
    notes = "\n".join(f"- {n['text']}" for n in rec.get("notes", []) if n["action"] == "changes_requested" and n.get("text"))
    return {"notes": notes, "brief": rec["brief"], "project": rec.get("project", ""), "issue": rec.get("issue"),
            "idea": rec.get("idea", ""), "audience": rec.get("audience_hint", ""), "source": rec.get("source", "idea")}


# ---- command line --------------------------------------------------------------------------------------
def main(a):
    c = a[0] if a else ""
    try:
        if c == "new-id":
            print(new_id())
        elif c == "check":
            print(json.dumps(check(sys.stdin.read())))
        elif c == "render":
            print(render(json.load(open(a[1]))), end="")
        elif c == "save":
            print(save(a[1], json.load(open(a[2]))))
        elif c == "stub":
            read = lambda p: "" if p == "-" else Path(p).read_text()
            stub(a[1], a[2], a[3], "" if a[4] == "-" else a[4], None if a[5] == "-" else int(a[5]), read(a[6]), read(a[7]),
                 a[8] if len(a) > 8 else "")
        elif c == "fail":
            fail(a[1], a[2], a[3])
        elif c in ("approve", "changes"):
            rec = act(a[1], a[2], c, a[3] if len(a) > 3 else "")
            print(f"{rec['id']} is now {rec['status'].replace('_', ' ')}.")
        elif c == "revise-context":
            r = revise_context(a[1], a[2])
            print(json.dumps(r))
        elif c == "list":
            if not list_all(a[1]):
                print("no briefs yet")
            for r in list_all(a[1]):
                t = (r.get("brief") or {}).get("title", r.get("idea", "")[:50])
                print(f"{r['id']}  {r['status']:18}  {r.get('project') or '(new idea)':20}  {t}")
        else:
            sys.exit(__doc__)
    except BriefError as e:
        sys.exit(f"brief: {e}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except OSError as e:
        from integrations import common as _common
        sys.exit("brief: " + _common.why_not_saved(e))
