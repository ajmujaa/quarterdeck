#!/usr/bin/env python3
"""The checks worth having: the two places where a quiet bug would be expensive.

Scheduling decides when something runs unattended, and validation is the only
thing standing between a loopback POST and a subprocess. Both are pure
functions, so they are cheap to check and there is no excuse for not doing it.

Run directly, or through `quarterdeck doctor`.
"""
import importlib.util
import pathlib
import shutil
import time
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import os as _os0, tempfile as _tf0
sys.path.insert(0, str(ROOT / "bin")); import home as _h0
_REAL_HOME = _h0.resolve()          # where the maintainer's own private denylist lives (read only), before the tests switch to a temporary data folder
# The tests never read anyone's real data: they build their own data folder from the shipped example registry, so they also pass on a fresh clone.
_TEST_HOME = Path(_tf0.mkdtemp(prefix="qd-selftest-"))
for _d0 in ("config", "state", "logs", "workspace"):
    (_TEST_HOME / _d0).mkdir()
shutil.copy(ROOT / "config" / "projects.example.json", _TEST_HOME / "config" / "projects.json")
_os0.environ["QUARTERDECK_HOME"] = str(_TEST_HOME)
spec = importlib.util.spec_from_file_location("dash", ROOT / "bin" / "dashboard.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

FAILS = []


def check(label, ok, detail=""):
    if ok:
        print(f"  ok    {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL  {label}{': ' + str(detail) if detail else ''}")


def refused(*args):
    """True when validate_run turns this away."""
    try:
        d.validate_run(*args)
        return False
    except ValueError:
        return True


now = d.now_utc()
ago = lambda **kw: d.iso(now - timedelta(**kw))

# ---- when things fire --------------------------------------------------------
check("an overdue interval is due now",
      d.next_due({"every": "30m", "last_run": ago(minutes=31)}) < now)
check("an interval that has not elapsed is not due",
      d.next_due({"every": "30m", "last_run": ago(minutes=29)}) > now)
check("a schedule that has never run waits a full interval",
      d.next_due({"every": "4h", "last_run": None}) > now + timedelta(hours=3))
check("a paused schedule never fires",
      d.next_due({"every": "30m", "paused": True}) is None)
check("a malformed interval never fires",
      d.next_due({"every": "sometime"}) is None)
# A daily schedule is where this went wrong once: next_due returned the NEXT
# occurrence, which is always in the future, so the scheduler — which fires on
# "due <= now" — never fired one. These pin the behaviour, not the arithmetic.
# Today at noon, not a fixed date: pinning an arbitrary date to the CURRENT
# UTC offset puts the test an hour out whenever the two fall on opposite sides
# of a daylight-saving change, which is a failing test that means nothing.
noon = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
at = lambda sched: d.next_due(sched, now=noon)

check("a daily time that passed today and has not run is due now",
      at({"at": "02:00", "created": d.iso(noon - timedelta(days=1))}) <= noon)
check("a daily time that already ran today is not due again today",
      at({"at": "02:00", "last_run": d.iso(noon.replace(hour=2, minute=1))}) > noon)
check("a daily time still ahead today waits for it",
      noon < at({"at": "23:00", "last_run": d.iso(noon - timedelta(hours=13))})
      <= noon + timedelta(days=1))
check("a daily run missed while the machine was off fires once on return",
      at({"at": "23:00", "last_run": d.iso(noon - timedelta(days=1, hours=4))}) <= noon)
check("a malformed daily time never fires",
      d.next_due({"at": "25:00"}) is None)

# ---- what may be run ---------------------------------------------------------
projects = d.read_json(d.PROJECTS_FILE, {})
built = {x["name"] for x in d.duty_list()}
pair = next(((p, x) for p, v in sorted(projects.items())
             for x in v.get("duties", []) if x in built), None)

if not pair:
    check("a project with a built duty exists to test against", False,
          "nothing registered — validation left unchecked")
else:
    project, duty = pair
    try:
        d.validate_run(project, duty, [])
        check("a registered project and enabled duty is accepted", True)
    except ValueError as e:
        check("a registered project and enabled duty is accepted", False, e)

    check("a shell metacharacter in a value is refused",
          refused(project, duty, ["--path", "; rm -rf /"]))
    check("a path traversal is refused",
          refused(project, duty, ["--from", "../../etc/passwd"]))
    check("an absolute path is refused",
          refused(project, duty, ["--from", "/etc/passwd"]))
    check("a newline in a value is refused",
          refused(project, duty, ["--path", "a\nb"]))
    check("a flag that is not a flag is refused",
          refused(project, duty, ["--rm -rf", "x"]))
    check("an unknown duty is refused", refused(project, "nope", []))
    check("an unregistered project is refused", refused("no-such-project", duty, []))
    check("too many arguments are refused", refused(project, duty, ["--a"] * 13))

    off = sorted(built - set(projects[project].get("duties", [])))
    if off:
        check("a duty not enabled for the project is refused",
              refused(project, off[0], []))

# ---- which panel is current ---------------------------------------------------
def pan(i, started, status="done", subject="components/", disc="design", project="my-web-app"):
    return {"id": i, "project": project, "discipline": disc, "subject": subject,
            "status": status, "started": started}

m = {p["id"]: p["superseded_by"] for p in d.mark_superseded([
    pan("old", "2026-09-21"), pan("new", "2026-09-23"),
    pan("crashed", "2026-09-22T10", "failed", "what next", "backlog"),
    pan("retried", "2026-09-22T11", "done", "what next", "backlog"),
    pan("latest-failed", "2026-09-24", "failed"),
    pan("other-target", "2026-09-20", subject="components/Modal.tsx"),
    pan("other-project", "2026-09-20", project="side-app"),
    pan("live", "2026-09-19", "running"),
])}
check("a newer run on the same target supersedes the older", m["old"] == "new")
check("the newest completed run is current", m["new"] is None)
check("a failed run is superseded once a retry succeeds", m["crashed"] == "retried")
check("a failure newer than the last success stays visible", m["latest-failed"] is None)
check("a different target is a different list", m["other-target"] is None)
check("a different project is a different list", m["other-project"] is None)
check("a running panel is never superseded", m["live"] is None)

# ---- one duty, several live locks -----------------------------------------------
# Several duties now lock per target (an issue, a PR), not per project, so the
# dashboard's agents list can no longer assume at most one running instance.
_dl_locks = {"shipwright-my-web-app-247": {"pid": 1}, "shipwright-my-web-app-300": {"pid": 2},
             "panel-my-web-app-9": {"pid": 3}, "surveyor-my-web-app-sweep": {"pid": 4}}
check("both live instances of the same duty are found",
      set(d.duty_locks("shipwright", "my-web-app", _dl_locks)) == {"shipwright-my-web-app-247", "shipwright-my-web-app-300"})
check("a different duty's lock on the same project is not matched",
      d.duty_locks("panel", "my-web-app", _dl_locks) == {"panel-my-web-app-9": {"pid": 3}})
check("no live lock at all is an empty result, not a guess",
      d.duty_locks("inspector", "my-web-app", _dl_locks) == {})
check("a bare project-wide lock (a duty not rekeyed) still matches by itself",
      d.duty_locks("joiner", "my-web-app", {"joiner-my-web-app": {"pid": 5}}) == {"joiner-my-web-app": {"pid": 5}})

_ml = {"shipwright-my-mobile-app-13": {"pid": 7}, "shipwright-my-web-app-4": {"pid": 8}}
check("my-mobile-app's lock is not my-web-app's, and my-web-app's own still is",
      d.duty_locks("shipwright", "my-web-app", _ml, ["my-web-app", "my-mobile-app"]) == {"shipwright-my-web-app-4": {"pid": 8}}
      and set(d.duty_locks("shipwright", "my-mobile-app", _ml, ["my-web-app", "my-mobile-app"])) == {"shipwright-my-mobile-app-13"})
_pg = d.summarize_progress([{"number": 1, "title": "a", "state": "CLOSED"}, {"number": 2, "title": "b", "state": "OPEN"},
                            {"number": 3, "title": "c", "state": "OPEN"}],
                           [{"state": "OPEN", "closingIssuesReferences": [{"number": 2}]},
                            {"state": "MERGED", "closingIssuesReferences": [{"number": 3}]}])
check("progress counts closed, open, and open issues that have an open PR",
      (_pg["total"], _pg["closed"], _pg["open"], _pg["in_review"]) == (3, 1, 2, 1))

import tempfile as _tf
_cd = Path(_tf.mkdtemp()); _cap = d.CAPTURE; d.CAPTURE = _cd / "capture.jsonl"
_n1 = d.capture_add("  call the   dentist \n"); _n2 = d.capture_add("x" * 5000)
d.capture_done(_n1["id"])
_v = d.captures_view()
_bad = []
for _f in (lambda: d.capture_add("   "), lambda: d.capture_done("zzzzzzzz"), lambda: d.capture_done("deadbeef")):
    try: _f(); _bad.append("accepted")
    except ValueError: pass
d.CAPTURE = _cap
check("the notes file is created readable by its owner only",
      oct((_cd / "capture.jsonl").stat().st_mode & 0o777) == "0o600")
check("a note is cleaned, capped, and gone once marked done; bad input is refused",
      _n1["text"] == "call the dentist" and len(_n2["text"]) == 1000
      and [r["id"] for r in _v["items"]] == [_n2["id"]] and _v["open"] == 1 and not _bad)

# ---- notes: edit, reopen, tag, promote (append-only, latest line wins) ----
import json as _json
_nd = Path(_tf.mkdtemp()); _sv = (d.CAPTURE, d.PROJECTS_FILE, d.MISSIONS_FILE, d.spawn_run)
d.CAPTURE = _nd / "capture.jsonl"; d.PROJECTS_FILE = _nd / "p.json"; d.MISSIONS_FILE = _nd / "missions.json"
d.PROJECTS_FILE.write_text(_json.dumps({"my-web-app": {"duties": ["panel"]}, "my-blog": {"duties": ["joiner"]}}))
_runs = []
d.spawn_run = lambda *a, **k: (_runs.append((a, k)), "started")[1]
_a = d.capture_add("call the dentist"); _b = d.capture_add("plan the offline mode", "my-web-app"); _c = d.capture_add("third note")
_size0 = d.CAPTURE.read_text()
_e = d.capture_edit(_a["id"], text="  call the   dentist on Monday ")
_t = d.capture_edit(_c["id"], project="my-blog"); _t2 = d.capture_edit(_c["id"], project="")
d.capture_done(_a["id"]); _done_a = next(n for n in d.captures_view()["done"] if n["id"] == _a["id"]); d.capture_reopen(_a["id"])
_raw = d.CAPTURE.read_text()
def _refused(f):
    try: f(); return False
    except ValueError: return True
_after = {n["id"]: n for n in d.capture_notes()}
check("notes: an edit appends a line with the same id and the latest text wins; the file only ever grows",
      _e["text"] == "call the dentist on Monday" and _after[_a["id"]]["text"] == "call the dentist on Monday" and _raw.startswith(_size0) and _raw.count("\n") == _size0.count("\n") + 5
      and len([n for n in d.capture_notes() if n["id"] == _a["id"]]) == 1 and _after[_a["id"]]["at"] == _a["at"])
check("notes: done and reopen both stick, and the tag can be set and cleared; a project must be registered",
      _done_a["done"] is True and _after[_a["id"]]["done"] is False and _t["project"] == "my-blog" and _t2["project"] == "" and _after[_b["id"]]["project"] == "my-web-app"
      and _refused(lambda: d.capture_edit(_a["id"], project="invented")) and _refused(lambda: d.capture_add("x", "invented")))
check("notes: bad input is refused (id rules, empty text, nothing to change, reopening a note that is open, unknown note)",
      all(_refused(f) for f in (lambda: d.capture_edit("zzzzzzzz", text="x"), lambda: d.capture_edit("deadbeef", text="x"), lambda: d.capture_edit("../../etc", text="x"),
                                lambda: d.capture_edit(_a["id"], text="   "), lambda: d.capture_edit(_a["id"]), lambda: d.capture_reopen(_a["id"]),
                                lambda: d.capture_reopen("deadbeef"), lambda: d.capture_edit(None, text="x")))
      and len(d.capture_edit(_a["id"], text="y" * 5000)["text"]) == 1000)
_m = d.capture_promote(_b["id"], "mission", "my-web-app")
_ms = d.load_missions()
check("notes: promoting to a mission makes a draft through the mission path and remembers it on the note",
      _m["kind"] == "mission" and len(_ms) == 1 and _ms[0]["objective"] == "plan the offline mode" and _ms[0]["status"] == "draft" and _ms[0]["project"] == "my-web-app"
      and next(n for n in d.capture_notes() if n["id"] == _b["id"])["promoted"]["ref"] == _ms[0]["id"] and not _runs)
check("notes: promoting to a plan needs a confirm, a registered project with the panel duty, and passes the idea as plain words",
      _refused(lambda: d.capture_promote(_b["id"], "plan", "my-web-app")) and _refused(lambda: d.capture_promote(_b["id"], "plan", "my-web-app", "yes")) and not _runs
      and _refused(lambda: d.capture_promote(_b["id"], "plan", "")) and _refused(lambda: d.capture_promote(_b["id"], "plan", "invented", True))
      and _refused(lambda: d.capture_promote(_b["id"], "merge", "my-web-app", True))
      and d.capture_promote(_b["id"], "plan", "my-web-app", True)["kind"] == "plan"
      and _runs[0][0][:3] == ("my-web-app", "panel", ["--panel", "spec", "--idea", "plan the offline mode"]) and _runs[0][0][3] is False)
_w = d.capture_add("--apply  ../../x; rm -rf / `id` $(id)")
d.capture_promote(_w["id"], "plan", "my-web-app", True)
_idea = _runs[-1][0][2][3]
check("notes: a note cannot smuggle a flag, a path or shell characters into the panel run",
      d.idea_text("--apply the thing") == "apply the thing" and ".." not in _idea and _idea and not _idea.startswith(("-", "/"))
      and not any(ch in _idea for ch in "`$;()") and d.idea_text("---") == "" and d.idea_text(None) == "")
with open(d.CAPTURE, "a") as _f: _f.write("not json\n[1]\n{\"id\": 5}\n{\"id\": \"deadbeef\", \"done\": true}\n{\"id\": \"%s\", \"text\": 7}\n" % _a["id"])
_tol = d.captures_view()
check("notes: bad lines, lines of the wrong shape and lines for a note that never existed are ignored",
      _tol["total"] == 4 and all(n["id"] != "deadbeef" for n in _tol["items"] + _tol["done"]) and _tol["path"].endswith("capture.jsonl"))
with open(d.CAPTURE, "a") as _f: _f.write(_json.dumps({"id": "');alert(1);//", "at": "2026-01-01T00:00:00Z", "text": "tampered"}) + "\\n")
check("notes: a line whose id is not one this program wrote (a hand-edited file) never becomes a note",
      all(n["id"].isalnum() for n in d.captures_view()["items"] + d.captures_view()["done"]) and "tampered" not in _json.dumps(d.captures_view()))
check("notes: the file stays owner-only and the view carries every note once, newest first",
      oct(d.CAPTURE.stat().st_mode & 0o777) == "0o600" and [n["id"] for n in _tol["items"]][0] == _w["id"] and _tol["open"] == len(_tol["items"]))
d.CAPTURE, d.PROJECTS_FILE, d.MISSIONS_FILE, d.spawn_run = _sv

import shutil as _sh, subprocess as _sp
import nodeok as _nodeok
if _nodeok.path():
    _r = _sp.run(["node", "--no-warnings", str(ROOT / "bin" / "selftest-assistant.mjs")], capture_output=True, text=True)
    for _ln in _r.stdout.splitlines():
        if _ln.strip().startswith("ok"):
            check(_ln.strip()[2:].strip(), True)
    check("the assistant logic (next up, digest, voice commands) passes under node", _r.returncode == 0, (_r.stderr or "")[-400:])
else:
    print("  skip  assistant logic: node is not installed")

_idx_html = (ROOT / "dashboard" / "index.html").read_text(); _ui = (ROOT / "dashboard" / "assets" / "ui.css").read_text(); _ll = (ROOT / "dashboard" / "assets" / "ledgerlog.js").read_text()
check("the Log view opened from a Ledger row has Back to Ledger, a breadcrumb, Esc, and links timestamps to rows (no em dashes)",
      all(w in _idx_html for w in ("backToLedger()", "Back to Ledger", "openFullLog(", "crumbText(", 'e.key === "Escape" && view === "log" && logFrom', "runForLine(line, S.runs", "data-lkey"))
      and "—" not in _ll and "document." not in _ll and "fetch(" not in _ll)
_bl = (ROOT / "dashboard" / "assets" / "brainlists.js").read_text(); _bj = (ROOT / "dashboard" / "assets" / "brain.js").read_text()
check("the Brain's counts are buttons (stats, area labels, legend), disabled at 0, with a list in the side panel and Mark all seen; no camera move, no em dashes",
      all(w in _bj for w in ('el("button", "st"', "s.disabled = !c[k]", 'el("button", "brain-count"', "c.disabled = !count", "openList(", "export function showList", "Back to the list"))
      and 'import("/assets/brainlists.js")' in _idx_html and "Mark all seen" in _idx_html and "quarterdeck.brainSeen" in _idx_html and "onList: openBrainList" in _idx_html
      and "stopRun(ref.agent" in _idx_html
      and "controls.target" not in _bj[_bj.index("function openList"):_bj.index("function showPanel")]
      and "—" not in _bl and "document." not in _bl and "fetch(" not in _bl)
_nj = (ROOT / "dashboard" / "assets" / "notes.js").read_text()
check("the Notes view is in the rail, the Home card links to it, edits and promotions go through /api/capture, and Helm answers the three note phrases",
      all(w in _idx_html for w in ('id:"notes", label:"Notes"', "notes:viewNotes", "go('notes')", 'action: "edit"', 'action: "promote"', "confirm: kind === \"plan\"", 'case "notedone"', 'case "promote"', 'case "notes"', "on this Mac. The file is only ever added to"))
      and "—" not in _nj and "document." not in _nj and "fetch(" not in _nj)
_tlj = (ROOT / "dashboard" / "assets" / "timeline.js").read_text()
check("the Timeline view is in the rail with windows, lanes, legend, filters remembered per browser, hover/focus detail and click to the Ledger; the Home strip shows 12 events",
      all(w in _idx_html for w in ('id:"timeline", label:"Timeline"', "timeline:viewTimeline", "quarterdeck.timeline", "tlHover(this)", "onfocus=\"tlHover(this)\"", "openEvent(", "recentStrip(", "/api/timeline?window=", "tl-legend"))
      and "—" not in _tlj and "document." not in _tlj and "fetch(" not in _tlj and "animation" not in _ui[_ui.index(".tl-strip{"):_ui.index(".c-bad{")])
_sj = (ROOT / "dashboard" / "assets" / "suggest.js").read_text()
check("the suggestion bar is quiet and kept in this browser: Snooze, Dismiss, What changed, speaking off by default and never while Helm is busy; the module has no DOM, network or em dashes",
      all(w in _idx_html for w in ('id="suggest"', "sgDo(kind)", "Snooze 1 hour", "openWhatChanged", "quarterdeck.suggest", "quarterdeck.sgSpeak", 'id="sg-say"', "helmState !== \"idle\" || micMode === \"push\" || busy", "shouldSpeak("))
      and 'id="sg-say" data-onchange="sgSpeakToggle(el.checked)">' in _idx_html and 'id="sg-say" checked' not in _idx_html
      and "—" not in _sj and "document." not in _sj and "fetch(" not in _sj and "window." not in _sj and "setTimeout" not in _sj and "localStorage" not in _sj
      and not any(w in _ui[_ui.index("#helm .suggest{flex:none"):_ui.index("#helm-caption{")] for w in ("animation", "transition", "gradient", "box-shadow")))
_cvj = (ROOT / "dashboard" / "assets" / "convo.js").read_text()
check("the page routes a command first and conversation otherwise, keeps its own memory, and sends it with the request; convo.js has no DOM, network or em dashes",
      all(w in _idx_html for w in ('import("/assets/convo.js")', "cv.route(c, t) === \"conversation\"", "memPush(\"user\", text, src)", "case \"deep\": return setDeep(c)", "opts.noChat", "mem = cv.expire(mem, Date.now())"))
      and "—" not in _cvj and "document." not in _cvj and "fetch(" not in _cvj and "localStorage" not in _cvj and "Date.now()" in _cvj)
_conv = _idx_html[_idx_html.index("async function converse("):_idx_html.index("function setDeep(c)")]
check("the page streams a reply into the log as text only (never HTML), speaks each sentence as it arrives, acknowledges a slow answer once, and runs an ACTION line through the normal pipeline with no chat of its own",
      all(w in _conv for w in ("/api/chat", "getReader()", "talkOpen(", "speakSentence(ev.s, gen)", "slowAckMs()", 'doCommand(action, {noChat: true, spoken})', "AbortError", "One moment."))
      and "innerHTML" not in _conv and "eval(" not in _conv and "Function(" not in _conv and "post(" not in _conv
      and "const slowAckMs = () => trn ? trn.T.SLOW_ACK_MS : 2000" in _idx_html and "t.textContent = l.text" in _idx_html and "memSkip" in _idx_html)
_ce = (ROOT / "bin" / "chat-eval.py").read_text()
compile(_ce, "chat-eval.py", "exec")
import re as _re0
_ns = {"re": _re0}; exec(_ce[_ce.index("IDK = ["):_ce.index("def post")], _ns)
_cv = _ns["CONVERSATIONS"]
check("bin/chat-eval.py is valid Python with 28 scripted conversations (the owner's, then the faults seen; an add-on's sit in their own file) of 3 to 5 turns, including 'I do not know' cases, 'the other one' follow-ups and no-invented-numbers checks",
      len(_cv) == 28 and all(3 <= len(c) <= 5 for c in _cv) and all(len(t) == 3 and isinstance(t[0], str) and isinstance(t[1], list) and isinstance(t[2], list) for c in _cv for t in c)
      and any("do not know" in t[1] for c in _cv for t in c) and any("the other one" in t[0] for c in _cv for t in c) and any("$" in t[1] for c in _cv for t in c)
      and any("I merged" in t[2] or "I started" in t[2] for c in _cv for t in c) and "/api/chat" in _ce and '"brain": "local"' in _ce and '"brain": "claude"' not in _ce)
check("the page shows the Think with Claude switch only when the setting is on and never in demo, a flat Claude badge with the session cost while it is on, and sends the brain choice and what the owner agreed to include",
      all(w in _idx_html for w in ('id="think-wrap" hidden', "wrap.hidden = !claudeOn()", '!(S.demo && S.demo.on)', 'id="helm-claude" hidden', 'brain: mem && mem.deep ? "claude" : "local"', "claudeCost += ev.cost", 'ev.fallback === "cap"', "thinkToggle("))
      and "animation" not in _ui[_ui.index(".helm-claude{"):_ui.index(".hd-switches{")] and "gradient" not in _ui[_ui.index(".helm-claude{"):_ui.index(".hd-switches{")])
_tj = (ROOT / "dashboard" / "assets" / "turns.js").read_text(); _hj = (ROOT / "dashboard" / "assets" / "helm.js").read_text()
check("turn-taking lives in turns.js (pure) and helm.js only moves audio: no hard-coded pause length left, the page cancels speech when the owner starts, does not pause the mic while Helm speaks, and has an interrupt switch",
      'from "./turns.js"' in _hj and "createSegmenter(" in _hj and "endMs = 900" not in _hj and "threshold = 0.02" not in _hj
      and all(w in _idx_html for w in ("function micOnset(o){ if(o && o.stopSpeaking){ speakCancel();", "timing: micTiming", "onPeek: micPeek", "pendingSeg", "bargeInToggle", 'id="bargein"', "trn.needsWake(", "speakEndedAt"))
      and "mic.setPaused(true)" not in _idx_html[_idx_html.index("async function onSegment("):_idx_html.index("// Speech is a queue of sentences")]
      and "—" not in _tj and "document." not in _tj and "fetch(" not in _tj and "Date.now" not in _tj and "localStorage" not in _tj)
check("a model's ACTION phrase is only run through doCommand with noChat and asst.actionAccepted, so it can never save a note, switch the deep brain on or start a chat of its own",
      "if(opts.noChat && !asst.actionAccepted(c)) return null;" in _idx_html and "doCommand(action, {noChat: true, spoken})" in _idx_html and "export function actionAccepted" in (ROOT / "dashboard" / "assets" / "assistant.js").read_text())
_feeds_js = (ROOT / "dashboard" / "assets" / "feeds.js").read_text()
check("the Brain loads the feed panels, and their code has no em dashes, DOM or network",
      'import("/assets/feeds.js")' in (ROOT / "dashboard" / "index.html").read_text() and "feedPanel(c, Date.now())" in (ROOT / "dashboard" / "index.html").read_text()
      and "—" not in _feeds_js and not any(w in _feeds_js for w in ("document.", "fetch(", "XMLHttpRequest")))

import importlib.util as _ilu, http.server as _hs, threading as _th, os
_sp_ = _ilu.spec_from_file_location("quarterdeck_check", ROOT / "bin" / "check.py"); _ck = _ilu.module_from_spec(_sp_); _sp_.loader.exec_module(_ck)
_hbody = [b""]
class _H(_hs.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(_hbody[0])
    def log_message(self, *a): pass
_hsrv = _hs.HTTPServer(("127.0.0.1", 0), _H); _th.Thread(target=_hsrv.serve_forever, daemon=True).start()
os.environ["QUARTERDECK_DASHBOARD_PORT"] = str(_hsrv.server_port)
_hbody[0] = b'{"ok": true, "uptime_seconds": 5, "commit": "abc"}'; _h_ok = _ck.health()
_hbody[0] = b'{"ok": false, "loops": {"scheduler": {"alive": false}, "agenda": {"alive": true}}}'; _h_bad = _ck.health()
_hbody[0] = b'[1]'; _h_odd = _ck.health()
_hsrv.shutdown(); _hsrv.server_close(); _h_down = _ck.health()
os.environ["QUARTERDECK_DASHBOARD_PORT"] = "x; rm"; _h_inj = _ck.health()
os.environ.pop("QUARTERDECK_DASHBOARD_PORT")
_s_ok = _ck.step("t", [sys.executable, "-c", "print('  ok    a'); print('  ok    b')"])
_s_bad = _ck.step("t", [sys.executable, "-c", "print('  ok    a'); print('  FAIL  the thing broke: why'); raise SystemExit(1)"])
_s_crash = _ck.step("t", [sys.executable, "-c", "raise SystemExit('boom')"])
_s_okfail = _ck.step("t", [sys.executable, "-c", "print('  ok    a failed run is superseded'); print('  FAIL  the real one: why'); raise SystemExit(1)"])
check("quarterdeck check: a healthy dashboard is green, a quiet loop is red and named, a stopped dashboard is reported not crashed",
      _h_ok[0] is True and _h_bad[0] is False and "scheduler" in _h_bad[2] and "agenda" not in _h_bad[2] and _h_odd[0] is False
      and _h_down[0] is None and "not running" in _h_down[1] and _h_inj[0] is None, (_h_ok, _h_bad, _h_down, _h_inj))
check("quarterdeck check: a step is green only on exit 0, and the first failing line is shown",
      _s_ok == (True, "2 ok", "") and _s_bad[0] is False and _s_bad[2] == "FAIL  the thing broke: why" and _s_crash[0] is False and _s_crash[2] == "boom" and _s_okfail[2] == "FAIL  the real one: why", (_s_ok, _s_bad, _s_crash, _s_okfail))
check("quarterdeck check is wired into the command line, its help and the README",
      'exec python3 "$QUARTERDECK_DIR/bin/check.py"' in (ROOT / "bin" / "quarterdeck").read_text() and "check  " in (ROOT / "bin" / "quarterdeck").read_text()
      and "quarterdeck check" in (ROOT / "README.md").read_text())
import wave as _wave
if _sh.which("whisper-cli") and d.WHISPER_MODEL.is_file():
    _w = Path(_tf.mkdtemp()) / "s.wav"
    with _wave.open(str(_w), "wb") as _f:
        _f.setnchannels(1); _f.setsampwidth(2); _f.setframerate(16000); _f.writeframes(b"\0\0" * 16000)
    _junk = []
    try: d.transcribe(b"x" * 100)
    except ValueError: _junk.append("refused")
    check("local speech: silence gives no words, and a non-WAV body is refused",
          d.transcribe(_w.read_bytes(), ["my-web-app"]) == "" and _junk == ["refused"])
else:
    print("  skip  local speech: whisper-cli or its model is not installed")

_views, _projs = {"go-a", "ledger", "prs"}, {"my-web-app", "my-mobile-app", "my-blog"}
_v = lambda cmd, text: d.vet_intent(cmd, text, _views, _projs)
check("a model guess is checked against the page and the registry before it is used",
      _v({"intent": "go", "view": "ledger", "project": "hammer"}, "x") == {"intent": "go", "view": "ledger"}
      and _v({"intent": "go", "view": "nope"}, "x")["intent"] == "clarify"
      and _v({"intent": "project", "project": "invented"}, "x")["intent"] == "clarify"
      and _v({"intent": "project", "project": "my-blog"}, "x") == {"intent": "project", "project": "my-blog"})
check("starting work needs the issue number to have been said; a note needs a cue word",
      _v({"intent": "work", "action": "start", "issue": 1, "project": "my-blog"}, "what is the status of my-blog")["intent"] == "clarify"
      and _v({"intent": "work", "action": "start", "issue": 13, "project": "my-mobile-app"}, "start work on issue thirteen")["intent"] == "work"
      and _v({"intent": "work", "action": "start", "issue": 21, "project": "my-web-app"}, "start twenty-one")["intent"] == "work"
      and _v({"intent": "capture", "text": "buy milk"}, "we need to buy milk")["intent"] == "none"
      and _v({"intent": "capture", "text": "buy milk"}, "remind me to buy milk")["intent"] == "capture"
      and _v({"intent": "capture", "text": "wire the money"}, "remind me to buy milk") == {"intent": "capture", "text": "buy milk"}
      and _v("junk", "x")["intent"] == "none")
_dof = {"my-web-app": ["surveyor", "panel", "shipwright"], "my-blog": ["joiner"]}
_vd = lambda cmd, text: d.vet_intent(cmd, text, _views, _projs, _dof)
check("helm run: only a duty Helm may start, enabled for that project, and apply only on the owner's own word",
      _vd({"intent": "run", "duty": "surveyor", "project": "my-web-app"}, "run the surveyor on my-web-app") == {"intent": "run", "duty": "surveyor", "project": "my-web-app"}
      and _vd({"intent": "run", "duty": "shipwright", "project": "my-web-app"}, "run the shipwright on my-web-app")["intent"] == "clarify"
      and _vd({"intent": "run", "duty": "rm -rf", "project": "my-web-app"}, "x")["intent"] == "clarify"
      and _vd({"intent": "run", "duty": "surveyor", "project": "my-blog"}, "run the surveyor on my-blog")["intent"] == "clarify"
      and "apply" not in _vd({"intent": "run", "duty": "surveyor", "project": "my-web-app", "apply": True}, "run the surveyor on my-web-app")
      and _vd({"intent": "run", "duty": "surveyor", "project": "my-web-app", "apply": True, "pr": 12}, "review pull request twelve on my-web-app and apply it")
      == {"intent": "run", "duty": "surveyor", "project": "my-web-app", "pr": 12, "apply": True}
      and "pr" not in _vd({"intent": "run", "duty": "surveyor", "project": "my-web-app", "pr": 99}, "run the surveyor on my-web-app"))
check("helm stop and acknowledge: the duty must exist and be enabled; a signal is named by words only",
      _vd({"intent": "halt", "duty": "shipwright", "project": "my-web-app"}, "x") == {"intent": "halt", "duty": "shipwright", "project": "my-web-app"}
      and _vd({"intent": "halt", "duty": "gadgeteer"}, "x")["intent"] == "clarify"
      and _vd({"intent": "halt", "duty": "../x"}, "x")["intent"] == "clarify"
      and _vd({"intent": "ack", "query": "surveyor log"}, "x") == {"intent": "ack", "query": "surveyor log"})
check("helm plan: the objective is only words that were said, the panel only if the word panel was said",
      _vd({"intent": "plan", "objective": "offline mode", "project": "my-web-app"}, "plan offline mode for my-web-app") == {"intent": "plan", "objective": "offline mode", "project": "my-web-app", "panel": False}
      and _vd({"intent": "plan", "objective": "wire the money", "project": "my-web-app"}, "plan offline mode for my-web-app")["intent"] == "clarify"
      and _vd({"intent": "plan", "objective": "offline mode", "panel": True}, "plan offline mode and get the panel to look at it")["panel"] is True
      and _vd({"intent": "plan", "objective": "offline mode", "panel": True}, "plan offline mode")["panel"] is False
      and _vd({"intent": "panelsay", "query": "onboarding", "project": "my-web-app"}, "x") == {"intent": "panelsay", "query": "onboarding", "project": "my-web-app"}
      and _vd({"intent": "missions"}, "x") == {"intent": "missions"})
import json as _j2, re as _re2
import guard as _gd0
_terms = _gd0.load_denylist(_REAL_HOME / "guard-denylist.txt")
_private_rx = _re2.compile("|".join(_re2.escape(t) for t in _terms) or "(?!x)x", _re2.I)      # matches nothing when you have no denylist, e.g. on a fresh clone
_ds = _j2.dumps(d.helm_shots(True)); _ps = set(d.demo.PROJECTS)
check("in demo mode the model's examples carry invented project names only; off, they are untouched",
      not _private_rx.search(_ds) and d.helm_shots(False)[:len(d.HELM_SHOTS)] == d.HELM_SHOTS
      and all(a.get("project") in _ps for u, a in d.helm_shots(True) if a.get("project")), _ds[:200])
check("helm notes: promote needs a note number and plan or mission; mark done needs a number or words; a project must exist",
      _vd({"intent": "promote", "n": 2, "kind": "plan", "project": "my-web-app"}, "x") == {"intent": "promote", "n": 2, "kind": "plan", "project": "my-web-app"}
      and _vd({"intent": "promote", "n": 2, "kind": "merge"}, "x")["intent"] == "clarify" and _vd({"intent": "promote", "kind": "plan"}, "x")["intent"] == "clarify"
      and _vd({"intent": "promote", "n": 0, "kind": "plan"}, "x")["intent"] == "clarify" and "project" not in _vd({"intent": "promote", "n": 1, "kind": "mission", "project": "invented"}, "x")
      and _vd({"intent": "notedone", "query": "dentist"}, "x") == {"intent": "notedone", "query": "dentist"} and _vd({"intent": "notedone", "n": 3}, "x") == {"intent": "notedone", "n": 3}
      and _vd({"intent": "notedone"}, "x")["intent"] == "clarify" and _vd({"intent": "notes"}, "x") == {"intent": "notes"})
# ---- Helm's conversation: persona, facts block, sentences, actions, history ----
import chatctx as _cc
_persona = _cc.PERSONA.lower()
check("the persona holds the owner's rules: calm, literal, brief, one idea at a time, no filler, no flattery, plain words, facts only, I do not know that, never claims an action, one ACTION line",
      all(w in _persona for w in ("calm", "literal", "brief", "one idea at a time", "no filler", "no flattery", "plain words", "only what is in the facts block",
                                  'say "i do not know that"', "where you would look", "never invent", "you have not done anything", "action: <one phrase", "one to three short spoken sentences", "read aloud")))
_priv = {"projects": [{"name": "alpha"}, {"name": "beta"}], "agents": [{"project": "alpha", "duty": "shipwright", "status": "running", "what": "issue #4", "since": "2026-10-05T11:30:00Z"}],
         "runs": [{"project": "alpha", "duty": "surveyor", "verdict": "ERROR", "at": "2026-10-05T11:50:00Z", "detail": "tests failed in test_x"}, {"project": "beta", "duty": "joiner", "verdict": "CLEAN", "at": "2026-10-05T11:00:00Z", "detail": "secret detail"}],
         "inbox": [{"project": "alpha", "duty": "surveyor", "text": "#4 tests failed", "acknowledged": False}, {"project": "beta", "duty": "x", "text": "acked item", "acknowledged": True}],
         "chat_notes": ["Elsewhere: 1 thing needs attention; scout-feed rate limited"], "spend": {"today": 2.5, "daily_budget": 6},
         "connectors": [{"name": "gmail", "connected": True, "unread": 5, "items": [{"title": "Invoice from Quokka Print", "sub": "billing@quokka.example"}]},
                        {"name": "slack", "connected": True, "unread": 2, "items": [{"title": "Zed (DM)", "sub": "lunch at the wombat cafe?"}]},
                        {"name": "calendar", "connected": True, "items": [{"title": "Meeting with Yuki about the platypus launch", "at": "2026-10-05T13:00:00Z"}]},
                        {"name": "reminders", "connected": True, "items": [{"title": "Call the emu vet", "at": "2026-10-05T09:00:00Z"}]}],
         "captures": {"open": 2, "items": [{"text": "buy a kazoo for the wallaby"}, {"text": "ask Marit about the dugong"}]}}
_prs = [{"project": "alpha", "number": 9, "title": "Add retries", "checks": {"pass": 3, "fail": 1, "pending": 0}}]
_now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
_dg0 = _cc.chat_digest(_priv, {"prs": _prs, "now": _now})
_dga = _cc.chat_digest(_priv, {"prs": _prs, "now": _now, "agenda": True})
_dgn = _cc.chat_digest(_priv, {"prs": _prs, "now": _now, "notes": True})
_secrets = ("Quokka", "quokka.example", "wombat", "Zed", "platypus", "Yuki", "emu vet", "kazoo", "wallaby", "Marit", "dugong")
check("chat digest: the facts are there, needs-you first, and acknowledged items and mail text are not",
      _dg0.splitlines()[0] == "Needs the owner:" and "- alpha surveyor: #4 tests failed" in _dg0 and "acked item" not in _dg0 and "shipwright on alpha (issue #4, 30 min)" in _dg0
      and "alpha surveyor ERROR 10 min ago: tests failed in test_x" in _dg0 and "beta joiner CLEAN" in _dg0 and "secret detail" not in _dg0
      and "alpha #9 Add retries: 3 passing, 1 failing, 0 running" in _dg0 and "Spend today: $2.50 of a $6.00 daily budget" in _dg0 and "scout-feed rate limited" in _dg0
      and "5 gmail, 2 slack, 2 open notes" in _dg0, _dg0)
check("chat digest: by default no calendar title, reminder, mail subject, sender, Slack text or note text appears (the cloud brain's rule)",
      not any(w in _dg0 for w in _secrets) and not any(w in _dga for w in ("Quokka", "quokka.example", "wombat", "Zed", "kazoo", "wallaby", "Marit", "dugong"))
      and not any(w in _dgn for w in ("Quokka", "wombat", "platypus", "Yuki", "emu vet")), _dg0)
check("chat digest: the agenda appears only with agenda on, the notes only with notes on, and mail and Slack are never more than a count",
      "platypus launch" in _dga and "emu vet" in _dga and "kazoo" not in _dga and "kazoo" in _dgn and "platypus" not in _dgn and "Quokka" not in _dga + _dgn)
_huge = {**_priv, "runs": [{"project": "p%d" % i, "duty": "d", "verdict": "ERROR", "at": "2026-10-05T11:00:00Z", "detail": "x" * 400} for i in range(300)],
         "inbox": [{"project": "p", "duty": "d", "text": "y" * 900, "acknowledged": False} for _ in range(50)], "agents": [{"project": "p%d" % i, "duty": "z", "status": "running", "what": "w" * 300} for i in range(80)]}
_dgh = _cc.chat_digest(_huge, {"prs": _prs * 30, "now": _now, "agenda": True, "notes": True})
check("chat digest: capped at 2500 characters with the most important facts kept, and junk state never raises",
      len(_dgh) <= 2500 and _dgh.startswith("Needs the owner:") and "Spend today" in _dgh and all(len(_cc.chat_digest(x, {})) >= 0 for x in (None, {}, {"runs": "x", "agents": [1, None], "inbox": {"a": 1}, "chat_notes": 5, "spend": [], "connectors": [None, 3], "captures": "no"})))
def _stream(text, final=True):
    out, buf = [], ""
    for ch in text:
        buf += ch
        sents, buf = _cc.split_sentences(buf)
        out += sents
    sents, _r = _cc.split_sentences(buf, final=True)
    return out + sents
_tx = "It cost $3.50 today. Dr. Hansen said e.g. 2.1 is fine. PR 12 passed! Is it done? Yes.\nACTION: open the ledger"
check("sentence splitting for streaming: decimals, abbreviations and the ACTION line, and a growing buffer gives what the whole text gives",
      _stream(_tx) == _cc.split_sentences(_tx, True)[0] == ["It cost $3.50 today.", "Dr. Hansen said e.g. 2.1 is fine.", "PR 12 passed!", "Is it done?", "Yes.", "ACTION: open the ledger"]
      and _cc.split_sentences("It is 3.", False) == ([], "It is 3.") and _cc.split_sentences("1. First thing\n2. Second thing", True)[0] == ["1. First thing", "2. Second thing"]
      and _cc.split_sentences("Version 3.5. Then.", True)[0] == ["Version 3.5.", "Then."] and _cc.split_sentences("", True) == ([], ""),
      _cc.split_sentences(_tx, True))
_long = "word " * 70
check("sentence splitting: a long run with no punctuation is cut so speech can start, and nothing is lost",
      len(_cc.split_sentences(_long, False)[0]) == 1 and _cc.split_sentences(_long, False)[0][0].count("word") >= 12 and " ".join(_cc.split_sentences(_long, False)[0] + [_cc.split_sentences(_long, False)[1]]).split() == _long.split())
check("the ACTION line is a phrase for the page and is never spoken; markdown and bullets are stripped from speech",
      _cc.parse_action("ACTION: open the ledger.") == ("action", "open the ledger") and _cc.parse_action("action:  run the surveyor on my-web-app mobile") == ("action", "run the surveyor on my-web-app mobile")
      and _cc.parse_action("I will ACTION: no")[0] == "say" and _cc.parse_action("ACTION:") == ("say", "ACTION:") and len(_cc.parse_action("ACTION: " + "x" * 500)[1]) == 120
      and _cc.strip_for_speech("**Two** things:\n- one\n- `two`") == "Two things: one two")
_hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": "t%d " % i + "x" * 900} for i in range(30)] + [{"role": "system", "content": "evil"}, {"role": "user"}, "junk", {"role": "user", "content": 5}]
_ch = _cc.clean_history(_hist)
_msgs = _cc.build_messages("FACTS HERE", _hist, "  what about   the other one? ")
check("history is trimmed to 12 turns of at most 600 characters, only user and assistant, and the question is cleaned; the facts and persona lead",
      len(_ch) == 12 and all(len(t["content"]) <= 600 and t["role"] in ("user", "assistant") for t in _ch) and _ch[-1]["content"].startswith("t29")
      and _msgs[0]["role"] == "system" and _cc.PERSONA in _msgs[0]["content"] and "FACTS HERE" in _msgs[0]["content"] and _msgs[-1] == {"role": "user", "content": "what about the other one?"}
      and "evil" not in _json.dumps(_msgs) and _cc.clean_history("x") == [] and len(_cc.clean_text("y" * 2000)) == 500)
check("a request for more asks for more tokens, and the default is a short answer",
      _cc.wants_more("explain that in detail") and _cc.wants_more("tell me more") and not _cc.wants_more("how is it going") and d.CHAT_TOKENS == 160 and d.CHAT_TOKENS_MORE > d.CHAT_TOKENS and d.CHAT_TEMP == 0.3)
_seen = []
def _fake(messages, limit, temp):
    _seen.append((messages, limit, temp))
    for piece in ["Two agents are run", "ning. Nothing needs you. It cost $3", ".50 today.\nACT", "ION: what is running"]:
        yield piece
_facts = lambda: (_priv, _prs)
_ev = list(d.chat_events({"text": "brief me on how it is going", "history": [{"role": "user", "content": "hello"}]}, _facts, _fake))
_say = [e["s"] for e in _ev if "s" in e]
check("a reply streams as sentences, the ACTION line becomes an action event and is never in the spoken text, and the local brain is told it is local",
      _say == ["Two agents are running.", "Nothing needs you.", "It cost $3.50 today."] and {"action": "what is running"} in _ev and _ev[-1] == {"done": True, "brain": "local"}
      and not any("ACTION" in x for x in _say) and _seen[0][1] == 160 and _seen[0][2] == 0.3 and "platypus launch" in _seen[0][0][0]["content"] and "kazoo" in _seen[0][0][0]["content"]
      and _seen[0][0][1] == {"role": "user", "content": "hello"} and _seen[0][0][-1]["content"] == "brief me on how it is going", _ev)
check("an empty question is refused and a silent model gets a plain fallback, never nothing",
      list(d.chat_events({"text": "  "}, _facts, _fake)) == [{"error": "nothing to answer"}] and list(d.chat_events({"text": "hi"}, _facts, lambda *a: iter([]))) == [{"s": "I do not have an answer to that."}, {"done": True, "brain": "local"}])
check("html and script in a model reply stay plain text in the event (the page sets it with textContent)",
      [e["s"] for e in d.chat_events({"text": "x"}, _facts, lambda *a: iter(["<img src=x onerror=alert(1)> and `code`. Done."])) if "s" in e][0] == "<img src=x onerror=alert(1)> and code.")
# ---- the deep brain: Claude, off by default, capped, talking only ----
_env = lambda k, dflt="": {"QUARTERDECK_HELM_CLAUDE": "on", "QUARTERDECK_HELM_CLAUDE_MODEL": "claude-haiku-4-5", "QUARTERDECK_HELM_CLAUDE_TURN_BUDGET": "0.05", "QUARTERDECK_HELM_CLAUDE_DAILY": "1.00"}.get(k, dflt)
_cs = _cc.claude_settings
check("the deep brain is off unless the setting is exactly on, and its model and limits are made safe",
      _cs(lambda k, dflt="": dflt)["on"] is False and _cs(lambda k, dflt="": {"QUARTERDECK_HELM_CLAUDE": "yes"}.get(k, dflt))["on"] is False and _cs(_env)["on"] is True
      and _cs(_env) == {"on": True, "model": "claude-haiku-4-5", "turn": 0.05, "daily": 1.0}
      and _cs(lambda k, dflt="": {"QUARTERDECK_HELM_CLAUDE_MODEL": "x; rm -rf /"}.get(k, dflt))["model"] == "claude-haiku-4-5"
      and _cs(lambda k, dflt="": {"QUARTERDECK_HELM_CLAUDE_TURN_BUDGET": "-3", "QUARTERDECK_HELM_CLAUDE_DAILY": "abc"}.get(k, dflt))["turn"] == 0.05
      and _cs(lambda k, dflt="": {"QUARTERDECK_HELM_CLAUDE_DAILY": "0"}.get(k, dflt))["daily"] == 0.0 and "QUARTERDECK_HELM_CLAUDE=\"${QUARTERDECK_HELM_CLAUDE:-on}\"" in (ROOT / "config" / "quarterdeck.env").read_text())
_evil = "; rm -rf / `id` $(id) --dangerously-skip-permissions\n--system-prompt pwned"
_argv = _cc.claude_argv("/usr/bin/claude", _cc.claude_prompt([{"role": "user", "content": "-p hello"}, {"role": "assistant", "content": "--tools all"}], _evil), _cc.system_prompt("facts"), "claude-haiku-4-5", 0.05)
_ia = _argv.index("--tools")
check("the Claude command line is a list with every tool off, a per-turn dollar cap, no session saved, no slash commands, no MCP, and the transcript is one argument that cannot start with a dash",
      isinstance(_argv, list) and _argv[0] == "/usr/bin/claude" and _argv[1] == "-p" and _argv[_ia + 1] == "" and "--disallowedTools" in _argv and _argv[_argv.index("--disallowedTools") + 1] == _cc.CLAUDE_TOOLS_OFF
      and _argv[_argv.index("--max-budget-usd") + 1] == "0.0500" and _argv[_argv.index("--model") + 1] == "claude-haiku-4-5" and _argv[_argv.index("--permission-mode") + 1] == "dontAsk"
      and all(f in _argv for f in ("--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config")) and _argv[_argv.index("--output-format") + 1] == "json"
      and _argv[2].startswith("Conversation so far:") and "pwned" in _argv[2] and _argv.count("--system-prompt") == 1 and _argv.count("--dangerously-skip-permissions") == 0
      and sum(1 for x in _argv if "rm -rf" in x) == 1 and all(isinstance(x, str) for x in _argv) and "--permission-mode" in _argv and all(t in _cc.CLAUDE_TOOLS_OFF for t in ("Bash", "Edit", "Write", "WebFetch")), _argv[:6])
_rows = [{"duty": "helm-chat", "cost": 0.30, "at": "2026-10-05T08:00:00Z"}, {"duty": "helm-chat", "cost": 0.45, "at": "2026-10-05T09:00:00Z"}, {"duty": "helm-chat", "cost": 9, "at": "2026-10-04T23:59:00Z"},
         {"duty": "shipwright", "cost": 5, "at": "2026-10-05T09:00:00Z"}, {"duty": "helm-chat", "cost": "bad", "at": "2026-10-05T10:00:00Z"}, "junk", {"duty": "helm-chat"}]
check("the daily cap counts only today's helm-chat rows from the spend ledger, and a turn may cost the turn limit or what is left of the day, never more; at the cap it is refused",
      abs(_cc.spent_today(_rows, "2026-10-05T00:00:00Z") - 0.75) < 1e-9 and _cc.spent_today("x", "") == 0 and _cc.turn_allowance(0, 1.0, 0.05) == 0.05 and _cc.turn_allowance(0.97, 1.0, 0.05) == 0.03
      and _cc.turn_allowance(0.999, 1.0, 0.05) == 0.0 and _cc.turn_allowance(1.0, 1.0, 0.05) == 0.0 and _cc.turn_allowance(5, 1.0, 0.05) == 0.0 and _cc.turn_allowance(0, 0.0, 0.05) == 0.0)
_calls = []
def _claude_ok(system, message, **kw):
    _calls.append((system, message, kw))
    yield ("s", "Two agents are running. Noth"); yield ("s", "ing needs you.\nACTION: what is running"); yield ("done", 0.0123)
_cfg_on = {"on": True, "model": "claude-haiku-4-5", "turn": 0.05, "daily": 1.0, "spent": 0.0}
_ev = list(d.chat_events({"text": "brief me, think about it", "brain": "claude", "history": [{"role": "user", "content": "hi", "src": "chat"}]}, _facts, _fake, _claude_ok, _cfg_on))
check("a Claude turn gets the persona alone as its system prompt and the newest digest WITHOUT the private parts in the message, the model, the allowance and a process cap, speaks sentence by sentence, passes the ACTION line to the page, and reports its cost",
      [e for e in _ev if "s" in e] == [{"s": "Two agents are running."}, {"s": "Nothing needs you."}] and {"action": "what is running"} in _ev and _ev[-1] == {"done": True, "brain": "claude", "cost": 0.0123}
      and _calls[0][2]["model"] == "claude-haiku-4-5" and _calls[0][2]["allow"] == 0.05 and _calls[0][2]["budget"] == 0.3 and _calls[0][2]["fresh"] is False and _calls[0][2]["inc"] == frozenset()
      and _calls[0][0] == _cc.claude_system() and "Helm" in _calls[0][0] and "Needs the owner" in _calls[0][1] and "Needs the owner" not in _calls[0][0]
      and not any(w in _calls[0][0] + _calls[0][1] for w in _secrets) and _calls[0][1].endswith("Owner: brief me, think about it\nHelm:"), _ev)
_calls.clear()
_ev2 = list(d.chat_events({"text": "think", "brain": "claude", "include": {"agenda": True, "notes": False}}, _facts, _fake, _claude_ok, _cfg_on))
check("only after the owner said include my agenda does the agenda go to Claude, and notes stay out until they say so; a non-boolean flag counts as no; the process is told what is shared",
      "platypus launch" in _calls[0][1] and "kazoo" not in _calls[0][1] and "Quokka" not in _calls[0][1] and _calls[0][2]["inc"] == frozenset({"agenda"}) and _calls[0][2]["fresh"] is True
      and (list(d.chat_events({"text": "t", "brain": "claude", "include": {"agenda": "yes", "notes": 1}}, _facts, _fake, _claude_ok, _cfg_on)) and "platypus" not in _calls[-1][1] and "kazoo" not in _calls[-1][1] and _calls[-1][2]["inc"] == frozenset()))
def _claude_boom(*a, **k): raise RuntimeError("it hit its limit for one turn")
_fb = list(d.chat_events({"text": "think", "brain": "claude"}, _facts, _fake, _claude_boom, _cfg_on))
_off = list(d.chat_events({"text": "think", "brain": "claude"}, _facts, _fake, _claude_ok, {**_cfg_on, "on": False}))
_cap = list(d.chat_events({"text": "think", "brain": "claude"}, _facts, _fake, _claude_ok, {**_cfg_on, "spent": 1.0}))
_calls.clear()
list(d.chat_events({"text": "think", "brain": "claude"}, _facts, _fake, _claude_ok, {**_cfg_on, "spent": 0.97}))
def _claude_half(system, message, **kw):
    yield ("s", "Two agents are running. Nothing"); raise RuntimeError("the call failed")
_half = list(d.chat_events({"text": "think", "brain": "claude"}, _facts, _fake, _claude_half, _cfg_on))
check("when Claude fails, is switched off or is capped, the local brain answers and the first spoken sentence says why; at the cap Claude is not called at all; the last 3 cents of the day cap the turn and the process cap; a failure after some sentences ends the reply honestly instead of answering twice",
      _fb[0]["s"].startswith("Claude did not answer (it hit its limit for one turn)") and _fb[-1] == {"done": True, "brain": "local", "fallback": "error"} and any("s" in e for e in _fb[1:])
      and _off[0]["s"] == "Thinking with Claude is switched off, so I am answering locally." and _off[-1]["fallback"] == "off"
      and _cap[0]["s"].startswith("Today's limit of $1.00 for thinking with Claude is reached") and _cap[-1]["fallback"] == "cap" and _calls[0][2]["allow"] == 0.03 and _calls[0][2]["budget"] == 0.03
      and [e.get("s") for e in _half if "s" in e] == ["Two agents are running.", "Nothing", "Claude stopped partway (the call failed)."] and _half[-1]["brain"] == "claude", (_half, _fb))
d.demo_set(True)
try:
    _dm = list(d.chat_events({"text": "think", "brain": "claude"}, d.chat_facts, _fake, _claude_ok, _cfg_on))
finally:
    d.demo_set(False)
_calls.clear()
check("in demo mode the deep brain is never called, whatever the page asks, and the local brain answers from the made-up world",
      _dm[0]["s"] == "Thinking with Claude is off in demo mode, so I am answering locally." and _dm[-1] == {"done": True, "brain": "local", "fallback": "demo"} and not _calls)
_sv = (d.subprocess.run, d.SPEND, d.shutil.which)
_sd = Path(_tf.mkdtemp()); d.SPEND = _sd / "spend.jsonl"; _ran = []
def _fake_run(argv, **kw):
    _ran.append((argv, kw))
    return type("R", (), {"returncode": 0, "stdout": _json.dumps({"result": "Fine.", "total_cost_usd": 0.0231, "num_turns": 1, "modelUsage": {"claude-haiku-4-5": {}}, "usage": {"input_tokens": 400, "output_tokens": 30}}), "stderr": ""})()
d.subprocess.run = _fake_run; d.shutil.which = lambda n: "/usr/bin/claude" if n == "claude" else None
_cb = d.os.environ.pop("CLAUDE_BIN", None)      # a duty runs with CLAUDE_BIN set; the test must not depend on it
_txt, _cost = d.claude_chat("SYSTEM", "Conversation so far:\nOwner: hi\nHelm:", 0.05, "claude-haiku-4-5")
_row = _json.loads(d.SPEND.read_text().splitlines()[0])
check("a deep-brain call goes out as an argv list with no shell, from an empty folder, with a timeout, and its cost lands in the spend ledger under helm-chat",
      (_txt, _cost) == ("Fine.", 0.0231) and _ran[0][0][0] == "/usr/bin/claude" and "--tools" in _ran[0][0] and _ran[0][1].get("timeout") == 45 and _ran[0][1].get("shell") is None and str(ROOT) not in _ran[0][1]["cwd"]
      and _row["duty"] == "helm-chat" and _row["cost"] == 0.0231 and _row["model"] == "claude-haiku-4-5" and _row["stopped"] is None and _row["out"] == 30 and _row["read"] == 400)
d.subprocess.run = lambda argv, **kw: type("R", (), {"returncode": 1, "stdout": _json.dumps({"subtype": "error_max_budget_usd", "total_cost_usd": 0.06, "is_error": True}), "stderr": ""})()
_capped = []
try: d.claude_chat("S", "P", 0.05, "m")
except RuntimeError as _e: _capped.append(str(_e))
_rows2 = [_json.loads(x) for x in d.SPEND.read_text().splitlines()]
d.subprocess.run, d.SPEND, d.shutil.which = _sv
if _cb is not None: d.os.environ["CLAUDE_BIN"] = _cb
check("a call that fails or hits its cap is still paid for, so it is recorded, and it raises so the page falls back to the local brain",
      _capped == ["it hit its limit for one turn"] and _rows2[1]["cost"] == 0.06 and _rows2[1]["stopped"] == "cap" and len(_rows2) == 2)
d.demo_set(True)
try:
    _dstate, _dprs = d.chat_facts()
    _ddig = _cc.chat_digest(_dstate, {"agenda": True, "notes": True, "prs": _dprs})
finally:
    d.demo_set(False)
check("in demo mode the conversation brain is given the made-up world only",
      "wayfarer" in _ddig and not _private_rx.search(_ddig) and _ddig.startswith("Needs the owner:") and len(_ddig) <= 2500, _ddig[:300])
# ---- where the owner's attention goes: the collector reads timestamps and counts only ----
import attention.collect as _ac, attention.sources as _as, subprocess as _sub2, stat as _stat
_MARK = ("SECRET-PROMPT-7f3a", "SECRET-REPLY-9c1b", "SECRET-DIFF-2d8e", "SECRET-COMMIT-5b6c", "SECRET-FILE-4e1a", "SECRET-CWD-8a0f", "SECRET-TOOL-3c7d")
_ad = Path(_tf.mkdtemp()); _home = _ad / "home"; _stt = _ad / "state"; _stt.mkdir()
_projdir = _ad / "work" / "alpha"; _projdir.mkdir(parents=True)
_other = _ad / "work" / "beta.site"; _other.mkdir(parents=True)
_t = lambda m: "2026-10-05T%02d:%02d:00Z" % (m // 60, m % 60)
# a Claude Code session file with marker text sits in a home folder: the collector must never be pointed at it, whatever it is handed
_sess = _home / ".claude" / "projects" / "-x-alpha"; _sess.mkdir(parents=True)
(_sess / "a.jsonl").write_text(_json.dumps({"type": "user", "timestamp": "2026-10-05T10:00:00Z", "message": {"role": "user", "content": _MARK[0]}}) + "\n")
_reg = {"alpha": {"path": str(_projdir)}, "beta": {"path": str(_other)}, "gone": {"path": str(_ad / "nowhere")}}
def _git(cwd, *args, **env): return _sub2.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_COMMITTER_NAME": "T", **env}, check=True)
_git(_projdir, "init", "-q"); _git(_projdir, "config", "user.email", "me@example.test")
for _i, (_mail, _dt) in enumerate([("me@example.test", "2026-10-05T09:00:00"), ("me@example.test", "2026-10-05T11:00:00"), ("other@example.test", "2026-10-05T12:00:00"), ("me@example.test", "2026-10-02T09:00:00")]):
    (_projdir / ("f%d_" % _i + _MARK[4] + ".txt")).write_text("line " + _MARK[2] + "\n"); _git(_projdir, "add", "-A")
    _git(_projdir, "commit", "-q", "-m", "message " + _MARK[3], GIT_AUTHOR_EMAIL=_mail, GIT_COMMITTER_EMAIL=_mail, GIT_AUTHOR_DATE=_dt, GIT_COMMITTER_DATE=_dt)
(_projdir / "agent.txt").write_text("agent " + _MARK[2] + "\n"); _git(_projdir, "add", "-A")          # an agent's commit under the owner's name carries the trailer: git itself drops it
_git(_projdir, "commit", "-q", "-m", "agent work " + _MARK[3] + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>", GIT_AUTHOR_EMAIL="me@example.test", GIT_COMMITTER_EMAIL="me@example.test", GIT_AUTHOR_DATE="2026-10-05T15:00:00", GIT_COMMITTER_DATE="2026-10-05T15:00:00")
_NOW = datetime(2026, 10, 6, 12, 0).timestamp()
_inp = {"homes": (".claude",), "home_dir": str(_home), "projects": _reg,
        "prs": [{"project": "alpha", "created": "2026-10-05T08:00:00Z", "title": _MARK[0]}, {"project": "ghost", "created": "2026-10-05T08:00:00Z"}, {"project": "alpha", "created": "bad"}],
        "notes": [{"project": "alpha", "at": "2026-10-05T10:00:00Z", "text": _MARK[0]}, {"project": None, "at": "2026-10-04T10:00:00Z"}],
        "runs": [{"project": "alpha", "at": "2026-10-05T13:30:00Z", "title": _MARK[1]}, {"project": "ghost", "at": "bad"}],
        "calendar": [{"title": _MARK[0], "at": "2026-10-06T09:00:00Z", "sub": "Tue 09:00 · Work"}, {"title": "x", "at": "2026-10-06T00:00:00Z", "sub": "Tue 6 Oct, all day · Work"}, {"title": "y", "at": "2026-10-06T14:00:00Z", "sub": "Tue 14:00"}]}
_sm = _ac.collect(_inp, _stt, now=_NOW, tz=timezone.utc)
_att = _json.loads((_stt / "attention.json").read_text()); _D = _att["days"]
_blob = (_stt / "attention.json").read_text() + _json.dumps(_sm)
check("attention: the collector writes only counts: per project and day commits, files, pull requests, notes and meetings",
      _att["estimated"] is True and set(_D) == {"alpha", "other", "(calendar)"} and not any(k in v for dd in _D.values() for v in dd.values() for k in ("minutes", "sessions")))
_src = "".join((ROOT / "bin" / "attention" / f).read_text() for f in ("sources.py", "collect.py", "intent.py", "__init__.py"))
check("attention STANDING RULE: nothing outside the registered projects and state/ is read: no Claude Code session file of any profile is opened (the code has no reader for them and no path to ~/.claude), and no keystroke, screen, app, clipboard or location API is used",
      not any(w in _src.replace("Co-Authored-By: Claude", "") for w in ("read_turns", "session_files", "claude_days", "projects/", ".claude", "CLAUDE_HOMES", "expanduser(\"~", "Path.home", "pynput", "pyautogui", "pbpaste", "screencapture", "CGEvent", "NSWorkspace", "CoreLocation", "osascript"))
      and "homes" not in _src and "home_dir" not in _src and not any(m in _blob for m in _MARK))
check("attention: git gives the owner's own commits and files per day (another author's and merges are not his), and the PR, note and calendar counts are by date only",
      _D["alpha"]["2026-10-05"]["commits"] == 2 and _D["alpha"]["2026-10-05"]["files"] == 2 and _D["alpha"]["2026-10-02"] == {"commits": 1, "files": 1}
      and _D["alpha"]["2026-10-05"]["prs"] == 1 and _D["alpha"]["2026-10-05"]["notes"] == 1 and _D["other"]["2026-10-05"]["prs"] == 1 and _D["other"]["2026-10-04"]["notes"] == 1
      and _D["(calendar)"]["2026-10-06"] == {"meetings": 2} and "beta" not in _D and "gone" not in _D, _D)
_H = _att["hours"]
check("attention keeps HOUR buckets (project, day, hour: counts only): commits from git, notes, pull requests, runs started by hand and calendar blocks by the hour they fall in; an agent's commit under the owner's name (the Co-Authored-By trailer) is not among them",
      _H["alpha"]["2026-10-05"] == {"09": {"commits": 1}, "11": {"commits": 1}, "08": {"prs": 1}, "10": {"notes": 1}, "13": {"runs": 1}} and "15" not in _H["alpha"]["2026-10-05"]
      and _H["alpha"]["2026-10-02"] == {"09": {"commits": 1}} and _H["other"]["2026-10-05"] == {"08": {"prs": 1}} and _H["other"]["2026-10-04"] == {"10": {"notes": 1}}
      and _H["(calendar)"]["2026-10-06"] == {"09": {"meetings": 1}, "14": {"meetings": 1}} and _D["alpha"]["2026-10-05"]["commits"] == 2 and _D["alpha"]["2026-10-05"]["runs"] == 1, _H)
check("attention PRIVACY: no prompt, reply, diff, commit message, file name, working folder, tool output or title is ever read into the output, the cache or the summary",
      not any(m in _blob for m in _MARK) and "message" not in _blob and "work profile" not in _blob, [m for m in _MARK if m in _blob])
check("attention: state/attention.json is written owner only, and no agent may read it (QUARTERDECK_PRIVATE_DENY and the sandbox list)",
      oct((_stt / "attention.json").stat().st_mode & 0o777) == "0o600" and not (_stt / "attention-cache.json").exists()
      and all(w in (ROOT / "config" / "quarterdeck.env").read_text() for w in ("state/attention.json", "state/intent.jsonl", "state/project-status.json"))
      and all(w in (ROOT / "bin" / "lib.sh").read_text() for w in ("state/attention.json", "state/intent.jsonl", "state/project-status.json")))
_ac.collect(_inp, _stt, now=_NOW, tz=timezone.utc); _same = _json.loads((_stt / "attention.json").read_text())["days"]
check("attention: a second pass over the same data changes nothing (idempotent)", _same == _D)
(_stt / "attention.json").write_text(_json.dumps({"days": {"alpha": {"2025-12-01": {"minutes": 99, "sessions": 3, "commits": 7}}}})); (_stt / "attention-cache.json").write_text("{}")
_ac.collect({"projects": {}}, _stt, now=_NOW, tz=timezone.utc)
check("attention: minutes and sessions written by an earlier version that read session files are removed from the store, and its cache file is deleted",
      _json.loads((_stt / "attention.json").read_text())["days"] == {"alpha": {"2025-12-01": {"commits": 7}}} and not (_stt / "attention-cache.json").exists())
(_stt / "attention.json").write_text("not json")
_empty = _ac.collect({"projects": {"x": {"path": "/no/such/dir"}, "bad": 5, "y": {}}, "prs": "junk", "notes": [None, 3], "calendar": [{"at": 5}, "x"]}, _stt, now=_NOW, tz=timezone.utc)
check("attention: missing folders, bad lines, junk inputs and a corrupt store give an empty result, not an error",
      _empty["projects"] == 0 and _json.loads((_stt / "attention.json").read_text())["days"] == {})
_old = {"p": {"2024-01-01": {"commits": 5}, "2026-10-01": {"commits": 5}}, "q": {"2024-01-02": {"notes": 1}}}
check("attention: 400 days are kept and older days and empty projects are dropped",
      _ac.prune(_old, _NOW) == {"p": {"2026-10-01": {"commits": 5}}})
_m = {"p": {"d1": {"commits": 4, "prs": 2}}}
_ac.merge(_m, "git", {"p": {"d1": {"commits": 9, "files": 1}}}); _ac.merge(_m, "prs", {"p": {"d1": {"prs": 1}}}, None, keep_max=True)
check("attention: a source only replaces the fields it owns, and a count that can only grow (pull requests) never shrinks",
      _m == {"p": {"d1": {"commits": 9, "files": 1, "prs": 2}}}, _m)
_sv_env = d.env_flag
d.env_flag = lambda k, dflt="": "off" if k == "QUARTERDECK_ATTENTION" else _sv_env(k, dflt)
_before = (_stt / "attention.json").read_bytes(); _ran = []
_realc = _ac.collect; _ac.collect = lambda *a, **k: _ran.append(1)
_tick_off = d.attention_tick()
d.env_flag = _sv_env
d.demo_set(True)
try: _tick_demo = d.attention_tick()
finally: d.demo_set(False)
_ac.collect = _realc
check("attention: QUARTERDECK_ATTENTION=off and Demo mode both stop the collector, and neither deletes anything; the loop is a health-checked loop",
      not _ran and _tick_off == d.ATTENTION_EVERY == _tick_demo and (_stt / "attention.json").read_bytes() == _before and "run_loop(\"attention\"" in (ROOT / "bin" / "dashboard.py").read_text()
      and "QUARTERDECK_ATTENTION=\"${QUARTERDECK_ATTENTION:-on}\"" in (ROOT / "config" / "quarterdeck.env").read_text())
# ---- attention hardening ----
import attention.sources as _as
_hd = Path(_tf.mkdtemp()); _calls_g = []
_gr = _as.git_days(_hd, "me@example.org", "2026-10-01", run=lambda argv, **k: (_calls_g.append(argv), type("R", (), {"returncode": 0, "stdout": "2026-10-05 09\n 1 file changed, 2 insertions(+)\n\nSECRET-MSG-LINE\n"})())[1]) if (_hd / ".git").mkdir() is None else None
_av = _calls_g[0]
check("git does the filtering of the agents' own commits: the command carries the case-insensitive inverted Co-Authored-By: Claude grep, signatures and fsmonitor off, and only dates and counts come out, whatever else git prints",
      "--invert-grep" in _av and "--grep=Co-Authored-By: Claude" in _av and "--regexp-ignore-case" in _av and "--fixed-strings" in _av and _av[:5] == ["git", "-c", "log.showSignature=false", "-c", "core.fsmonitor=false"]
      and "--pretty=format:%ad" in _av and not any(x in _av for x in ("%s", "%b", "%B")) and "SECRET-MSG-LINE" not in _json.dumps(_gr) and set(next(iter(_gr.values()))) == {"commits", "files", "hours"} and _gr["2026-10-05"]["hours"] == {"09": 1}, (_av, _gr))
_envt = (ROOT / "config" / "quarterdeck.env").read_text(); _libt = (ROOT / "bin" / "lib.sh").read_text()
check("the private deny patterns and the sandbox deny list end in a wildcard, so the temp files written beside the private files are covered too",
      all(f"state/{n}*" in _envt and f"state/{n}*" in _libt for n in ("attention.json", "intent.jsonl", "project-status.json")))
check("in the share, a commit is worth 6 points and nothing else is read from the computer",
      "6 * n0(r.commits)" in (ROOT / "dashboard" / "assets" / "attention.js").read_text())
# ---- My rhythm on real data: the adapter, the route and the log of runs started by hand ----
import attention.rhythm_feed as _rf
_store = {"updated": "2026-10-06T12:00:00", "hours": {"alpha": {"2026-10-05": {"09": {"commits": 3, "notes": 1}, "10": {"commits": 1}}, "2026-01-01": {"09": {"commits": 9}}},
                                                       "beta": {"2026-10-05": {"09": {"commits": 2}}}, "(calendar)": {"2026-10-05": {"14": {"meetings": 2}}}, "bad": 5, "other": {"2026-10-05": {"11": {"prs": 1}}}},
          "days": {"alpha": {"2026-10-05": {"commits": 99}}}}
_fb = _rf.build(_store, "2026-10-06")
_ev = _fb["events"]
check("the adapter gives rhythm.js the demo's shape from hour buckets alone: events {t, kind, project} spread inside their hour with one project after another, meetings with a start and no length, the real rules and badge, old and odd buckets left out",
      _fb["concept"] is False and _fb["estimated"] is True and _fb["badge"] == "Estimated from your commits, branches, notes and calendar. It cannot see reading, thinking or other work." and _fb["rules"] == {"gap": 44, "minBlock": 20, "tail": 5, "switchKinds": ["commit"], "minEvents": 15, "minDays": 3}
      and all(set(e) == {"t", "kind", "project"} for e in _ev) and len(_ev) == 3 + 1 + 1 + 2 + 1 and all(e["t"].startswith("2026-10-05T") for e in _ev) and not any(e["t"].startswith("2026-01-01") for e in _ev)
      and [e["project"] for e in _ev if e["t"].startswith("2026-10-05T09")] == ["alpha"] * 4 + ["beta"] * 2 and [m for m in _fb["meetings"]] == [{"day": "2026-10-05", "from": "14:05", "to": None}, {"day": "2026-10-05", "from": "14:55", "to": None}]
      and _ev == sorted(_ev, key=lambda e: e["t"]) and _rf.build({}, "2026-10-06")["events"] == [] and _rf.build(None, "2026-10-06")["meetings"] == [] and _rf.build({"hours": {"a": {"2026-10-05": {"99": {"commits": 1}, "x": {"commits": 1}, "09": {"commits": "9", "notes": True}}}}}, "2026-10-06")["events"] == [], _ev)
check("the adapter never carries text: the output holds only times, kinds, project names and counts, and nothing outside the hour buckets (the day totals are not used)",
      _json.dumps(_fb).count("99") == 0 and set(_fb) == {"concept", "on", "estimated", "badge", "today", "updated", "rules", "events", "meetings"})
_svr = (d.ATTENTION, d.HAND_RUNS, d.STATE)
_rd = Path(_tf.mkdtemp()); d.ATTENTION = _rd / "attention.json"; d.HAND_RUNS = _rd / "hand-runs.jsonl"
d.ATTENTION.write_text(_json.dumps({"updated": "x", "hours": {"REAL-PROJECT-MARK": {d._today(): {"09": {"commits": 2}}}}}))
_rv = d.rhythm_view()
_sv_env2 = d.env_flag; d.env_flag = lambda k, dflt="": "off" if k == "QUARTERDECK_ATTENTION" else _sv_env2(k, dflt)
_rv_off = d.rhythm_view(); d.env_flag = _sv_env2
d.demo_set(True)
try: _rv_demo = d.rhythm_view()
finally: d.demo_set(False)
check("the real route answers from the owner's own counts, says honestly when collection is off, and in Demo mode answers only the invented preview and never touches the real file",
      _rv["concept"] is False and _rv["events"] and _rv["events"][0]["project"] == "REAL-PROJECT-MARK" and _rv_off["on"] is False and _rv_off["events"] == []
      and _rv_demo["concept"] is True and "REAL-PROJECT-MARK" not in _json.dumps(_rv_demo) and _rv_demo["badge"] == "Concept preview: invented data, nothing is collected")
_ran2 = []; _svp = (d.subprocess.Popen, d.validate_run, d.LOGS)
d.subprocess.Popen = lambda *a, **k: _ran2.append(a); d.validate_run = lambda *a: ["x", "y", "z"]; d.LOGS = _rd / "logs"
d.spawn_run("alpha", "surveyor", [], False); d.spawn_run("alpha", "surveyor", [], False, source="schedule")
_hr = d.HAND_RUNS.read_text().splitlines()
d.demo_set(True)
try:
    try: d.spawn_run("alpha", "surveyor", [], False); _dm_run = ""
    except RuntimeError as e: _dm_run = str(e)
finally: d.demo_set(False)
d.subprocess.Popen, d.validate_run, d.LOGS = _svp
d.ATTENTION, d.HAND_RUNS, d.STATE = _svr
check("a run started by hand from the dashboard leaves one line of time and project in Quarterdeck's own state, mode 0600 and on the private deny lists; a scheduled run and a Demo mode run leave none",
      len(_hr) == 1 and set(_json.loads(_hr[0])) == {"at", "project", "label"} and _json.loads(_hr[0])["label"] == "surveyor" and _json.loads(_hr[0])["project"] == "alpha" and len(_ran2) == 2 and "demo mode" in _dm_run
      and "state/hand-runs.jsonl*" in (ROOT / "config" / "quarterdeck.env").read_text() and "state/hand-runs.jsonl*" in (ROOT / "bin" / "lib.sh").read_text())
# ---- My rhythm task timeline: the ONE file that holds titles (state/rhythm-tasks.json) and exactly what it may hold ----
import attention.tasks as _tk
_TM = {k: "SECRET-" + k + "-" + v for k, v in dict(subj1="1a", body="2b", fname="3c", content="4d", subj2="5e", agent="6f", other="7g", note="8h", pr="9i", cal="0j", slack="1k", gmail="2l", run="3m").items()}
_td = Path(_tf.mkdtemp()); _tproj = _td / "work" / "tproj"; _tproj.mkdir(parents=True); _tst = _td / "state"; _tst.mkdir()
def _tg(*args, **env): return _sub2.run(["git", "-C", str(_tproj), *args], capture_output=True, text=True, env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_COMMITTER_NAME": "T", "GIT_AUTHOR_EMAIL": "me@example.test", "GIT_COMMITTER_EMAIL": "me@example.test", **env}, check=True)
def _tc(msg, when, name, mail="me@example.test", content="x"):
    (_tproj / name).write_text(content + "\n"); _tg("add", "-A")
    _tg("commit", "-q", "-m", msg, GIT_AUTHOR_EMAIL=mail, GIT_COMMITTER_EMAIL=mail, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
_tg("init", "-q"); _tg("config", "user.email", "me@example.test")
_tc("first", "2026-10-05T08:00:00", "a.txt")
_tg("checkout", "-q", "-b", "feat/fix-47-offline-cache", GIT_COMMITTER_DATE="2026-10-05T08:55:00")
_tc(_TM["subj1"] + "\n\n" + _TM["body"] + " the body of the message", "2026-10-05T09:10:00", _TM["fname"] + ".txt", content=_TM["content"])
_tc("Second " + _TM["subj2"], "2026-10-05T09:40:00", "b.txt")
_tc("agent work " + _TM["agent"] + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>", "2026-10-05T10:00:00", "c.txt")
_tc("other author " + _TM["other"], "2026-10-05T10:05:00", "d.txt", mail="other@example.test")
_tinp = {"projects": {"tproj": {"path": str(_tproj)}}, "rhythm_tasks": True,
         "prs": [{"project": "tproj", "created": "2026-10-05T09:20:00Z", "title": "PR " + _TM["pr"], "body": _TM["body"]}],
         "notes": [{"project": "tproj", "at": "2026-10-05T09:30:00Z", "text": "Note " + _TM["note"]}],
         "runs": [{"project": "tproj", "at": "2026-10-05T09:50:00Z", "label": "surveyor, PR #12"}],
         "calendar": [{"title": "Meet " + _TM["cal"], "at": "2026-10-05T11:00:00Z", "sub": "Mon 11:00"}, {"title": "all day thing", "at": "2026-10-05T00:00:00Z", "sub": "Mon 5 Oct, all day"}],
         "slack": [{"text": _TM["slack"]}], "gmail": [{"subject": _TM["gmail"]}], "email_of": None}
_NOW2 = datetime(2026, 10, 6, 12, 0).timestamp()
_ac.collect(_tinp, _td / "state", now=_NOW2, tz=timezone.utc)
_tf_path = _td / "state" / "rhythm-tasks.json"; _tt = _tf_path.read_text(); _te = _json.loads(_tt)["events"]
_pairs = {(e["kind"], e["label"]) for e in _te}
check("the task file holds ONLY the allowed fields: a commit's subject line (not its body, file names, file contents or diff), the branch from the reflog as a plain label, a pull request title, note text, a run label and a calendar title; the time and project beside each",
      {("commit", "first"), ("commit", _TM["subj1"]), ("commit", "Second " + _TM["subj2"]), ("branch", "#47 fix offline cache"), ("pr", "PR " + _TM["pr"]), ("note", "Note " + _TM["note"]), ("run", "surveyor, PR #12"), ("meeting", "Meet " + _TM["cal"])} <= _pairs
      and all(set(e) <= {"t", "kind", "project", "label", "branch"} and _re2.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", e["t"]) for e in _te)
      and [e["branch"] for e in _te if e["kind"] == "branch" and e["label"] == "#47 fix offline cache"] == ["feat/fix-47-offline-cache"], sorted(_pairs))
check("the task file never holds a commit body, a diff, a file name or content, an agent's commit under the owner's name, another author's commit, a message from Slack or Gmail, a pull request body or an all day entry",
      not any(_TM[k] in _tt for k in ("body", "fname", "content", "agent", "other", "slack", "gmail")) and "all day thing" not in _tt and "SECRET-body" not in _tt and "the body of the message" not in _tt
      and not any(e["label"].startswith("agent") or e["label"].startswith("other author") for e in _te))
check("the task file is owner only (and its temp files fall under the same deny patterns), on QUARTERDECK_PRIVATE_DENY and the sandbox deny list; the counts file stays free of every title",
      oct(_tf_path.stat().st_mode & 0o777) == "0o600" and "state/rhythm-tasks.json*" in (ROOT / "config" / "quarterdeck.env").read_text() and "state/rhythm-tasks.json*" in (ROOT / "bin" / "lib.sh").read_text()
      and not any(v in (_td / "state" / "attention.json").read_text() for v in _TM.values()) and "subject" not in (ROOT / "bin" / "attention" / "collect.py").read_text().lower().replace("tasks.py", ""))
_n1 = len(_te); _ac.collect(_tinp, _td / "state", now=_NOW2, tz=timezone.utc); _te2 = _json.loads(_tf_path.read_text())["events"]
_ac.collect({**_tinp, "calendar": [], "prs": [], "notes": []}, _td / "state", now=_NOW2, tz=timezone.utc); _te3 = _json.loads(_tf_path.read_text())["events"]
_p3 = {(e["kind"], e["label"]) for e in _te3}
check("a second pass changes nothing; a pull request and a calendar block already seen stay (the cache and the snapshot forget), a deleted note goes",
      len(_te2) == _n1 and ("pr", "PR " + _TM["pr"]) in _p3 and ("meeting", "Meet " + _TM["cal"]) in _p3 and not any(k == "note" for k, _l in _p3))
_old = _json.loads(_tf_path.read_text()); _old["events"].append({"t": "2024-01-01T09:00", "kind": "note", "project": "x", "label": "ancient", "body": "x"}); _old["events"].append({"t": "2026-10-05T09:00", "kind": "evil", "project": "x", "label": "bad kind"})
_tf_path.write_text(_json.dumps(_old)); _ac.collect(_tinp, _td / "state", now=_NOW2, tz=timezone.utc); _te4 = _json.loads(_tf_path.read_text())["events"]
check("400 days of retention, and a stored event of an unknown kind or with an extra field is cleaned out", not any(e["label"] in ("ancient", "bad kind") for e in _te4) and all(set(e) <= {"t", "kind", "project", "label", "branch"} for e in _te4))
_tf_path.unlink(); _ac.collect({**_tinp, "rhythm_tasks": False}, _td / "state", now=_NOW2, tz=timezone.utc)
check("with QUARTERDECK_RHYTHM_TASKS=off no title is collected and the file is not created", not _tf_path.exists() and "QUARTERDECK_RHYTHM_TASKS" in (ROOT / "config" / "quarterdeck.env").read_text())
check("branch names become plain words (feat/focus-voice is focus voice, an issue number is #47), a run is labelled by its duty and number or its idea, control characters and long text are cut",
      _tk.branch_label("feat/focus-voice") == "focus voice" and _tk.branch_label("fix/47-login") == "#47 login" and _tk.branch_label("a1b2c3d4e5f6") == "" and _tk.branch_label("issue-12") == "#12"
      and _tk.run_label("surveyor", ["--pr", "12"]) == "surveyor, PR #12" and _tk.run_label("panel", ["--panel", "spec", "--idea", "offline mode"]) == "panel: offline mode" and _tk.run_label("trials", []) == "trials"
      and _tk.clean("a\x00b\n\tc") == "a b c" and len(_tk.clean("x" * 500)) == 140)
import attention.rhythm_feed as _rf2
check("the screen is given only the allowed fields, cleaned again, and nothing when the switch is off",
      _rf2.task_view({"events": [{"t": "2026-10-05T09:00", "kind": "commit", "project": "p", "label": "ok", "body": "NOPE", "diff": "NOPE"}, {"t": "2026-10-05T09:00", "kind": "evil", "label": "x"}, {"t": "2001-01-01T09:00", "kind": "note", "label": "old"}, 5]}, "2026-10-06")["events"] == [{"t": "2026-10-05T09:00", "kind": "commit", "project": "p", "label": "ok"}]
      and _rf2.task_view({"events": [{"t": "2026-10-05T09:00", "kind": "note", "label": "x"}]}, "2026-10-06", False) == {"on": False, "events": [], "file": "state/rhythm-tasks.json"})
_rv_t = (d.RHYTHM_TASKS, d.ATTENTION); d.RHYTHM_TASKS = _rd / "rhythm-tasks.json"; d.ATTENTION = _rd / "att2.json"
d.RHYTHM_TASKS.write_text(_json.dumps({"events": [{"t": d._today() + "T09:00", "kind": "commit", "project": "p", "label": "TASKROUTE-OK", "body": "TASKROUTE-BODY"}]}))
_rt_on = d.rhythm_view()
_sv_env3 = d.env_flag; d.env_flag = lambda k, dflt="": "off" if k == "QUARTERDECK_RHYTHM_TASKS" else _sv_env3(k, dflt)
_rt_off = d.rhythm_view(); d.env_flag = _sv_env3
d.demo_set(True)
try: _rt_demo = _json.dumps(d.rhythm_view())
finally: d.demo_set(False)
d.RHYTHM_TASKS, d.ATTENTION = _rv_t
check("the real route hands the screen the task titles only while QUARTERDECK_RHYTHM_TASKS is on, with the allowed fields alone; Demo mode never reads the real task file",
      [e["label"] for e in _rt_on["tasks"]["events"]] == ["TASKROUTE-OK"] and "TASKROUTE-BODY" not in _json.dumps(_rt_on) and _rt_off["tasks"] == {"on": False, "events": [], "file": "state/rhythm-tasks.json"} and "TASKROUTE" not in _rt_demo)
# ---- intent and project status ----
_id = Path(_tf.mkdtemp()); _svi = (d.INTENT, d.PROJECT_STATUS, d.PROJECTS_FILE)
d.INTENT = _id / "intent.jsonl"; d.PROJECT_STATUS = _id / "project-status.json"; d.PROJECTS_FILE = _id / "p.json"
d.PROJECTS_FILE.write_text(_json.dumps({"alpha": {}, "beta": {}, "gamma": {}, "delta": {}, "eps": {}}))
def _err(fn, *a):
    try: fn(*a); return None
    except ValueError as e: return str(e)
_ok1 = d.intent_set([{"name": "alpha", "share": 0.6}, {"name": "beta"}], "this", True)
_v = d.intent_view()
check("intent: the focus is set only on the owner's click, from registered projects, one to four, shares between 0 and 1 adding up to at most 1",
      _err(d.intent_set, [{"name": "alpha"}], "this", None) == "the owner has to confirm this" and _err(d.intent_set, [{"name": "nope"}], "this", True) == "unknown project"
      and _err(d.intent_set, [], "this", True) and _err(d.intent_set, [{"name": n} for n in ("alpha", "beta", "gamma", "delta", "eps")], "this", True)
      and _err(d.intent_set, [{"name": "alpha", "share": 0.7}, {"name": "beta", "share": 0.6}], "this", True) and _err(d.intent_set, [{"name": "alpha", "share": True}], "this", True)
      and _err(d.intent_set, [{"name": "alpha"}, {"name": "alpha"}], "this", True) and _err(d.intent_set, [{"name": "alpha"}], "someday", True)
      and _v["current"]["projects"] == [{"name": "alpha", "share": 0.6}, {"name": "beta"}] and _v["current"]["from"] <= _v["today"] <= _v["current"]["to"] and _ok1["projects"][0]["name"] == "alpha")
check("intent: the file is append-only, owner only, in the deny lists, and a later record for the same week wins; next week is not current yet",
      oct(d.INTENT.stat().st_mode & 0o777) == "0o600" and d.intent_set([{"name": "gamma"}], "next", True) and len(d.INTENT.read_text().splitlines()) == 2
      and d.intent_view()["current"]["projects"] == [{"name": "alpha", "share": 0.6}, {"name": "beta"}]
      and d.intent_set([{"name": "delta"}], "this", True) and d.intent_view()["current"]["projects"] == [{"name": "delta"}]
      and "state/intent.jsonl" in (ROOT / "config" / "quarterdeck.env").read_text() and "state/project-status.json" in (ROOT / "config" / "quarterdeck.env").read_text())
d.INTENT.write_text(d.INTENT.read_text() + "not json\n{\"from\": 5}\n[]\n")
check("intent: junk lines are skipped without error", d.intent_view()["current"]["projects"] == [{"name": "delta"}])
_ps = d.project_status_set("alpha", "park", True)
check("project status: Continue, Park and Archive only mark a project (a confirmed write of one small file, 0600); nothing else is touched",
      _ps["status"] == "park" and d.intent_view()["status"]["alpha"]["status"] == "park" and oct(d.PROJECT_STATUS.stat().st_mode & 0o777) == "0o600"
      and _err(d.project_status_set, "alpha", "delete", True) and _err(d.project_status_set, "nope", "park", True) and _err(d.project_status_set, "alpha", "park", "yes")
      and d.project_status_set("alpha", "continue", True)["status"] == "continue" and set(d.PROJECT_STATUS.parent.iterdir()) >= {d.PROJECT_STATUS}
      and not [x for x in d.PROJECT_STATUS.parent.iterdir() if ".tmp" in x.name])
d.demo_set(True)
_n_before = len(d.INTENT.read_text().splitlines()); _dn = []
try:
    for _f, _a in ((d.intent_set, ([{"name": "alpha"}], "this", True)), (d.project_status_set, ("alpha", "park", True))):
        try: _f(*_a)
        except RuntimeError as e: _dn.append(str(e))
finally: d.demo_set(False)
check("intent: Demo mode refuses to write the real files", len(_dn) == 2 and len(d.INTENT.read_text().splitlines()) == _n_before)
d.INTENT, d.PROJECT_STATUS, d.PROJECTS_FILE = _svi
_page = (ROOT / "dashboard" / "index.html").read_text()
check("intent: the page sends confirm true only from its own button or from Helm's Yes click, and the card is rebuilt in its own slot so a tick never loses a draft",
      _page.count('"/api/intent", {projects') == 2 and _page.count("confirm: true") >= 2 and 'id="brain-bar"' in _page and "if(inside && !force) return;" in _page and "function openFocusDrawer" in _page)
_brain = (ROOT / "dashboard" / "assets" / "brain.js").read_text()
check("attention UI: the size toggle sets node weight, the Attention panel marks a project only after a second click, and the bars are flat with no animation",
      "n.weight" in _brain and "section(r.label)" in _brain and "lbar" in _brain and "markProject" in _page and "Confirm " in _page and "/api/project-status" in _page
      and "quarterdeck.brainSize" in _page and "gradient" not in _ui.split(".brain-bar{")[1].split(".brain-panel .lk{")[0] and "animation" not in _ui.split(".brain-bar{")[1].split(".brain-panel .lk{")[0]
      and "\u2014" not in _page.split("let sizeBy =")[1].split("/* ---- Helm: duties")[0])
_realatt = d.attention_view(); _realint = d.intent_view(); _svatt = d.ATTENTION
d.ATTENTION = _id / "att-real.json"; d.ATTENTION.write_text(_json.dumps({"updated": "x", "days": {"REAL-PROJECT-MARK": {"2026-10-05": {"commits": 9}}}}))
d.demo_set(True)
try: _demoatt = d.attention_view(); _demoint = d.intent_view(); _demoget = _json.dumps(_demoatt) + _json.dumps(_demoint)
finally: d.demo_set(False)
d.ATTENTION = _svatt
check("attention: Demo mode returns the made-up buckets in the same shape as the real endpoint, reads nothing real, and has a starting focus",
      set(_demoatt) == set(_realatt) and "REAL-PROJECT-MARK" not in _demoget and _demoatt["days"] and _demoint["current"]["projects"][0]["name"] in d.demo.PROJECTS
      and set(_demoint) == set(_realint))
_page = (ROOT / "dashboard" / "index.html").read_text()
check("replay: a day slider that only resizes nodes and lists that day's Ledger events; it never plays by itself and nothing animates",
      "replayRange" in _page and "dayRuns" in _page and "setInterval" not in _page.split("function toggleReplay")[1].split("function replayList")[0] and "requestAnimationFrame" not in _page.split("function replayRow")[1].split("function replayList")[0]
      and '<sl-range id="replay-r"' in _page and "Back to now" in _page)
# ---- My rhythm: a demo-only concept preview ----
_rui = (ROOT / "dashboard" / "assets" / "rhythm-ui.js").read_text(); _rjs = (ROOT / "dashboard" / "assets" / "rhythm.js").read_text(); _ix = (ROOT / "dashboard" / "index.html").read_text()
_rh_text = _rui + _rjs
check("My rhythm serves two sources through one screen: the page tells the module demo or real, the module fetches only /api/rhythm, and the server answers it from the demo world in Demo mode and from the owner's own counts otherwise",
      'rhythmMod.sync(S && S.demo && S.demo.on ? "demo" : "real"' in _ix and _ix.count("rhythm") <= 40 and _rui.count("fetch(") == 1 and "/api/rhythm" in _rui and 'if(modeNow !== "demo" && modeNow !== "real"){ remove(); return; }' in _rui
      and "def rhythm_view" in (ROOT / "bin" / "dashboard.py").read_text() and "/api/rhythm" in (ROOT / "bin" / "demo.py").read_text())
check("My rhythm is flat and calm: solid colours, no gradient, glow, blur or animation, no em dashes in what it says, and it carries the concept badge",
      not any(w in _rui.lower() for w in ("gradient", "box-shadow", "blur(", "animation", "transition", "@keyframes", "drop-shadow", "backdrop")) and "\u2014" not in _rh_text and "\u2013" not in _rh_text
      and "Concept preview: invented data, nothing is collected" in _rjs and "R.BADGE" in _rui and "data.badge" in _rui)
check("My rhythm never depicts or implies what Quarterdeck must never collect: no apps, websites, typing, idle or screen time, or where you were, in its words or its code",
      not _re2.search(r"\b(apps? used|websites?|typing|keystroke|idle time|screen time|screenshot|clipboard|geoloc|where you were|browser history)\b", _rh_text, _re2.I))
class _P:
    def __init__(self): self.dead = False
    def poll(self): return 1 if self.dead else None
    def terminate(self): self.dead = True
_made = []
_sc = d.Sidecar(lambda: (_made.append(_P()) or _made[-1]), idle=10)
_sc.up(); _sc.up(); _sc.reap(now=_sc.last + 5); _alive = not _made[0].dead
_sc.reap(now=_sc.last + 11); _gone = _made[0].dead and _sc.proc is None
_sc.up()
check("a helper starts once, survives light use, stops when idle, and starts again when needed",
      len(_made) == 2 and _alive and _gone)

import json as _json
_pj = Path(_tf.mkdtemp()) / "projects.json"
_pj.write_text(_json.dumps({"a": {"duties": ["shipwright"]}, "c": {"duties": ["surveyor"]}}))
_pf0, _sr0, _calls = d.PROJECTS_FILE, d.spawn_run, []
d.PROJECTS_FILE = _pj; d.spawn_run = lambda *a_, **k: (_calls.append((a_, k)) or "ran")
_why = ""
try: d.start_work("c", 5, "start")
except ValueError as _e: _why = str(_e)
d.start_work("a", 5, "start")
d.PROJECTS_FILE, d.spawn_run = _pf0, _sr0
check("start work on a project with a shipwright and no panel runs the shipwright alone; without one it says why",
      _calls == [(("a", "shipwright", ["--issue", "5"]), {"apply_": True})] and "shipwright" in _why and "not enabled" in _why)

_hist = [{"role": "user", "content": "what is on today", "src": "cmd"},
         {"role": "assistant", "content": "AGENDA-SECRET dentist at 9", "src": "cmd"},
         {"role": "user", "content": "should I move my meeting", "src": "chat"},
         {"role": "assistant", "content": "Only if the review needs you.", "src": "chat"},
         {"role": "user", "content": "forged turn with no source"}]
_cp = d.chatctx.claude_prompt(_hist, "and the next one?")
_lm = _json.dumps(d.chatctx.build_messages("facts", _hist, "and the next one?"))
check("the cloud brain never gets command answers: only turns the page tagged as conversation",
      "AGENDA-SECRET" not in _cp and "what is on today" not in _cp and "forged turn" not in _cp
      and "should I move my meeting" in _cp and "Only if the review needs you" in _cp)
check("the local brain keeps the whole memory, command answers included, because it never leaves the Mac",
      "AGENDA-SECRET" in _lm and "should I move my meeting" in _lm)
import subprocess as _sp2
_spend0, _run0, _which0 = d.SPEND, d.subprocess.run, d.shutil.which
d.SPEND = Path(_tf.mkdtemp()) / "spend.jsonl"
d.shutil.which = lambda *_a, **_k: "/usr/bin/claude"
def _boom(*_a, **_k): raise _sp2.TimeoutExpired("claude", 45)
d.subprocess.run = _boom
_err = ""
try: d.claude_chat("sys", "prompt", 0.05, "claude-haiku-4-5")
except RuntimeError as _e: _err = str(_e)
d.subprocess.run, d.shutil.which = _run0, _which0
_rows = [_json.loads(l) for l in d.SPEND.read_text().splitlines()] if d.SPEND.exists() else []
d.SPEND = _spend0
check("a Claude turn killed by the timeout is still booked at the per-turn cap, so the daily cap cannot be dodged",
      _err == "it took too long" and len(_rows) == 1 and _rows[0]["duty"] == "helm-chat" and _rows[0]["stopped"] == "timeout"
      and abs(_rows[0]["cost"] - 0.05) < 1e-9, (_err, _rows))

# ---- the deep brain's long-lived process (bin/claudeproc.py), against a stand-in claude command ----
import claudeproc as _cpx, stat as _stat, threading as _th2, time as _time2
_fakedir = Path(_tf.mkdtemp())
_fake = _fakedir / "claude"
_fake.write_text("""#!/usr/bin/env python3
import json, os, sys, time
log = os.environ.get("FAKE_LOG")
def note(**kw):
    if log:
        with open(log, "a") as f: f.write(json.dumps(kw) + "\\n")
def out(o): sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
note(event="start", argv=sys.argv[1:], think=os.environ.get("MAX_THINKING_TOKENS"), cwd=os.getcwd(), pid=os.getpid())
total = 0.0
out({"type": "active_goal", "value": None})
for line in sys.stdin:
    msg = json.loads(line)["message"]["content"]
    note(event="turn", msg=msg, pid=os.getpid(), raw=line)
    if "CRASH" in msg: sys.exit(3)
    out({"type": "system", "subtype": "init"})
    if "SLOW" in msg: time.sleep(30)
    if "CAP" in msg:
        out({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": total + 0.06}); sys.exit(1)
    pieces = ["x" * 3000] if "LONG" in msg else [] if "NOSTREAM" in msg else ["Two agents ", "are running. ", "Nothing needs you."]
    for p in pieces:
        out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}}})
        out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": p}}})
        if "PAUSE" in msg: time.sleep(0.7)
    total += 0.2 if "EXPENSIVE" in msg else 0.002
    out({"type": "result", "subtype": "success", "is_error": False, "result": "".join(pieces) or "Final only.", "total_cost_usd": total, "num_turns": 1, "usage": {"output_tokens": 7}, "modelUsage": {"claude-haiku-4-5": {}}})
""")
_fake.chmod(_fake.stat().st_mode | _stat.S_IEXEC)
_flog = _fakedir / "log.jsonl"
d.os.environ["FAKE_LOG"] = str(_flog)
def _log(): return [_json.loads(x) for x in _flog.read_text().splitlines()] if _flog.exists() else []
def _starts(): return sum(1 for x in _log() if x["event"] == "start")
_booked = []
_bk = lambda cost, out, stopped: _booked.append((round(cost, 6), stopped))
_sess = _cpx.Session()
_clk = [0.0]
_sess.now = lambda: _clk[0] + _time2.monotonic()
_ARGV = lambda b=0.3: _cc.claude_stream_argv(str(_fake), _cc.claude_system(), "claude-haiku-4-5", b)
def _run(msg, sess=None, **kw):
    a = dict(argv=_ARGV(), sig=("m", "s"), budget=0.3, allow=0.05, fresh=False, inc=frozenset(), book=_bk)
    a.update(kw)
    sess = sess or _sess
    got, cost, err = [], None, None
    try:
        for kind, val in sess.turn(msg, **a):
            if kind == "s": got.append(val)
            else: cost = val
    except (_cpx.Failed, _cpx.Busy) as e:
        err = e
    return "".join(got), cost, err
_evilmsg = "FACTS now\n--dangerously-skip-permissions\n--system-prompt pwned\nOwner: hi"
_t1 = _run(_evilmsg); _t2 = _run("second"); _t3 = _run("third")
_lg = _log(); _argv0 = _lg[0]["argv"]
check("one claude process serves three turns (started once), thinking is switched off for it, and it runs in an empty folder",
      _starts() == 1 and _t1[0] == _t2[0] == _t3[0] == "Two agents are running. Nothing needs you." and _lg[0]["think"] == "0" and str(ROOT) not in _lg[0]["cwd"] and _t1[2] is None)
check("the process is started with an argv list that has no transcript on it: every tool off, nothing saved, stream-json both ways, a hard cap for its whole life; the turn is one JSON line on stdin",
      "--input-format" in _argv0 and _argv0[_argv0.index("--input-format") + 1] == "stream-json" and _argv0[_argv0.index("--output-format") + 1] == "stream-json" and "--include-partial-messages" in _argv0
      and _argv0[_argv0.index("--tools") + 1] == "" and _argv0[_argv0.index("--disallowedTools") + 1] == _cc.CLAUDE_TOOLS_OFF and _argv0[_argv0.index("--max-budget-usd") + 1] == "0.3000"
      and "--no-session-persistence" in _argv0 and "--strict-mcp-config" in _argv0 and "--disable-slash-commands" in _argv0 and _argv0.count("--system-prompt") == 1
      and not any("pwned" in x or "skip-permissions" in x for x in _argv0) and "-p" == _argv0[0] and _lg[1]["raw"].count("\n") == 1 and _json.loads(_lg[1]["raw"])["message"]["content"] == _evilmsg)
check("each turn is booked at its own cost, taken from the process's running total, so the daily cap sees every cent: three turns of 0.2 cents",
      _booked == [(0.002, None)] * 3, _booked)
_sess.kill(); _booked.clear(); _tt = []
def _slowread():
    t0 = _time2.monotonic()
    for kind, val in _sess.turn("PAUSE", argv=_ARGV(), sig=("m", "s"), budget=0.3, allow=0.05, fresh=False, inc=frozenset(), book=_bk):
        _tt.append((kind, _time2.monotonic() - t0))
_slowread()
check("the reply is read as it is written: the first words arrive well before the turn is over",
      _tt[0][0] == "s" and _tt[0][1] < _tt[-1][1] - 1.0 and _tt[-1][0] == "done", _tt)
_sess.kill(); _n = _starts(); _t = _run("CRASH"); _after = _run("after the crash")
check("a process that dies is replaced on the next turn, and the failed turn raises so the page can fall back",
      isinstance(_t[2], _cpx.Failed) and _after[0] == "Two agents are running. Nothing needs you." and _after[2] is None and _starts() == _n + 2, (_n, _starts()))
_n = _starts(); _run("a", fresh=True); _run("b", fresh=False); _s1 = _starts(); _run("c", fresh=True); _s2 = _starts()
check("a conversation that starts over (nothing said yet, but the process has been talking) gets a fresh process, a continuing one does not",
      _s1 == _starts() - 1 and _s2 == _s1 + 1, (_s1, _s2))
_run("d", inc=frozenset({"agenda"})); _s3 = _starts(); _run("e", inc=frozenset({"agenda"})); _s4 = _starts(); _run("f", inc=frozenset()); _s5 = _starts()
check("sharing the agenda stays while it is shared, and withdrawing it starts a fresh process so nothing carries over",
      _s4 == _s3 and _s5 == _s4 + 1, (_s3, _s4, _s5))
_run("g", sig=("m2", "s")); _s6 = _starts()
check("a changed model setting starts a fresh process", _s6 == _s5 + 1, (_s5, _s6))
_cpx.MAX_PROC_TURNS = 2; _sess.kill(); _a = _starts(); _run("1"); _run("2"); _run("3")
check("a process is replaced after a few turns so its own context cannot grow", _starts() == _a + 2, (_a, _starts())); _cpx.MAX_PROC_TURNS = 6
_sess.kill(); _a = _starts(); _run("x"); _clk[0] += 700; _run("y")
check("a process that has been idle for ten minutes is replaced, and the reaper stops one nobody is using", _starts() == _a + 2)
_clk[0] += 700; _sess.reap(); _gone = _sess.proc is None; _run("z"); _alive = _sess.alive(); _sess.reap(); _kept = _sess.alive()
check("reap stops an idle process but leaves one in use alone", _gone and _alive and _kept)
_a = _starts(); _sess.kill(); _run("EXPENSIVE", budget=0.3, allow=0.05); _run("next", budget=0.3, allow=0.05)
check("a process with too little of its own cap left for another turn is replaced; a turn that cost more than a turn may is booked in full",
      _starts() == _a + 2 and _booked[-2][0] == 0.2, (_a, _starts(), _booked[-3:]))
_booked.clear(); _sess.kill(); _r = _run("CAP")
check("a turn that hits the hard cap raises and is still booked, and the process is gone", isinstance(_r[2], _cpx.Failed) and "limit" in str(_r[2]) and _booked == [(0.06, "cap")] and _sess.proc is None, _booked)
_cpx.TURN_TIMEOUT = 1.2; _booked.clear(); _sess.kill(); _t0 = _time2.monotonic(); _r = _run("SLOW"); _dt = _time2.monotonic() - _t0; _cpx.TURN_TIMEOUT = 45
check("a turn that takes too long is killed, booked at the most it could have cost (so the daily cap cannot be dodged), and raises",
      isinstance(_r[2], _cpx.Failed) and str(_r[2]) == "it took too long" and _booked == [(0.05, "timeout")] and _sess.proc is None and _dt < 4, (_booked, _dt))
_cpx.MAX_REPLY_CHARS = 100; _booked.clear(); _sess.kill(); _r = _run("LONG"); _cpx.MAX_REPLY_CHARS = 2500
check("a reply that runs on is cut off, booked at the most a turn may cost, and the process is stopped", len(_r[0]) <= 3100 and _r[1] == 0.05 and _booked == [(0.05, "long")] and _sess.proc is None, (_r[1], _booked))
_booked.clear(); _sess.kill(); _r = _run("NOSTREAM")
check("a process that only sends the finished answer still speaks it", _r[0] == "Final only." and _r[2] is None)
_sess.kill(); _g = _sess.turn("PAUSE", argv=_ARGV(), sig=("m", "s"), budget=0.3, allow=0.05, fresh=False, inc=frozenset(), book=_bk); next(_g); _g.close()
_r = _run("after the listener left")
check("when the page stops listening mid reply the process is stopped (it was left in an odd state) and the next turn works", _r[0].startswith("Two agents") and _r[2] is None and not _sess.lock.locked())
_sess.kill(); _booked.clear()
_g = _sess.turn("PAUSE", argv=_ARGV(), sig=("m", "s"), budget=0.3, allow=0.05, fresh=False, inc=frozenset(), book=_bk); next(_g); _g.close()
_ab1 = list(_booked); _sess.kill()
check("a reply abandoned after its first sentence (the page aborted) is still booked, exactly once, at the most a turn may cost, so it cannot sit outside the daily cap",
      _ab1 == [(0.05, "aborted")] and _booked == [(0.05, "aborted")], _booked)
_cpx.LOCK_WAIT = 0.2; _sess.kill(); _res = []
_th = _th2.Thread(target=lambda: _res.append(_run("PAUSE"))); _th.start(); _time2.sleep(0.3)
_busy = _run("second at once"); _th.join(); _cpx.LOCK_WAIT = 2
check("a second reply asked for while one is being written is refused as busy, not mixed in", isinstance(_busy[2], _cpx.Busy) and _res[0][0].startswith("Two agents"))
_sess.kill()
_sf = _cpx.Session(); _st = []; _booked.clear()
try: list(_sf.turn("x", argv=["/nonexistent/claude-binary"], sig=1, budget=0.3, allow=0.05, fresh=False, inc=frozenset(), book=_bk))
except _cpx.StartFailed as e: _st.append(str(e))
check("a command that cannot start raises StartFailed, books nothing, and leaves nothing running", _st == ["the claude command could not be started"] and _sf.proc is None and not _booked)
# the dashboard's wrapper: the ledger, the one-shot way out, demo mode
_sv = (d.SPEND, d.CLAUDE_SESSION, d.subprocess.run, d.os.environ.get("CLAUDE_BIN"))
d.SPEND = _fakedir / "spend.jsonl"; d.CLAUDE_SESSION = _cpx.Session(); d.os.environ["CLAUDE_BIN"] = str(_fake)
_out = list(d.claude_stream(_cc.claude_system(), "FACTS now\nOwner: hi\nHelm:", allow=0.05, model="claude-haiku-4-5", fresh=True, inc=frozenset(), budget=0.3))
_row = _json.loads(d.SPEND.read_text().splitlines()[0])
d.CLAUDE_SESSION.kill()
check("the dashboard's deep-brain call goes through the long-lived process and books a helm-chat row with its cost, model and tokens",
      [k for k, v in _out] == ["s", "s", "s", "done"] and _out[-1] == ("done", 0.002) and _row["duty"] == "helm-chat" and _row["cost"] == 0.002 and _row["model"] == "claude-haiku-4-5" and _row["out"] == 7)
d.os.environ["CLAUDE_BIN"] = "/nonexistent/claude-binary"
d.subprocess.run = lambda argv, **kw: type("R", (), {"returncode": 0, "stdout": _json.dumps({"result": "One shot.", "total_cost_usd": 0.01, "usage": {}}), "stderr": ""})()
_one = list(d.claude_stream(_cc.claude_system(), "FACTS now\nOwner: hi\nHelm:", allow=0.05, model="claude-haiku-4-5", fresh=True, inc=frozenset(), budget=0.3))
d.subprocess.run = _sv[2]
d.demo_set(True)
try:
    try: list(d.claude_stream("s", "m", allow=0.05, model="m", fresh=True, inc=frozenset(), budget=0.3)); _dd = ""
    except RuntimeError as e: _dd = str(e)
finally: d.demo_set(False)
d.SPEND, d.CLAUDE_SESSION = _sv[0], _sv[1]
if _sv[3] is None: d.os.environ.pop("CLAUDE_BIN", None)
else: d.os.environ["CLAUDE_BIN"] = _sv[3]
d.os.environ.pop("FAKE_LOG", None)
check("when the long-lived process cannot start, the one-shot call answers instead (slower, same limits), and in Demo mode neither is ever started",
      _one == [("s", "One shot."), ("done", 0.01)] and "demo mode is on" in _dd)
# a warm request only readies the process
_wev = list(d.chat_events({"brain": "claude", "warm": True}, _facts, _fake, lambda system, message, **kw: iter([("s", "ready"), ("done", 0.004)]), _cfg_on))
_woff = list(d.chat_events({"brain": "claude", "warm": True}, _facts, _fake, _claude_ok, {**_cfg_on, "on": False}))
check("a warm-up request says nothing aloud and reports its cost; when Claude is off or capped it does nothing",
      _wev == [{"done": True, "brain": "claude", "warm": True, "cost": 0.004}] and _woff == [{"done": True, "brain": "local", "warm": True, "fallback": "off"}])
# the message the process is given, and the wording kept out of speech
_hist = [{"role": "user", "content": "what is on today", "src": "cmd"}, {"role": "assistant", "content": "AGENDA-SECRET dentist at 9", "src": "cmd"},
         {"role": "user", "content": "should I move my meeting", "src": "chat"}, {"role": "assistant", "content": "Only if the review needs you.", "src": "chat"}]
_cm = _cc.claude_message("Needs the owner: nothing.", _hist, "and the next one?")
check("the long-lived process is given the newest facts each turn, the chat-tagged conversation only (never a command's answer), and the question, in a message that starts with a fixed word",
      _cm.startswith("FACTS now") and "Needs the owner: nothing." in _cm and "AGENDA-SECRET" not in _cm and "what is on today" not in _cm and "should I move my meeting" in _cm and _cm.endswith("Owner: and the next one?\nHelm:")
      and "older ones" in _cc.CLAUDE_NOTE and _cc.CLAUDE_NOTE in _cc.claude_system() and "Needs the owner" not in _cc.claude_system())
check("a process starts with the most that a few turns may cost, never more than is left of the day",
      _cc.process_budget(1.0, 0.05) == 0.3 and _cc.process_budget(0.1, 0.05) == 0.1 and _cc.process_budget(0.0, 0.05) == 0.0 and _cc.process_budget(-1, 0.05) == 0.0)
check("the model's own instruction wording is kept out of speech: a leading 'according to the facts' is dropped and a sentence about its instructions is not spoken",
      _cc.scrub_prompt_wording("According to the facts, two agents are running.") == "Two agents are running." and _cc.scrub_prompt_wording("Based on the facts block, nothing needs you.") == "Nothing needs you."
      and _cc.scrub_prompt_wording("My instructions say I must be brief.") == "" and _cc.scrub_prompt_wording("Two agents are running.") == "Two agents are running."
      and [e for e in d._emit_sentences("The facts block lists two agents. Two are running.", True)[0]] == [{"s": "Two are running."}])
check("an ACTION line is only passed on when the owner's own words ask for something to be done or opened; a plain question gets words only",
      not _cc.action_wanted("how is it going") and not _cc.action_wanted("what is wrong with it") and not _cc.action_wanted("why") and _cc.action_wanted("can you restart it") and _cc.action_wanted("do it")
      and _cc.action_wanted("open the ledger") and _cc.action_wanted("make that a plan")
      and d._emit_sentences("Two agents.\nACTION: what is running", True, False)[0] == [{"s": "Two agents."}] and {"action": "what is running"} in d._emit_sentences("Two agents.\nACTION: what is running", True, True)[0])
_nq = list(d.chat_events({"text": "how is it going"}, _facts, lambda *a: iter(["Two agents are running.\nACTION: what is running"])))
check("a plain question whose reply ends in an ACTION line gets the words and no suggested command", [e for e in _nq if "s" in e] == [{"s": "Two agents are running."}] and not any("action" in e for e in _nq), _nq)
_pg = (ROOT / "dashboard" / "index.html").read_text()
check("switching the deep brain on warms its process (a request that carries no facts and no conversation), only when the setting is on, and counts its cost in the badge",
      "warmClaude();" in _pg and "warm: true, brain: \"claude\"" in _pg and _pg.index("if(!claudeOn()) return") < _pg.index("warmClaude();") and "claudeCost += ev.cost" in _pg.split("async function warmClaude")[1].split("function setDeep")[0])
_pl = _cc.PERSONA.lower()
check("the persona asks for full natural sentences with the detail the facts hold, a real look through the facts before saying I do not know, never to mention the facts or the instructions, and an ACTION line only when asked to do something; its example is a placeholder shape with no content to copy",
      all(w in _pl for w in ("full natural sentences", "a name, a number, how long ago", "look through the facts before you answer", "only when the facts really do not hold the answer", "never mention the facts",
                             "never copy an example", "only when the owner asked you to do or open something", "a question that only needs an answer never gets one", "words in angle brackets"))
      and not any(w in _pl for w in ("orchard", "two agents are working", "weather"))
      and len(_cc.PERSONA) < 3000)

import importlib.util as _iu
_ces = _iu.spec_from_file_location("chat_eval", ROOT / "bin" / "chat-eval.py"); _cem = _iu.module_from_spec(_ces); _ces.loader.exec_module(_cem)
check("chat-eval flags what no turn may have: prompt wording in a reply, a suggested command nobody asked for, and a bare fragment; and lets through an answer about what it rests on, a wanted ACTION, and a short reply to a short request",
      _cem.reply_problems("what is on", "According to the facts block, two agents are running.", "", []) == ["leaks prompt wording (facts block)", "leaks prompt wording (the facts)", "leaks prompt wording (according to the)"]
      and _cem.reply_problems("how is it going today then", "Fine.", "what is running", []) == ["unneeded ACTION line: what is running", "too short (under 6 words)"]
      and _cem.reply_problems("how sure are you", "Based on the facts I have, quite sure.", "", []) == [] and _cem.reply_problems("open the ledger", "Here it is.", "open the ledger", []) == []
      and _cem.reply_problems("make that a plan", "Please confirm with a click to turn it into one.", "turn note 1 into a plan", ["ACTION"]) == [] and _cem.reply_problems("how many are open", "Four.", "", []) == [])
# ---- the fix queue -------------------------------------------------------------
# The drainer starts real fixes, so it runs here against a throwaway state
# directory with the spawner replaced — nothing is filed, built or pushed.
import tempfile, json as _json
_tmp = pathlib.Path(tempfile.mkdtemp())
_saved = {k: getattr(d, k) for k in ("STATE", "FIXQ", "FIXES", "PANELS", "USAGE_MARK",
                                     "LOGS", "SPEND", "spawn_fix", "running_locks", "START_GRACE")}
import os as _os
_budget_env = _os.environ.get("QUARTERDECK_DAILY_BUDGET")
try:
    d.STATE, d.FIXQ, d.FIXES = _tmp, _tmp / "fixqueue", _tmp / "fixes"
    d.PANELS, d.USAGE_MARK, d.LOGS = _tmp / "panels", _tmp / "usage-limit", _tmp / "logs"
    d.SPEND = _tmp / "spend.jsonl"
    _os.environ.pop("QUARTERDECK_DAILY_BUDGET", None)
    d.START_GRACE = -1
    for x in (d.PANELS, d.FIXES):
        x.mkdir(parents=True)
    spawned, locks = [], {}
    d.spawn_fix = lambda project, panel, items, source: spawned.append(items[0] if len(items) == 1 else tuple(items))
    d.running_locks = lambda: dict(locks)
    ruling = [{"title": f"item {i}", "area": f"area {i}"} for i in range(1, 6)]
    (d.PANELS / "qp.json").write_text(_json.dumps(
        {"id": "qp", "project": "my-web-app", "discipline": "design", "status": "done",
         "subject": "components/", "started": "2026-09-23", "ruling": ruling}))
    def finish(item, status, lock=None):
        rec = {"project": "my-web-app", "panel": "qp", "item": item, "status": status}
        if lock:
            rec["lock"] = lock
        (d.FIXES / f"qp-{item}.json").write_text(_json.dumps(rec))
    q = lambda: d.load_q("my-web-app")["items"]

    # fix_index() is what drain_fix_queues actually asks — now that several
    # fixes can run on one project, "is this one still running" has to come
    # from its OWN lock, not any lock on the project.
    finish(9, "running", lock="fix-my-web-app-qp-9")
    locks["fix-my-web-app-qp-9"] = {"pid": 1}
    check("a record whose own lock is alive stays running",
          d.fix_index(locks)["qp#9"]["status"] == "running")
    del locks["fix-my-web-app-qp-9"]
    check("a record whose own lock died is abandoned, not left running",
          d.fix_index(locks)["qp#9"]["status"] == "abandoned")
    finish(9, "running")  # no lock field at all: a record from before this existed
    check("a record with no lock field to check is trusted as-is",
          d.fix_index(locks)["qp#9"]["status"] == "running")
    (d.FIXES / "qp-9.json").unlink()

    _, queued, skipped = d.enqueue("qp", [1, 2, 3])
    check("queuing three on a free project starts the first at once",
          spawned == [1] and [x["state"] for x in q()] == ["active", "pending", "pending"], (spawned, q()))

    finish(1, "running"); d.drain_fix_queues()
    check("nothing else starts while one is running", spawned == [1])

    finish(1, "pr"); d.drain_fix_queues()
    check("a finished fix leaves the queue and the next one starts",
          spawned == [1, 2] and [x["item"] for x in q()] == [2, 3], (spawned, q()))

    # the usage limit hits while #2 is running
    d.USAGE_MARK.write_text(d.iso(d.now_utc() + d.timedelta(seconds=5)))
    finish(2, "blocked"); d.drain_fix_queues()
    check("a fix cut off by the usage limit goes back to the head, not lost",
          [(x["item"], x["state"], x.get("retries")) for x in q()] == [(2, "pending", 1), (3, "pending", None)], q())
    check("and nothing starts while the limit lasts", spawned == [1, 2])

    d.USAGE_MARK.write_text(d.iso(d.now_utc() - d.timedelta(hours=2))); d.drain_fix_queues()
    check("once the limit has passed, the interrupted fix runs again", spawned == [1, 2, 2])

    del_ = d.load_q("my-web-app"); del_["paused"] = True; d.save_q("my-web-app", del_)
    finish(2, "pr"); d.drain_fix_queues()
    check("a paused queue finishes what is running but starts nothing new",
          spawned == [1, 2, 2] and [x["item"] for x in q()] == [3], (spawned, q()))

    _, queued, skipped = d.enqueue("qp", [3, 2, 4])
    check("queuing again skips what is queued or already has a PR",
          queued == [4] and {x["item"]: x["why"] for x in skipped}.keys() == {3, 2}, (queued, skipped))

    (d.PANELS / "qp2.json").write_text(_json.dumps(
        {"id": "qp2", "project": "my-web-app", "discipline": "design", "status": "done",
         "subject": "components/", "started": "2026-09-24", "ruling": ruling}))
    try:
        d.enqueue("qp", [5]); refused = False
    except ValueError:
        refused = True
    check("items from a superseded panel cannot be queued", refused)

    # related items (same area of the ruling) go out as one batch, one PR
    d.save_q("my-web-app", {"paused": True, "items": []})
    (d.PANELS / "qb.json").write_text(_json.dumps(
        {"id": "qb", "project": "my-web-app", "discipline": "design", "status": "done",
         "subject": "lib/", "started": "2026-09-24",
         "ruling": [{"title": "t1", "area": "copy"}, {"title": "t2", "area": "a11y"},
                    {"title": "t3", "area": "copy"}]}))
    _, queued, skipped = d.enqueue("qb", [1, 2, 3])
    (d.PANELS / "qz.json").write_text(_json.dumps(
        {"id": "qz", "project": "my-web-app", "discipline": "design", "status": "done",
         "subject": "zz/", "started": "2026-09-24",
         "ruling": [{"title": "u1"}, {"title": "u2", "area": ""}]}))
    d.enqueue("qz", [1, 2])
    check("items with no area are never batched together",
          [x["items"] for x in q() if x["panel"] == "qz"] == [[1], [2]], q())
    d.save_q("my-web-app", {"paused": True, "items": [x for x in q() if x["panel"] != "qz"]})
    check("items sharing an area are queued as one batch",
          [x["items"] for x in q()] == [[1, 3], [2]] and q()[0]["title"].startswith("copy: 2 fixes"), q())
    _, queued, skipped = d.enqueue("qb", [3])
    check("an item already queued inside a batch is not queued again",
          queued == [] and skipped[0]["why"] == "already queued", skipped)
    before = len(spawned)
    d.save_q("my-web-app", {**d.load_q("my-web-app"), "paused": False}); d.drain_fix_queues()
    check("a batch starts as one fix of all its items", spawned[before:] == [(1, 3)], spawned[before:])
    # labelling dropped item 1 as a decision; item 3 got the PR; a limit was hit after
    (d.FIXES / "qb-3.json").write_text(_json.dumps({"project": "my-web-app", "panel": "qb", "item": 3, "status": "pr"}))
    d.USAGE_MARK.write_text(d.iso(d.now_utc() + d.timedelta(seconds=5))); d.drain_fix_queues()
    check("a batch done under a later member is not retried", all(x.get("items") != [1, 3] for x in q()), q())
    d.USAGE_MARK.unlink()
    d.save_q("my-web-app", {"paused": False, "items": []})

    # only a change is ever queued; a decision has nothing to build
    (d.PANELS / "qd.json").write_text(_json.dumps(
        {"id": "qd", "project": "my-web-app", "discipline": "design", "status": "done",
         "subject": "src/", "started": "2026-09-25",
         "ruling": [{"title": "keep X", "kind": "decision"}, {"title": "fix Y", "kind": "change"}]}))
    _, queued, skipped = d.enqueue("qd", [1, 2])
    check("a decision is skipped, a change is queued", queued == [2] and skipped[0]["item"] == 1, (queued, skipped))

    # the daily budget holds automatic work, and only automatic work
    d.save_q("my-web-app", {"paused": False, "items": [{"panel": "qd", "item": 2, "title": "fix Y",
                                                  "state": "pending", "queued": d.iso(d.now_utc())}]})
    d.SPEND.write_text(_json.dumps({"at": d.iso(d.now_utc()), "cost": 12.5}) + "\n")
    _os.environ["QUARTERDECK_DAILY_BUDGET"] = "10"
    before = len(spawned); d.drain_fix_queues()
    check("over the daily budget, the queue starts nothing", len(spawned) == before and d.over_budget())
    _os.environ["QUARTERDECK_DAILY_BUDGET"] = "20"; d.drain_fix_queues()
    check("under it, the queue carries on", len(spawned) == before + 1 and not d.over_budget())
    d.SPEND.write_text(_json.dumps({"at": d.iso(d.now_utc() - d.timedelta(days=2)), "cost": 99}) + "\n")
    _os.environ["QUARTERDECK_DAILY_BUDGET"] = "10"
    check("yesterday's spend does not count against today", not d.over_budget())
finally:
    if _budget_env is None:
        _os.environ.pop("QUARTERDECK_DAILY_BUDGET", None)
    else:
        _os.environ["QUARTERDECK_DAILY_BUDGET"] = _budget_env
    for k, v in _saved.items():
        setattr(d, k, v)

# ---- the HTTP boundary ---------------------------------------------------------
def _handler(headers):
    h = d.Handler.__new__(d.Handler)
    h.headers = headers
    return h
check("a loopback Host is served", _handler({"Host": "127.0.0.1:7878"})._local_host()
      and _handler({"Host": "localhost:7878"})._local_host())
check("any other Host is refused, reads included (DNS rebinding)",
      not _handler({"Host": "evil.example:7878"})._local_host() and not _handler({})._local_host())
check("an id with a traversal in it is refused",
      d.valid_id("my-web-app-design-1790122096") and not d.valid_id("..") and not d.valid_id("a/b")
      and not d.valid_id(7))

# board.py is imported by the dashboard: a failed gh call must be an exception
# the server can answer with, never a SystemExit that stops it
import importlib.util as _ilu, subprocess as _sp
_spec = _ilu.spec_from_file_location("board", ROOT / "bin" / "board.py")
_board = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_board)
_board.subprocess = type("S", (), {"run": staticmethod(
    lambda *a, **k: _sp.CompletedProcess(a, 1, "", "boom"))})
try:
    _board.gh("api", "x"); raised = None
except BaseException as e:
    raised = e
check("a failed gh call in board.py raises, it does not exit",
      isinstance(raised, Exception) and not isinstance(raised, SystemExit), repr(raised))
# ---- an item's status is read back from GitHub ----------------------------------
_rul = {"np": [{"title": f"t{i}"} for i in range(1, 7)]}
_fx = {"np#1": {"panel": "np", "item": 1, "status": "blocked", "issue": 273, "pr": None},
       "np#2": {"panel": "np", "item": 2, "status": "pr", "issue": 280, "pr": "u/280"},
       "np#3": {"panel": "np", "item": 3, "status": "running", "issue": 290, "pr": None},
       "np#4": {"panel": "np", "item": 4, "status": "pr", "issue": None, "pr": "u/300"},
       "np#6": {"panel": "np", "item": 6, "status": "pr", "issue": None, "pr": "u/310"}}
_prs = [{"number": 284, "url": "u/284", "state": "OPEN", "body": "Closes #273",
         "closingIssuesReferences": [{"number": 273}]},
        {"number": 280, "url": "u/280", "state": "MERGED", "mergedAt": "2026-09-24T08:00:00Z", "body": "",
         "closingIssuesReferences": [{"number": 280}]},
        {"number": 291, "url": "u/291", "state": "MERGED", "body": "", "closingIssuesReferences": [{"number": 290}]},
        {"number": 282, "url": "u/282", "state": "OPEN", "body": "Fixes np#5. Design ruling items 1, 2, 3",
         "closingIssuesReferences": []},
        {"number": 300, "url": "u/300", "state": "CLOSED", "body": "", "closingIssuesReferences": []},
        {"number": 310, "url": "u/310", "state": "OPEN", "body": "", "closingIssuesReferences": []}]
_got = d.reconcile_fixes("my-web-app", _prs, _rul, _fx)
check("a PR closing the item's issue links it, even if the pipeline never did",
      _got.get("np#1", {}).get("pr") == "u/284" and _got["np#1"]["status"] == "pr", _got.get("np#1"))
check("a merged PR marks the item fixed", _got.get("np#2", {}).get("status") == "merged", _got.get("np#2"))
check("a running fix is left to write its own record", "np#3" not in _got)
check("a PR closed unmerged makes the item fixable again", _got.get("np#4", {}).get("status") == "closed")
check("a hand fix naming <panel>#<n> gets a record of its own",
      _got.get("np#5", {}).get("pr") == "u/282" and _got["np#5"]["title"] == "t5", _got.get("np#5"))
check("item numbers in prose are not read", set(_got) == {"np#1", "np#2", "np#4", "np#5"}, sorted(_got))
check("nothing is rewritten when GitHub agrees with the record", "np#6" not in _got)
_got2 = d.reconcile_fixes("my-web-app", [{"number": 9, "url": "u/9", "state": "MERGED",
                                    "body": "see xnp#6 and x-np#6", "closingIssuesReferences": []}], _rul, {})
check("a panel id is only read as a whole word", _got2 == {}, _got2)

# ---- starting work from a board card -------------------------------------------
# /api/work is a loopback POST that ends in a subprocess, so it gets the same
# treatment as /api/run: what it refuses is asserted, and nothing is spawned.
import json
import tempfile

_tmp = Path(tempfile.mkdtemp())
(_tmp / "p.json").write_text(json.dumps({
    "full": {"duties": ["shipwright", "panel", "purser"]},
    "nobuild": {"duties": ["panel", "purser"]}}))
_saved = (d.PROJECTS_FILE, d._spawn_fix, d.spawn_run, d.running_locks, d.load_q, d.FIXES)
_calls = []
d.PROJECTS_FILE = _tmp / "p.json"
d._spawn_fix = lambda project, args, what, source: _calls.append(("fix", project, args))
d.spawn_run = lambda project, duty, args, apply_=False, source="dashboard": (
    _calls.append((duty, project, args, apply_)) or "ok")
d.running_locks = lambda: {}
d.load_q = lambda project: {"items": []}
d.FIXES = _tmp / "fixes"; d.FIXES.mkdir()


def work_refused(*a):
    n = len(_calls)
    try:
        d.start_work(*a)
        return False
    except ValueError:
        return len(_calls) == n          # refused AND nothing was spawned


d.start_work("full", 247, "start")
check("start runs `fix --issue` for that issue", _calls[-1:] == [("fix", "full", ["--issue", "247"])], _calls)
d.start_work("full", 247, "analyse")
check("analyse runs the purser, writing", _calls[-1:] == [("purser", "full", ["--issue", "247"], True)], _calls)
check("an unknown project is refused", work_refused("nope", 1, "start"))
check("an issue must be a plain positive number",
      all(work_refused("full", i, "start") for i in ("247", "1;rm", True, 0, -3, 10**8, None, 2.5)))
check("only the two known actions are accepted", work_refused("full", 1, "delete") and work_refused("full", 1, None))
check("start needs the builder and the planner enabled", work_refused("nobuild", 1, "start"))
(d.FIXES / "issue-1.json").write_text(json.dumps({"panel": "issue", "item": 1, "issue": 1, "status": "running"}))
check("start is refused while this exact issue is already being fixed", work_refused("full", 1, "start"))
check("a different issue on the same project is not held up by it",
      not work_refused("full", 2, "start"))
(d.FIXES / "issue-1.json").unlink()
# The queue processing something else on this project is no reason to refuse —
# only the same issue already running is.
d.load_q = lambda project: {"items": [{"state": "active"}]}
check("a busy queue on the same project does not block a direct start", not work_refused("full", 3, "start"))
d.PROJECTS_FILE, d._spawn_fix, d.spawn_run, d.running_locks, d.load_q, d.FIXES = _saved

# ---- which column is which ---------------------------------------------------
_bs = importlib.util.spec_from_file_location("board", ROOT / "bin" / "board.py")
b = importlib.util.module_from_spec(_bs)
_bs.loader.exec_module(b)
_std = ["Backlog", "Ready", "In progress", "In review", "Done"]
check("columns are found by meaning on the usual board",
      [b.column(_std, m) for m in ("todo", "ready", "doing", "review", "done")] == _std)
_alt = ["Triage", "Doing", "Shipped"]
check("a board with other names still resolves",
      (b.column(_alt, "todo"), b.column(_alt, "doing"), b.column(_alt, "done")) == ("Triage", "Doing", "Shipped"))
check("a column that cannot be identified is empty, never guessed",
      b.column(_alt, "ready") == "" and b.column(_alt, "review") == "")
check("the registry's name wins over matching", b.column(_std, "ready", {"ready": "Up next"}) == "Up next")
check("a column can be named outright, and a missing one is empty",
      b.column(_std, "in review") == "In review" and b.column(_std, "Nope") == "")

# ---- the crew ----------------------------------------------------------------
crew = d.crew_list()
bare = [c["name"] for c in crew if not (c["discipline"] and c["seat"] and c["bias"])]
check("every crew file declares a panel, a seat and a bias", not bare, ", ".join(bare))

# Derived from the crew files, not a list kept here — a new discipline should
# be checked the moment someone adds it, not the moment someone remembers to.
# "chair" is the dockmaster's own and is a seat of one by design. "supply" and "deck" are the one seat each of the quartermaster and the
# bosun, and "infra" the one seat of the rigger: the voice of a single duty, not a panel.
disciplines = sorted({d for c in crew for d in c["panels"]} - {"chair", "supply", "deck", "infra"})
for disc in disciplines:
    seats = [c["name"] for c in crew if disc in c["panels"]]
    check(f"the {disc} panel has at least two seats", len(seats) >= 2, seats)

check("the dockmaster exists to chair a panel",
      any(c["name"] == "dockmaster" for c in crew))

# ---- mission drafts: the only writes are create / update / link, nothing else --
_mtmp = pathlib.Path(tempfile.mkdtemp())
_msaved = (d.MISSIONS_FILE, d.PANELS, d.PROJECTS_FILE, d.SPEND)
d.MISSIONS_FILE = _mtmp / "missions.json"
d.PANELS = _mtmp / "panels"; d.PANELS.mkdir()
d.PROJECTS_FILE = _mtmp / "projects.json"
d.PROJECTS_FILE.write_text(_json.dumps({"my-web-app": {"duties": ["panel", "shipwright", "gadgeteer"]}}))
d.SPEND = _mtmp / "spend.jsonl"
d.SPEND.write_text("\n".join(_json.dumps(r) for r in [
    {"project": "my-web-app", "duty": "shipwright", "cost": 2.0}, {"project": "my-web-app", "duty": "shipwright", "cost": 4.0},
    {"project": "side-app", "duty": "shipwright", "cost": 99},   # a different project's history must not leak in
]) + "\n")
(d.PANELS / "p1.json").write_text("{}")


def mact_refused(*a):
    before = d.load_missions()
    try:
        d.mission_act(*a)
        return False
    except ValueError:
        return d.load_missions() == before      # refused AND nothing written


check("an unregistered project is refused", mact_refused("create", {"project": "nope", "objective": "x"}, "test"))
check("a plan whose spoken objective is over 2000 characters is refused, nothing written",
      mact_refused("create", {"project": "my-web-app", "objective": "offline mode " * 200}, "helm"))
_rcalls, _lp = [], d.subprocess.Popen
d.subprocess.Popen = lambda *a_, **k: _rcalls.append(a_[0]) or None
_lg0 = d.LOGS; d.LOGS = _mtmp / "logs"
try:
    d.spawn_run("my-web-app", "panel", ["--panel", "spec", "--idea", "offline mode"])
    d.spawn_run("my-web-app", "panel", ["--panel", "spec", "--idea", "offline mode"], apply_=False)
finally:
    d.subprocess.Popen, d.LOGS = _lp, _lg0
check("the spec panel Helm offers runs as 'quarterdeck run <project> panel --panel spec --idea <words>', never with --apply",
      len(_rcalls) == 2 and _rcalls[0][1:] == ["run", "my-web-app", "panel", "--panel", "spec", "--idea", "offline mode"]
      and "--apply" not in _rcalls[0], _rcalls)
def _vr(*a):
    try:
        d.validate_run(*a)
        return False
    except ValueError:
        return True
check("helm run is refused for an unknown duty, a duty not enabled for the project, an unknown project and a shell value",
      _vr("my-web-app", "nonesuch", []) and _vr("my-web-app", "surveyor", []) and _vr("nope", "panel", [])
      and _vr("my-web-app", "panel", ["--idea", "$(reboot)"]) and not _vr("my-web-app", "panel", ["--panel", "spec", "--idea", "offline mode"]))
check("an empty objective is refused", mact_refused("create", {"project": "my-web-app", "objective": "  "}, "test"))
m = d.mission_act("create", {"project": "my-web-app", "objective": "Improve onboarding", "constraints": "no schema changes"}, "owner")
check("a created draft is persisted, not just returned",
      d.load_missions() and d.load_missions()[0]["id"] == m["id"], d.load_missions())
check("a fresh draft starts empty of links, with one creation event",
      m["status"] == "draft" and m["links"]["panels"] == [] and len(m["events"]) == 1)
check("an unknown mission id is refused", mact_refused("update", {"id": "nope", "objective": "x"}, "test"))
d.mission_act("update", {"id": m["id"], "objective": "Improve onboarding accessibility"}, "owner")
check("an edit updates the record and logs an event",
      d.load_missions()[0]["objective"] == "Improve onboarding accessibility" and len(d.load_missions()[0]["events"]) == 2)
check("clearing the objective on edit is refused, the old one survives",
      mact_refused("update", {"id": m["id"], "objective": ""}, "test")
      and d.load_missions()[0]["objective"] == "Improve onboarding accessibility")
check("linking a panel that does not exist is refused", mact_refused("link", {"id": m["id"], "panel": "ghost"}, "test"))
check("a path smuggled in as a panel id is refused", mact_refused("link", {"id": m["id"], "panel": "../../etc/passwd"}, "test"))
d.mission_act("link", {"id": m["id"], "panel": "p1"}, "owner")
d.mission_act("link", {"id": m["id"], "panel": "p1"}, "owner")   # linking twice is a no-op, not two entries
check("linking a real panel records it once, however often it is clicked",
      d.load_missions()[0]["links"]["panels"] == ["p1"])

check("approving before a plan exists is refused", mact_refused("approve_plan", {"id": m["id"], "revision": 0}, "test"))
plan = d.mission_act("propose_plan", {"id": m["id"]}, "owner")["plan"]
check("a plan has one step per registered duty, in the project's own order",
      [s["duty"] for s in plan] == ["panel", "shipwright", "gadgeteer"], plan)
check("a step's cost estimate is scoped to this project and duty, not the fleet",
      plan[1]["cost_estimate"] == {"avg": 3.0, "n": 2}, plan[1])
check("a duty with no spend history yet shows an honest unknown, not a guessed number",
      plan[0]["cost_estimate"] is None)
check("a duty this table does not know is unclassified, not silently guessed",
      plan[2]["permission"] == "unclassified")
check("approving the wrong revision is refused",
      mact_refused("approve_plan", {"id": m["id"], "revision": 0}, "test"))
d.mission_act("approve_plan", {"id": m["id"], "revision": 1}, "owner")
check("approving the current revision records it",
      d.load_missions()[0]["plan_approved_revision"] == 1)

# A second, disposable mission, so exercising start_panel (which moves a
# mission past "draft" for good) does not disturb m's own remaining checks.
_saved_spawn_run = d.spawn_run
_spawn_calls = []
d.spawn_run = lambda project, duty, args, apply_=False, source="dashboard", mission=None: (
    _spawn_calls.append((project, duty, args, apply_, source, mission)) or "ok")
m2 = d.mission_act("create", {"project": "my-web-app", "objective": "Ship the export button",
                              "constraints": "no new dependencies"}, "owner")
check("starting a mission with no plan at all is refused", mact_refused("start_panel", {"id": m2["id"]}, "test") and not _spawn_calls)
d.mission_act("propose_plan", {"id": m2["id"]}, "owner")
check("starting before the plan is approved is refused",
      mact_refused("start_panel", {"id": m2["id"]}, "test") and not _spawn_calls)
d.mission_act("approve_plan", {"id": m2["id"], "revision": 1}, "owner")
d.mission_act("start_panel", {"id": m2["id"]}, "owner")
check("starting spawns a spec panel seeded with the objective and constraints",
      _spawn_calls and _spawn_calls[0][:2] == ("my-web-app", "panel")
      and _spawn_calls[0][2][:3] == ["--panel", "spec", "--idea"]
      and "Ship the export button" in _spawn_calls[0][2][3]
      and "no new dependencies" in _spawn_calls[0][2][3],
      _spawn_calls)
check("starting is a real write, not a dry run", _spawn_calls[0][3] is True)
check("the run is tagged with this exact mission, so the ledger can find it back",
      _spawn_calls[0][5] == m2["id"])
check("a started mission is no longer a draft", d.load_missions()[-1]["status"] == "started")
check("starting an already-started mission is refused", mact_refused("start_panel", {"id": m2["id"]}, "test"))
d.spawn_run = _saved_spawn_run

d.mission_act("update", {"id": m["id"], "constraints": "changed my mind"}, "owner")
check("editing an approved draft invalidates that approval",
      d.load_missions()[0]["plan_approved_revision"] is None
      and d.load_missions()[0]["events"][-2]["kind"] == "approval-invalidated")

_items = d.load_missions(); _items[0]["status"] = "closed"; d.save_missions(_items)
check("a mission that is no longer a draft cannot be edited",
      mact_refused("update", {"id": m["id"], "objective": "y"}, "test"))
check("a closed mission cannot get a new plan either",
      mact_refused("propose_plan", {"id": m["id"]}, "test"))
d.MISSIONS_FILE, d.PANELS, d.PROJECTS_FILE, d.SPEND = _msaved

# ---- the needs-you inbox: deduplicated, and resolved by a later success ------
_itmp = pathlib.Path(tempfile.mkdtemp())
_isaved = d.INBOX_ACK_FILE
d.INBOX_ACK_FILE = _itmp / "inbox_ack.json"

FRESH = d.iso(d.now_utc() - d.timedelta(hours=1))
STALE = d.iso(d.now_utc() - d.timedelta(hours=30))
lbp = {("my-web-app", "shipwright"): {"project": "my-web-app", "verdict": "ERROR", "detail": "boom", "at": FRESH},
       ("my-web-app", "inspector"): {"project": "my-web-app", "verdict": "PROVEN", "detail": "ok", "at": FRESH},
       ("side-app", "surveyor"): {"project": "side-app", "verdict": "BLOCKED", "detail": "old", "at": STALE}}
items = d.inbox_items(lbp)
check("a failing duty appears", any(i["source"] == "local" and i["duty"] == "shipwright" for i in items), items)
check("a duty whose newest run succeeded does not appear, even with older failures on record",
      not any(i["duty"] == "inspector" for i in items))
check("a failure older than 24h does not appear", not any(i["duty"] == "surveyor" for i in items))

_lid = "local:my-web-app:shipwright:" + FRESH
d.inbox_act("acknowledge", {"id": _lid, "text": "boom"}, "owner")
check("acknowledging hides that exact item", next(i for i in d.inbox_items(lbp) if i["id"] == _lid)["acknowledged"])

def iact_refused(*a):
    before = d.load_inbox_ack()
    try:
        d.inbox_act(*a)
        return False
    except ValueError:
        return d.load_inbox_ack() == before


check("only acknowledge is a real action here", iact_refused("resolve", {"id": "x"}, "test"))
check("acknowledging nothing is refused", iact_refused("acknowledge", {"id": ""}, "test"))
d.INBOX_ACK_FILE = _isaved

# ---- the showcase publishing boundary -----------------------------------------
_stmp = pathlib.Path(tempfile.mkdtemp())
_ssaved = d.SHOWCASE_FILE
d.SHOWCASE_FILE = _stmp / "showcase.json"


def sact_refused(*a):
    before = d.load_showcase()
    try:
        d.showcase_act(*a)
        return False
    except ValueError:
        return d.load_showcase() == before


check("an empty title is refused", sact_refused("create", {"title": " "}, "test"))
check("a draft is private by default", d.public_showcase() == [])
s = d.showcase_act("create", {"title": "Onboarding, made accessible", "summary": "sum",
                              "before": "no aria", "after": "aria-modal", "role": "chose the scope",
                              "mission_id": "m-x", "synthetic": True}, "owner")
check("an unpublished draft never appears in the public payload", d.public_showcase() == [])
d.showcase_act("publish", {"id": s["id"]}, "owner")
check("publishing requires the explicit action, and only then appears publicly", len(d.public_showcase()) == 1)
pub = d.public_showcase()[0]
check("the public payload is exactly the approved allowlist, nothing else — the actual leak guard",
      set(pub.keys()) == set(d.PUBLIC_SHOWCASE_FIELDS), pub.keys())
check("mission_id and every private/internal field stay off the public payload",
      "mission_id" not in pub and "events" not in pub and "created_at" not in pub)
check("synthetic content is labeled on the public payload, not silently indistinguishable from real work",
      pub["synthetic"] is True)
check("a published item can no longer be edited directly", sact_refused("update", {"id": s["id"], "title": "y"}, "test"))
d.showcase_act("unpublish", {"id": s["id"]}, "owner")
check("unpublishing removes it from the public payload immediately", d.public_showcase() == [])
d.showcase_act("update", {"id": s["id"], "title": "Onboarding, made accessible (v2)"}, "owner")
check("a draft again can be edited again", d.load_showcase()[0]["title"].endswith("(v2)"))
d.showcase_act("publish", {"id": s["id"]}, "owner")
check("publishing an already-published item is refused", sact_refused("publish", {"id": s["id"]}, "test"))
d.SHOWCASE_FILE = _ssaved

# ---- F09: a verdict names its revision, and a later push outdates it ----------
check("same revision, no news", not d.verdict_outdated("abc123", "abc123"))
check("a later push outdates the verdict", d.verdict_outdated("abc123", "def456"))
check("an older row with no recorded revision is unknown, never guessed outdated",
      not d.verdict_outdated(None, "def456"))
check("gh not returning a head is unknown too, not a false outdated",
      not d.verdict_outdated("abc123", None))

_run_calls = []


def _fake_run(argv, **kw):
    _run_calls.append(argv)
    prs = [{"number": 42, "title": "t", "url": "https://github.com/x/my-web-app/pull/42",
            "headRefName": "b", "headRefOid": "NEWSHA", "createdAt": "2026-01-01T00:00:00Z",
            "isDraft": False, "body": "", "closingIssuesReferences": [], "reviewDecision": "",
            "statusCheckRollup": [], "additions": 1, "deletions": 1, "changedFiles": 1}]
    return type("R", (), {"returncode": 0, "stdout": json.dumps(prs), "stderr": ""})()


_runs_fixture = [
    {"project": "my-web-app", "duty": "surveyor", "verdict": "CLEAN", "detail": "#42", "sha": "OLDSHA", "at": "t"},
    {"project": "my-web-app", "duty": "inspector", "verdict": "PROVEN", "detail": "#42 — checked", "sha": "NEWSHA", "at": "t"},
]
_psaved = (d.subprocess.run, d.PR_CACHE)
d.subprocess.run = _fake_run
d.PR_CACHE = {}
prs, _ = d.open_prs("my-web-app", "x/my-web-app", _runs_fixture, {})
d.subprocess.run, d.PR_CACHE = _psaved
check("gh is asked for the head revision so it can be compared at all",
      "headRefOid" in _run_calls[0][_run_calls[0].index("--json") + 1])
check("a review recorded against an old commit is marked outdated once the PR moved on",
      prs[0]["review"]["outdated"] is True, prs[0]["review"])
check("a verify recorded against the PR's current head is not outdated",
      prs[0]["verify"]["outdated"] is False, prs[0]["verify"])

# ---- merging a pull request from the dashboard ---------------------------------
# The one write in this system a human makes directly rather than a duty
# proposing it — every guardrail tells the crew never to merge; this checks
# the harness side of that human decision, never the model's.
_mtmp = pathlib.Path(tempfile.mkdtemp())
(_mtmp / "p.json").write_text(json.dumps({"my-web-app": {"repo": "ajmujaa/my-web-app"}, "norepo": {}}))
_merge_calls = []
def _fake_merge_run(argv, **kw):
    _merge_calls.append(argv)
    return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
_msaved = (d.subprocess.run, d.PR_CACHE, d.STATE, d.PROJECTS_FILE)
d.subprocess.run = _fake_merge_run
d.PR_CACHE = {"ajmujaa/my-web-app": {"at": 0, "prs": []}}
d.STATE = _mtmp
d.PROJECTS_FILE = _mtmp / "p.json"


def merge_refused(*a):
    n = len(_merge_calls)
    try:
        d.merge_pr(*a)
        return False
    except ValueError:
        return len(_merge_calls) == n          # refused AND nothing was called


check("an unknown project is refused, nothing called", merge_refused("nope", 1, "a" * 40))
check("a project with no repo configured is refused", merge_refused("norepo", 1, "a" * 40))
check("a smuggled pull request number is refused",
      all(merge_refused("my-web-app", x, "a" * 40) for x in ("1;rm", True, 0, -3, 10 ** 8, None, 2.5)))
check("a value that is not a real commit sha is refused",
      all(merge_refused("my-web-app", 1, x) for x in ("not-a-sha", "", None, "'; rm -rf /'")))

d.merge_pr("my-web-app", 42, "a" * 40)
argv = _merge_calls[-1]
check("a real merge asks gh to merge, pinned to the exact commit the button showed",
      argv[:3] == ["gh", "pr", "merge"]
      and argv[argv.index("--match-head-commit") + 1] == "a" * 40, argv)
check("merging deletes the branch, the same cleanup every fix pipeline PR gets",
      "--delete-branch" in argv and "--merge" in argv)
check("a merge writes its own ledger row, like every other write here",
      d.read_json(d.STATE / "runs.json", [])[-1]["verdict"] == "MERGED")
check("the PR cache is dropped so the next poll doesn't still show it open",
      "ajmujaa/my-web-app" not in d.PR_CACHE)

d.subprocess.run = lambda argv, **kw: type(
    "R", (), {"returncode": 1, "stdout": "", "stderr": "expected the SHA to match, but it changed"})()
try:
    d.merge_pr("my-web-app", 42, "a" * 40); _raised = None
except ValueError as e:
    _raised = e
check("gh refusing the merge (a push since the button was drawn) surfaces its own reason",
      _raised is not None and "expected the SHA" in str(_raised), _raised)

d.subprocess.run, d.PR_CACHE, d.STATE, d.PROJECTS_FILE = _msaved

# The brain view shows what other tools drop in state/connectors/. Quarterdeck holds no
# login for any of it, so that file is data from outside and is cleaned on the way in.
import json as _json, tempfile as _tf
_bsaved = d.CONNECTORS
d.CONNECTORS = Path(_tf.mkdtemp()) / "connectors"; d.CONNECTORS.mkdir()
(d.CONNECTORS / "gmail.json").write_text(_json.dumps({
    "updated": "2026-01-01T00:00:00Z", "unread": 3,
    "items": [{"title": "x" * 500, "url": "javascript:alert(1)", "new": True},
              {"title": "ok", "url": "https://mail.google.com/x", "new": "yes"}, "junk"] + [{"title": "n"}] * 20}))
(d.CONNECTORS / "slack.json").write_text(_json.dumps({"unread": "many", "items": "nope"}))
(d.CONNECTORS / "drive.json").write_text("not json")
_bc = {c["name"]: c for c in d.brain_connectors()}
check("a connector with no snapshot is shown as not connected, never guessed",
      _bc["calendar"] == {"name": "calendar", "label": "Calendar", "connected": False}
      and _bc["drive"]["connected"] is False)
check("a snapshot's strings are clipped and its items capped",
      len(_bc["gmail"]["items"]) <= 12 and len(_bc["gmail"]["items"][0]["title"]) == 140)
check("only https links survive, so a snapshot cannot plant a javascript: link",
      _bc["gmail"]["items"][0]["url"] is None and _bc["gmail"]["items"][1]["url"] == "https://mail.google.com/x")
check("'new' must be exactly true and unread exactly an integer",
      _bc["gmail"]["items"][1]["new"] is False and _bc["gmail"]["unread"] == 3
      and _bc["slack"]["unread"] is None and _bc["slack"]["items"] == [])
_ev = lambda t, at, sub="": {"title": t, "sub": sub, "at": at, "new": False}
_cal = [_ev("Standup", "2026-10-05T07:30:00Z", "Mon 09:30 · Work A"), _ev("  standup ", "2026-10-05T07:30:00Z", "Mon 09:30 · Work B"),
        _ev("Planning", "2026-10-05T09:00:00Z", "Mon 11:00 · Work A"), _ev("Planning", "2026-10-05T10:00:00Z", "Mon 12:00 · Work A"),
        _ev("Offsite", "2026-10-05T00:00:00Z", "Mon 5 Oct, all day · Work A"), _ev("Offsite", "2026-10-05T00:00:00Z", "Mon 09:00 · Work B"),
        _ev("Offsite", "2026-10-05T00:00:00Z", "Mon 5 Oct, all day · Work B"), _ev("Retro", "2026-10-06T08:00:00Z", "Tue 10:00 · A"),
        _ev("Retro", "2026-10-06T08:00:00Z", "Tue 10:00 · B"), _ev("Retro", "2026-10-06T08:00:00Z", "Tue 10:00 · C")]
_cal += [_ev(f"Distinct {i}", f"2026-10-0{7 + i % 2}T{8 + i}:00:00Z") for i in range(10)]     # 20 raw items, 16 distinct
(d.CONNECTORS / "calendar.json").write_text(_json.dumps({"updated": "2026-10-05T06:00:00Z", "items": _cal}))
_ci = next(c for c in d.brain_connectors() if c["name"] == "calendar")["items"]
_t = lambda title: [i for i in _ci if i["title"].strip().lower() == title]
check("calendar: the same event on two calendars is one item, saying so, whatever the case or spacing of its title",
      len(_t("standup")) == 1 and _t("standup")[0]["sub"] == "Mon 09:30 · Work A · on 2 calendars" and len(_t("retro")) == 1 and _t("retro")[0]["sub"].endswith("on 3 calendars"))
check("calendar: different start times are never merged, and an all-day event is never merged with a timed one",
      len(_t("planning")) == 2 and len(_t("offsite")) == 2 and any("all day" in i["sub"] and "on 2 calendars" in i["sub"] for i in _t("offsite"))
      and any("all day" not in i["sub"] and "calendars" not in i["sub"] for i in _t("offsite")))
check("calendar: duplicates are removed before the 12 item cap, so the card shows more distinct events",
      len(_ci) == 12 and len({(i["title"].strip().lower(), i["at"], "all day" in i["sub"]) for i in _ci}) == 12 and [i["title"] for i in _ci][-1] == "Distinct 5", [i["title"] for i in _ci])
(d.CONNECTORS / "reminders.json").write_text(_json.dumps({"items": [_ev("Pay the invoice", "2026-10-05T09:00:00Z"), _ev("Pay the invoice", "2026-10-05T09:00:00Z")]}))
check("reminders are left alone: two reminders with the same title and time stay two",
      len(next(c for c in d.brain_connectors() if c["name"] == "reminders")["items"]) == 2)
# ---- the fleet timeline: every run and merge inside a window ----
_td = Path(_tf.mkdtemp()); _tsv = d.STATE
d.STATE = _td
_tn = d.now_utc(); _agoi = lambda m: d.iso(_tn - d.timedelta(minutes=m))
_rows = [{"project": "alpha", "duty": ["shipwright", "surveyor", "joiner"][i % 3], "verdict": ["PR", "ERROR", "CLEAN", "DRY-RUN"][i % 4],
          "detail": "d%d" % i, "url": "https://example.test/%d" % i if i % 7 == 0 else "javascript:alert(1)", "at": _agoi(i * 17 % 9000)} for i in range(650)]
_rows += [{"project": "beta", "duty": "dashboard", "verdict": "MERGED", "detail": "#9", "url": "https://example.test/pull/9", "at": _agoi(30)},
          {"project": "beta", "duty": "x", "verdict": "ERROR tests failed", "detail": "two", "at": _agoi(45)}, "junk", {"at": 5}, {"project": "beta", "at": "not a time"}]
(_td / "runs.json").write_text(_json.dumps(_rows))
import time as _tm
_t0 = _tm.time(); _w6, _w24, _w7 = (d.timeline_view(w) for w in ("6h", "24h", "7d")); _ms = (_tm.time() - _t0) * 1000
_ev7 = _w7["events"]
check("timeline: a window holds exactly the ledger rows inside it, newest first, plus merges, with only https links",
      len(_w6["events"]) < len(_w24["events"]) < len(_w7["events"]) and all(e["at"] >= d.iso(_tn - d.timedelta(hours=6)) for e in _w6["events"])
      and [e["at"] for e in _ev7] == sorted((e["at"] for e in _ev7), reverse=True)
      and any(e["kind"] == "merge" and e["project"] == "beta" for e in _ev7)
      and all(e["url"] is None or e["url"].startswith("https://") for e in _ev7)
      and next(e for e in _ev7 if e["detail"] == "tests failed — two")["verdict"] == "ERROR", (len(_w6["events"]), len(_w24["events"]), len(_w7["events"])))
check("timeline: junk rows and rows without a usable time are skipped, an unknown window is refused, and 650 rows are read in well under a second",
      all(isinstance(e["at"], str) and e["at"][:2] == "20" for e in _ev7) and _ms < 800 and len(_ev7) >= 600
      and all(_refused(lambda w=w: d.timeline_view(w)) for w in ("1h", "", None, "../x", "7d; rm")) and _w7["total"] == len(_ev7) and _w7["capped"] is False, (_ms, len(_ev7)))
d.STATE = _tsv
d.CONNECTORS = _bsaved

# The memory area reads Claude's memory folders on this Mac: names only, deduped through symlinks.
_mh = Path(_tf.mkdtemp()); _mm = _mh / ".claude" / "projects" / "-Users-x-Projects-Foo" / "memory"; _mm.mkdir(parents=True)
(_mm / "a.md").write_text("---\nname: A\ndescription: d\ntype: feedback\n---\nBODY-SECRET")
(_mm / "b.md").write_text("---\nname: B\nmetadata:\n  type: project\n---\n")
(_mm / "MEMORY.md").write_text("- index")
_kn = _mh / ".claude" / "projects" / "-Users-x-Projects-Foo2" / "memory"; _kn.parent.mkdir(parents=True)
_kn.symlink_to(_mm)
_mp, _mb, d._mem_cache[0] = d.Path.home, d.MEMORY_BACKUP, 0.0
d.Path.home = classmethod(lambda cls: _mh); d.MEMORY_BACKUP = _mh / "no-backup"
try:
    _mv = d.memory_view()
finally:
    d.Path.home, d.MEMORY_BACKUP, d._mem_cache[0] = _mp, _mb, 0.0
check("memory: a symlinked scope is counted once, MEMORY.md is skipped, bodies never leave the disk",
      _mv["total"] == 2 and _mv["projects"][0]["label"] == "Foo" and "BODY-SECRET" not in _json.dumps(_mv)
      and _mv["projects"][0]["types"] == {"feedback": 1, "project": 1} and _mv["backup"] is None)
check("memory: the backup is behind only when something changed over an hour ago and nothing was committed since",
      d.memory_stale(time.time() - 7200, time.time() - 9000) and not d.memory_stale(time.time() - 7200, time.time() - 60)
      and not d.memory_stale(time.time() - 60, 0) and not d.memory_stale(0, 0))

check("the brain's own script and vendored library are served with the right type",
      (d.asset_file("/assets/brain.js") or (0, 0))[1].startswith("text/javascript")
      and (d.asset_file("/assets/vendor/three.module.js") or (0, 0))[1].startswith("text/javascript"))
check("asset paths cannot climb out or name anything else",
      all(d.asset_file(x) is None for x in (
          "/assets/../bin/dashboard.py", "/assets/vendor/../../bin/dashboard.py", "/assets/%2e%2e/x.js",
          "/assets/vendor/vendor/three.core.js", "/assets/brain.html", "/assets/a/b.js", "/assets/", "/other/brain.js")))

# The head is drawn around the brain, so no part of the brain may stick out of it. The three
# ellipsoids below mirror HEMI/TEMP/CEREB in brain.js; the head is checked at its real slices.
_headjs = ROOT / "dashboard" / "assets" / "head.js" if "ROOT" in globals() else Path(__file__).resolve().parent.parent / "dashboard" / "assets" / "head.js"
_probe = """
import {headSlice, buildHead} from %r;
const B = [[-0.5,0.08,0,0.62,0.72,1.12],[0.5,0.08,0,0.62,0.72,1.12],[-0.74,-0.4,0.3,0.36,0.3,0.6],[0.74,-0.4,0.3,0.36,0.3,0.6],[0,-0.6,-0.85,0.62,0.34,0.42]];
let bad = 0;
for(const [cx,cy,cz,rx,ry,rz] of B) for(let i = 0; i < 4000; i++){
  const z = Math.random()*2-1, t = Math.random()*6.283, r = Math.sqrt(1-z*z);
  const p = [cx+r*Math.cos(t)*rx, cy+z*ry, cz+r*Math.sin(t)*rz], h = headSlice(p[1]);
  if(!h || Math.abs(p[0]) > h.w - 0.02 || p[2] > h.front - 0.02 || p[2] < h.back + 0.02) bad++;
}
const n = buildHead(() => 0.5).length / 3;
console.log(JSON.stringify({bad, n}));
""" % _headjs.as_uri()
if _nodeok.path():
    try:
        _r = _sp.run(["node", "--input-type=module", "-e", _probe], capture_output=True, text=True, timeout=30)
        _o = _json.loads(_r.stdout.strip().splitlines()[-1]) if _r.returncode == 0 and _r.stdout.strip() else {"bad": -1, "n": 0}
    except _sp.TimeoutExpired:
        _o = {"bad": -1, "n": 0}
    check("the brain fits entirely inside the head, and the head has points", _o["bad"] == 0 and _o["n"] > 5000)
else:
    print("  skipped: the brain-inside-the-head check (node not on PATH)")

# ---- reliability: loops survive, health tells the truth, bad state never 500s ---
import json as _rj, os as _ros
_rtmp = pathlib.Path(tempfile.mkdtemp())
_rsaved = d.relocate_state(_rtmp / "state")
(_rtmp / "state").mkdir()
d.LOGS.mkdir()


class _Halt(BaseException):
    pass


def _run_loop(step, passes):
    seen = []
    clk = [0.0]
    def nap(secs):
        seen.append(secs)
        clk[0] += secs
        if len(seen) >= passes:
            raise _Halt
    try:
        d.run_loop("probe", 10, step, sleep=nap, clock=lambda: clk[0])
    except _Halt:
        pass
    return seen


_calls = []
def _flaky():
    _calls.append(1)
    if len(_calls) < 3:
        raise RuntimeError("boom")
_naps = _run_loop(_flaky, 4)
check("a loop that raises keeps going and recovers", len(_calls) == 4 and _naps[-1] == 10, _naps)
check("a failing loop backs off, bounded", _naps[:2] == [10, 20] and max(_run_loop(lambda: 1 / 0, 12)) == d.LOOP_BACKOFF_MAX)
_log = (d.LOGS / "dashboard-server.log").read_text()
check("the loop error is logged with a timestamp",
      "ERROR probe loop: RuntimeError: boom" in _log and _log.startswith("20"))
check("a step can choose its own sleep", _run_loop(lambda: 7, 1) == [7])


def _sleepy_run(interval, jump_seconds):
    """A half-hour loop whose first wait spans a real machine sleep: the fake
    clock leaps by jump_seconds on that one tick, as if the sleep() call had
    actually taken that long in wall-clock time. Returns the ticks asked for
    and the fake-clock reading at each step() call."""
    seen, steps, clk = [], [], [0.0]
    def nap(secs):
        seen.append(secs)
        clk[0] += jump_seconds if len(seen) == 1 else secs
        if len(seen) >= 2:
            raise _Halt
    def step():
        steps.append(clk[0])
    try:
        d.run_loop("probe", interval, step, sleep=nap, clock=lambda: clk[0])
    except _Halt:
        pass
    return seen, steps


_slept, _woke = _sleepy_run(1800, 8 * 3600)
check("a loop that runs every half hour asks for one bounded tick, not the whole interval, and catches up as soon as it notices the machine slept past its deadline",
      _slept[0] == d.LOOP_TICK_MAX and len(_woke) == 2, (_slept, _woke))

d.HEARTBEAT.clear()
d.HEARTBEAT["probe"] = (time.time(), 10)
_h = d.health()
check("health is ok while every loop has beaten recently", _h["ok"] and _h["loops"]["probe"]["alive"])
d.HEARTBEAT["probe"] = (time.time() - 31, 10)
check("a loop silent for 3 intervals makes health not ok", not d.health()["ok"])
d.HEARTBEAT["probe"] = (time.time() - 29, 10)
check("a loop silent for less than 3 intervals is still alive", d.health()["ok"])
d.HEARTBEAT.clear()
check("health reports the fields and leaks no path",
      {"ok", "uptime_seconds", "commit", "loops", "writable", "disk_free_bytes",
       "last_state_build_age_seconds", "helpers"} <= set(d.health())
      and str(_rtmp) not in _rj.dumps(d.health()))
_sr = d.subprocess.run
d.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no git"))
check("a missing git gives no commit, not an error", d.git_commit() is None)
d.subprocess.run = _sr

# Every file build_state reads, corrupted every way a crash or an editor can.
_shapes = ['{"a": [1, 2', "\x00\xff garbage", "", "null", "5", '"str"', "[1,\"x\",null]", "{}", "[]",
           '[{}]', '[{"project":5,"duty":[],"at":3,"every":5}]', '{"items":[1,{"item":5}],"paused":3}',
           '{"id":5,"status":[],"ruling":"x","items":"x"}', '{"events":"x","unread":"x","items":3}']
_files = ["runs.json", "schedules.json", "missions.json", "showcase.json", "inbox_ack.json",
          "agenda-status.json", "filed.json", "usage-limit", "spend.jsonl", "capture.jsonl",
          "fixqueue/my-web-app.json", "connectors/gmail.json", "panels/p1.json", "fixes/f1.json"]
_bad = []
for _f in _files:
    for _shape in _shapes:
        _root = pathlib.Path(tempfile.mkdtemp()) / "state"
        for _sub in ("panels", "fixes", "fixqueue", "connectors"):
            (_root / _sub).mkdir(parents=True)
        _inner = d.relocate_state(_root)
        try:
            (_root / _f).write_bytes(_shape.encode("latin-1", "replace"))
            d.build_state()
        except Exception as _e:
            _bad.append(f"{_f} <- {_shape[:20]!r}: {type(_e).__name__}")
        finally:
            d.restore_state(_inner)
check(f"a corrupt state file never stops the state building ({len(_files)} files x {len(_shapes)} shapes)", not _bad, _bad[:3])
d.restore_state(_rsaved)

# ---- demo mode: a made-up world, and proof nothing real is touched while it is on ----
import ast as _ast, builtins as _bi, hashlib as _hl, http.client as _hc, json as _dj, os as _dos, subprocess as _dsp
import threading as _dth, urllib.request as _dur

_demo_src = (ROOT / "bin" / "demo.py").read_text()
_imports = {n.names[0].name.split(".")[0] if isinstance(n, _ast.Import) else n.module.split(".")[0]
            for n in _ast.walk(_ast.parse(_demo_src)) if isinstance(n, (_ast.Import, _ast.ImportFrom))}
check("demo.py imports nothing that can touch files, processes or the network", _imports <= {"json", "random", "re", "time", "datetime"}, _imports)
check("demo text has no em dashes", "—" not in _demo_src)

def _tree_print():
    """What Demo mode must never change: the registry and the state, logs and workspace folders, in the program folder and in the data folder."""
    bases = list(dict.fromkeys((ROOT, d.HOME)))
    h = "".join(_hl.sha256((b / "config" / "projects.json").read_bytes()).hexdigest() for b in bases if (b / "config" / "projects.json").is_file())
    seen = []
    for b in bases:
        for top in ("state", "logs", "workspace"):
            for dp, _, fs in _dos.walk(b / top):
                seen += [(str(Path(dp, f)), (Path(dp, f).stat().st_size, Path(dp, f).stat().st_mtime_ns)) for f in fs]
    return h, sorted(seen)

_before = _tree_print()
_real_state = d.build_state()
_real_names = {p["name"] for p in _real_state["projects"]}
_srv = d.ThreadingHTTPServer(("127.0.0.1", 0), d.Handler)
_dth.Thread(target=_srv.serve_forever, daemon=True).start()

def _call(method, path, body=None):
    c = _hc.HTTPConnection("127.0.0.1", _srv.server_address[1], timeout=20)
    try:
        c.request(method, path, _dj.dumps(body) if body is not None else None, {"X-Quarterdeck-Token": d.TOKEN, "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, _dj.loads(r.read() or b"{}")
    finally:
        c.close()

_trips = []
_PROTECTED = [str(ROOT / x) for x in ("state", "logs", "config", "workspace")] + [str(Path.home() / x) for x in (".claude", "claude-memory-backup", "Applications")]
def _guard_path(p):
    q = str(p)
    return any(q.startswith(x) for x in _PROTECTED)
_real_open, _real_popen, _real_urlopen = _bi.open, _dsp.Popen, _dur.urlopen
def _open(f, mode="r", *a, **k):
    if isinstance(f, (str, bytes, _dos.PathLike)) and (_guard_path(_dos.fsdecode(f)) or any(c in mode for c in "wax+")):
        _trips.append(("open", str(f), mode)); raise OSError("demo test: file access refused")
    return _real_open(f, mode, *a, **k)
def _popen(*a, **k):
    _trips.append(("Popen", str(a[:1]))); raise OSError("demo test: process refused")
def _urlopen(*a, **k):
    _trips.append(("urlopen", str(a[:1]))); raise OSError("demo test: network refused")
_path_ops = {n: getattr(Path, n) for n in ("read_text", "read_bytes", "write_text", "write_bytes", "mkdir", "glob", "iterdir", "open", "stat", "is_file", "is_dir", "exists")}
def _wrap(name):
    def f(self, *a, **k):
        if _guard_path(self):
            _trips.append((name, str(self))); raise OSError("demo test: path access refused")
        return _path_ops[name](self, *a, **k)
    return f

def _by(lst, key):
    return {x[key]: x for x in lst}

try:
    _on = _call("POST", "/api/demo", {"on": True, "restart": True})
    _bi.open, _dsp.Popen, _dur.urlopen = _open, _popen, _urlopen
    for _n in _path_ops:
        setattr(Path, _n, _wrap(_n))
    _st = _call("GET", "/api/state")[1]
    check("demo mode switches on and says so in the state", _on == (200, {"on": True}) and _st["demo"]["on"] is True)
    check("the demo world has 5 made-up projects and none of the real ones",
          len(_st["projects"]) == 5 and not ({p["name"] for p in _st["projects"]} & _real_names))
    _real_words = {w for p in _real_state["projects"] for w in (p["name"], p["repo"], p["summary"]) if len(w) > 3 and "quarterdeck" not in w.lower()}
    _blob = _dj.dumps([_st, _call("GET", "/api/prs")[1]])
    check("nothing from the real projects (names, repos, summaries; the tool's own name aside) appears in the demo world", not [w for w in _real_words if w in _blob], [w for w in _real_words if w in _blob])
    # the guards must actually bite, or a clean trip list proves nothing
    _canary = []
    for _try in (lambda: open(ROOT / "state" / "canary", "w"), lambda: Path(ROOT / "state" / "runs.json").read_text(), lambda: _dsp.Popen(["true"]),
                 lambda: open(_dos.devnull, "w")):
        try:
            _try()
            _canary.append("not refused")
        except OSError:
            _canary.append("refused")
    check("the test's own guards refuse a state read, a state write, a process and any write", _canary == ["refused"] * 4, _canary)
    _trips.clear()
    check("demo state has every key the real state has", set(_real_state) <= set(_st), set(_real_state) - set(_st))
    check("demo state keeps the real shape of agents, runs, projects, spend",
          set(_real_state["projects"][0]) == set(_st["projects"][0])
          and (not _real_state["agents"] or set(_real_state["agents"][0]) <= set(_st["agents"][0]))
          and set(_real_state["spend"]) == set(_st["spend"])
          and {"at", "project", "duty", "verdict", "detail", "url"} <= set(_st["runs"][0]))
    check("the ledger spans 24 hours with believable verdicts",
          len(_st["runs"]) >= 24 and {"PR", "CLEAN", "NEEDS_HUMAN", "FILED"} <= {r["verdict"] for r in _st["runs"]}
          and (d.now_utc() - d._ts(_st["runs"][-1]["at"])).total_seconds() > 20 * 3600)
    check("the demo world has panels, docs, fixes, schedules, spend and a budget",
          len(_st["panels"]) >= 3 and len(_st["docs"]) >= 3 and _st["fixes"] and _st["schedules"] and _st["spend"]["daily_budget"])
    _conn = _by(_st["connectors"], "name")
    check("connectors cover mail, calendar, reminders, Slack, analytics, LinkedIn, Facebook, Instagram",
          {"gmail", "calendar", "reminders", "slack", "analytics", "linkedin", "facebook", "instagram"} <= set(_conn)
          and all(c["connected"] and c["items"] for c in _conn.values()))
    check("memory projects and brain dump notes exist",
          _st["memory"]["total"] > 20 and _st["captures"]["open"] >= 2)
    _prs = _call("GET", "/api/prs")[1]
    check("open pull requests carry checks and a failing one", len(_prs["prs"]) >= 4 and any(p["checks"]["fail"] for p in _prs["prs"])
          and {"project", "number", "title", "url", "branch", "checks", "review", "verify", "by_quarterdeck", "closes", "size"} <= set(_prs["prs"][0]))
    _pr0 = _call("GET", "/api/progress?project=wayfarer-mobile")[1]
    check("progress, panel, doc and log answer from the made-up world",
          _pr0["total"] == len(_pr0["titles"]) and _call("GET", "/api/panel?id=" + _st["panels"][0]["id"])[1]["ruling"]
          and "text" in _call("GET", "/api/doc?name=" + _st["docs"][0]["name"])[1] and _call("GET", "/api/log?name=surveyor-wayfarer-mobile&n=20")[1]["lines"])
    check("an unknown project is refused, not read from disk", _call("GET", "/api/progress?project=my-web-app")[0] == 400)

    # every write endpoint: a believable success, a trace in the world, and nothing real touched
    mob = "wayfarer-mobile"
    check("/api/run starts a run that shows in Operations",
          _call("POST", "/api/run", {"project": mob, "duty": "trials", "args": []})[0] == 200
          and any(a["status"] == "running" and a["duty"] == "trials" and a["project"] == mob for a in _call("GET", "/api/state")[1]["agents"]))
    check("/api/run refuses a duty the project does not have", _call("POST", "/api/run", {"project": "saltpan-blog", "duty": "shipwright"})[0] == 400)
    check("/api/work starts an issue and the shipwright shows as running",
          _call("POST", "/api/work", {"project": mob, "issue": 15, "action": "start"})[0] == 200
          and any(a["status"] == "running" and a["duty"] == "shipwright" for a in _call("GET", "/api/state")[1]["agents"]))
    check("/api/work will not start the same issue twice", _call("POST", "/api/work", {"project": mob, "issue": 15, "action": "start"})[0] == 409)
    _pid = _st["panels"][1]["id"]
    _fx = _call("POST", "/api/fix", {"panel": _pid, "items": [2]})
    check("/api/fix queues an item", _fx[0] == 200 and _fx[1]["queued"] == [2] and _fx[1]["project"] == "wayfarer-web")
    check("/api/fix with nothing eligible says why", _call("POST", "/api/fix", {"panel": _pid, "items": [99]})[0] == 409)
    _cap = _call("POST", "/api/capture", {"text": "Mention the offline mode in the talk"})
    _caps = _call("GET", "/api/state")[1]["captures"]
    check("/api/capture adds a note to the brain dump", _cap[0] == 200 and any(c["text"] == "Mention the offline mode in the talk" for c in _caps["items"]))
    check("/api/capture done closes it", _call("POST", "/api/capture", {"action": "done", "id": _cap[1]["id"]})[0] == 200
          and not any(c["id"] == _cap[1]["id"] for c in _call("GET", "/api/state")[1]["captures"]["items"]))
    _id1 = _cap[1]["id"]
    _ed = _call("POST", "/api/capture", {"action": "edit", "id": _id1, "text": "  Mention offline mode   twice ", "project": "wayfarer-mobile"})
    _ro = _call("POST", "/api/capture", {"action": "reopen", "id": _id1})
    _pm = _call("POST", "/api/capture", {"action": "promote", "id": "a1b2c3d4", "to": "mission", "project": "wayfarer-mobile"})
    _pp0 = _call("POST", "/api/capture", {"action": "promote", "id": "a1b2c3d5", "to": "plan", "project": "wayfarer-mobile"})
    _pp = _call("POST", "/api/capture", {"action": "promote", "id": "a1b2c3d5", "to": "plan", "project": "wayfarer-mobile", "confirm": True})
    _stn = _call("GET", "/api/state")[1]
    check("demo notes: edit, reopen, tag and promote work on the made-up notes, with the same refusals as the real ones",
          _ed[0] == 200 and _ed[1]["text"] == "Mention offline mode twice" and _ed[1]["project"] == "wayfarer-mobile" and _ro[0] == 200
          and _call("POST", "/api/capture", {"action": "reopen", "id": _id1})[0] == 400
          and _call("POST", "/api/capture", {"action": "edit", "id": _id1, "project": "invented"})[0] == 400
          and _call("POST", "/api/capture", {"action": "edit", "id": _id1, "text": "  "})[0] == 400 and _call("POST", "/api/capture", {"action": "edit", "id": "zzzzzzzz", "text": "x"})[0] == 400
          and _call("POST", "/api/capture", {"action": "promote", "id": _id1, "to": "mission"})[0] == 400
          and _pm[0] == 200 and _pm[1]["kind"] == "mission" and any(m["objective"] == "Ask design for the empty-state illustration" for m in (_stn["missions"].values() if isinstance(_stn["missions"], dict) else _stn["missions"]))
          and _pp0[0] == 400 and "confirm" in _pp0[1]["error"] and _pp[0] == 200 and _pp[1]["kind"] == "plan"
          and _call("POST", "/api/capture", {"action": "promote", "id": _id1, "to": "plan", "project": "saltpan-blog", "confirm": True})[0] == 400, (_ed, _pm, _pp0, _pp))
    _tl6, _tl24, _tl7 = (_call("GET", "/api/timeline?window=" + w) for w in ("6h", "24h", "7d"))
    _lanes7 = {e["project"] for e in _tl7[1]["events"]}
    check("demo timeline: the same endpoint and shape as the real one, a week of history on every project, and the same refusals",
          _tl6[0] == _tl24[0] == _tl7[0] == 200 and set(_tl7[1]) == {"window", "now", "total", "capped", "events"} and len(_tl6[1]["events"]) < len(_tl24[1]["events"]) < len(_tl7[1]["events"])
          and set(d.demo.PROJECTS) <= _lanes7
          and all(set(e) == {"at", "project", "duty", "verdict", "detail", "kind", "url"} for e in _tl7[1]["events"])
          and [e["at"] for e in _tl7[1]["events"]] == sorted((e["at"] for e in _tl7[1]["events"]), reverse=True)
          and _call("GET", "/api/timeline?window=1h")[0] == 400, (len(_tl7[1]["events"]), _lanes7))
    check("demo notes: the state has the same keys as the real notes view, open and done, and a path that is not a real one",
          set(_stn["captures"]) == {"items", "open", "done", "total", "path"} and _stn["captures"]["done"] and _stn["captures"]["path"] == "state/capture.jsonl"
          and all({"id", "at", "text", "project", "done", "updated", "promoted"} <= set(n) for n in _stn["captures"]["items"] + _stn["captures"]["done"]))
    _m = _call("POST", "/api/merge", {"project": "wayfarer-web", "number": 77, "head_sha": "abcdef1"})
    _after = _call("GET", "/api/state")[1]
    check("/api/merge merges a pull request and records it in the ledger",
          _m == (200, {"merged": True, "number": 77}) and not any(p["number"] == 77 for p in _call("GET", "/api/prs")[1]["prs"])
          and any(r["verdict"] == "MERGED" for r in _after["runs"]))
    _ib = _after["inbox"][0]["id"]
    check("/api/inbox acknowledges", _call("POST", "/api/inbox", {"action": "acknowledge", "id": _ib})[0] == 200
          and next(i for i in _call("GET", "/api/state")[1]["inbox"] if i["id"] == _ib)["acknowledged"])
    _run = next(a for a in _call("GET", "/api/state")[1]["agents"] if a["status"] == "running")
    check("/api/stop stops a running agent", _call("POST", "/api/stop", {"lock": _run["lock"]})[0] == 200
          and not any(a["lock"] == _run["lock"] and a["status"] == "running" for a in _call("GET", "/api/state")[1]["agents"]))
    _mi = _call("POST", "/api/missions", {"action": "create", "project": mob, "objective": "Add a share link"})
    check("/api/missions creates a draft and walks it through a plan",
          _mi[0] == 200 and _call("POST", "/api/missions", {"action": "propose_plan", "id": _mi[1]["id"]})[0] == 200
          and _call("POST", "/api/missions", {"action": "approve_plan", "id": _mi[1]["id"], "revision": 1})[0] == 200
          and _call("POST", "/api/missions", {"action": "start_panel", "id": _mi[1]["id"]})[0] == 200
          and any(m["id"] == _mi[1]["id"] and m["status"] == "started" for m in _call("GET", "/api/state")[1]["missions"]))
    _sw = next(p for p in _st["projects"] if "surveyor" in p["duties"] and "panel" not in p["duties"])["name"]
    check("demo: every new Helm intent works against the made-up world, and refuses what it should",
          _call("POST", "/api/run", {"project": mob, "duty": "surveyor", "args": ["--pr", "12"], "apply": False})[0] == 200
          and _call("POST", "/api/run", {"project": mob, "duty": "panel", "args": ["--panel", "spec", "--idea", "offline mode"], "apply": False})[0] == 200
          and _call("POST", "/api/run", {"project": _sw, "duty": "panel", "args": []})[0] == 400
          and _call("POST", "/api/run", {"project": mob, "duty": "nonesuch", "args": []})[0] == 400
          and _call("POST", "/api/missions", {"action": "create", "project": mob, "objective": "offline mode"})[0] == 200
          and _call("POST", "/api/missions", {"action": "create", "project": mob, "objective": "x" * 2001})[0] == 400
          and _call("POST", "/api/stop", {"lock": "shipwright-nowhere"})[0] == 404)
    _dv = d.vet_intent({"intent": "run", "duty": "surveyor", "project": mob}, "run the surveyor on " + mob, {"overview"}, set(_pj_names := [p["name"] for p in _st["projects"]]),
                       {p["name"]: p["duties"] for p in _st["projects"]})
    check("demo: a model answer for a made-up project is vetted against the made-up world's duties",
          _dv == {"intent": "run", "duty": "surveyor", "project": mob})
    _sc = _call("POST", "/api/showcase", {"action": "create", "title": "Offline trips"})
    check("/api/showcase creates and publishes a draft", _sc[0] == 200 and _call("POST", "/api/showcase", {"action": "publish", "id": _sc[1]["id"]})[0] == 200)
    _sd = _call("POST", "/api/schedule", {"project": mob, "duty": "surveyor", "every": "2h"})
    check("/api/schedule creates, pauses and deletes", _sd[0] == 200
          and _call("POST", "/api/schedule", {"id": _sd[1]["id"], "toggle": True})[0] == 200
          and _call("POST", "/api/schedule", {"id": _sd[1]["id"], "delete": True})[0] == 200
          and not any(s["id"] == _sd[1]["id"] for s in _call("GET", "/api/state")[1]["schedules"]))
    check("/api/fixqueue answers", _call("POST", "/api/fixqueue", {"project": mob, "action": "pause"})[0] == 200)
    check("a path demo mode does not know is a 404, not a real handler", _call("POST", "/api/nonsense", {})[0] == 404 and _call("GET", "/api/nonsense")[0] == 404)
    _vf = _dos.environ.get("QUARTERDECK_DEMO_VOICE")
    _dos.environ["QUARTERDECK_DEMO_VOICE"] = "off"
    check("voice can be switched off in demo mode", _call("POST", "/api/understand", {"text": "what is running"})[0] == 503)
    if _vf is None:
        del _dos.environ["QUARTERDECK_DEMO_VOICE"]
    else:
        _dos.environ["QUARTERDECK_DEMO_VOICE"] = _vf

    # the real code paths refuse outright while demo is on
    def _raises(fn, *a):
        try:
            fn(*a)
            return False
        except RuntimeError as e:
            return "demo mode" in str(e)
    check("every real reader, writer and spawner refuses while demo is on",
          all(_raises(*x) for x in ((d.read_json, ROOT / "state" / "runs.json", []), (d.write_json, ROOT / "state" / "x.json", {}),
                                    (d.spawn_run, mob, "surveyor", []), (d.merge_pr, mob, 1, "abcdef1"),
                                    (d.memory_view,), (d.issue_progress, "a/b"), (d.open_prs, mob, "a/b", [], {}), (d._append_private, ROOT / "state" / "c", "x"))))
finally:
    _bi.open, _dsp.Popen, _dur.urlopen = _real_open, _real_popen, _real_urlopen
    for _n, _f in _path_ops.items():
        setattr(Path, _n, _f)
check("while demo ran, no file, process or network was touched (and every attempt would have been caught)", _trips == [], _trips[:3])

_off = _call("POST", "/api/demo", {"on": False})
_back = _call("GET", "/api/state")[1]
check("demo off puts the real world back, with no demo marker", _off == (200, {"on": False}) and "demo" not in _back
      and {p["name"] for p in _back["projects"]} == _real_names)
check("state/, logs/, workspace/ and config/projects.json are byte for byte as they were", _tree_print() == _before)
_srv.shutdown()

# the scenario: deterministic, it moves, then settles
_dm = d.demo
_snap = lambda w, t: (setattr(w, "clock", lambda: w.t0 + t), w.state())[1]
_w1, _w2 = _dm.World(clock=lambda: 1000.0), _dm.World(clock=lambda: 1000.0)
_strip = lambda s: _dj.dumps({k: v for k, v in s.items() if k not in ("demo",)}, sort_keys=True)
check("the scenario is deterministic: two rehearsals match at every second I looked at",
      all(_strip(_snap(_w1, t)) == _strip(_snap(_w2, t)) for t in (0, 30, 75, 125, 160, 210, 300, 399)))
_run_at = lambda t: sorted((a["project"], a["duty"], a["what"]) for a in _snap(_w1, t)["agents"] if a["status"] == "running")
_busy = lambda t: [x[:2] for x in _run_at(t)]
check("the Brain moves: agents start and finish over the first minutes",
      _busy(0) == [("wayfarer-mobile", "shipwright")] and ("wayfarer-mobile", "shipwright") in _busy(30) and ("wayfarer-web", "shipwright") in _busy(60)
      and ("wayfarer-api", "shipwright") in _busy(130) and ("wayfarer-api", "shipwright") in _busy(190) and _run_at(130) != _run_at(190)
      and ("wayfarer-web", "inspector") in _busy(210))
_prn = lambda t: len(_dm.World.open_prs(_w1, t))
check("pull requests open as the scenario runs", _prn(0) == 4 and _prn(80) == 5 and _prn(110) == 6 and _prn(230) == 7)
check("a surveyor reviews a new pull request after it opens",
      next(p for p in _w1.open_prs(120) if p["number"] == 42)["review"]["verdict"] == "CLEAN" and next(p for p in _w1.open_prs(90) if p["number"] == 42)["review"] is None)
_errs = lambda t: [i["text"] for i in _snap(_w1, t)["inbox"] if "#131 tests failed" in i["text"]]
check("a run fails, shows in Needs you, then the re-run clears it", not _errs(100) and _errs(160) and not _errs(300))
_unread = lambda t: {c["name"]: len([i for i in c["items"] if i["new"]]) for c in _snap(_w1, t)["connectors"]}
check("a mail, a Slack mention and an analytics spike arrive on schedule",
      _unread(0)["gmail"] == 0 and _unread(70)["gmail"] == 1 and _unread(140)["slack"] == 1 and _unread(190)["analytics"] == 1 and _unread(0)["analytics"] == 0)
check("spend climbs as runs finish", _snap(_w1, 300)["spend"]["today"] > _snap(_w1, 0)["spend"]["today"])
_end = lambda t: _dj.dumps([_snap(_w1, t)[k] for k in ("agents", "runs", "fixes", "connectors", "spend")] + [[i["id"] for i in _snap(_w1, t)["inbox"]]], sort_keys=True)
check("after about six minutes the scenario settles and stays calm", _end(400) == _end(900) and _run_at(900) == [])
_w1.clock = lambda: 5000.0
_w1.reset()
check("restarting returns the scenario to second zero, with nothing pressed",
      _w1.elapsed() == 0 and len(_run_at(0)) == 1 and not _w1.user_jobs and _snap(_w1, 0)["agents"] == _snap(_w1, 0)["agents"] and _w1.t0 == 5000.0)

_idx = (ROOT / "dashboard" / "index.html").read_text()
check("the page shows a permanent DEMO DATA banner and a Demo toggle", "DEMO DATA" in _idx and 'js-demo' in _idx and "toggleDemo" in _idx)
_banner_css = next(l for l in _ui.splitlines() if l.startswith(".demo-banner{"))
check("the banner is flat: no gradient, no animation, no em dash", "gradient" not in _banner_css and "animation" not in _banner_css and "—" not in _idx[_idx.index('id="demo-banner"'):_idx.index('id="demo-banner"') + 400])

sys.path.insert(0, str(ROOT / "bin"))
from integrations import checks as _integration_checks   # the direct feeds, with a fake transport
_integration_checks.run_checks(check)
_slow, _slowclk = [], [0.0]
def _nap_slow(secs):
    _slow.append(secs)
    _slowclk[0] += secs
    if _slowclk[0] >= 4 * 1050:
        raise _Halt
try:
    d.run_loop("slowprobe", 1050, lambda: 1 / 0, sleep=_nap_slow, clock=lambda: _slowclk[0])
except _Halt:
    pass
check("a failing slow loop never retries faster than its own pace", _slowclk[0] >= 4 * 1050 and max(_slow) <= d.LOOP_TICK_MAX and sum(_slow) >= 4 * 1050, (len(_slow), _slowclk[0]))
import integrations.loop as _il
_cfg = {"sources": {"ga4": {"enabled": True, "minutes": 5}}}
_ran = []
_il.SKIP = lambda: True
_il.tick({}, _cfg, runner=_ran.append, now=10**9)
_while_demo = list(_ran)
_il.SKIP = lambda: False
_il.tick({}, _cfg, runner=_ran.append, now=10**9)
check("the feeds loop does nothing while demo mode is on, and runs what is due otherwise", _while_demo == [] and _ran == ["ga4"], _ran)


# ---- reading one board card: read only, argv only, validated, cached in memory, nothing on disk ----
_ctmp = pathlib.Path(tempfile.mkdtemp())
(_ctmp / "p.json").write_text(json.dumps({"my-web-app": {"repo": "ajmujaa/my-web-app"}, "norepo": {}}))
_card_calls = []
_card_json = {"number": 7, "title": "Cache it", "state": "OPEN", "body": "## Hi\n\n- [x] done\n<script>alert(1)</script>", "url": "https://github.com/ajmujaa/my-web-app/issues/7",
              "labels": [{"name": "bug"}], "assignees": [{"login": "mina"}], "milestone": {"title": "Beta"}, "createdAt": "2026-10-01T10:00:00Z", "updatedAt": "2026-10-02T10:00:00Z",
              "author": {"login": "jonas"}, "comments": [{"author": {"login": "mina"}, "createdAt": "2026-10-02T11:00:00Z", "body": "ok"}] * 150,
              "closedByPullRequestsReferences": [{"number": 9, "url": "https://github.com/ajmujaa/my-web-app/pull/9"}, {"number": 10, "url": "javascript:alert(1)"}, "junk"]}
def _fake_card_run(argv, **kw):
    _card_calls.append((argv, kw))
    return type("R", (), {"returncode": 0, "stdout": json.dumps(_card_json), "stderr": ""})()
_csaved = (d.subprocess.run, d.STATE, d.PROJECTS_FILE, d.CARD_CACHE)
d.subprocess.run = _fake_card_run; d.STATE = _ctmp; d.PROJECTS_FILE = _ctmp / "p.json"; d.CARD_CACHE = {}
def _card_refused(*a):
    n = len(_card_calls)
    try:
        d.card_view(*a)
        return False
    except ValueError:
        return len(_card_calls) == n
check("a card of an unknown project, a project without a repo, a smuggled number or a bad kind is refused with nothing called",
      _card_refused("nope", "7") and _card_refused("norepo", "7") and all(_card_refused("my-web-app", x) for x in ("7;rm", "0", "-1", "07", "12345678", "", None, 7, "7 8", "$(id)")) and _card_refused("my-web-app", "7", "gist"))
_c, _at = d.card_view("my-web-app", "7")
_argv, _kw = _card_calls[-1]
check("a card is read with one gh call, as argv items (no shell), for the registered repository, with a timeout",
      len(_card_calls) == 1 and _argv[:4] == ["gh", "issue", "view", "7"] and _argv[4:6] == ["-R", "ajmujaa/my-web-app"] and "--json" in _argv and not _kw.get("shell") and _kw.get("timeout"), _argv)
check("a pull request card uses gh pr view and asks for its closing issues", d.card_view("my-web-app", "7", "pr") and _card_calls[-1][0][:3] == ["gh", "pr", "view"] and "closingIssuesReferences" in _card_calls[-1][0][-1])
check("the card is shaped and trimmed: the body is data, comments are capped, links keep only GitHub addresses, nothing writes anything",
      _c["title"] == "Cache it" and "<script>" in _c["body"] and len(_c["comments"]) == 100 and _c["comments_more"] == 50 and _c["labels"] == ["bug"] and _c["assignees"] == ["mina"]
      and _c["milestone"] == "Beta" and [l["number"] for l in _c["linked"]] == [9, 10] and _c["linked"][1]["url"] == "" and _c["url"].startswith("https://github.com/"), _c["linked"])
_n = len(_card_calls); d.card_view("my-web-app", "7"); d.card_view("my-web-app", "7", "issue")
check("a card is cached for 60 seconds in memory (no second gh call), and fresh asks again", len(_card_calls) == _n and (d.card_view("my-web-app", "7", "issue", True) and len(_card_calls) == _n + 1))
_json_big = dict(_card_json, body="x" * 300000); _card_json_saved = _card_json; _card_json = _json_big
_cb, _ = d.card_view("my-web-app", "8")
_card_json = _card_json_saved
check("a 300 KB body is cut at 200 KB and says so", len(_cb["body"]) == 200000 and _cb["body_cut"] is True)
check("nothing about a card is written to disk: the state folder holds no file after reading", [p.name for p in _ctmp.glob("**/*") if p.is_file()] == ["p.json"])
d.subprocess.run = lambda argv, **kw: type("R", (), {"returncode": 1, "stdout": "", "stderr": "HTTP 404: Not Found"})()
try:
    d.card_view("my-web-app", "99"); _cerr = None
except RuntimeError as e:
    _cerr = e
check("GitHub not answering raises an error the route turns into a 502 (the page then says GitHub did not answer)", _cerr is not None and "404" in str(_cerr))
d.subprocess.run, d.STATE, d.PROJECTS_FILE, d.CARD_CACHE = _csaved[0], _csaved[1], _csaved[2], _csaved[3]
_src = pathlib.Path(d.__file__).read_text()
_card_src = _src[_src.index("def card_view"):_src.index("def board_snapshot")]
check("the card code has no write verb: no comment, edit, close, label or merge call", not _re2.search(r"\"(comment|edit|close|reopen|label|merge|create|delete|lock|transfer)\"|--add-|--remove-|--body", _card_src))


# ---- Fleet: local agent folders (bin/fleetview.py). It can start and stop things, so the safety rules are tested, not assumed ----
import fleetview as _fv, tempfile as _tf, json as _fj, os as _fo
_ft = pathlib.Path(_tf.mkdtemp())
(_ft / "fleet" / "bin").mkdir(parents=True); (_ft / "fleet" / "logs").mkdir()
(_ft / "fleet" / "bin" / "fleet").write_text("#!/bin/bash\necho \"$@\" >> \"$(dirname \"$0\")/../calls\"\n[ \"$1\" = status ] && printf '  alpha          loaded  (next in 3 min)\\n  beta           NOT LOADED\\n  alpha PRs: 4 open\\n'\n")
_fo.chmod(_ft / "fleet" / "bin" / "fleet", 0o755)
(_ft / "fleet" / "logs" / "alpha.log").write_text("one\ntwo\nthree\nfour\n")
(_ft / "repo" / ".claude" / "agents").mkdir(parents=True); (_ft / "repo" / ".claude" / "commands").mkdir(parents=True)
(_ft / "repo" / ".claude" / "agents" / "planner.md").write_text("---\nname: planner\ndescription: Decides where work belongs.\nmodel: sonnet\n---\nSECRET BODY\n")
(_ft / "repo" / ".claude" / "agents" / "builder.md").write_text("---\nname: builder\ndescription: >\n  Builds the change\n  inside one service.\n---\nbody\n")
(_ft / "repo" / ".claude" / "commands" / "feature.md").write_text("---\ndescription: Build it\nargument-hint: what\n---\nFirst the `planner` decides, then the builder agent builds. Plan the plan.\n")
_fcfg = _ft / "fleet.json"
_fcfg.write_text(_fj.dumps({"sources": [
    {"id": "f", "kind": "command-fleet", "title": "F", "path": str(_ft / "fleet"), "cli": "bin/fleet",
     "jobs": [{"id": "a", "name": "Alpha", "status_key": "alpha", "arg": "al", "log": "logs/alpha.log"}, {"id": "b", "name": "Beta", "status_key": "beta", "arg": "be"}]},
    {"id": "r", "kind": "repo-agents", "title": "R", "path": str(_ft / "repo")},
    {"id": "esc", "kind": "command-fleet", "path": str(_ft / "fleet"), "cli": "../../etc/passwd", "jobs": []},
    {"id": "esc2", "kind": "command-fleet", "path": str(_ft / "fleet"), "cli": "bin/fleet", "jobs": [{"id": "x", "log": "/etc/hosts"}]},
    {"id": "Bad Id", "kind": "repo-agents", "path": str(_ft / "repo")},
    {"id": "nokind", "kind": "shell", "path": str(_ft / "repo")},
    {"id": "gone", "kind": "repo-agents", "path": str(_ft / "missing")},
    {"id": "f", "kind": "repo-agents", "path": str(_ft / "repo")}]}))
_fc = _fv.load_config(_fcfg)
check("fleet config: a source with a path or command outside its folder, a bad id, an unknown kind, a missing folder or a repeated id is refused with a reason, and the good ones still load",
      [s["id"] for s in _fc["sources"]] == ["f", "r"] and len(_fc["errors"]) == 6, (len(_fc["errors"]), _fc["errors"]))
check("fleet config: a missing file is no sources, not a crash", _fv.load_config(_ft / "none.json") == {"sources": [], "errors": []})
check("fleet paths: absolute, climbing and link-escaping paths resolve to nothing", _fv.inside(_ft, "/etc/hosts") is None and _fv.inside(_ft, "../x") is None and _fv.inside(_ft, "a/../../x") is None
      and _fv.inside(_ft, "fleet/logs") is not None)
_ps = _fv.parse_status("  alpha          loaded  (next in 3 min)\n  beta           NOT LOADED\n  alpha PRs: 4 open\n  slack token: present\n  dashboard      loaded — http://127.0.0.1:3905\n")
check("fleet status: a job's own line is read, a later count line with the same first word does not replace it, and a 'name: value' line is not a job",
      _ps["alpha"][1:] == ("on", "in 3 min") and _ps["beta"][1] == "paused" and "slack" not in _ps and len(_ps) == 3, _ps)
_fs = _fv.snapshot(_fc)
_fj0 = _fs["sources"][0]["jobs"]
check("fleet snapshot: states come from the command's own status, the log shows only its last three lines, and a job missing from the output is unknown",
      [j["state"] for j in _fj0] == ["on", "paused"] and _fj0[0]["log"] == ["two", "three", "four"] and _fj0[0]["actions"] == ["pause", "test"] and _fj0[1]["actions"] == ["resume", "test"], _fj0)
_fr = _fs["sources"][1]
check("fleet repo: agent names and descriptions come from the front matter only (never the body), a folded description is joined, and a command chain lists only agents named as agents",
      [a["name"] for a in _fr["agents"]] == ["builder", "planner"] and "SECRET" not in _fj.dumps(_fr) and _fr["agents"][0]["what"] == "Builds the change inside one service."
      and _fr["commands"][0]["chain"] == ["planner", "builder"], _fr)
check("fleet actions: only pause, resume and test of a job in the config become a command, as an argv list built from the config's own arg, never from what was typed",
      _fv.action_argv(_fc, "f", "a", "pause") == [str(_ft / "fleet" / "bin" / "fleet"), "pause", "al", ] [:3] or _fv.action_argv(_fc, "f", "a", "pause")[0][1:] == [_fv.action_argv(_fc, "f", "a", "pause")[0][0], "pause", "al"][1:],
      _fv.action_argv(_fc, "f", "a", "pause"))
_aa = _fv.action_argv(_fc, "f", "a", "pause")
check("fleet actions: the command is [cli, action, arg] with no shell, test runs detached, and unknown sources, jobs and actions are refused",
      isinstance(_aa, tuple) and _aa[0][1:] == ["pause", "al"] and _fv.action_argv(_fc, "f", "a", "test")[2] is True and _aa[2] is False
      and all(isinstance(_fv.action_argv(_fc, *x), str) for x in [("nope", "a", "pause"), ("f", "zz", "pause"), ("f", "a", "rm -rf /"), ("f", "a", "status"), ("r", "a", "pause"), ("f", "a;ls", "pause")]))
_calls = []
class _R:
    returncode, stdout, stderr = 0, "paused: alpha", ""
_ok, _msg = _fv.run_action(_fc, "f", "a", "pause", _ft / "st", runner=lambda argv, **k: (_calls.append((argv, k)) or _R()))
check("fleet actions: pause waits for the command, runs it in the fleet's own folder with a timeout, and reports what it said",
      _ok and _msg == "paused: alpha" and _calls[0][0][1:] == ["pause", "al"] and _calls[0][1]["cwd"] == str(_ft / "fleet") and _calls[0][1]["timeout"] == 30 and "shell" not in _calls[0][1], _calls)
_pc = []
_ok2, _ = _fv.run_action(_fc, "f", "a", "test", _ft / "st", popen=lambda argv, **k: _pc.append((argv, k)))
check("fleet actions: test starts one run in its own session with its output in a private file, and returns at once",
      _ok2 and _pc[0][0][1:] == ["test", "al"] and _pc[0][1]["start_new_session"] is True and (_ft / "st" / "fleet-f-a-test.log").exists()
      and oct((_ft / "st" / "fleet-f-a-test.log").stat().st_mode & 0o777) == "0o600", _pc)
# worktrees of a repository: a real throwaway git repo with two extra worktrees, and a fake `gh`
import subprocess as _sp
_gr = _ft / "gitrepo"; _gr.mkdir()
def _g(*a, cwd=_gr): return _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=develop"] + list(a), cwd=cwd, capture_output=True, text=True)
_g("init", "-q"); (_gr / "a.txt").write_text("1"); _g("add", "."); _g("commit", "-qm", "base"); _g("branch", "origin-develop")
_g("worktree", "add", "-q", "-b", "feat/working", str(_ft / "wt-working")); (_ft / "wt-working" / "new.txt").write_text("x")
_g("worktree", "add", "-q", "-b", "fix/reviewed", str(_ft / "wt-reviewed")); (_ft / "wt-reviewed" / "r.txt").write_text("y"); _g("add", ".", cwd=_ft / "wt-reviewed"); _g("commit", "-qm", "work", cwd=_ft / "wt-reviewed")
_g("worktree", "add", "-q", "-b", "task/merged", str(_ft / "wt-merged")); (_ft / "wt-merged" / "m.txt").write_text("z"); _g("add", ".", cwd=_ft / "wt-merged"); _g("commit", "-qm", "m", cwd=_ft / "wt-merged")
_wt = _fv.read_all_worktrees(_gr, base="origin-develop")
_by = {w["branch"]: w for w in _wt}
check("worktrees: every worktree git knows is listed with its branch and changes, the main checkout is marked and last, and how far each is ahead of its base is counted",
      len(_wt) == 4 and _wt[-1]["main"] and sum(1 for w in _wt if w["main"]) == 1 and _by["feat/working"]["changed"] == 1 and _by["fix/reviewed"]["ahead"] == 1 and _by["fix/reviewed"]["behind"] == 0
      and _by["feat/working"]["ahead"] == 0, [(w["branch"], w["changed"], w["ahead"], w["main"]) for w in _wt])
_prs = {"fix/reviewed": {"number": 5, "title": "t", "state": "open", "draft": False}, "task/merged": {"number": 4, "title": "t", "state": "merged", "draft": False}}
for w in _wt: w["pr"] = _prs.get(w["branch"])
check("worktrees: a stage comes from facts only: merged and open pull requests, changes with no pull request, commits with none, and nothing at all",
      [_fv.stage_of(w) for w in sorted(_wt, key=lambda w: w["branch"])] == ["clean", "working", "in review", "merged"]
      and _fv.stage_of({"pr": {"state": "open", "draft": True}}) == "draft" and _fv.stage_of({"pr": None, "changed": 0, "ahead": 2}) == "committed"
      and _fv.stage_of({"pr": {"state": "closed"}}) == "closed" and _fv.stage_of({"pr": {"state": "merged"}, "changed": 3}) == "working"
      and _fv.stage_of({"pr": {"state": "merged"}, "changed": 0, "main": True}) == "clean", [(w["branch"], _fv.stage_of(w)) for w in _wt])
check("worktrees: recent changes or commits are active, two weeks idle, longer old",
      _fv.activity_of({"changed": 1, "last_commit_ago": 10 ** 7}) == "active" and _fv.activity_of({"changed": 0, "last_commit_ago": 3600}) == "active"
      and _fv.activity_of({"changed": 0, "last_commit_ago": 5 * 86400}) == "idle" and _fv.activity_of({"changed": 0, "last_commit_ago": 30 * 86400}) == "old"
      and _fv.activity_of({"changed": 0, "last_commit_ago": None}) == "old")
_gh = []
class _GR:
    returncode = 0
    stdout = _fj.dumps([
        {"number": 9, "title": "newest on the branch", "state": "OPEN", "isDraft": False, "headRefName": "fix/reviewed", "reviewDecision": "REVIEW_REQUIRED",
         "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}, {"status": "IN_PROGRESS"}, {"conclusion": "SKIPPED"}]},
        {"number": 3, "title": "older, same branch", "state": "MERGED", "isDraft": False, "headRefName": "fix/reviewed", "statusCheckRollup": []}])
    stderr = ""
_fv.PR_CACHE.clear()
_pm = _fv.pull_requests("o/r", runner=lambda argv, **k: (_gh.append(argv) or _GR()))
check("pull requests: one read only GitHub call for the repository's own pull requests, the newest per branch wins, and checks are counted passing, failing and running",
      len(_gh) == 1 and _gh[0][:3] == ["gh", "pr", "list"] and "--author" in _gh[0] and "@me" in _gh[0] and not any(x in _gh[0] for x in ("merge", "comment", "edit", "close"))
      and _pm["fix/reviewed"]["number"] == 9 and _pm["fix/reviewed"]["state"] == "open" and (_pm["fix/reviewed"]["checks_ok"], _pm["fix/reviewed"]["checks_bad"], _pm["fix/reviewed"]["checks_wait"]) == (2, 1, 1), _pm)
_fv.pull_requests("o/r", runner=lambda argv, **k: (_gh.append(argv) or _GR()))
_fv.PR_CACHE.clear(); _fv.HEAD_CACHE.clear(); _hc = []
class _HR:
    returncode, stderr = 0, ""
    def __init__(self, branch): self.stdout = _fj.dumps([{"number": 7, "title": "colleague", "state": "MERGED", "isDraft": False, "headRefName": branch, "statusCheckRollup": []}] if branch == "task/theirs" else [])
def _hrun(argv, **k):
    _hc.append(argv)
    return _GR() if "--author" in argv else _HR(argv[argv.index("--head") + 1])
_pm2 = _fv.pull_requests("o/h", runner=_hrun, branches=["fix/reviewed", "task/theirs", "task/none", "develop", "x; rm -rf /"])
check("pull requests: a branch the owner's list misses is looked up on its own (a colleague's or an older pull request), once, read only, and trunk names, bad names and known branches are never asked about",
      _pm2["task/theirs"]["number"] == 7 and "task/none" not in _pm2 and sum(1 for a in _hc if "--head" in a) == 2 and all("--head" in a or "--author" in a for a in _hc)
      and not any("develop" in a or "rm -rf" in " ".join(a) for a in _hc if "--head" in a) and "fix/reviewed" in _pm2, [a for a in _hc if "--head" in a])
_fv.pull_requests("o/h", runner=_hrun, branches=["task/theirs", "task/none"])
check("pull requests: a direct look is cached, including finding nothing", sum(1 for a in _hc if "--head" in a) == 2)
check("pull requests: a second look within the cache time makes no second GitHub call, and a failing gh gives no pull requests, not an error",
      len(_gh) == 1 and _fv.pull_requests("o/x", runner=lambda argv, **k: (_ for _ in ()).throw(OSError("no gh"))) == {})
_bad = _ft / "bad.json"
_bad.write_text(_fj.dumps({"sources": [{"id": "r1", "kind": "repo-agents", "path": str(_gr), "repo": "no spaces/allowed here"},
                                       {"id": "r2", "kind": "repo-agents", "path": str(_gr), "base": "origin/dev; rm -rf /"},
                                       {"id": "r3", "kind": "repo-agents", "path": str(_gr), "repo": "Owner/name", "base": "origin/develop"}]}))
_bc = _fv.load_config(_bad)
check("fleet config: repo must look like owner/name and base like a branch name, and anything else is refused with a reason",
      [x["id"] for x in _bc["sources"]] == ["r3"] and len(_bc["errors"]) == 2 and _bc["sources"][0]["repo"] == "Owner/name", _bc)
_pj = _ft / "pj.json"
_pj.write_text(_fj.dumps({"sources": [{"id": "a", "kind": "repo-agents", "path": str(_gr), "project": "work-app"}, {"id": "b", "kind": "repo-agents", "path": str(_gr), "project": "Bad Name!"},
                                      {"id": "c", "kind": "repo-agents", "path": str(_gr)}]}))
_pc2 = _fv.load_config(_pj)
check("fleet projects: a source may name the Quarterdeck project it belongs to, a bad name is refused, and the page is told only the names",
      _fv.projects(_pc2) == ["work-app"] and len(_pc2["errors"]) == 1 and [s["id"] for s in _pc2["sources"]] == ["a", "c"], _pc2["errors"])
# live sessions: events a hook writes into state/, read back into sessions
_ev = _ft / "events"; _ev.mkdir()
_N = 1_000_000.0
def _e(sess, t, kind, **k): return _fj.dumps({"t": _N - t, "event": kind, "session": sess, "worktree": k.get("wt", "wt-a"), "branch": k.get("br", "feat/a"), "agent": k.get("agent", ""), "prompt": "SECRET PROMPT TEXT"})
(_ev / "src.jsonl").write_text("\n".join([
    _e("aaaaaaaa1", 600, "session_start"), _e("aaaaaaaa1", 590, "prompt"), _e("aaaaaaaa1", 500, "agent_start", agent="planner"), _e("aaaaaaaa1", 400, "agent_start", agent="builder"), _e("aaaaaaaa1", 300, "agent_stop", agent="planner"),
    _e("bbbbbbbb2", 900, "session_start", wt="wt-b", br="fix/b"), _e("bbbbbbbb2", 880, "prompt", wt="wt-b", br="fix/b"), _e("bbbbbbbb2", 700, "stop", wt="wt-b", br="fix/b"),
    _e("cccccccc3", 7200, "prompt", wt="wt-c"), _e("dddddddd4", 3000, "session_start", wt="wt-d"), _e("dddddddd4", 2900, "session_end", wt="wt-d"),
    _e("eeeeeeee5", 90000, "prompt", wt="wt-e"), "not json at all", _fj.dumps({"t": _N, "event": "keystroke", "session": "ffffffff6"}), _fj.dumps({"t": _N, "event": "prompt", "session": "bad session id!"}),
    ""]))
_evs = _fv.read_events("src", _ev)
_sx = {x["id"]: x for x in _fv.build_sessions(_evs, now=_N)}
check("sessions: events become sessions: working with the agents running now and those used, idle after a stop, quiet after half an hour, ended when closed, older than a day dropped, and a bad line, an unknown event or a bad id is ignored",
      _sx["aaaaaaaa"]["state"] == "working" and _sx["aaaaaaaa"]["running_agents"] == ["builder"] and _sx["aaaaaaaa"]["agents_used"] == {"planner": 1, "builder": 1}
      and _sx["bbbbbbbb"]["state"] == "idle" and _sx["bbbbbbbb"]["worktree"] == "wt-b" and _sx["cccccccc"]["state"] == "quiet" and _sx["dddddddd"]["state"] == "ended"
      and "eeeeeeee" not in _sx and "ffffffff" not in _sx and len(_sx) == 4, {k: v["state"] for k, v in _sx.items()})
check("sessions: only the known fields are read, so no prompt text can reach the page, and the newest working session comes first",
      "SECRET" not in _fj.dumps(_fv.build_sessions(_evs, now=_N)) and [x["id"] for x in _fv.build_sessions(_evs, now=_N)][0] == "aaaaaaaa"
      and _fv.read_events("nothing", _ev) is None and _fv.build_sessions(None) == [])
# the observer hook: only fixed fields, only registered repositories, never a failure, and a reversible install
import shutil as _sh
_hk = _ft / "hk"; (_hk / "bin").mkdir(parents=True); (_hk / "config").mkdir()
_sh.copy(str(pathlib.Path(d.__file__).parent / "fleet-hook.sh"), str(_hk / "bin" / "fleet-hook.sh"))
(_hk / "config" / "fleet.local.json").write_text(_fj.dumps({"sources": [{"id": "src", "kind": "repo-agents", "path": str(_gr)}]}))
_hf = _hk / "state" / "fleet-events" / "src.jsonl"
def _hook(payload, home=None, raw=None):
    return _sp.run(["bash", str(_hk / "bin" / "fleet-hook.sh")], input=raw if raw is not None else _fj.dumps(payload), capture_output=True, text=True,
                   env={"PATH": _fo.environ["PATH"], "HOME": str(home or _ft)})
_pl = {"hook_event_name": "UserPromptSubmit", "session_id": "sess-1", "cwd": str(_gr), "prompt": "TOP SECRET PROMPT", "last_assistant_message": "TOP SECRET REPLY", "transcript_path": "/x/secret.jsonl"}
_r1 = _hook(_pl)
_l1 = [_fj.loads(x) for x in _hf.read_text().splitlines()] if _hf.exists() else []
check("hook: an event in a registered repository adds one line with only the time, kind, session, worktree, branch and agent, and nothing of the prompt, reply or transcript",
      _r1.returncode == 0 and len(_l1) == 1 and set(_l1[0]) == {"t", "event", "session", "worktree", "branch", "agent"} and _l1[0]["event"] == "prompt" and _l1[0]["session"] == "sess-1"
      and "SECRET" not in _hf.read_text() and _l1[0]["agent"] == "" and oct(_hf.stat().st_mode & 0o777) == "0o600" and oct(_hf.parent.stat().st_mode & 0o777) == "0o700", _l1)
_hook({**_pl, "hook_event_name": "SubagentStart", "agent_type": "builder", "agent_id": "x1", "cwd": str(_ft / "wt-working")})
_hook({**_pl, "hook_event_name": "SubagentStop", "agent_type": "builder", "cwd": str(_ft / "wt-working")})
_l2 = [_fj.loads(x) for x in _hf.read_text().splitlines()]
check("hook: a session in another worktree of the same repository is matched, with that worktree's name and branch, and an agent's name is kept only on its start and stop",
      len(_l2) == 3 and _l2[1]["event"] == "agent_start" and _l2[1]["agent"] == "builder" and _l2[1]["worktree"] == "wt-working" and _l2[1]["branch"] == "feat/working" and _l2[2]["event"] == "agent_stop"
      and _fv.build_sessions(_fv.read_events("src", _hf.parent))[0]["worktree"] in ("wt-working", _gr.name), _l2[1:])
_n0 = len(_hf.read_text().splitlines())
_other = _ft / "elsewhere"; _other.mkdir()
_rs = [_hook({**_pl, "cwd": str(_other)}), _hook({**_pl, "hook_event_name": "PreToolUse"}), _hook({**_pl, "session_id": "bad id!"}), _hook({**_pl, "cwd": "/nonexistent/x"}), _hook(None, raw="not json {{"), _hook(None, raw="")]
check("hook: another folder, an unknown event, a bad session id, a missing folder, garbage and empty input all leave no trace and never fail",
      all(r.returncode == 0 and r.stdout == "" for r in _rs) and len(_hf.read_text().splitlines()) == _n0, [r.returncode for r in _rs])
(_hk / "config" / "fleet.local.json").unlink()
_hook(_pl)
check("hook: with no config it writes nothing and still exits 0", len(_hf.read_text().splitlines()) == _n0)
(_hk / "config" / "projects.json").write_text(_fj.dumps({"regproj": {"repo": "acme/regproj", "path": str(_gr)}, "Bad Name!": {"path": str(_other)}}))
_hook({**_pl, "session_id": "sess-reg"})
_rf = _hk / "state" / "fleet-events" / "regproj.jsonl"
check("hook: a registered project is watched with no fleet file, under its own name; with neither config the hook stays silent",
      _rf.exists() and "sess-reg" in _rf.read_text() and "SECRET" not in _rf.read_text() and not (_hk / "state" / "fleet-events" / "Bad Name!.jsonl").exists())
(_hk / "config" / "projects.json").unlink()
_home = _ft / "home"; (_home / ".claude").mkdir(parents=True)
_st = _home / ".claude" / "settings.json"
_st.write_text(_fj.dumps({"model": "x", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "/other/hook.sh"}]}], "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/other/guard.sh"}]}]}}))
_env = {"PATH": _fo.environ["PATH"], "HOME": str(_home), "CLAUDE_SETTINGS_FILE": str(_st)}
_hs = str(_hk / "bin" / "fleet-hook.sh")
_i1 = _sp.run(["bash", _hs, "install"], capture_output=True, text=True, env=_env); _sp.run(["bash", _hs, "install"], capture_output=True, text=True, env=_env)
_cfg = _fj.loads(_st.read_text())
_ours = lambda c: sum(1 for k, v in c["hooks"].items() for e in v for h in e["hooks"] if h["command"] == _hs)
check("hook install: it adds itself to the six events once (repeating changes nothing), keeps every other hook and setting, marks it async, and makes a backup first",
      _i1.returncode == 0 and _ours(_cfg) == 6 and set(_cfg["hooks"]) >= {"SessionStart", "SessionEnd", "UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop", "PreToolUse"}
      and any(h["command"] == "/other/hook.sh" for e in _cfg["hooks"]["SessionStart"] for h in e["hooks"]) and _cfg["hooks"]["PreToolUse"][0]["matcher"] == "Bash" and _cfg["model"] == "x"
      and all(h.get("async") is True for v in _cfg["hooks"].values() for e in v for h in e["hooks"] if h["command"] == _hs) and len(list((_home / ".claude").glob("settings.json.quarterdeck-bak-*"))) >= 1
      and _sp.run(["bash", _hs, "status"], capture_output=True, text=True, env=_env).stdout.strip() == "installed", (_ours(_cfg), _i1.stderr))
_sp.run(["bash", _hs, "uninstall"], capture_output=True, text=True, env=_env)
_cfg2 = _fj.loads(_st.read_text())
check("hook uninstall: only its own entries go, the other hooks and settings stay, and it says it is not installed",
      "hooks" in _cfg2 and _ours(_cfg2) == 0 and _cfg2["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "/other/hook.sh" and _cfg2["hooks"]["PreToolUse"][0]["matcher"] == "Bash" and _cfg2["model"] == "x"
      and "SessionEnd" not in _cfg2["hooks"] and _sp.run(["bash", _hs, "status"], capture_output=True, text=True, env=_env).stdout.strip() == "not installed", _cfg2)
_st.write_text("{ not json")
_bad = _sp.run(["bash", _hs, "install"], capture_output=True, text=True, env=_env)
check("hook install: a settings file that is not valid JSON is left exactly as it was", _bad.returncode != 0 and _st.read_text() == "{ not json")
# the data folder: your data apart from the program (bin/home.py, and the same four rules in bin/lib.sh)
import home as _hm
_uh = _ft / "userhome"; (_uh / ".quarterdeck").mkdir(parents=True); _code = _ft / "code"; _code.mkdir()
_ev0 = {"PATH": _fo.environ["PATH"]}
check("data folder: QUARTERDECK_HOME wins, then QUARTERDECK_DIR (a throwaway Quarterdeck), then ~/.quarterdeck only with its marker, then the program folder",
      _hm.resolve({"QUARTERDECK_HOME": "/a", "QUARTERDECK_DIR": "/b"}, _uh, _code) == pathlib.Path("/a") and _hm.resolve({"QUARTERDECK_DIR": "/b"}, _uh, _code) == pathlib.Path("/b")
      and _hm.resolve({}, _uh, _code) == _code and (_uh / ".quarterdeck" / ".quarterdeck-home").write_text("x") is not None and _hm.resolve({}, _uh, _code) == _uh / ".quarterdeck"
      and _hm.resolve({"QUARTERDECK_DIR": "/b"}, _uh, _code) == pathlib.Path("/b"))
(_uh / ".quarterdeck" / ".quarterdeck-home").unlink()
def _shell_home(env):
    r = _sp.run(["bash", "-c", f'. "{pathlib.Path(d.__file__).parent}/lib.sh" >/dev/null 2>&1; echo "$QUARTERDECK_HOME"'], capture_output=True, text=True, env={**_ev0, "HOME": str(_uh), **env})
    return r.stdout.strip()
_pr = str(pathlib.Path(d.__file__).parent.parent)
(_uh / ".quarterdeck" / ".quarterdeck-home").write_text("x")
check("data folder: the shell follows the same four rules, so a duty and the dashboard always agree",
      _shell_home({"QUARTERDECK_HOME": "/a"}) == "/a" and _shell_home({}) == str(_uh / ".quarterdeck") and _shell_home({"QUARTERDECK_DIR": _pr}) == _pr
      and (lambda: ((_uh / ".quarterdeck" / ".quarterdeck-home").unlink(), _shell_home({}))[1])() == _pr)
_hm.init(_ft / "newhome")
check("data folder: init makes config, state, logs and workspace with the marker, owner only, and never overwrites what is there",
      all((_ft / "newhome" / x).is_dir() for x in ("config", "state", "logs", "workspace")) and (_ft / "newhome" / ".quarterdeck-home").is_file()
      and oct((_ft / "newhome").stat().st_mode & 0o777) == "0o700" and (_ft / "newhome" / "state" / "keep").write_text("mine") is not None and _hm.init(_ft / "newhome") and (_ft / "newhome" / "state" / "keep").read_text() == "mine")
# a real duty-side run with the data folder apart from the program: it reads YOUR registry from there and writes only there
_dh = _ft / "yourdata"; _hm.init(_dh)
(_dh / "config" / "projects.json").write_text(_fj.dumps({"mine": {"repo": "o/mine", "path": str(_ft / "wt-working"), "summary": "split test", "duties": ["surveyor"], "guardrails": [], "default_branch": "develop"}}))
_cstate = pathlib.Path(_pr) / "state" / "runs.json"; _before = _cstate.read_bytes() if _cstate.exists() else b""
_r = _sp.run(["bash", "-c", f'export QUARTERDECK_HOME="{_dh}"; . "{_pr}/bin/lib.sh" >/dev/null 2>&1; project_names; record_run mine surveyor SPLIT-TEST "kept in your data folder"; echo "$QUARTERDECK_HOME"'],
             capture_output=True, text=True, env={**_ev0, "HOME": str(_uh)})
_runs = _fj.loads((_dh / "state" / "runs.json").read_text()) if (_dh / "state" / "runs.json").exists() else []
check("data folder: with it apart from the program, a duty reads the registry from your folder, records its run there, and leaves the program folder's own state alone",
      _r.stdout.split() [0] == "mine" and _r.stdout.split()[-1] == str(_dh) and any(x.get("verdict") == "SPLIT-TEST" for x in _runs) and (_cstate.read_bytes() if _cstate.exists() else b"") == _before, _r.stdout + _r.stderr)
# guard: nothing private or secret may be committed (bin/guard.py)
import guard as _gd
_k = lambda *a: "".join(a)          # fake keys are built at run time so this file holds nothing that looks like a credential
_FAKE = {"anthropic": _k("sk-", "ant-api03-", "A" * 40), "github": _k("gh", "p_", "B" * 36), "slack": _k("xo", "xp-", "123456789012-abcdefghij"),
         "aws": _k("AK", "IA", "ABCDEFGHIJKLMNOP"), "google": _k("AI", "za", "C" * 35), "pem": _k("-----BEGIN RSA ", "PRIVATE KEY-----")}
check("guard: every kind of credential is found on a line, and what is shown is masked (a few characters and a length, never the secret)",
      all(_gd.scan_line("token = " + v, [], False) for v in _FAKE.values()) and all(v not in " ".join(h[1] for h in _gd.scan_line("x " + v, [], False)) for v in _FAKE.values()
          if not v.startswith("-----")) and not _gd.scan_line("sk-ant-… is how an Anthropic key starts, and AKIA is an AWS prefix", [], False))
_nm = _gd.compile_names(["acme", "Project-X"])
check("guard: a private name is matched as a whole word in any case, and not inside another word",
      _gd.scan_line("see ACME docs", _nm, False)[0][0] == "a private name" and _gd.scan_line("the project-x repo", _nm, False) and not _gd.scan_line("acmeCorp and academe", _nm, False))
check("guard: an e-mail address is a hit unless it is an obvious placeholder (example, test, localhost, noreply)",
      bool(_gd.scan_line("write to " + "jane@" + "realcompany.io", [], True)) and not _gd.scan_line("me@example.test and noreply@anthropic.com and 1+a@users.noreply.github.com", [], True))
_gg = _ft / "guardrepo"; _gg.mkdir()
def _gx(*a, cwd=_gg): return _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *a], cwd=cwd, capture_output=True, text=True)
_gx("init", "-q"); (_gg / "ok.py").write_text("print('hello')\n"); (_gg / "leak.py").write_text("KEY = '" + _FAKE["github"] + "'\n# contact acme staff\n")
(_gg / "big.bin").write_bytes(b"x" * 10); (_gg / "dashboard" / "assets" / "vendor").mkdir(parents=True); (_gg / "dashboard" / "assets" / "vendor" / "lib.js").write_text("sk-" + "ant-" + "z" * 30)
_gx("add", "."); _gx("commit", "-qm", "c1")
_h1 = _gd.scan(_gg); _h2 = _gd.scan(_gg, _gd.compile_names(["acme"]), True)
check("guard: secrets are found in tracked files by file and line, names only with the list, and vendored libraries and binaries are not scanned",
      [(h[0], h[1], h[2]) for h in _h1] == [("leak.py", 1, "a GitHub token")] and sorted((h[0], h[1]) for h in _h2) == [("leak.py", 1), ("leak.py", 2)], (_h1, _h2))
