#!/usr/bin/env python3
"""End-to-end smoke test: the real dashboard, in this process, on a free port,
against a throwaway copy of the state layout. Nothing in the real state/ or
logs/ is touched. Stdlib only. Exits non-zero if any check fails.

    python3 bin/smoke.py
"""
import http.client
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()


def call(method, path, body=None, headers=None, raw=None):
    """-> (status, body bytes). Host defaults to loopback, as a browser sends it."""
    h = {"Host": f"127.0.0.1:{PORT}", **(headers or {})}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h.setdefault("Content-Length", str(len(data)))
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def jget(path):
    code, body = call("GET", path)
    return code, json.loads(body or b"{}")


def serve():
    srv = d.make_server(PORT)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t


def stop(srv, t):
    srv.shutdown()
    srv.server_close()
    t.join(5)


tmp = Path(tempfile.mkdtemp(prefix="quarterdeck-smoke-"))
state = tmp / "state"
for sub in ("panels", "fixes", "fixqueue", "connectors"):
    (state / sub).mkdir(parents=True)
(state / "runs.json").write_text("[]")
saved = d.relocate_state(state)
d.LOGS.mkdir(parents=True, exist_ok=True)
srv, thread = serve()
try:
    code, body = call("GET", "/")
    page = body.decode(errors="replace")
    check("GET / returns the page with the token in it", code == 200 and d.TOKEN in page and "__QUARTERDECK_TOKEN__" not in page)
    tok = {"X-Quarterdeck-Token": d.TOKEN}

    code, st = jget("/api/state")
    want = {"now", "agents", "crew", "missions", "inbox", "panels", "fixes", "fixqueue", "spend",
            "schedules", "docs", "projects", "duties", "runs", "system", "logs", "captures"}
    check("/api/state is 200 with the expected top-level keys", code == 200 and want <= set(st), want - set(st))

    _c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    _c.request("GET", "/api/health", headers={"Host": f"127.0.0.1:{PORT}"})
    _r = _c.getresponse(); _r.read(); _hd = {k.lower(): v for k, v in _r.getheaders()}; _c.close()
    check("every answer says it may not be framed or sniffed", _hd.get("x-frame-options") == "DENY" and _hd.get("x-content-type-options") == "nosniff" and "frame-ancestors 'none'" in _hd.get("content-security-policy", ""), _hd)

    code, h = jget("/api/health")
    check("/api/health is ok", code == 200 and h.get("ok") is True and h["writable"] == {"state": True, "logs": True}, h)
    check("/api/health says how old the last state build is", isinstance(h.get("last_state_build_age_seconds"), int))
    check("/api/health carries no paths or environment values",
          str(tmp) not in json.dumps(h) and str(ROOT) not in json.dumps(h))

    code, _ = call("POST", "/api/capture", {"text": "smoke note"})
    check("a write without the token is 403", code == 403)
    code, _ = call("POST", "/api/capture", {"text": "smoke note"}, {**tok, "Origin": "http://evil.example"})
    check("a write with a foreign Origin is 403", code == 403)
    code, _ = call("GET", "/api/state", headers={"Host": "evil.example"})
    check("a foreign Host header is rejected", code == 403)

    code, body = call("POST", "/api/capture", {"text": "smoke note"}, tok)
    note = json.loads(body or b"{}")
    _, st = jget("/api/state")
    check("POST /api/capture add shows up in state",
          code == 200 and any(i["id"] == note.get("id") for i in st["captures"]["items"]))
    code, _ = call("POST", "/api/capture", {"action": "done", "id": note.get("id")}, tok)
    _, st = jget("/api/state")
    check("POST /api/capture done takes it off the list",
          code == 200 and not any(i["id"] == note.get("id") for i in st["captures"]["items"]))

    code, _ = call("POST", "/api/chat", {"text": "how is it going"})
    check("/api/chat without the token is 403", code == 403)
    code, _ = call("POST", "/api/chat", {"text": "how is it going"}, {**tok, "Origin": "http://evil.example"})
    check("/api/chat with a foreign Origin is 403", code == 403)
    _model = os.environ.get("QUARTERDECK_HELM_MODEL")
    os.environ["QUARTERDECK_HELM_MODEL"] = "/nonexistent/no-model.gguf"       # force "not installed" on any machine
    try:
        code, body = call("POST", "/api/chat", {"text": "how is it going"}, tok)
    finally:
        os.environ.pop("QUARTERDECK_HELM_MODEL") if _model is None else os.environ.__setitem__("QUARTERDECK_HELM_MODEL", _model)
    check("/api/chat with no local model installed answers with one plain error event, not a crash",
          code == 200 and body.startswith(b"data: ") and b'"error"' in body and b"Traceback" not in body, body[:160])
    code, _ = call("POST", "/api/transcribe", headers=tok, raw=b"this is not a wav file, but it is long enough " * 3)
    check("/api/transcribe with a non-WAV body is 400", code == 400)

    code, body = call("POST", "/api/capture", {"text": "survives a restart"}, tok)
    kept = json.loads(body or b"{}").get("id")
    stop(srv, thread)
    srv, thread = serve()
    _, st = jget("/api/state")
    check("state survives stopping and starting the server",
          any(i["id"] == kept for i in st["captures"]["items"]))

    call("POST", "/api/demo", {"on": True}, tok)
    code, body = call("GET", "/api/health")
    call("POST", "/api/demo", {"on": False}, tok)
    check("/api/health answers while Demo mode is on (quarterdeck check runs during a rehearsal)",
          code == 200 and "loops" in json.loads(body or b"{}"), code)


    # ---- design briefs, mock-ups and sprint plans: the approval endpoints, against a throwaway data folder ----
    import brief as B, mockup as M, plan as P
    _pf_saved = d.PROJECTS_FILE
    d.PROJECTS_FILE = tmp / "projects.json"
    (tmp / "tp").mkdir()
    d.PROJECTS_FILE.write_text(json.dumps({
        "tp": {"repo": "x/tp", "path": str(tmp / "tp"), "duties": ["brief"], "board": {"owner": "x", "number": 1}},
        "nb": {"repo": "x/nb", "path": str(tmp / "tp"), "duties": [], "board": {"owner": "x", "number": 2}}}))
    spawned = []
    _sp_saved = d._spawn_detached
    d._spawn_detached = lambda argv, log: spawned.append(argv)
    GOOD = {"title": "Book swap", "one_line": "A page for neighbours.", "audience": "Neighbours.", "goals": ["List a book"],
            "key_screens": [{"name": "Available books", "purpose": "Show books."}, {"name": "Add a book", "purpose": "List one."}],
            "flows": [{"name": "List", "steps": ["Open", "Save"]}], "accessibility": "Everything is reachable by keyboard and the focus is always visible.",
            "success_checks": ["A neighbour lists a book"]}

    def mk(project=""):
        bid = B.new_id() if not mk.n else "b20260101-00000%d-abcd" % mk.n
        mk.n += 1
        B.stub(tmp, bid, "idea", project, None, "an idea", "")
        rec = B.load(tmp, bid)
        rec["brief"] = B.check(GOOD)
        B.save(tmp, rec)
        return bid
    mk.n = 1
    b1, b2 = mk("tp"), mk("tp")
    post = lambda p, b, h=tok: call("POST", p, b, h)
    pj = lambda p, b: (lambda r: (r[0], json.loads(r[1] or b"{}")))(post(p, b))

    check("GET /api/brief: a bad id is 400, an unknown one 404, a real one 200 with its status",
          jget("/api/brief?id=..%2Fx")[0] == 400 and jget("/api/brief?id=b1")[0] == 400 and jget("/api/brief?id=b20200101-000000-0000")[0] == 404
          and jget(f"/api/brief?id={b1}")[1]["status"] == "proposed")
    check("POST /api/brief/action: without the token 403, foreign Origin 403",
          call("POST", "/api/brief/action", {"id": b1, "action": "approve", "confirm": True})[0] == 403
          and call("POST", "/api/brief/action", {"id": b1, "action": "approve", "confirm": True}, {**tok, "Origin": "http://evil.example"})[0] == 403)
    check("  a bad id, an unknown action and a missing confirm are 400, and an unknown brief 404",
          pj("/api/brief/action", {"id": "../x", "action": "approve", "confirm": True})[0] == 400
          and pj("/api/brief/action", {"id": b1, "action": "delete", "confirm": True})[0] == 400
          and pj("/api/brief/action", {"id": b1, "action": "approve"})[0] == 400 and pj("/api/brief/action", {"id": b1, "action": "approve", "confirm": "yes"})[0] == 400
          and pj("/api/brief/action", {"id": "b20200101-000000-0000", "action": "approve", "confirm": True})[0] == 404
          and jget(f"/api/brief?id={b1}")[1]["status"] == "proposed")
    check("  mock-ups before approval, approving a set that is not there, and changes without a note are 409, and nothing starts",
          pj("/api/brief/action", {"id": b1, "action": "mockups", "confirm": True})[0] == 409
          and pj("/api/brief/action", {"id": b1, "action": "mockups_approve", "confirm": True})[0] == 409
          and pj("/api/brief/action", {"id": b1, "action": "changes", "note": " ", "confirm": True})[0] == 409 and not spawned)
    check("  approve: proposed becomes approved once, and a second approve is 409",
          pj("/api/brief/action", {"id": b1, "action": "approve", "confirm": True})[1]["status"] == "approved"
          and pj("/api/brief/action", {"id": b1, "action": "approve", "confirm": True})[0] == 409)
    code, r = pj("/api/brief/action", {"id": b1, "action": "mockups", "confirm": True})
    check("  mock-ups on an approved brief start the duty by argv, with apply and no shell, and say nothing is written yet",
          code == 200 and len(spawned) == 1 and spawned[0][1:] == ["mockup", b1, "--apply"] and "mockup" in r["started"])
    _page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>t</title><style>body{color:#1d2433;background:#fff}"
             "a:focus-visible{outline:3px solid #036}</style></head><body><main><h1>Hi</h1><a href=\"#x\">x</a></main></body></html>")
    M.save(tmp, b1, [{"name": "available-books", "title": "Available books", "html": _page, "contrast": 14.5, "contrast_note": ""}])
    _c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    _c.request("GET", f"/api/mockup?brief={b1}&name=available-books", headers={"Host": f"127.0.0.1:{PORT}"})
    _r = _c.getresponse(); _body = _r.read(); _h = {k.lower(): v for k, v in _r.getheaders()}; _c.close()
    check("GET /api/mockup: the page comes with the strict Content-Security-Policy, nosniff, same-origin framing only, no referrer",
          _r.status == 200 and _body.decode() == _page and _h["content-security-policy"].startswith("default-src 'none'; style-src 'unsafe-inline'; img-src data:")
          and "sandbox" in _h["content-security-policy"] and "frame-ancestors 'self'" in _h["content-security-policy"] and "script-src" not in _h["content-security-policy"]
          and _h["x-content-type-options"] == "nosniff" and _h["x-frame-options"] == "SAMEORIGIN" and _h["referrer-policy"] == "no-referrer"
          and _h["content-type"].startswith("text/html"), _h)
    check("  a bad id or name is 400, a page that is not in the manifest is 404",
          call("GET", "/api/mockup?brief=../x&name=a")[0] == 400 and call("GET", f"/api/mockup?brief={b1}&name=..%2Fmanifest")[0] == 400
          and call("GET", f"/api/mockup?brief={b1}&name=nothing")[0] == 404 and call("GET", f"/api/mockup?brief={b2}&name=available-books")[0] == 404)
    (tmp / "workspace" / "mockups" / b1 / "available-books.html").write_text(_page.replace("<main>", "<main><script>x()</script>"))
    check("  a saved page changed to hold a script is not served", call("GET", f"/api/mockup?brief={b1}&name=available-books")[0] == 404)
    (tmp / "workspace" / "mockups" / b1 / "available-books.html").write_text(_page)
    check("  mock-up approval: changes without a note 409, approve 200 once, then 409",
          pj("/api/brief/action", {"id": b1, "action": "mockups_changes", "confirm": True})[0] == 409
          and pj("/api/brief/action", {"id": b1, "action": "mockups_approve", "confirm": True})[1]["mockups"]["state"] == "approved"
          and pj("/api/brief/action", {"id": b1, "action": "mockups_approve", "confirm": True})[0] == 409)
    check("  add to the project: writes docs/BRIEF.md once, is refused the second time, and leaves other files alone",
          pj("/api/brief/action", {"id": b1, "action": "add_to_project", "confirm": True})[1]["added_to_project"]["path"] == "docs/BRIEF.md"
          and "Book swap" in (tmp / "tp" / "docs" / "BRIEF.md").read_text()
          and pj("/api/brief/action", {"id": b1, "action": "add_to_project", "confirm": True})[0] == 409 and sorted(p.name for p in (tmp / "tp").iterdir()) == ["docs"])
    check("  add to the project is refused for a brief that is not approved or has no project",
          pj("/api/brief/action", {"id": b2, "action": "add_to_project", "confirm": True})[0] == 409
          and pj("/api/brief/action", {"id": mk(""), "action": "add_to_project", "confirm": True})[0] == 409)
    check("  asking changes on an approved brief then revising: a new stub is made and the duty started with --revise; revising a proposed brief is 409",
          pj("/api/brief/action", {"id": b1, "action": "changes", "note": "shorter", "confirm": True})[1]["status"] == "changes_requested"
          and pj("/api/brief/action", {"id": b1, "action": "revise", "confirm": True})[0] == 200 and spawned[-1][1:3] == ["brief", "--revise"]
          and pj("/api/brief/action", {"id": b2, "action": "revise", "confirm": True})[0] == 409)
    n0 = len(spawned)
    check("POST /api/brief/new: no confirm, a short idea and a bad issue or project name are 400, and nothing starts",
          pj("/api/brief/new", {"idea": "a page for my book swap, please"})[0] == 400 and pj("/api/brief/new", {"idea": "short", "confirm": True})[0] == 400
          and pj("/api/brief/new", {"project": "tp", "issue": -1, "confirm": True})[0] == 400 and pj("/api/brief/new", {"idea": "a" * 12, "project": "../x", "confirm": True})[0] == 400
          and pj("/api/brief/new", {"project": "nb", "issue": 4, "confirm": True})[0] == 400 and len(spawned) == n0)
    code, r = pj("/api/brief/new", {"idea": "a page for my neighbourhood book swap", "audience": "neighbours", "project": "newapp", "confirm": True})
    check("  an idea starts `quarterdeck brief --idea ... --id ... --apply` by argv and leaves a drafting record the page can watch",
          code == 200 and B.id_ok(r["id"]) and spawned[-1][1:4] == ["brief", "--idea", "a page for my neighbourhood book swap"] and "--apply" in spawned[-1] and "--project" in spawned[-1]
          and jget(f"/api/brief?id={r['id']}")[1]["status"] == "drafting")
    code, r = pj("/api/brief/new", {"project": "tp", "issue": 12, "confirm": True})
    check("  an issue of a project with the duty on starts `quarterdeck run tp brief --issue 12 --id ... --apply`", code == 200 and spawned[-1][1:6] == ["run", "tp", "brief", "--issue", "12"] and "--apply" in spawned[-1])
    d._spawn_detached = _sp_saved
    _, ms = jget(f"/api/mission?id=brief:{b2}")
    check("the mission page composes a brief (kind, plain-words state, pipeline) and refuses a bad id", ms["kind"] == "brief" and ms["state"] == "awaiting" and len(ms["pipeline"]) == 4
          and jget("/api/mission?id=brief:..%2F..")[0] == 404)

    # a plan: approve and apply go through plan.py, with a board stand-in that records every call
    _calls = []
    class _R:
        def __init__(self, out="", rc=0): self.stdout, self.stderr, self.returncode = out, "", rc
    def _board(*a):
        _calls.append(a)
        if a[0] == "snapshot":
            return _R(json.dumps({"columns": {"todo": "Backlog", "ready": "Ready"}, "items": [
                {"type": "Issue", "number": 1, "state": "OPEN", "status": "Backlog"}, {"type": "Issue", "number": 2, "state": "OPEN", "status": "In Progress"}], "missing_from_board": []}))
        return _R("Backlog\n")
    _pb = P._board
    P._board = _board
    pid = "tp-20260101-000000"
    (tmp / "state" / "plans").mkdir(exist_ok=True)
    (tmp / "state" / "plans" / f"{pid}.json").write_text(json.dumps({
        "id": pid, "project": "tp", "created": "2026-01-01T00:00:00Z", "status": "proposed", "capacity": None, "budget": None, "reordered": False, "measured_runs": 0,
        "columns": {"todo": "Backlog", "ready": "Ready"}, "sprint": [1, 2], "later": [], "left_out": [], "total_cost": None, "moves": [],
        "plan": [{"issue": n, "title": f"t{n}", "size": "S", "reason": "r", "depends_on": [], "parallel_ok": True, "needs_decision": "", "why_now": "", "from_status": "Backlog" if n == 1 else "Backlog", "cost": None} for n in (1, 2)]}))
    check("GET /api/plan: a bad id is 400, an unknown 404, a real one 200; its mission states the cost as unknown with no measurement",
          jget("/api/plan?id=..%2Fx")[0] == 400 and jget("/api/plan?id=nope")[0] == 404 and jget(f"/api/plan?id={pid}")[1]["status"] == "proposed"
          and "unknown (no measurement yet)" in jget(f"/api/mission?id=plan:{pid}")[1]["cost_line"])
    pp = lambda b: pj("/api/plan/action", b)
    check("POST /api/plan/action: without the token 403; a bad id, an unknown project or action, and a missing confirm are 400; a plan of another project is 409",
          call("POST", "/api/plan/action", {"id": pid, "project": "tp", "action": "approve", "confirm": True})[0] == 403
          and pp({"id": "../x", "project": "tp", "action": "approve", "confirm": True})[0] == 400 and pp({"id": pid, "project": "zz", "action": "approve", "confirm": True})[0] == 400
          and pp({"id": pid, "project": "tp", "action": "burn", "confirm": True})[0] == 400 and pp({"id": pid, "project": "tp", "action": "approve"})[0] == 400
          and pp({"id": pid, "project": "tp", "action": "apply"})[0] == 400 and pp({"id": pid, "project": "nb", "action": "approve", "confirm": True})[0] == 409 and not _calls)
    check("  apply before approval is refused with nothing moved (the preview moves nothing either)",
          pp({"id": pid, "project": "tp", "action": "apply", "confirm": True})[0] == 409
          and all(c[0] == "snapshot" for c in _calls) and "preview" in " ".join(pp({"id": pid, "project": "tp", "action": "preview"})[1]["lines"]))
    check("  approve records the yes and moves nothing", pp({"id": pid, "project": "tp", "action": "approve", "confirm": True})[1]["plan"]["status"] == "approved"
          and not any(c[0] == "to" for c in _calls))
    code, r = pp({"id": pid, "project": "tp", "action": "apply", "confirm": True})
    check("  apply moves the sprint's cards one at a time through the board keeper's own move, and a card that moved meanwhile is left alone and says why",
          code == 200 and [c[0] for c in _calls if c[0] == "to"] == ["to"] and len(r["lines"]) == 2 and r["lines"][0].startswith("#1: moved")
          and "left alone (moved meanwhile" in r["lines"][1] and [m["result"] for m in r["plan"]["moves"]] == ["moved", "skipped"], r)
    P._board = _pb
    d.PROJECTS_FILE = _pf_saved
    with ThreadPoolExecutor(30) as pool:
        results = list(pool.map(lambda i: call("GET", "/api/state" if i % 2 else "/api/health")[0], range(30)))
    check("30 concurrent requests all succeed", results.count(200) == 30, results)
finally:
    stop(srv, thread)
    d.restore_state(saved)

print()
if FAILS:
    print(f"  {len(FAILS)} check(s) failed")
    sys.exit(1)
print("  all checks passed")