(_gg / "staged.txt").write_text("secret " + _FAKE["slack"] + "\n"); _gx("add", "staged.txt")
check("guard: staged mode looks only at what is about to be committed", [h[0] for h in _gd.scan(_gg, staged=True)] == ["staged.txt"])
_gx("rm", "-q", "--cached", "leak.py"); _gx("commit", "-qm", "remove the leak")
check("guard: history mode still finds a secret that was committed and later deleted, naming the commit",
      any(h[0].startswith("leak.py @") and h[2] == "a GitHub token" for h in _gd.scan_history(_gg)) and not any(h[0].startswith("leak.py") for h in _gd.scan(_gg)))
_gc = _ft / "cleanrepo"; _gc.mkdir(); _gx("init", "-q", cwd=_gc); (_gc / "a.py").write_text("print(1)\\n"); _gx("add", ".", cwd=_gc); _gx("commit", "-qm", "c", cwd=_gc)
_dl = _ft / "deny.txt"; _dl.write_text("# private\nacme  # a client\n\nbeta-corp\n")
check("guard: the denylist ignores comments and blank lines", _gd.load_denylist(_dl) == ["acme", "beta-corp"] and _gd.load_denylist(_ft / "missing.txt") == [])
_rc = _sp.run(["python3", str(pathlib.Path(d.__file__).parent / "guard.py"), "--names", "--denylist", str(_dl), str(_gg)], capture_output=True, text=True)
_hk = _sp.run(["python3", str(pathlib.Path(d.__file__).parent / "guard.py"), "install-hook"], capture_output=True, text=True, cwd=_gg)
_real_hook = pathlib.Path(d.__file__).parent.parent / ".git" / "hooks" / "pre-commit"
check("guard: install-hook goes into the repository it is run in and never into this one",
      not _real_hook.exists() and (_gg / ".git" / "hooks" / "pre-commit").is_file())
(_gg / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\necho someone else's hook\n")
_clob = _sp.run(["python3", str(pathlib.Path(d.__file__).parent / "guard.py"), "install-hook"], capture_output=True, text=True, cwd=_gg)
check("guard: it refuses to overwrite a different pre-commit hook", _clob.returncode == 2 and "someone else" in (_gg / ".git" / "hooks" / "pre-commit").read_text())
(_gg / ".git" / "hooks" / "pre-commit").unlink(); _hk = _sp.run(["python3", str(pathlib.Path(d.__file__).parent / "guard.py"), "install-hook"], capture_output=True, text=True, cwd=_gg)
check("guard: the command exits 1 on a hit and 0 when clean, and install-hook writes an executable pre-commit that runs the staged check",
      _rc.returncode == 1 and _sp.run(["python3", str(pathlib.Path(d.__file__).parent / "guard.py"), str(_gc)], capture_output=True, text=True).returncode == 0
      and _hk.returncode == 0 and (_gg / ".git" / "hooks" / "pre-commit").is_file() and _fo.access(_gg / ".git" / "hooks" / "pre-commit", _fo.X_OK) and "--staged" in (_gg / ".git" / "hooks" / "pre-commit").read_text(), _hk.stderr)
# moving an existing setup across (bin/home.py migrate): copy, check, switch, never delete
def _mk_old(root):
    root = pathlib.Path(root); (root / "state" / "panels").mkdir(parents=True); (root / "logs").mkdir(); (root / "workspace" / "w").mkdir(parents=True); (root / "config").mkdir()
    (root / "config" / "projects.json").write_text('{"p": {}}'); (root / "config" / "fleet.local.json").write_text('{"sources": []}')
    (root / "state" / "runs.json").write_text('[{"verdict": "X"}]'); (root / "state" / "panels" / "a.json").write_text("{}")
    sec = root / "state" / "capture.jsonl"; sec.write_text("note\n"); _fo.chmod(sec, 0o600); (root / "logs" / "x.log").write_text("log"); (root / "workspace" / "w" / "f.txt").write_text("w")
    return root
_old = _mk_old(_ft / "oldprog"); _new = _ft / "newhomedir"
_ok0, _l0 = _hm.migrate(_old, _new)
check("migrate: a dry run lists what would move and creates nothing",
      _ok0 and not _new.exists() and any("state/" in l and "file(s)" in l for l in _l0) and any("dry run" in l for l in _l0), _l0)
_ok1, _l1 = _hm.migrate(_old, _new, apply=True)
check("migrate: apply copies every folder and file, keeps the owner-only mode, leaves the originals alone, and adds the marker only after the copy checked out",
      _ok1 and (_new / ".quarterdeck-home").is_file() and (_new / "state" / "panels" / "a.json").is_file() and (_new / "config" / "projects.json").read_text() == '{"p": {}}'
      and oct((_new / "state" / "capture.jsonl").stat().st_mode & 0o777) == "0o600" and (_old / "state" / "runs.json").is_file() and (_old / "config" / "projects.json").is_file()
      and (_new / "workspace" / "w" / "f.txt").read_text() == "w" and (_new / "MIGRATED-FROM").is_file(), _l1)
_ok2, _l2 = _hm.migrate(_old, _new, apply=True)
check("migrate: running it again changes nothing and still reports success", _ok2 and (_new / "state" / "runs.json").read_text() == '[{"verdict": "X"}]')
_old2 = _mk_old(_ft / "oldprog2"); _new2 = _ft / "newhomedir2"; _real_copy = _hm._copy_tree
def _boom(a, b):
    raise OSError("disk full")
_hm._copy_tree = _boom
_ok3, _l3 = _hm.migrate(_old2, _new2, apply=True)
_hm._copy_tree = _real_copy
check("migrate: a copy that fails half way switches nothing: no marker, the originals untouched, and it says so",
      not _ok3 and not (_new2 / ".quarterdeck-home").exists() and (_old2 / "state" / "runs.json").is_file() and any("untouched" in l for l in _l3), _l3)
(_old2 / "state" / "dashboard.pid").write_text(str(_fo.getpid()))
_ok4, _l4 = _hm.migrate(_old2, _ft / "newhomedir3", apply=True)
check("migrate: it refuses while the dashboard is running or a duty holds a lock, unless forced, and copies nothing",
      not _ok4 and not (_ft / "newhomedir3").exists() and any("running" in l for l in _l4) and _hm.migrate(_old2, _ft / "newhomedir4", apply=True, force=True)[0], _l4)
(_old2 / "state" / "dashboard.pid").unlink()
(_old2 / "state" / "dead.lock").mkdir(); (_old2 / "state" / "dead.lock" / "pid").write_text("2147483646")
(_old2 / "state" / "alive.lock").mkdir(); (_old2 / "state" / "alive.lock" / "pid").write_text(str(_fo.getpid()))
_lv = _hm.live_processes(_old2)
check("migrate: a duty lock counts only when the process it names is alive; a leftover lock is ignored",
      len(_lv) == 1 and "alive.lock" in _lv[0] and not any("dead.lock" in x for x in _lv), _lv)
(_old2 / "state" / "dead.lock" / "pid").unlink(); (_old2 / "state" / "dead.lock").rmdir(); (_old2 / "state" / "alive.lock" / "pid").unlink(); (_old2 / "state" / "alive.lock").rmdir()
_old5 = _mk_old(_ft / "oldprog5"); _new5 = _ft / "newhomedir5"; _hm.init(_new5); (_new5 / "config" / "projects.json").write_text('{"mine": {}}')
_ok5, _l5 = _hm.migrate(_old5, _new5, apply=True)
check("migrate: a file that already exists in the data folder is never overwritten; the program's copy is kept beside it",
      _ok5 and (_new5 / "config" / "projects.json").read_text() == '{"mine": {}}' and (_new5 / "config" / "projects.json.from-program").read_text() == '{"p": {}}', _l5)
_okr, _lr = _hm.rollback(_new)
check("migrate: rollback turns the marker off without deleting anything, and a second rollback says it is not active",
      _okr and not (_new / ".quarterdeck-home").exists() and (_new / ".quarterdeck-home.off").is_file() and (_new / "state" / "runs.json").is_file() and not _hm.rollback(_new)[0])
check("migrate: with the marker in ~/.quarterdeck the next start uses it, and without it the program folder again",
      (lambda uh: (_hm.init(uh / ".quarterdeck"), _hm.resolve({}, uh, _code) == uh / ".quarterdeck", _hm.rollback(uh / ".quarterdeck"), _hm.resolve({}, uh, _code) == _code)[1:] )(_ft / "uh2")[0] is True
      and _hm.resolve({}, _ft / "uh2", _code) == _code)
# the same commands through the real command line (a Python-only test missed that the wrapper dispatched on the wrong word)
_cli = str(pathlib.Path(d.__file__).parent / "quarterdeck")
_cli_home = _ft / "cli-home"
_c1 = _sp.run(["bash", _cli, "home", "init", str(_cli_home)], capture_output=True, text=True, env={**_ev0, "HOME": str(_ft / "uh3")})
_c2 = _sp.run(["bash", _cli, "home", "migrate"], capture_output=True, text=True, env={**_ev0, "HOME": str(_ft / "uh3")})
_c3 = _sp.run(["bash", _cli, "home"], capture_output=True, text=True, env={**_ev0, "HOME": str(_ft / "uh3")})
check("quarterdeck home: init makes the folder, migrate with no flag is a dry run that copies nothing, and plain home shows both folders, all through the command line",
      _c1.returncode == 0 and (_cli_home / ".quarterdeck-home").is_file() and _c2.returncode in (0, 1) and ("dry run" in _c2.stdout or "not safe to copy" in _c2.stdout) and not (_ft / "uh3" / ".quarterdeck").exists()
      and "the program" in _c3.stdout and "your data" in _c3.stdout, (_c1.stderr, _c2.stdout[-300:]))
# publish: the public tree is built from committed files, renamed, with the private left out (bin/publish.py; absent from the public tree itself, so these skip there)
if (pathlib.Path(d.__file__).parent / "publish.py").exists():
    import publish as _pb
    _pr_ = _ft / "pubrepo"; (_pr_ / "bin").mkdir(parents=True); (_pr_ / "docs" / "cloud-tasks").mkdir(parents=True); (_pr_ / "config").mkdir(); (_pr_ / "tools" / "QuarterdeckAgenda").mkdir(parents=True)
    (_pr_ / "README.md").write_text("Quarterdeck runs with QUARTERDECK_HOME. Try `quarterdeck home`. See github.com/o/quarterdeck.\n")
    (_pr_ / "bin" / "quarterdeck").write_text("#!/bin/bash\necho \"$QUARTERDECK_HOME\" # quarterdeck\n"); _fo.chmod(_pr_ / "bin" / "quarterdeck", 0o755)
    (_pr_ / "docs" / "cloud-tasks" / "brief.md").write_text("private brief about Quarterdeck\n"); (_pr_ / "config" / "projects.json").write_text('{"mine": {}}')
    (_pr_ / "config" / "projects.example.json").write_text('{"my-web-app": {}}'); (_pr_ / "tools" / "QuarterdeckAgenda" / "main.swift").write_text("// Quarterdeck agenda\n")
    (_pr_ / "logo-quarterdeck.png").write_bytes(b"\x89PNG\0quarterdeck\0data"); (_pr_ / "state").mkdir(); (_pr_ / "state" / "runs.json").write_text("[]")
    (_pr_ / "leak.py").write_text("token = '" + _k("gh", "p_", "Z" * 36) + "'\n")
    _hx, _or = "her" + "mes", "ora" + "cle"          # spelt apart, so the public copy of this file never says it
    (_pr_ / "dashboard" / "assets").mkdir(parents=True); (_pr_ / "dashboard" / "assets" / f"ext-{_hx}.js").write_text(f"// the {_hx} add-on\n"); (_pr_ / "bin" / f"ext_{_hx}.py").write_text(f"# {_hx}\n")
    _gx("init", "-q", cwd=_pr_); _gx("add", ".", cwd=_pr_, ); _gx("commit", "-qm", "c", cwd=_pr_); (_pr_ / "uncommitted.txt").write_text("quarterdeck secret plans")
    _po = _ft / "pubout"; _st = _pb.build(_po, repo=_pr_)
    check("publish: the tree is built from what is committed, leaves out the private paths, and never includes an uncommitted or ignored file",
          not (_po / "docs" / "cloud-tasks").exists() and not (_po / "config" / "projects.json").exists() and not (_po / "state").exists() and not (_po / "uncommitted.txt").exists()
          and (_po / "config" / "projects.example.json").is_file() and _st["excluded"] == 5, _st)
    check("publish: the product is renamed in file names, folder names, settings, the command, prose and links, and an executable stays executable",
          (_po / "bin" / "quarterdeck").is_file() and not (_po / "bin" / "quarterdeck").exists() and _fo.access(_po / "bin" / "quarterdeck", _fo.X_OK)
          and "QUARTERDECK_HOME" in (_po / "bin" / "quarterdeck").read_text() and "Quarterdeck runs with QUARTERDECK_HOME" in (_po / "README.md").read_text()
          and "`quarterdeck home`" in (_po / "README.md").read_text() and "github.com/o/quarterdeck" in (_po / "README.md").read_text()
          and (_po / "tools" / "QuarterdeckAgenda" / "main.swift").read_text().startswith("// Quarterdeck"), _st)
    check("publish: a binary file is copied byte for byte (its name is renamed, its content is not touched)",
          (_po / "logo-quarterdeck.png").read_bytes() == b"\x89PNG\0quarterdeck\0data" and _pb.leftover(_po) == [], _pb.leftover(_po))
    check("publish: it refuses to write into a folder that already has files",
          _sp.run(["python3", str(pathlib.Path(d.__file__).parent / "publish.py"), "--out", str(_po)], capture_output=True, text=True).returncode == 2
          and _fo.path.exists(_po / "README.md"))
    _pp = _ft / "pubrepo2"; (_pp / "docs" / "public").mkdir(parents=True); (_pp / "docs" / "public" / "README.md").write_text("Public Quarterdeck readme\n")
    (_pp / "docs" / "public" / "LICENSE").write_text("Apache 2.0\n"); (_pp / "README.md").write_text("PRIVATE working readme about my setup\n"); (_pp / "docs" / "guide.md").write_text("guide\n")
    _gx("init", "-q", cwd=_pp); _gx("add", ".", cwd=_pp); _gx("commit", "-qm", "c", cwd=_pp); _po2 = _ft / "pubout2"; _pb.build(_po2, repo=_pp)
    check("publish: the README and licence written for strangers (docs/public/) sit at the top of the public tree and replace the working README, which never ships",
          (_po2 / "README.md").read_text() == "Public Quarterdeck readme\n" and (_po2 / "LICENSE").is_file() and not (_po2 / "docs" / "public").exists()
          and "PRIVATE" not in "".join(p.read_text() for p in _po2.rglob("*") if p.is_file()) and (_po2 / "docs" / "guide.md").is_file())
    _gh_ = _pb.guard_result(_po, None)
    _dn = _ft / "pubdeny.txt"; _dn.write_text("quarterdeck\n")      # pretend the new name were private: the check over the result must notice it
    _gn = _pb.guard_result(_po, str(_dn))
    check("publish: the check over the result finds a credential that was committed, finds a denylisted name that survived the rename, and finds neither when there is none",
          any(h[0] == "leak.py" and h[2] == "a GitHub token" for h in _gh_) and not any(h[2] == "a private name" for h in _gh_)
          and any(h[2] == "a private name" and h[0] == "README.md" for h in _gn)
          and not any(h[2] == "a private name" for h in _pb.guard_result(_po, str(_ft / "deny.txt"))), (_gh_, _gn[:2]))
    _pq = _ft / "pubrepo3"; (_pq / "docs").mkdir(parents=True); (_pq / "docs" / "notes.md").write_text(f"see the {_hx} box and {_or.capitalize()}\n"); (_pq / f"{_hx}.txt").write_text("x\n"); (_pq / "ok.md").write_text("fine\n")
    _gx("init", "-q", cwd=_pq); _gx("add", ".", cwd=_pq); _gx("commit", "-qm", "c", cwd=_pq); _po3 = _ft / "pubout3"; _pb.build(_po3, repo=_pq); _said = _pb.private_mentions(_po3)
    check("publish: add-on files (named for them) are left out, and a banned word left in a file name or a line is found, whatever its case, while a clean tree has none and nothing is patched any more",
          not (_po / "bin" / f"ext_{_hx}.py").exists() and not (_po / "dashboard" / "assets" / f"ext-{_hx}.js").exists() and _pb.private_mentions(_po) == []
          and {w for r, w in _said} == {_hx, _or} and {r for r, w in _said} == {"docs/notes.md", f"{_hx}.txt"} and not hasattr(_pb, "PATCHES"), _said)
# speech hints: your own words and corrections, from your data folder, optional
_sp_home = d.HOME; d.HOME = _ft / "sp-home"; (d.HOME / "config").mkdir(parents=True)
_before = (d.speech_hints(), d.misheard_note(), d.speech_vocab(["a"]))
(d.HOME / "config" / "speech.json").write_text(_fj.dumps({"words": ["Acme", "", 5, "x" * 90], "sounds_like": {"hair vest": "harvest", 'bad"quote': "x", "": "y"}}))
_after = (d.speech_hints(), d.misheard_note(), d.speech_vocab(["a"]))
(d.HOME / "config" / "speech.json").write_text("not json"); _bad = d.speech_hints()
d.HOME = _sp_home
check("speech hints: with no file there are none; with one, the words and the corrections reach the vocabulary and the prompt, bad entries and quotes are dropped, and a broken file is ignored",
      _before[0] == {"words": [], "sounds_like": {}} and "means harvest" not in _before[1] and _before[2][-4:] == ["Helm", "shipwright", "surveyor", "ledger"]
      and _after[0]["words"] == ["Acme", "x" * 40] and _after[0]["sounds_like"] == {"hair vest": "harvest"} and '"hair vest" means harvest' in _after[1] and "Acme" in _after[2]
      and _bad == {"words": [], "sounds_like": {}}, (_before, _after))
_dsrc = pathlib.Path(d.__file__).read_text()
_fa = _dsrc[_dsrc.index("def fleet_action"):_dsrc.index("import fleetview") if False else _dsrc.index("CLAUDE_SESSION = ")]
check("fleet route: starting or stopping needs confirm true, and the fleet view is built only for its own route, never in /api/state or the chat digest",
      "confirm is required" in _dsrc and _dsrc.count("fleet_view(") == 2 and "fleet" not in pathlib.Path(d.chatctx.__file__).read_text().lower())
_fsrc = pathlib.Path(_fv.__file__).read_text()
check("fleet module: no shell, no eval, and no read of the clipboard, screen, apps or location",
      not _re2.search(r"shell\s*=\s*True|os\.system|\beval\(|\bexec\(|pbpaste|screencapture|NSWorkspace|geolocation", _fsrc))
check("fleet demo: the invented fleet answers GET and the confirmed POST changes only the made-up state, and an unconfirmed POST is refused",
      (lambda w: w.get("/api/fleet", {})[0] == 200 and w.post("/api/fleet/action", {"source": "fleet", "job": "customs", "action": "resume"})[0] == 400
       and w.post("/api/fleet/action", {"source": "fleet", "job": "customs", "action": "resume", "confirm": True})[0] == 200
       and [j for j in w.get("/api/fleet", {})[1]["sources"][0]["jobs"] if j["id"] == "customs"][0]["state"] == "on")(d.demo.World()))

# An optional add-on brings its own checks beside this file (selftest-ext-<name>.py). They run when the file is there, so a tree without the add-on is checked without it.
import subprocess as _sp
# ---- scan: what is in a project folder, by plain code, read-only ----
import scan as _scan
import hashlib as _hl

def _mk(base, files):
    for rel, text in files.items():
        f = Path(base) / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

def _digest(base):
    h = _hl.sha256()
    for q in sorted(Path(base).rglob("*")):
        h.update(str(q.relative_to(base)).encode())
        if q.is_file():
            h.update(q.read_bytes())
    return h.hexdigest()

with _tf.TemporaryDirectory() as _sc:
    _node, _py, _empty = Path(_sc) / "shopfront", Path(_sc) / "ledgerpy", Path(_sc) / "bare"
    _empty.mkdir()
    _mk(_node, {
        "package.json": '{"scripts":{"test":"jest","build":"vite build"},"dependencies":{"react":"18"},"devDependencies":{"jest":"29","serverless":"3"}}',
        "package-lock.json": "{}", "src/app.tsx": "x", "serverless.yml": "service: a", "infra/main.tf": "x", "vercel.json": "{}",
        ".github/workflows/ci.yml": "on: push", "Dockerfile": "FROM x", "db/migrations/001.sql": "x", ".claude/agents/reviewer.md": "x", "AGENTS.md": "x",
        ".env": "TOPSECRETVALUE=hunter2-should-never-be-read", ".env.example": "KEY=", "keys/server.pem": "-----BEGIN " + "PRIVATE KEY-----",
        "node_modules/leftpad/index.js": "x", ".claude/worktrees/other/package.json": "{}"})
    _mk(_py, {"pyproject.toml": "[tool.poetry]\n[tool.poetry.dependencies]\nfastapi='*'\npytest='*'", "app/main.py": "x", "tests/test_a.py": "x", "Makefile": "test:\n\tpytest\nlint:\n\truff"})
    for _git in (_node, _py):
        (_git / ".git").mkdir()
        (_git / ".git" / "HEAD").write_text("ref: refs/heads/feat/thing\n")
        (_git / ".git" / "config").write_text('[remote "origin"]\n\turl = https://user:tok123' + "@" + 'github.com/acme/shop.git\n')
    (_node / ".env").chmod(0)                                    # unreadable: a scan that tried to open it would fail or leak
    (_node / "keys" / "server.pem").chmod(0)
    for _q in ((_node / ".env"), (_node / "keys" / "server.pem")):
        _q.chmod(0o600)
    _before = _digest(_node)
    for _q in ((_node / ".env"), (_node / "keys" / "server.pem")):
        _q.chmod(0)
    _p = _scan.scan(_node)
    for _q in ((_node / ".env"), (_node / "keys" / "server.pem")):
        _q.chmod(0o600)
    _names = lambda k: {i["name"] for i in _p[k]}
    check("scan: finds the languages, frameworks, package manager and commands of a Node project, each from its file",
          {"TypeScript"} <= _names("languages") and {"React", "Jest", "Serverless Framework"} <= _names("frameworks") and "npm" in _names("package_managers")
          and any(c.startswith("test:") for c in _names("commands")) and any(c.startswith("build:") for c in _names("commands")), _p)
    check("scan: finds CI, containers, infrastructure and deploy targets from files only",
          "GitHub Actions" in _names("ci") and "Docker" in _names("containers") and {"Terraform", "Serverless Framework"} <= _names("infrastructure")
          and {"Vercel", "AWS"} <= _names("deploy_targets"), _p)
    check("scan: every claim carries evidence", all(i["evidence"] for k in ("languages", "frameworks", "package_managers", "commands", "ci", "containers", "infrastructure", "deploy_targets", "sensitive", "secret_files", "agent_config") for i in _p[k]))
    check("scan: secret files are named, never opened (unreadable files do not stop it, and their contents appear nowhere in the profile)",
          {".env", "server.pem"} <= _names("secret_files") and ".env.example" not in _names("secret_files") and "hunter2" not in _json.dumps(_p) and "BEGIN " + "PRIVATE" not in _json.dumps(_p))
    check("scan: sensitive folders and the project's own agent set-up are noticed", "database migrations" in _names("sensitive") and {"Claude Code agents", "AGENTS.md"} <= _names("agent_config"), _p)
    check("scan: dependency folders and other checkouts are not read", not any("node_modules" in e or "worktrees" in e for k in ("languages", "frameworks") for i in _p[k] for e in i["evidence"]))
    check("scan: the branch is read whole and a credential in the remote address is dropped",
          _p["git"].get("branch") == "feat/thing" and "tok123" not in _json.dumps(_p) and _p["git"].get("origin") == "https://github.com/acme/shop.git", _p["git"])
    check("scan: scanning changes nothing in the project", _digest(_node) == _before)
    _q2 = _scan.scan(_py)
    check("scan: a Python project gets its manager, frameworks and make targets", "poetry" in {i["name"] for i in _q2["package_managers"]} and {"FastAPI", "pytest"} <= {i["name"] for i in _q2["frameworks"]}
          and {"test: make test", "lint: make lint"} <= {i["name"] for i in _q2["commands"]}, _q2)
    _e = _scan.scan(_empty)
    check("scan: an empty folder says so plainly instead of guessing", not _e["languages"] and any("verify command" in n for n in _e["notes"]) and any("not a git" in n for n in _e["notes"]))
    try:
        _scan.scan(Path(_sc) / "missing")
        _miss = False
    except ValueError:
        _miss = True
    check("scan: a folder that does not exist is refused", _miss)
    _src = (ROOT / "bin" / "scan.py").read_text()
    check("scan: no network, no shell, no model", not any(w in _src for w in ("urllib", "socket", "subprocess", "os.system", "claude_run", "requests")))

# ---- attach: scan, propose, register only on --apply ----
import attach as _attach
with _tf.TemporaryDirectory() as _at:
    _proj, _bare = Path(_at) / "shopfront", Path(_at) / "notes"
    _mk(_proj, {"package.json": '{"scripts":{"test":"jest"}}', "db/migrations/1.sql": "x", ".env": "A=1", "infra/prod/main.tf": "x"})
    _mk(_bare, {"README.md": "hi"})
    (_proj / ".git" / "refs" / "heads").mkdir(parents=True)
    (_proj / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (_proj / ".git" / "refs" / "heads" / "main").write_text("0" * 40)
    (_proj / ".git" / "config").write_text('[remote "origin"]\n\turl = https://github.com/acme/shopfront.git\n')
    _pf = _scan.scan(_proj)
    _pr = _attach.propose(_pf)
    _en = _pr["entry"]
    check("attach: the proposal takes repo, branch and verify command from the scan and adds the Shipwright because there is a way to prove its work",
          _en["repo"] == "acme/shopfront" and _en["default_branch"] == "main" and _en["verify"] == "npm test" and "shipwright" in _en["duties"] and _pr["name"] == "shopfront", _pr)
    check("attach: sensitive folders, secret files and production infrastructure become forbidden paths",
          {"db/migrations/", ".env", "infra/prod/"} <= set(_en["forbidden_paths"]), _en["forbidden_paths"])
    check("attach: a project with no test command gets read-only duties only", "shipwright" not in _attach.propose(_scan.scan(_bare))["entry"]["duties"])
    _snap = _digest(_proj)
    _regf = Path(_at) / "reg" / "projects.json"
    check("attach: showing a proposal registers nothing", not _regf.exists() and _digest(_proj) == _snap)
    _attach.apply(_pr, _pf, _regf)
    _got = _json.loads(_regf.read_text())
    _rec = _json.loads((_scan.profile_dir() / "shopfront.attach.json").read_text())
    check("attach: --apply registers the project, keeps the profile and a record of what was proposed and approved, and leaves the project alone",
          "shopfront" in _got and _got["shopfront"]["verify"] == "npm test" and _rec["approved"] == _rec["proposed"] and (_scan.profile_dir() / "shopfront.json").exists() and _digest(_proj) == _snap)
    try:
        _attach.apply(_pr, _pf, _regf)
        _dup = False
    except ValueError:
        _dup = True
    check("attach: a name that is already registered is refused, not overwritten", _dup)
    (_scan.profile_dir() / "shopfront.json").unlink()
    (_scan.profile_dir() / "shopfront.attach.json").unlink()

# ---- the dashboard's attach endpoint: looks freely, registers only when confirmed ----
with _tf.TemporaryDirectory() as _ad:
    _app = Path(_ad) / "tidy-app"
    _mk(_app, {"package.json": '{"scripts":{"test":"vitest"}}'})
    _oldpf, d.PROJECTS_FILE = d.PROJECTS_FILE, Path(_ad) / "reg.json"
    try:
        _c1, _b1 = d.attach_api({})
        _c2, _b2 = d.attach_api({"path": str(Path(_ad) / "nope")})
        _c3, _b3 = d.attach_api({"path": str(_app)})
        _c4, _b4 = d.attach_api({"path": str(_app), "apply": True})
        _none = not d.PROJECTS_FILE.exists()
        _c5, _b5 = d.attach_api({"path": str(_app), "apply": True, "confirm": True, "name": "Tidy-App"})
        _c6, _b6 = d.attach_api({"path": str(_app), "apply": True, "confirm": True, "name": "Tidy-App"})
        check("attach endpoint: no folder, or a folder that is not there, is a plain 400", _c1 == 400 and _c2 == 400 and "not a folder" in _b2["error"])
        check("attach endpoint: looking returns the profile and the proposal and registers nothing", _c3 == 200 and _b3["proposal"]["entry"]["verify"] == "npm test" and not _b3["applied"])
        check("attach endpoint: applying without confirm is refused and nothing is written", _c4 == 400 and "confirm" in _b4["error"] and _none)
        check("attach endpoint: with confirm the project is registered under the lowercase name; a second time is refused",
              _c5 == 200 and "tidy-app" in _json.loads(d.PROJECTS_FILE.read_text()) and _c6 == 400 and "already registered" in _b6["error"])
        for _f in (_scan.profile_dir() / "tidy-app.json", _scan.profile_dir() / "tidy-app.attach.json"):
            _f.unlink(missing_ok=True)
    finally:
        d.PROJECTS_FILE = _oldpf
    _attach_log = (d.LOGS / "attach.log")
    _attach_log.unlink(missing_ok=True)

# ---- every registered project shows its agents and work with nothing to configure ----
with _tf.TemporaryDirectory() as _fd:
    _fd = Path(_fd)
    for _n in ("alpha", "beta", "gamma"):
        (_fd / _n / ".git").mkdir(parents=True)
    (_fd / "alpha" / ".claude" / "agents").mkdir(parents=True)
    (_fd / "alpha" / ".claude" / "agents" / "scout.md").write_text("---\nname: scout\ndescription: looks around\n---\nbody")
    (_fd / "delta").mkdir()                                   # registered but not a git checkout
    _reg = _fd / "projects.json"
    _reg.write_text(_json.dumps({n: {"repo": f"acme/{n}", "path": str(_fd / n), "summary": f"the {n} app", "duties": ["surveyor", "foreman"]} for n in ("alpha", "beta", "gamma", "delta")}))
    _lst = _fd / "fleet.local.json"
    _lst.write_text(_json.dumps({"sources": [{"id": "gamma-fleet", "kind": "repo-agents", "path": str(_fd / "gamma"), "project": "gamma", "title": "Gamma by hand"}]}))
    _oc, _or = _fv.CONFIG, _fv.REGISTRY
    _fv.CONFIG, _fv.REGISTRY = _lst, _reg
    try:
        _cfg = _fv.load_config()
        _ids = {s["id"]: s for s in _cfg["sources"]}
        check("fleet: a registered project with a git checkout gets a source without any configuration; a listed one is not doubled; a non-checkout is skipped",
              set(_ids) == {"alpha", "beta", "gamma-fleet"} and _ids["alpha"]["implicit"] and not _ids["gamma-fleet"]["implicit"] and not _cfg["errors"], list(_ids))
        _st = {x["id"]: x for x in _fv.snapshot(_cfg, runner=lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})())["sources"]}
        check("fleet: it says whether a project runs its own agents or the built-in crew",
              _st["alpha"]["runs"] == "own" and _st["beta"]["runs"] == "crew" and _st["beta"]["crew"] == ["surveyor", "foreman"] and _st["gamma-fleet"]["runs"] == "none", {k: v["runs"] for k, v in _st.items()})
        check("fleet: only a project with agents of its own sends the project picker to the Fleet page", _fv.projects(_cfg) == ["alpha", "gamma"], _fv.projects(_cfg))
        check("fleet: an explicit config path never picks up the registry", _fv.load_config(_lst)["sources"][0]["id"] == "gamma-fleet" and len(_fv.load_config(_lst)["sources"]) == 1)
    finally:
        _fv.CONFIG, _fv.REGISTRY = _oc, _or

# ---- connections: manifests, status, and a credential store that never gives a value back ----
from integrations import manifest as _mf, common as _cm
with _tf.TemporaryDirectory() as _cd:
    _cd = Path(_cd)
    _oc = (_cm.CONFIG_DIR, _cm.HOME, _cm.STATE)
    _cm.CONFIG_DIR, _cm.HOME, _cm.STATE = _cd / "cfg", _cd / "home", _cd / "home" / "state"
    try:
        (_cd / "extra").mkdir()
        (_cd / "extra" / "newsvc.json").write_text(_json.dumps({"id": "newsvc", "label": "New service", "what": "x", "credentials": [{"key": "NEWSVC_TOKEN", "label": "Token"}], "steps": ["one"]}))
        (_cd / "extra" / "bad.json").write_text(_json.dumps({"id": "Bad Id!", "credentials": []}))
        (_cd / "extra" / "badkey.json").write_text(_json.dumps({"id": "badkey", "credentials": [{"key": "lower-case"}]}))
        (_cd / "extra" / "broken.json").write_text("{not json")
        _svc = _mf.load_services(_cd / "extra")
        _ids = {x["id"] for x in _svc}
        check("manifests: the built-in services load, a service of your own is added by adding a file, and bad files are skipped without a crash",
              {"ga4", "gmail", "slack", "meta", "linkedin", "calendar", "newsvc"} <= _ids and not ({"badkey"} & _ids) and not any(" " in i for i in _ids), sorted(_ids))
        check("manifests: every built-in credential is a plain key name and every service has steps", all(_mf.SAFE_KEY.match(c["key"]) for x in _svc for c in x["credentials"]) and all(x["steps"] for x in _svc))
        _rows = {r["id"]: r for r in _mf.status(_svc)}
        check("connections: with nothing set up every feed is off and the helper app is not claimed to work", _rows["slack"]["state"] == "off" and _rows["calendar"]["state"] == "ready", {k: v["state"] for k, v in _rows.items()})
        check("connections: a missing credential is named, never filled in", _mf.set_enabled("slack", True) and {r["id"]: r for r in _mf.status(_svc)}["slack"]["state"] == "needs set-up"
              and {r["id"]: r for r in _mf.status(_svc)}["slack"]["missing"] == ["SLACK_USER_TOKEN"])
        _secret = "xoxp-" + "123456789-" + "abcdefghij"
        _mf.set_credential("SLACK_USER_TOKEN", _secret, _svc)
        _st = {r["id"]: r for r in _mf.status(_svc)}["slack"]
        _envp = _cm.env_path()
        check("connections: once the credential is saved the feed is ready, and the status never carries the value",
              _st["state"] == "ready" and _st["credentials"][0]["present"] and _secret not in _json.dumps(_mf.status(_svc)), _st["state"])
        check("connections: the store is owner-only, and its folder too", oct(_envp.stat().st_mode & 0o777) == "0o600" and oct(_envp.parent.stat().st_mode & 0o777) == "0o700")
        _envp.write_text("# mine\nOTHER_THING=keep-me\n" + _envp.read_text())
        _mf.set_credential("SLACK_USER_TOKEN", "new-value-two", _svc)
        _txt = _envp.read_text()
        check("connections: replacing a value keeps the other lines and leaves one entry for the key", "OTHER_THING=keep-me" in _txt and _txt.count("SLACK_USER_TOKEN=") == 1 and "new-value-two" in _txt and _secret not in _txt)
        _mf.set_credential("SLACK_USER_TOKEN", "", _svc)
        check("connections: an empty value removes the credential", "SLACK_USER_TOKEN" not in _envp.read_text() and "SLACK_USER_TOKEN" in {r["id"] and m for r in _mf.status(_svc) for m in r["missing"]})
        _bad = []
        for _k, _v in (("NOT_A_KEY", "x"), ("SLACK_USER_TOKEN", "two\nlines"), ("SLACK_USER_TOKEN", "x" * 4001)):
            try:
                _mf.set_credential(_k, _v, _svc)
                _bad.append((_k, "accepted"))
            except ValueError:
                pass
        check("connections: only keys a service asks for are accepted, as one short line", not _bad, _bad)
        (_cm.HOME / "config").mkdir(parents=True, exist_ok=True)
        (_cm.HOME / "config" / "integrations.json").write_text(_json.dumps({"ga4": {"property_id": "42"}, "sources": {"gmail": {"enabled": False, "minutes": 7}}}))
        _mf.set_enabled("gmail", True, _svc)
        _cfgj = _json.loads((_cm.HOME / "config" / "integrations.json").read_text())
        check("connections: switching a feed on keeps the rest of the config", _cfgj["sources"]["gmail"] == {"enabled": True, "minutes": 7} and _cfgj["ga4"]["property_id"] == "42")
        _od = (d.LOGS, d.PROJECTS_FILE)
        d.LOGS = _cd / "logs"
        _c1, _ = d.connections_api({"action": "enable", "id": "gmail", "on": True})
        _c2, _b2 = d.connections_api({"action": "credential", "key": "SLACK_USER_TOKEN", "value": "log-me-not", "confirm": True})
        _c3, _ = d.connections_api({"action": "credential", "key": "NOT_A_KEY", "value": "x", "confirm": True})
        _logtxt = (d.LOGS / "connections.log").read_text() if (d.LOGS / "connections.log").exists() else ""
        check("connections endpoint: nothing changes without confirm, unknown keys are refused, the answer and the log never hold the value",
              _c1 == 400 and _c2 == 200 and _c3 == 400 and "log-me-not" not in _json.dumps(_b2) and "log-me-not" not in _logtxt and "credential" in _logtxt, (_c1, _c2, _c3, _b2, _logtxt))
        d.LOGS = _od[0]
        _src = (ROOT / "bin" / "integrations" / "manifest.py").read_text()
        check("connections: the manifest module makes no network call and starts no process", not any(w in _src for w in ("urllib", "socket", "subprocess", "os.system")))
    finally:
        _cm.CONFIG_DIR, _cm.HOME, _cm.STATE = _oc

# ---- newproject: start something new, writing only inside the new folder ----
import newproject as _np
with _tf.TemporaryDirectory() as _nd:
    _nd = Path(_nd)
    _made = _np.create("fresh-app", _nd, "  A   tidy\napp  ")
    check("new: makes a git repository with a README that says what it is for and a .gitignore that keeps secrets out",
          (_made / ".git").is_dir() and "A tidy app" in (_made / "README.md").read_text() and ".env" in (_made / ".gitignore").read_text() and sorted(p.name for p in _nd.iterdir()) == ["fresh-app"])
    _errs = []
    for _args in (("fresh-app", _nd), ("../escape", _nd), ("", _nd), ("has space", _nd)):
        try:
            _np.create(*_args)
            _errs.append(_args)
        except ValueError:
            pass
    check("new: a folder that already has things in it, a path that climbs out, an empty name and a name with spaces are all refused", not _errs, _errs)
    (_nd / "empty").mkdir()
    check("new: an existing empty folder is fine", (_np.create("empty", _nd) / ".git").is_dir())
    _c0, _ = d.newproject_api({"name": "no-confirm", "folder": str(_nd)})
    _c1, _b1 = d.newproject_api({"name": "via-api", "folder": str(_nd), "confirm": True, "about": "x"})
    _c2, _ = d.newproject_api({"name": "via-api", "folder": str(_nd), "confirm": True})
    check("new endpoint: nothing is created without confirm, a created project is reported by path, a second try is refused",
          _c0 == 400 and not (_nd / "no-confirm").exists() and _c1 == 200 and _b1["path"] == str(_nd / "via-api") and _c2 == 400)
    _snp = (ROOT / "bin" / "newproject.py").read_text()
    check("new: no network and no shell, git only", "urllib" not in _snp and "socket" not in _snp and "shell=True" not in _snp and "os.system" not in _snp)

# ---- settings: facts only, no secrets ----
_sv_ = d.settings_view()
check("settings: the data folder, program folder, run defaults and version are reported, read-only",
      {"data_folder", "program_folder", "dry_run", "model", "sandbox", "commit", "uptime_seconds", "projects"} <= set(_sv_) and _sv_["data_folder"] == str(d.HOME) and isinstance(_sv_["dry_run"], bool))
_sv_txt = _json.dumps(_sv_)
check("settings: nothing that looks like a credential or a token is in it", "TOKEN" not in _sv_txt and not any(w in _sv_txt.lower() for w in ("password", "secret", "api_key")) and d.TOKEN not in _sv_txt)

# ---- packs: stack knowledge, plugged in ----
import packs as _pk
_pl = _pk.load()
check("packs: the built-in packs load, each with matches and a note that is not empty or huge",
      {"typescript-node", "python"} <= {p["id"] for p in _pl} and all(p["knowledge"] and len(p["knowledge"]) <= _pk.MAX_KNOWLEDGE and any(p["match"].values()) for p in _pl))
_fitp = _pk.select({"languages": [{"name": "TypeScript", "evidence": ["x"]}], "frameworks": [{"name": "React", "evidence": ["x"]}], "package_managers": [{"name": "npm", "evidence": ["x"]}]}, _pl)
check("packs: a TypeScript project fits the TypeScript pack and not the Python one, with what matched", [p["id"] for p, _ in _fitp] == ["typescript-node"] and len(_fitp[0][1]) == 3, _fitp)
check("packs: nothing in the profile means no pack", _pk.select({}, _pl) == [])
with _tf.TemporaryDirectory() as _pd:
    _pd = Path(_pd)
    for _id, _ok in (("mine", True), ("nomatch", False), ("bad id", False), ("noknowledge", False)):
        (_pd / _id).mkdir()
        (_pd / _id / "pack.json").write_text(_json.dumps({"id": _id, "match": {"languages": ["Go"] if _id != "nomatch" else []}}))
        if _id != "noknowledge":
            (_pd / _id / "knowledge.md").write_text("Run go vet.\n")
    (_pd / "broken").mkdir(); (_pd / "broken" / "pack.json").write_text("{nope")
    _got = {p["id"] for p in _pk.load(_pd)}
    check("packs: a pack of your own is added by adding a folder; one with no match, a bad id, no note or broken JSON is skipped", _got == {"mine"}, _got)
check("packs: text puts the label above each note and skips unknown ids", _pk.text(["python", "nope"], _pl).startswith("## Stack notes: Python") and "nope" not in _pk.text(["python", "nope"], _pl))
_src = (ROOT / "bin" / "packs.py").read_text()
check("packs: no network, no shell, no model", not any(w in _src for w in ("urllib", "socket", "subprocess", "os.system", "claude_run")))
_byid = {p["id"]: p for p in _pl}
check("packs: the cloud packs load, carry a plain statement of what was tested, and keep their note inside the cap",
      {"aws", "vercel-supabase"} <= set(_byid) and all(_byid[i]["tested"] and len(_byid[i]["knowledge"]) <= _pk.MAX_KNOWLEDGE for i in ("aws", "vercel-supabase")), {i: len(_byid[i]["knowledge"]) for i in ("aws", "vercel-supabase")})
_fa = _pk.select({"infrastructure": [{"name": "Terraform", "evidence": ["x"]}]}, _pl)
_fv = _pk.select({"deploy_targets": [{"name": "Supabase", "evidence": ["x"]}, {"name": "Vercel", "evidence": ["x"]}]}, _pl)
check("packs: Terraform fits the AWS pack, Vercel or Supabase fits the Vercel and Supabase pack, and neither fits the other",
      [p["id"] for p, _ in _fa] == ["aws"] and [p["id"] for p, _ in _fv] == ["vercel-supabase"], (_fa, _fv))
check("packs: list prints what was tested", "tested:" in _sp.run([sys.executable, str(ROOT / "bin" / "packs.py"), "list"], capture_output=True, text=True).stdout)
with _tf.TemporaryDirectory() as _id_dir:
    _r = Path(_id_dir)
    for _f, _t in (("main.tf", "resource {}"), ("terraform.tfvars", "pw=1"), ("README.md", "x"), ("t/template.yaml", "AWSTemplateFormatVersion: x"), ("t/other.yaml", "a: 1"), ("lib/s.ts", "import {} from 'aws-cdk-lib'"),
                   ("lib/u.ts", "export const x = 1"), ("serverless.yml", "service: a"), ("vercel.json", "{}"), ("supabase/migrations/1.sql", "select 1"), (".env.local", "K=1")):
        (_r / _f).parent.mkdir(parents=True, exist_ok=True); (_r / _f).write_text(_t)
    _got, _skip = _scan.infra_changed(_r, ["main.tf", "terraform.tfvars", "README.md", "t/template.yaml", "t/other.yaml", "lib/s.ts", "lib/u.ts", "serverless.yml", "vercel.json", "supabase/migrations/1.sql", ".env.local", "gone/old.tf"])
    check("infra: the changed files that are infrastructure are found by the scan's own names, secret-looking ones are named and never opened, and a deleted .tf still counts",
          dict(_got) == {"main.tf": "Terraform", "t/template.yaml": "AWS CloudFormation / SAM", "lib/s.ts": "AWS CDK", "serverless.yml": "Serverless Framework", "vercel.json": "Vercel", "supabase/migrations/1.sql": "Supabase", "gone/old.tf": "Terraform"}
          and sorted(_skip) == [".env.local", "terraform.tfvars"], (_got, _skip))
check("attach: the proposal names the stack packs that fit", _attach.propose(_scan.scan(ROOT))["entry"]["packs"] == ["python"])

# ---- theme: light tokens exist, every token used is defined, no raw colours outside the token blocks ----
# One scheme: the semantic tokens in assets/ui.css (dark by default, a light block as an explicit choice and as the OS default).
import re as _re
_dh = (ROOT / "dashboard" / "index.html").read_text() + (ROOT / "dashboard" / "assets" / "ui.css").read_text()
_rh = (ROOT / "dashboard" / "assets" / "rhythm-ui.js").read_text()
_decl = _re.compile(r"--[\w-]+\s*:\s*#[0-9a-fA-F]{3,8}")
_rawhex = _re.compile(r"(?<![\w&%-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")
_lt_blocks = _re.findall(r':root\[data-theme="light"\]\{([^}]*)\}', _dh)
_lt_media = _re.findall(r'prefers-color-scheme:light\)\{:root:not\(\[data-theme="dark"\]\)\{([^}]*)\}', _dh)
_dk_block = _re.search(r":root,\.brain-host\{([^}]*)\}", _dh)
check("theme: a light token block exists, as an explicit choice and as the OS default (not applied over an explicit dark)",
      len(_lt_blocks) == 1 and len(_lt_media) == 1 and _lt_blocks[0] == _lt_media[0] and "color-scheme:light" in _lt_blocks[0] and "color-scheme:dark" in (_dk_block.group(1) if _dk_block else ""))
_defined = set(_re.findall(r"(--[\w-]+)\s*:", _dh + _rh))
_used = set(_re.findall(r"var\((--[\w-]+)\s*\)", _dh + _rh))
check("theme: every var(--x) used without a fallback is defined", not (_used - _defined), str(sorted(_used - _defined)[:8]))
_dead = _sp.run([sys.executable, str(ROOT / "bin" / "ui-dead-css.py"), str(ROOT / "dashboard")], capture_output=True, text=True)
check("ui.css defines no class that no markup uses (bin/ui-dead-css.py reads index.html and assets/*.js)", _dead.returncode == 0, _dead.stdout.strip()[:200])
_dkv = dict(_re.findall(r"(--[\w-]+):([^;]+);", _dk_block.group(1))) if _dk_block else {}
_ltv = dict(_re.findall(r"(--[\w-]+):([^;]+);", _lt_blocks[0])) if _lt_blocks else {}
_colour = {k for k, v in _dkv.items() if v.strip().startswith(("#", "rgba("))}
check("theme: every colour token has a dark and a light value", _colour and _colour <= set(_ltv), str(sorted(_colour - set(_ltv))[:8]))
_lp = {"--bg", "--card", "--card2", "--raised", "--line", "--line-2", "--ink", "--ink-2", "--dim", "--dimmer", "--accent", "--accent-ink", "--accent-bg", "--ok", "--bad", "--await"}
check("theme: the light block redefines the whole palette", _lp <= set(_ltv))
_stray = _rawhex.findall(_decl.sub("", _dh)) + _rawhex.findall(_decl.sub("", _rh))
check("theme: no raw hex colour outside the token blocks (dashboard page, stylesheet and My rhythm)", not _stray, str(_stray[:6]))
check("theme: Settings has the Theme control and it persists under quarterdeck.theme", "setTheme(selVal(el))" in _dh and 'localStorage.setItem("quarterdeck.theme"' in _dh)

# ---- mission focus: the pipeline is read from the record, never guessed ----
_tx = {"id": "pp", "project": "alpha", "discipline": "design", "status": "done", "headline": "Two things to fix", "seats": [{"name": "a"}],
       "items": [{"id": 1, "seat": "surveyor", "title": "t1"}], "stances": [{"id": 1, "by": "signaller", "stance": "dispute", "note": "too broad"}],
       "ruling": [{"title": "Fix one", "kind": "change", "tier": "routine", "claim": "c", "where": "w", "action": "a"},
                  {"title": "Pick a voice", "kind": "decision", "claim": "three tones", "where": "copy", "action": "decide once"}]}
_fx = {"pp#1": {"project": "alpha", "panel": "pp", "item": 1, "title": "Fix one", "status": "running", "step": "building", "issue": 5, "plan": "p.md",
                "started": "2026-01-01T00:00:00Z", "pr": None, "verdict": None, "fixrun": "fr1"}}
_m = lambda mid, fixes=None, runs=(), inbox=(), q=None: d.compose_mission(mid, lambda i: _tx if i == "pp" else None, _fx if fixes is None else fixes, list(runs), list(inbox), q or {})
_states = lambda m: [n["state"] for n in m["pipeline"]]
_r = _m("fix:pp#1")
check("mission: a running fix shows Brief and Panel done, Build active, the rest not started",
      _r["state"] == "running" and _states(_r) == ["done", "done", "active", "notstarted", "notstarted"])
_pr = {**_fx["pp#1"], "status": "pr", "step": None, "pr": "https://github.com/x/y/pull/9", "verdict": "PROVEN"}
_r = _m("fix:pp#1", {"pp#1": _pr})
check("mission: an open pull request with a verdict is awaiting you at Review, and the proof does not claim a commit",
      _r["state"] == "awaiting" and _states(_r) == ["done", "done", "done", "done", "awaiting"] and "does not say which commit" in _r["evidence"]["proof"])
check("mission: a pull request with no verdict shows Verify as skipped, never done",
      _states(_m("fix:pp#1", {"pp#1": {**_pr, "verdict": "skipped: inspector busy"}}))[3] == "skipped")
check("mission: a merged fix is done at every node", _states(_m("fix:pp#1", {"pp#1": {**_pr, "status": "merged"}})) == ["done"] * 5)
_r = _m("fix:pp#1", {"pp#1": {**_fx["pp#1"], "status": "blocked", "step": None, "plan": None, "detail": "the dev panel wrote no plan"}})
check("mission: a blocked fix names the first missing node and the cause, and a rerun is meaningful",
      _r["state"] == "blocked" and _states(_r) == ["done", "blocked", "notstarted", "notstarted", "notstarted"]
      and _r["blocker"]["cause"] == "the dev panel wrote no plan" and _r["blocker"]["rerun"] is True and _r["blocker"]["cls"] is None)
check("mission: a record that did not come from the pipeline has no pipeline to show",
      _m("fix:pp#1", {"pp#1": {"project": "alpha", "panel": "pp", "item": 1, "status": "merged", "pr": "u"}})["pipeline"] is None)
_r = _m("fix:pp#2", {})
check("mission: a ruling item nobody started is idle, not started, and a decision item is awaiting you with no invented options",
      _r["state"] == "awaiting" and _r["decision"]["options"] == [] and _r["decision"]["title"] == "Pick a voice" and _states(_r)[1:] == ["notstarted"] * 4)
_r = _m("panel:pp")
check("mission: a panel lists its ruling items, its disputes in the seat's words, and an open decision",
      len(_r["items"]) == 2 and _r["disputes"][0]["note"] == "too broad" and _r["state"] == "awaiting" and _r["pipeline"][1]["state"] == "done")
check("mission: unknown, malformed and path-like ids name nothing",
      all(_m(x) is None for x in ("", "fix:nope#1", "fix:../x#1", "fix:pp#x", "panel:../../etc", "zzz:1", "run:1|a|b")))
_run = {"at": "2026-01-01T00:00:00Z", "project": "alpha", "duty": "surveyor", "verdict": "ERROR", "detail": "boom"}
_r = _m("run:2026-01-01T00:00:00Z|alpha|surveyor", runs=[_run])
check("mission: a failed ledger run is blocked with its cause and no rerun offered; it has no pipeline",
      _r["state"] == "blocked" and _r["pipeline"] is None and _r["blocker"]["cause"] == "boom" and _r["blocker"]["rerun"] is False)
_r = _m("run:2026-01-01T00:00:00Z|alpha|shipwright", runs=[{**_run, "duty": "shipwright", "fixrun": "fr1"}])
check("mission: a ledger run that belongs to a fix opens that fix", _r["id"] == "fix:pp#1")
_r = _m("attn:remote:scout:job_failed", inbox=[{"id": "remote:scout:job_failed", "label": "Remote · scout", "text": "no key", "blocker": "config", "place": "remote"}])
check("mission: a configuration blocker offers Inspect blocker (a class and a place), never a rerun",
      _r["blocker"]["cls"] == "config" and _r["blocker"]["rerun"] is False and _r["blocker"]["place"] == "remote")

# ---- mission focus: a `quarterdeck cycle` run record is a mission too (read only; the dashboard cannot start one) ----
def _cst(sid, title, duty, state, verdict, cost, detail=""):
    return {"id": sid, "title": title, "duty": duty, "state": state, "verdict": verdict, "detail": detail, "cost": cost, "url": "", "runs": ["r"],
            "started": "2026-01-01T00:00:00Z", "finished": "2026-01-01T00:01:00Z"}
_cy = {"kind": "cycle", "id": "cyc-a-7-1", "project": "alpha", "issue": 7, "title": "Add a Reset button", "apply": True, "status": "awaiting-review",
       "final": "u is open with no open findings.", "pr": "https://github.com/x/y/pull/9", "cost": 3.5, "seconds": 600, "notes": [],
       "stages": [_cst("purser", "Purser", "purser", "done", "READY", 0.5), _cst("panel", "Dev panel", "panel", "done", "RULED", 1.0),
                  _cst("shipwright", "Shipwright", "shipwright", "done", "PR", 0.8), _cst("r1:surveyor", "Surveyor (round 1)", "surveyor", "done", "CLEAN", 0.4),
                  _cst("r1:pilot", "Pilot (round 1)", "pilot", "skipped", "SKIPPED", 0, "no qa.start"), _cst("r1:inspector", "Inspector (round 1)", "inspector", "done", "PROVEN", 0.8),
                  {"id": "human", "title": "Human review", "duty": "human", "state": "waiting", "verdict": "WAITING", "cost": 0, "runs": [], "detail": ""}]}
_mcy = lambda rec, mid="cycle:cyc-a-7-1": d.compose_mission(mid, lambda i: None, {}, [], [], {}, get_cycle=lambda c: rec if c == "cyc-a-7-1" else None)
_r = _mcy(_cy)
check("cycle: a finished cycle is awaiting you, with the five nodes read from its stages and the pull request as evidence",
      _r["state"] == "awaiting" and _states(_r) == ["done", "done", "done", "notstarted", "awaiting"]
      and [n["id"] for n in _r["pipeline"]] == ["brief", "build", "review", "seal", "human"] and _r["evidence"]["pr"].endswith("/pull/9")
      and _r["blocker"] is None and _r["detail"]["title"] == "Waiting for you")
check("cycle: each node carries its verdicts and its cost; a stage that was not run is not claimed", _r["pipeline"][2]["note"] == "CLEAN, PROVEN · $1.20"
      and _r["pipeline"][3]["state"] == "notstarted" and _r["pipeline"][3]["note"] == "" and _r["pipeline"][0]["note"] == "READY, RULED · $1.50")
check("cycle: the history is one row per stage, with its cost and its reason in the detail, and the cost adds up to the total",
      len(_r["history"]) == 7 and _r["history"][4]["verdict"] == "SKIPPED" and "no qa.start" in _r["history"][4]["detail"] and _r["history"][0]["detail"].startswith("$0.50")
      and "$3.50" in _r["evidence"]["proof"])
_r = _mcy({**_cy, "status": "stopped-cap", "final": "stopped at the cap: $119.99 of today's $120 is spent, so the next stage (assayer) was not started.", "pr": "u",
           "stages": _cy["stages"][:3]})
check("cycle: a cycle stopped at the cap is blocked, says so in its own words, and the next group is the one marked blocked; nothing offers a rerun",
      _r["state"] == "blocked" and "stopped at the cap" in _r["blocker"]["cause"] and _r["blocker"]["rerun"] is False and _states(_r)[1] == "done" and _states(_r)[2] == "blocked"
      and _r["pipeline"][2]["note"].startswith("Not started"))
_r = _mcy({**_cy, "status": "failed", "stages": _cy["stages"][:2] + [{**_cst("shipwright", "Shipwright", "shipwright", "failed", "ERROR", 0.2), "detail": "run failed"}]})
check("cycle: a failed stage marks its group blocked and the cycle blocked", _r["state"] == "blocked" and _states(_r)[1] == "blocked")
_r = _mcy({**_cy, "status": "needs-human", "final": "3 finding(s) are still open after 3 caulker cycle(s).",
           "stages": _cy["stages"] + [_cst("caulk1", "Caulker (cycle 1)", "caulker", "done", "SEALED", 0.5), _cst("caulk-handoff", "Caulker (hand-over)", "caulker", "done", "NEEDS_HUMAN", 0)]})
check("cycle: a hand-over to a person shows the Seal group as the blocked one", _r["state"] == "blocked" and _states(_r)[3] == "blocked" and "still open" in _r["blocker"]["cause"])
check("cycle: a report-only record is done and claims no stage it did not run",
      _states(_mcy({**_cy, "status": "report-only", "apply": False, "final": "report only", "pr": None, "stages": _cy["stages"][:2]
                    + [{**_cst("shipwright", "Shipwright", "shipwright", "would", "WOULD", 0), "state": "would"}]}))[2:] == ["notstarted"] * 3)
check("cycle: unknown, malformed and path-like cycle ids name nothing; without a reader there is nothing to show",
      all(_mcy(_cy, x) is None for x in ("cycle:nope", "cycle:../x", "cycle:", "cycle:a/b")) and d.compose_mission("cycle:cyc-a-7-1", lambda i: None, {}, [], [], {}) is None)
_td = _tf.mkdtemp()
_saved = d.relocate_state(Path(_td))
try:
    (Path(_td) / "cycles").mkdir()
    (Path(_td) / "cycles" / "cyc-a-7-1.json").write_text(_json.dumps({**_cy, "status": "running", "finished": None, "final": ""}))
    (Path(_td) / "cycles" / "alpha-pr9.json").write_text(_json.dumps({"pr": 9, "cycles": 1, "history": []}))
    (Path(_td) / "cycles" / "cyc-b-1-1.json").write_text("{not json")
    _live = {"cycle-alpha-7": {"pid": 1}}
    check("cycle: a running record with no live lock is shown as failed (the process was killed); with its lock it still runs",
          d.cycle_record("cyc-a-7-1", {})["status"] == "failed" and "resume" in d.cycle_record("cyc-a-7-1", {})["final"] and d.cycle_record("cyc-a-7-1", _live)["status"] == "running")
    check("cycle: the list holds cycle records only: the caulker's own counters and a broken file are skipped",
          [c["id"] for c in d.cycles_summary({})] == ["cyc-a-7-1"] and d.cycles_summary({})[0]["cost"] == 3.5)
    check("cycle: a path-like id reads nothing from disk", d.cycle_record("../panels/x", {}) is None and d.cycle_record("cyc-a-7-1/../../x", {}) is None)
finally:
    d.restore_state(_saved)
check("cycle: the dashboard cannot start one: a cycle is not a duty, so no run button, schedule or mission step can name it",
      "cycle" not in {x["name"] for x in d.duty_list()} and not (ROOT / "duties" / "cycle.sh").exists())
_dw = _dm.World(clock=lambda: 1000.0); _dst = _dw.state()
check("cycle: the demo world has invented cycle records, listed in the state, with the project flag and no real names",
      len(_dst["cycles"]) == 2 and any(c["status"] == "awaiting-review" for c in _dst["cycles"]) and any(c["status"] == "stopped-cap" for c in _dst["cycles"])
      and any(p["cycle"] for p in _dst["projects"]) and all(c["project"] in _dm.PROJECTS for c in _dst["cycles"]))
_dc = next(c for c in _dst["cycles"] if c["status"] == "awaiting-review")
_rd = d.compose_mission("cycle:" + _dc["id"], _dw.panel_transcript, _dst["fixes"], _dst["runs"], _dst["inbox"], _dst["fixqueue"], get_cycle=_dw.cycle_record)
check("cycle: the demo cycle opens as a mission, read through the same function as a real one; its stage costs add up to the cycle's cost",
      _rd and _rd["state"] == "awaiting" and len(_rd["history"]) == 14 and abs(sum(float(h["detail"].split(" ")[0].lstrip("$")) for h in _rd["history"] if h["detail"].startswith("$")) - _dc["cost"]) < 0.02)
_idx_cy = (ROOT / "dashboard" / "index.html").read_text()
check("cycle: the Mission list reads S.cycles and the page has no control that starts, resumes or stops a cycle",
      "S.cycles" in _idx_cy and "cycle:" in _idx_cy and not _re.search(r"post\(\"/api/[a-z]+\", *\{[^}]*cycle", _idx_cy) and "quarterdeck cycle --resume" not in _idx_cy)

# ---- showcase case study: nothing private survives the sanitizing step ----
_dirty = ("see /Users/bob/Projects/x/a.py, ~/notes/b.md and C:\\Users\\bob\\x.txt; https://git.corp.example.com/x/pull/3; token=ghp_abcdefghijklmnop1234; "
          "Authorization: Bearer abcdef123456789; host 10.0.0.5:8080 and bob-mac.local and app.mycorp.io; by @alice; sk-abcdefghijklmnopqrstuvwx")
_clean = d.sanitize_public(_dirty, ["bob"])
check("sanitize: absolute paths, links, hosts, handles, tokens and the owner's name are all removed",
      not any(x in _clean for x in ("/Users", "bob", "ghp_", "corp.example", "10.0.0.5", "mycorp", "@alice", "abcdef123456789", "sk-abc", "C:\\")), _clean)
check("sanitize: relative paths, file names and CSS rules in a diff are kept",
      d.sanitize_public("src/styles/tokens.css", []) == "src/styles/tokens.css" and d.sanitize_public("@media (x) { }", [], code=True) == "@media (x) { }")
check("sanitize: prompt text and text handed to a model as data are removed",
      "secret plan" not in d.sanitize_public("You are the surveyor. secret plan\nkeep this\n<untrusted source=x>secret plan</untrusted>", [])
      and "keep this" in d.sanitize_public("You are the surveyor. secret plan\nkeep this", []))
check("sanitize: it is a function of its input (twice the same, and idempotent)",
      d.sanitize_public(_dirty, ["bob"]) == _clean and d.sanitize_public(_clean, ["bob"]) == _clean)
_done = {"pp#1": {**_fx["pp#1"], "status": "merged", "step": None, "pr": "https://github.com/x/y/pull/9", "verdict": "PROVEN", "fixrun": "fr1",
                  "diff": "--- a/src/a.css\n+++ b/src/a.css\n-x\n+y /Users/bob/p"}}
_mm = _m("fix:pp#1", _done, runs=[{"at": "t1", "duty": "inspector", "verdict": "PROVEN", "detail": "d", "fixrun": "fr1"},
                                  {"at": "t0", "duty": "shipwright", "verdict": "PR", "detail": "d", "fixrun": "fr1"}])
_case = d.showcase_case(_mm, {"shipwright": "builds it", "inspector": "checks it /Users/bob/x"}, ["bob"])
check("case: a merged, proven fix becomes a case study with a byline in the order it happened, stages and no commit claim",
      _case and [b["duty"] for b in _case["byline"]] == ["shipwright", "inspector"] and len(_case["stages"]) == 5
      and "does not say which commit" in _case["verified"] and _case["pr_number"] == "9" and _case["headline"].endswith("verified."))
check("case: everything it shows is sanitized, the diff and the byline included",
      "/Users" not in json.dumps(_case) and "bob" not in json.dumps(_case))
check("case: a fix that is not proven, or not a fix, is not a case study",
      d.showcase_case(_m("fix:pp#1"), {}) is None and d.showcase_case(_m("panel:pp"), {}) is None
      and d.showcase_candidates({"a": {"verdict": "skipped: busy", "status": "pr"}, "b": {"verdict": "PROVEN", "status": "running"}}) == [])

# ---- Harbor map: a toggle on the Fleet strip; berths are the same projects in an order, with the strip's own words ----
_hb = (ROOT / "dashboard" / "assets" / "harbor.js").read_text()
_fs = _idx_html[_idx_html.index("function fleetStrip("):_idx_html.index("function finishedCard")]
check("the Fleet strip has a Map | List toggle (button group, aria-pressed) kept in quarterdeck.fleetView, List by default; berths are buttons that select the project; an empty install shows none",
      all(w in _fs for w in ('<sl-button-group label="Fleet view">', 'aria-pressed=', "setFleetView(", 'class="berth ', "selectProject(", "if(!S.projects.length) return \"\""))
      and 'localStorage.getItem("quarterdeck.fleetView") === "map"' in _idx_html and 'let fleetView = "list"' in _idx_html)
check("berth text is only the strip's own name and state label (no lanes, no counts, no invented words); harbor.js is pure",
      "i.label" in _fs and "i.name" in _fs and not any(w in _fs.lower() for w in ("inspection", "repair", "launch", "lane", "moored"))
      and "—" not in _hb and "document." not in _hb and "localStorage" not in _hb)
check("the map draws with tokens and nothing moving: no hex, animation, transition, gradient or shadow in its CSS",
      not _re.search(r"#[0-9a-fA-F]{3,6}\b|animation|transition|gradient|shadow", _ui[_ui.index(".fleet-tools{"):_ui.index(".home-row{")]))
if _nodeok.path():
    _r = _sp.run(["node", "--no-warnings", "-e", "import('" + (ROOT / "dashboard" / "assets" / "harbor.js").as_uri() + "').then(m=>console.log(JSON.stringify(m.berthOrder([{name:'b',st:'idle'},{name:'z',st:'blocked'},{name:'a',st:'idle'},{name:'m',st:'running'},{name:'c',st:'awaiting'},{name:'a2',st:'blocked'}]).map(x=>x.name))))"], capture_output=True, text=True)
    check("berths are ordered blocked, waiting for you, running, idle, then by name", _r.stdout.strip() == '["a2","z","c","m","a","b"]', _r.stdout + _r.stderr[-200:])
for _x in sorted((ROOT / "bin").glob("selftest-ext-*.py")):
    _r = _sp.run([sys.executable, str(_x)], capture_output=True, text=True)
    check("the " + _x.stem[len("selftest-ext-"):] + " add-on's own checks pass", _r.returncode == 0, "\n".join((_r.stdout + _r.stderr).splitlines()[-8:]))
for _x in sorted((ROOT / "bin").glob("selftest-ext-*.mjs")) if _nodeok.path() else []:
    _r = _sp.run(["node", "--no-warnings", str(_x)], capture_output=True, text=True, cwd=str(ROOT))
    check("the " + _x.stem[len("selftest-ext-"):] + " add-on's page logic passes under node", _r.returncode == 0, (_r.stderr or "")[-400:])

# ---- the Brain as a place of its own, and the Start a full cycle button ----
_pg2 = (ROOT / "dashboard" / "index.html").read_text(); _bj2 = (ROOT / "dashboard" / "assets" / "brain.js").read_text()
_bg = _pg2[_pg2.index("function brainGraph(){"):_pg2.index("// ---- the lists behind the Brain's counts")]
check("the Brain is not project scoped: its graph never reads the selected project, the Brain toolbar has no project filter (My rhythm has the one project choice, which is the app's project scope), and no tabs or switcher are drawn over it",
      "mine(" not in _bg and "sel ===" not in _bg and "brainProject" not in _pg2 and 'id: "brain-proj"' not in _pg2 and 'id: "rh-proj"' in _pg2
      and "body.brain-mode .topbar,body.brain-mode .phead,body.brain-mode .ptabs{display:none}" in _ui)
check("the Brain is immersive: Leave Brain and Esc return to where you were (an open card or list closes first), Helm collapses for the visit and comes back, the palette finds it, the rail item stays",
      all(w in _pg2 for w in ("function leaveBrain", "brainReturn = {view, place: atPlace}", "brainMod.closePanel()", "brainHelmOpen", 'dockMode = brainHelmOpen ? "dock" : "rail"', "dockGo('brain')", 'id:"brain",       label:"Brain"'))
      and "export function closePanel" in _bj2 and 'sl-button-group label="Size the map by"' in _pg2)
check("the Brain's panel is made of the kit (mono kicker, pills, sl-details sections, rows), sits beside the map and below it on a phone, and text is only ever set as text",
      all(w in _bj2 for w in ('"sl-details"', '"kicker"', '"pill "', "brain-stage")) and ".innerHTML" not in _bj2
      and ".brain-host{flex-direction:column}" in _ui and not _re.search(r"#[0-9a-fA-F]{3,6}\b", _ui[_ui.index(".brain-bar{display:none}"):_ui.index("/* Start a full cycle")]))
_ts = d.start_cycle
_svpf, _svlk, _svdb, _svsp, _svpo, _svsl = d.PROJECTS_FILE, d.running_locks, d.daily_budget, d.spent_today, d.subprocess.Popen, d.time.sleep
_tdc = Path(_tf.mkdtemp()); d.PROJECTS_FILE = _tdc / "projects.json"
d.PROJECTS_FILE.write_text(_json.dumps({"on": {"cycle": True}, "off": {}, "str": {"cycle": "true"}}))
d.running_locks = lambda: {}; d.daily_budget = lambda: 10.0; d.spent_today = lambda rows=None: 1.0
_calls = []
d.subprocess.Popen = lambda argv, **kw: _calls.append(argv); d.time.sleep = lambda s: None
def _refused(*a):
    try: _ts(*a)
    except ValueError as e: return str(e)
    return None
try:
    _r1 = [_refused("off", 3, True), _refused("str", 3, True), _refused("nope", 3, True), _refused("on", 0, True), _refused("on", "3", True), _refused("on", True, True), _refused("on", 3, None), _refused("on", 3, "yes")]
    d.running_locks = lambda: {"cycle-on-3": {}}; _dup = _refused("on", 3, True); d.running_locks = lambda: {}
    d.spent_today = lambda rows=None: 10.0; _cap = _refused("on", 3, True); d.spent_today = lambda rows=None: 1.0
    check("start cycle: refused when the project has not opted in (a string 'true' is not true), the issue is not a positive integer, confirm is not exactly true, a cycle for it already runs, or the day's budget is spent; nothing is spawned for any of them",
          all(_r1) and "opted in" in _r1[0] and "opted in" in _r1[1] and "unknown" in _r1[2] and _r1[3] == _r1[4] == _r1[5] == "bad issue" and "confirm" in _r1[6] and "confirm" in _r1[7]
          and _dup and "already running" in _dup and _cap and "budget" in _cap and not _calls, (_r1, _dup, _cap, _calls))
    _ok = _ts("on", 3, True)
    check("start cycle: a good request runs bin/quarterdeck cycle <project> --issue <n> --apply as an argv list, detached, logging under logs/, and answers with the record's id or none yet",
          len(_calls) == 1 and _calls[0][1:] == ["cycle", "on", "--issue", "3", "--apply"] and _ok["id"] is None and _ok["started"] == "cycle on --issue 3", (_calls, _ok))
finally:
    d.PROJECTS_FILE, d.running_locks, d.daily_budget, d.spent_today, d.subprocess.Popen, d.time.sleep = _svpf, _svlk, _svdb, _svsp, _svpo, _svsl
_e = d.cycle_estimate_calc
_o = _e([5, 9, 3], 15, 20, 4); _ev = _e([2, 4], 15, 20, 4); _no = _e([], 15, None, 4); _ovr = _e([0, "x", None], 15, 20, 25)
check("cycle estimate: median, lowest and highest of the project's own totals (odd and even counts), today's budget left never below zero, and with no runs of its own the stated default with no invented range",
      (_o["basis"], _o["min"], _o["median"], _o["max"], _o["runs"], _o["daily_left"]) == ("own", 3.0, 5.0, 9.0, 3, 16.0) and _ev["median"] == 3.0
      and _no["basis"] == "default" and "min" not in _no and "max" not in _no and _no["daily_left"] is None and _no["note"].startswith("no runs of its own yet; the first measured run cost about 7 dollars")
      and "QUARTERDECK_CYCLE_BUDGET" in _no["note"] and _ovr["basis"] == "default" and _ovr["daily_left"] == 0.0 and _o["ceiling"] == 15)
_dw = _dm.World(clock=lambda: 1e9)
_a1 = _dw.post("/api/cycle/start", {"project": "wayfarer-web", "issue": 29, "confirm": True}); _a2 = _dw.post("/api/cycle/start", {"project": "wayfarer-web", "issue": 29, "confirm": True})
check("demo: the start answers with a made-up cycle id and a running record, runs nothing, and refuses the same cases (not opted in, bad issue, no confirm, a duplicate)",
      _a1[0] == 200 and _a1[1]["id"].startswith("cyc-wayfarer-web-29-") and _dw.cycle_record(_a1[1]["id"])["status"] == "running" and _a2[0] == 409
      and _dw.post("/api/cycle/start", {"project": "harvest-pipeline", "issue": 3, "confirm": True})[0] == 400 and _dw.post("/api/cycle/start", {"project": "wayfarer-web", "issue": -1, "confirm": True})[0] == 400
      and _dw.post("/api/cycle/start", {"project": "wayfarer-web", "issue": 5})[0] == 400)
_cyc = _pg2[_pg2.index("let cycleDlg"):_pg2.index("function missionEmpty()")]
check("the Start a full cycle dialog states the cost, the ceiling, today's budget left, a plain list of what it does and that it never merges; only its Start button posts, no poll or render can; no raw hex",
      all(w in _cyc for w in ("Expected cost", "Ceiling", "Budget left today", "What it will do", "never merges", "writes a branch and a pull request", "confirm: true", "e.note", "if(atPlace) return"))
      and _pg2.count('post("/api/cycle/start"') == 1 and 'onclick="startCycle()"' in _pg2 and "startCycle(" not in _pg2.split("async function tick()")[1].split("function renderLost")[0]
      and "startCycle(" not in _pg2.split("function render(){")[1].split("function showPrivacy")[0] and "has not opted in to full cycles" in _cyc and '"cycle": true' in _cyc
      and not _re.search(r"#[0-9a-fA-F]{3,6}\b", _cyc + _ui[_ui.index("/* Start a full cycle"):_ui.index("/* search everywhere")]))

# ---- one Brain workspace, one project selector, help on every connection (the rules in dashboard/UI.md) ----
_bb = _pg2[_pg2.index("function brainBar(){"):_pg2.index("// Replay: drag a day slider")]
check("Brain and My rhythm are two modes of one workspace: one toolbar with a Map | Rhythm switch that does not move, a Leave control, Esc from either mode, and no module-made button or second chrome",
      'sl-button-group label="Brain view"' in _bb and "setBrainMode('map')" in _bb and "setBrainMode('rhythm')" in _bb and "leaveBrain()" in _bb
      and "function setBrainMode" in _pg2 and "brainMode = \"map\"" in _pg2 and "createElement(\"sl-button\")" not in _rui and "#brain-bar .bb-tools" not in _pg2
      and "container:bbar/inline-size" in _ui and "@container bbar (max-width:1160px)" in _ui and "sl-dropdown" in _bb and 'data-k="more"' in _bb)
check("the Brain toolbar has no project filter, My rhythm's project choice is the app's one scope (the same `sel`) in the toolbar, and the top bar's selector is the only other one",
      "brainProject" not in _pg2 and 'id: "brain-proj"' not in _pg2 and "function rhythmScope" in _pg2 and "sel = v; localStorage.setItem(\"quarterdeck.project\", v)" in _pg2
      and _pg2.count('id="proj-switch"') == 1 and "proj-switch" not in _bb)
check("no view carries a project filter of its own: Timeline and Notes use the top bar's project, and a project inside a form is a labelled field",
      "tlUi.project" not in _pg2 and "noteUi.project" not in _pg2 and 'label: "Show one project"' not in _pg2
      and all(('label: "Project"' in x) for x in [l for l in _pg2.splitlines() if 'id: "mi-project"' in l or 'id: "s-project"' in l or 'id: "cycle-proj"' in l]))
check("the kit holds: no raw <select>, no native confirm, alert or prompt outside the one fallback, drawers take their buttons from the shared footer helper, and each drawer button row is Cancel or Close then the primary",
      "<select" not in _pg2 and "alert(" not in _pg2.replace("sl-alert", "") and "prompt(" not in _pg2 and _pg2.count("window.confirm(") == 1
      and "const drawerFoot" in _pg2 and "function openDrawer(foot" in _pg2 and 'drawerFoot(btn("Cancel"' in _pg2 and 'drawerFoot(btn("Close"' in _pg2
      and _pg2.index('btn("Cancel", {click: "closeDrawer()"}), btn("Save focus"') > 0 and 'id="dfoot"' in _pg2)
check("every Connections row has a help icon button with an accessible label, in the same place (right of its header, after the switch), and the help drawer shows what is read and not read, what to get, the steps, the scopes, how to revoke, the Tested line and only https links that open safely",
      'sl-icon-button name="question-circle" label="How to connect ${esc(c.label)}"' in _pg2 and '<div class="conn-end">' in _pg2 and "function connHelp" in _pg2
      and all(w in _pg2.split("function connHelp")[1].split("function viewConnections")[0] for w in ("What it reads", "What it never reads", "What you need", '"Steps"', "Permissions to grant", "How to take access back", '"Tested"', "Provider pages", "Provider screens change", 'rel="noopener noreferrer"', "drawerFoot"))
      and ".conn-end{" in _ui and (ROOT / "dashboard/assets/vendor/shoelace/assets/icons/question-circle.svg").is_file() and "Made-up help text." in (ROOT / "bin/demo.py").read_text())
check("Connections shows one primary action per view (a credential's Save is the plain button), and a Tested pill per service that is 'Not tested' unless its manifest says it was tested against the real service",
      'btn("Save", {size: "small", attrs: \'type="submit"\'})' in _pg2 and 'c.verified ? "Tested" : "Not tested"' in _pg2)

# ---- design briefs, mock-ups and sprint plans: ids, transitions, the sandbox, the demo world, the page ----
import brief as _bf, mockup as _mk
_dmk = ROOT / "bin" / "demo_maker.py"
_dmk_src = _dmk.read_text()
_dmk_imports = {n.names[0].name.split(".")[0] if isinstance(n, _ast.Import) else n.module.split(".")[0] for n in _ast.walk(_ast.parse(_dmk_src)) if isinstance(n, (_ast.Import, _ast.ImportFrom))}
check("demo_maker.py imports only re (no file, process or network), and has no em dash", _dmk_imports <= {"re"} and "—" not in _dmk_src, _dmk_imports)
check("brief ids: only b<date>-<time>-<4 hex> passes, so no path can be made from one",
      _bf.id_ok(_bf.new_id()) and not any(_bf.id_ok(x) for x in ("", "b1", "../x", "b20260101-000000-abcd/../x", "b20260101-000000-ABCD", "b20260101-000000-abc", None, 5, "b20260101-000000-abcd\n")))
check("plan ids: plain names only (no slash, no dot-dot, bounded)", d._plan_ok("tp-20260101-000000") and not any(d._plan_ok(x) for x in ("", "../x", "a/b", "a..b", "x" * 81, None, "a b")))
_w = _dm.World(clock=lambda: 1000.0)
_mkr = _w.maker
_bid = "b20261015-090000-d3a1"
_pg = lambda n: _mkr.mockup_page("b20261014-150000-d3a2", n)
check("demo: every made-up mock-up page passes the same check as a real one, and each carries a visible focus style and body contrast over 4.5",
      all(not _mk.check_page(_pg(n))["errors"] and _mk.contrast_of(_mk.check_page(_pg(n))["css"])[0] > 4.5 for n in ("settings", "trip-list"))
      and _mkr.mockup_page(_bid, "settings") is None and _mkr.mockup_page("../x", "settings") is None)
check("demo: the made-up briefs satisfy the real contract (limits, no code, keyboard and focus named)", all(_bf.check(r["brief"]) for r in _mkr.briefs.values()))
_a = lambda **k: _w.post("/api/brief/action", {"id": _bid, "confirm": True, **k})
check("demo: approve once, a second approve is 409, changes need a note, mock-ups need an approved brief, and no confirm is 400",
      _w.post("/api/brief/action", {"id": _bid, "action": "approve"})[0] == 400 and _a(action="mockups")[0] == 409 and _a(action="changes", note="")[0] == 409
      and _a(action="approve")[1]["status"] == "approved" and _a(action="approve")[0] == 409 and _a(action="mockups")[0] == 200 and _mkr.briefs[_bid]["mockups"]["state"] == "ready"
      and _a(action="mockups_approve")[1]["mockups"]["state"] == "approved" and _a(action="add_to_project")[0] == 400 and _a(action="nope")[0] == 400
      and _w.post("/api/brief/action", {"id": "../x", "action": "approve", "confirm": True})[0] == 400)
_n = _w.post("/api/brief/new", {"idea": "a page for my street's book swap", "confirm": True})
check("demo: a new brief is made up at once (no model), refuses a short idea or a missing confirm, and its id passes the real regex",
      _n[0] == 200 and _bf.id_ok(_n[1]["id"]) and _w.post("/api/brief/new", {"idea": "x", "confirm": True})[0] == 400 and _w.post("/api/brief/new", {"idea": "a page for my street"})[0] == 400)
_pid = "wayfarer-web-20261015-100000"
_pa = lambda **k: _w.post("/api/plan/action", {"id": _pid, "project": "wayfarer-web", **k})
check("demo: a plan can be approved, previewed and applied in memory; apply before approval is 409; no confirm 400; a wrong project 409",
      _pa(action="apply", confirm=True)[0] == 409 and _pa(action="approve")[0] == 400 and _pa(action="preview")[1]["lines"][0].startswith("(")
      and _pa(action="approve", confirm=True)[1]["plan"]["status"] == "approved" and len(_pa(action="apply", confirm=True)[1]["lines"]) == 2
      and _w.post("/api/plan/action", {"id": _pid, "project": "harvest-pipeline", "action": "approve", "confirm": True})[0] == 409)
_m1 = d.compose_mission("brief:b20261015-090000-d3a1", None, {}, [], [], {}, get_brief=_dm.World(clock=lambda: 1.0).maker.brief)
check("the mission composer makes a brief and a plan mission, and returns nothing for an id that is not one",
      _m1 and _m1["kind"] == "brief" and _m1["state"] == "awaiting" and d.compose_mission("brief:nope", None, {}, [], [], {}, get_brief=lambda i: None) is None
      and d.compose_mission("plan:x", None, {}, [], [], {}) is None
      and d.compose_mission("plan:" + _pid, None, {}, [], [], {}, get_plan=_w.maker.plan)["cost_line"].startswith("Expected cost of the sprint:"))
check("a brief or plan the owner has not answered is awaiting; a failed brief is blocked; a drafting one is running",
      all(d.compose_mission("brief:x", None, {}, [], [], {}, get_brief=lambda i, s=s: {"id": "b1", "status": s, "mockups": {"state": "none"}, "brief": None, "idea": "i"})["state"] == w
          for s, w in (("proposed", "awaiting"), ("failed", "blocked"), ("drafting", "running"), ("approved", "done"))))
_ix2 = (ROOT / "dashboard" / "index.html").read_text()
_bk = _ix2[_ix2.index("/* ---- design briefs and sprint plans"):_ix2.index('document.addEventListener("sl-tab-show"')]
check("the page shows each mock-up in a frame with sandbox=\"\" (no permission at all), never srcdoc or allow-*, from the strict-CSP route",
      'sandbox=""' in _bk and "allow-" not in _bk and "srcdoc" not in _bk and "/api/mockup?brief=" in _bk and "<script" not in _bk)
check("every write on those screens is a click that asks first (confirmDlg) and posts confirm:true, except the notes the owner types and the read-only preview; none runs from a render or a poll",
      _bk.count("confirmDlg(") >= 4 and _bk.count("confirm: true") >= 5 and "action: \"preview\"" in _bk
      and all(f in _bk for f in ("Approve the brief", "Ask for changes", "Make mock-ups", "Open full size", "Approve the plan", "Move the cards", "Approve the mock-ups"))
      and "briefAct(" not in _ix2.split("function render(){")[1].split("function showPrivacy")[0] and "planMove(" not in _ix2.split("function render(){")[1].split("function showPrivacy")[0])
check("make-mock-ups says what it costs (model usage on the subscription), that it writes only into the data folder and merges nothing; the plan's move lists each card before it moves",
      "model usage on your subscription" in _bk and "never into a project" in _bk and "merges and sends nothing" in _bk and "lines.join" in _bk and "left alone" in _bk)
check("the Add a project drawer has Describe your idea and Make a brief after the folder step, and links the brief to the project once added",
      "Describe your idea" in _ix2 and "nwMakeBrief" in _ix2 and 'action: "link"' in _ix2 and _ix2.index("Describe your idea") > _ix2.index("async function attachNew"))
check("a fix or cycle mission offers Make a brief for this issue only through its own confirm, and says how to switch the duty on when it is off",
      "briefForIssue(" in _ix2 and "add \"brief\" to the duties" in _ix2)

print()
if FAILS:
    print(f"  {len(FAILS)} check(s) failed")
    sys.exit(1)
print("  all checks passed")
