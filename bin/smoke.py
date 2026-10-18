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
import time
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
SESSION = {}                                             # the paired browser every call below speaks for, once pair() has run


def call(method, path, body=None, headers=None, raw=None):
    """-> (status, body bytes). Host defaults to loopback, as a browser sends it."""
    h = {"Host": f"127.0.0.1:{PORT}", **({"Cookie": SESSION["cookie"]} if SESSION.get("cookie") else {}), **(headers or {})}
    if h.get("Cookie") == "":
        del h["Cookie"]                                  # a test that wants to be unpaired says so
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
    _c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    _c.request("GET", "/", headers={"Host": f"127.0.0.1:{PORT}"})
    _r = _c.getresponse(); body = _r.read(); _csp = _r.getheader("Content-Security-Policy", ""); _c.close()
    page, code = body.decode(errors="replace"), _r.status
    import re as _re
    _nonce = (_re.search(r"'nonce-([\w-]+)'", _csp) or [None, ""])[1]
    check("GET / serves the page with no token or secret in it, and a nonce that is in its CSP and on every inline script",
          code == 200 and d.TOKEN not in page and "__QUARTERDECK_TOKEN__" not in page and "__QUARTERDECK_NONCE__" not in page and _nonce
          and page.count(f'nonce="{_nonce}"') == len(_re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", page)) >= 4)
    check("the page's CSP has no unsafe-inline or unsafe-eval for scripts, nothing from another site, no framing, no form posts, no base",
          "script-src 'self' 'nonce-" in _csp and "unsafe-eval" not in _csp and "default-src 'self'" in _csp and "object-src 'none'" in _csp
          and "frame-ancestors 'none'" in _csp and "form-action 'none'" in _csp and "base-uri 'none'" in _csp and "script-src 'unsafe" not in _csp, _csp)
    tok = {"X-Quarterdeck-Token": d.TOKEN}
    check("a second GET / gets a different nonce", _nonce and _nonce not in call("GET", "/")[1].decode(errors="replace"))

    # --- pairing: unpaired reads are 401, a one-time nonce is traded for a cookie and a token, once ---
    code, _ = call("GET", "/api/state")
    check("an unpaired GET /api/state is 401", code == 401)
    check("unpaired GETs of /api/log, /api/doc, /api/panel, /api/connections and /api/settings are 401 too",
          all(call("GET", u)[0] == 401 for u in ("/api/log?name=quarterdeck", "/api/doc?name=x", "/api/panel?id=x", "/api/connections", "/api/settings")))
    check("the assets and /api/health need no pairing", call("GET", "/assets/ui.css")[0] == 200 and call("GET", "/api/health")[0] == 200)
    check("an unpaired write is 401", call("POST", "/api/capture", {"text": "x"})[0] == 401)
    check("a wrong nonce is 401", call("POST", "/api/pair", {"nonce": "A" * 32})[0] == 401 and call("POST", "/api/pair", {"nonce": "no"})[0] == 400)

    def _pair(nonce, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        data = json.dumps({"nonce": nonce}).encode()
        c.request("POST", "/api/pair", body=data, headers={"Host": f"127.0.0.1:{PORT}", "Content-Length": str(len(data)), **(headers or {})})
        r = c.getresponse(); b = r.read(); ck = r.getheader("Set-Cookie", ""); c.close()
        return r.status, (json.loads(b) if b else {}), ck

    _n1 = d.pair_mint()
    check("the nonce is only on disk as a hash, in a folder and file only the owner can read",
          not (d.STATE / "pair" / _n1).exists() and (d.STATE / "pair" / d._sha(_n1)).exists()
          and oct((d.STATE / "pair").stat().st_mode & 0o777) == "0o700" and oct((d.STATE / "pair" / d._sha(_n1)).stat().st_mode & 0o777) == "0o600")
    check("a foreign Origin cannot even try a nonce", _pair(_n1, {"Origin": "http://evil.example"})[0] == 403 and _pair(_n1, {"Origin": f"http://127.0.0.1:{PORT + 1}"})[0] == 403)
    code, pj_, ck = _pair(_n1)
    check("a good nonce is 200 with the token in the body and an HttpOnly, SameSite=Strict cookie that holds no token",
          code == 200 and len(pj_.get("token", "")) >= 24 and "HttpOnly" in ck and "SameSite=Strict" in ck and "Path=/" in ck and pj_["token"] not in ck and d.TOKEN not in ck, (code, ck))
    check("the same nonce a second time is 401 (single use)", _pair(_n1)[0] == 401)
    _n2 = d.pair_mint(); (d.STATE / "pair" / d._sha(_n2)).write_text("1")
    check("an expired nonce is 401", _pair(_n2)[0] == 401)
    SESSION["cookie"] = ck.split(";")[0]; SESSION["token"] = pj_["token"]
    check("the session token is not the process token", SESSION["token"] != d.TOKEN)
    check("a paired browser reads /api/state", call("GET", "/api/state")[0] == 200)
    # M1 (round 5): the cookie reaches any server on 127.0.0.1 the browser visits (cookies are not per port), so the cookie alone must never give the token
    _sc, _sb = call("GET", "/api/session")
    _sc2, _sb2 = call("GET", "/api/session", headers={"X-Quarterdeck-Token": SESSION["token"]})
    check("M1 /api/session never hands out the token: the cookie alone is refused, the cookie with this tab's token is 200 with no token in it, and an unpaired tab gets nothing",
          _sc in (401, 403) and SESSION["token"].encode() not in _sb and _sc2 == 200 and SESSION["token"].encode() not in _sb2 and b"token" not in _sb2
          and call("GET", "/api/session", headers={"Cookie": ""})[0] == 401
          and call("GET", "/api/session", headers={"X-Quarterdeck-Token": "wrong" + SESSION["token"]})[0] in (401, 403), (_sc, _sb, _sc2, _sb2))
    check("M1 a write with the cookie and the token but no Origin and no Sec-Fetch-Site (not a browser) is refused; a browser's same-origin request without Origin is not",
          call("POST", "/api/capture", {"text": "no origin"}, {"X-Quarterdeck-Token": SESSION["token"]})[0] == 403
          and call("POST", "/api/capture", {"text": "fetch metadata"}, {"X-Quarterdeck-Token": SESSION["token"], "Sec-Fetch-Site": "same-origin"})[0] == 200
          and call("POST", "/api/capture", {"text": "x"}, {"X-Quarterdeck-Token": SESSION["token"], "Sec-Fetch-Site": "none"})[0] == 403)
    check("a cookie read from another origin is refused", call("GET", "/api/state", headers={"Origin": "http://localhost:3000"})[0] == 401
          and call("GET", "/api/session", headers={"Sec-Fetch-Site": "same-site"})[0] == 401)
    pt = {"X-Quarterdeck-Token": SESSION["token"]}
    check("a cookie alone cannot write; with the session token and this server's Origin it can; a foreign or other-port Origin cannot",
          call("POST", "/api/capture", {"text": "paired note"})[0] == 403
          and call("POST", "/api/capture", {"text": "paired note"}, {**pt, "Origin": "http://evil.example"})[0] == 403
          and call("POST", "/api/capture", {"text": "paired note"}, {**pt, "Origin": "http://localhost:3000"})[0] == 403
          and call("POST", "/api/capture", {"text": "paired note"}, {**pt, "Origin": f"http://127.0.0.1:{PORT}"})[0] == 200)
    check("the process token is not accepted from a browser (an Origin is sent)", call("POST", "/api/capture", {"text": "x"}, {**tok, "Origin": f"http://127.0.0.1:{PORT}", "Cookie": ""})[0] == 403
          or call("POST", "/api/capture", {"text": "x"}, {**tok, "Origin": f"http://127.0.0.1:{PORT}", "Cookie": ""})[0] == 401)
    d._SESSIONS["map"] = None                                                # as after a restart: the session comes back from disk
    check("a paired browser stays paired across a restart", call("GET", "/api/state")[0] == 200
          and oct((d.STATE / "dashboard.sessions.json").stat().st_mode & 0o777) == "0o600" and SESSION["cookie"].split("=")[1] not in (d.STATE / "dashboard.sessions.json").read_text())
    # R-LOW: a session lasts a day (renewed when its page asks again), can be ended from the page (logout) and revoked from the command line, even while the server runs
    check("a session lasts a day, not a week", d.SESSION_TTL == 86400)
    _c2, _j2, _ck2 = _pair(d.pair_mint())
    S2 = {"Cookie": _ck2.split(";")[0]}
    check("a second paired browser reads /api/state", call("GET", "/api/state", headers=S2)[0] == 200)
    _k2 = d._sha(S2["Cookie"].split("=", 1)[1])
    _exp0 = d._sessions()[_k2]["exp"]
    def _ask(h):
        _c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        _c.request("GET", "/api/session", headers={"Host": f"127.0.0.1:{PORT}", **S2, **h}); _r = _c.getresponse(); _r.read(); _c.close()
        return _r.status, _r.getheader("Set-Cookie", "")
    _a1 = _ask({}); _a2 = _ask({"X-Quarterdeck-Token": _j2["token"]})
    check("M1 asking /api/session does not extend a fresh session, with or without the token", _a1[0] in (401, 403) and _a2[0] == 200 and not _a1[1] and not _a2[1]
          and d._sessions()[_k2]["exp"] == _exp0, (_a1, _a2))
    with d._SESSIONS_LOCK:
        d._sessions()[_k2]["exp"] = time.time() + 3600; d._sessions_save(d._sessions())
    _a3 = _ask({}); _e3 = d._sessions()[_k2]["exp"]; _a4 = _ask({"X-Quarterdeck-Token": _j2["token"]})
    check("M1 a session past half its day is renewed only by its own tab (cookie and token), never by the cookie alone",
          _a3[0] in (401, 403) and _e3 < time.time() + 3700 and _a4[0] == 200 and "Max-Age=86400" in _a4[1] and "HttpOnly" in _a4[1] and d._sessions()[_k2]["exp"] > time.time() + 86000, (_a3, _a4))
    check("logout ends that session: the same cookie is 401 afterwards, the other browser is untouched",
          call("POST", "/api/logout", {}, {**S2, "X-Quarterdeck-Token": _j2["token"], "Origin": f"http://127.0.0.1:{PORT}"})[0] == 200
          and call("GET", "/api/state", headers=S2)[0] == 401 and call("GET", "/api/state")[0] == 200)
    _c3, _j3, _ck3 = _pair(d.pair_mint()); S3 = {"Cookie": _ck3.split(";")[0]}
    check("a third browser is paired", call("GET", "/api/state", headers=S3)[0] == 200)
    d.sessions_revoke()                                                      # what `qtdeck dashboard sessions revoke` does: writes the file, touches nothing in memory
    check("revoking from the command line ends every session at once, in the running server (the file is re-read when it changes)",
          call("GET", "/api/state", headers=S3)[0] == 401 and call("GET", "/api/state")[0] == 401)
    _c4, _j4, _ck4 = _pair(d.pair_mint())
    SESSION["cookie"] = _ck4.split(";")[0]; SESSION["token"] = _j4["token"]    # the tests below speak as this fresh browser
    pt = {"X-Quarterdeck-Token": SESSION["token"]}
    check("the owner's CLI token (no Origin) still opens the API without a cookie", call("GET", "/api/state", headers={**tok, "Cookie": ""})[0] == 200)
    # R2: the CLI token is for the owner's own dev tools (chat-eval, helm-eval). A process that merely READ the file can read, and talk to Helm, but not run
    # anything: no capture, run, merge, attach, connections. (Before: any write.)
    cli = tok
    check("R2 the CLI token can POST /api/chat and /api/understand but no other write: /api/capture, /api/run, /api/merge, /api/attach, /api/connections, /api/newproject, /api/demo are 403",
          all(call("POST", p_, {"text": "x"}, {**cli, "Cookie": ""})[0] == 403 for p_ in ("/api/capture", "/api/run", "/api/merge", "/api/attach", "/api/connections", "/api/newproject", "/api/demo", "/api/fix"))
          and call("POST", "/api/chat", {}, {**cli, "Cookie": ""})[0] == 200)
    check("R2 pairing: 15 junk nonces (any page can send them) do not stop the owner's real link; junk is slowed, and a valid nonce is always redeemed",
          all(_pair("J" * 24 + str(i))[0] in (401, 429) for i in range(15)) and _pair("K" * 24)[0] == 429
          and _pair(d.pair_mint())[0] == 200)
    # from here on the tests speak as the paired browser (session token + this server's Origin), as the page does
    tok = {"X-Quarterdeck-Token": SESSION["token"], "Origin": f"http://127.0.0.1:{PORT}"}
    check("HEAD is refused and reads nothing", call("HEAD", "/bin/dashboard.py", headers={"Host": "evil.example"})[0] == 405 and call("HEAD", "/")[0] == 405)
    check("a negative Content-Length is 400 at once", call("POST", "/api/capture", headers={**tok, "Content-Length": "-1"})[0] == 400)
    check("a body that is not JSON, or not an object, is 400, never read as empty", call("POST", "/api/capture", raw=b"{nope", headers=tok)[0] == 400
          and call("POST", "/api/capture", raw=b"[1,2]", headers=tok)[0] == 400)
    check("a body over the cap is 413", call("POST", "/api/capture", raw=b"{}", headers={**tok, "Content-Length": "3000000"})[0] == 413)
    # L2 (round 5): idle half-open connections time out, and there is a cap, so a local process cannot use up the server's file descriptors
    check("L2 every connection has a socket timeout and the server caps how many it serves at once",
          getattr(d.Handler, "timeout", None) == 15 and 0 < getattr(d, "MAX_CONNECTIONS", 0) <= 128)
    _t_old = d.Handler.timeout
    d.Handler.timeout = 3                                                    # the real one is 15 seconds; the test waits for 3
    _idle = []
    try:
        for _ in range(getattr(d, "MAX_CONNECTIONS", 128) + 40):
            _s = socket.create_connection(("127.0.0.1", PORT)); _s.sendall(b"GET / HTTP/1.1\r\n"); _idle.append(_s)
        def _n_closed(wait):
            n = 0
            for _s in _idle:
                _s.settimeout(wait)
                try:
                    n += _s.recv(1) == b""
                except TimeoutError:
                    pass                                                     # still open: nobody closed it
                except OSError:
                    n += 1
            return n
        time.sleep(0.3)
        _early = _n_closed(0.001)                                            # well inside the 3 second timeout
        time.sleep(3.5)
        _late = _n_closed(1)
        check("L2 connections beyond the cap are closed at once, idle ones time out, and the owner's request is answered",
              _early >= 40 and _late == len(_idle) and call("GET", "/api/health")[0] == 200, (_early, _late, len(_idle)))
    finally:
        for _s in _idle:
            _s.close()
        d.Handler.timeout = _t_old
    # round 6 L-1: a client that sends a header line every second never goes idle, so the idle timeout is not enough: the whole request has a deadline
    check("L-1 the whole request (line, headers, body) has a deadline of at most 25 seconds", 0 < getattr(d.Handler, "DEADLINE", 0) <= 25)
    _dl_old = getattr(d.Handler, "DEADLINE", None)
    d.Handler.DEADLINE = 3                                                   # the real one is 20 seconds; the test waits for 3
    _drip = []
    try:
        for _ in range(d.MAX_CONNECTIONS):
            _s = socket.create_connection(("127.0.0.1", PORT)); _s.sendall(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n"); _drip.append(_s)
        for _ in range(5):                                                   # 5 seconds of one header line per second per socket
            time.sleep(1)
            for _s in _drip:
                try:
                    _s.sendall(b"X-a: b\r\n")
                except OSError:
                    pass
        try:
            _hc = call("GET", "/api/health")[0]
        except OSError:
            _hc = 0                                                          # reset: every slot was taken
        _dead = 0
        for _s in _drip:
            _s.settimeout(0.5)
            try:
                _dead += _s.recv(1) == b""
            except TimeoutError:
                pass
            except OSError:
                _dead += 1
        check("L-1 slow-drip sockets are cut at the deadline and the owner's request is answered", _hc == 200 and _dead == len(_drip), (_hc, _dead))
    finally:
        for _s in _drip:
            _s.close()
        if _dl_old is not None:
            d.Handler.DEADLINE = _dl_old
    # round 6 I-2: pairing works in demo mode too (sessions are not project data)
    d.demo_set(True)
    try:
        d._SESSIONS["map"] = None
        _dc, _dj, _dck = _pair(d.pair_mint())
        check("I-2 pairing works while demo mode is on", _dc == 200 and _dj.get("token") and "qd_session=" in _dck, (_dc, _dj))
    finally:
        d.demo_set(False)
    check("project folders must sit under the allowed roots, not in a dot folder, and the error says where is allowed",
          (lambda e: e is not None and str(Path.home().resolve()) in e and "QUARTERDECK_PROJECT_ROOTS" in e)(
              next(iter([x for x in [d.attach_api({"path": "/etc"})[1].get("error")] if x]), None))
          and d.attach_api({"path": str(Path.home() / ".ssh")})[0] == 400 and d.newproject_api({"name": "x", "folder": "/etc", "confirm": True})[0] == 400
          and d.newproject_api({"name": "x", "folder": str(Path.home() / ".config"), "confirm": True})[0] == 400)
    _rt = Path(tempfile.mkdtemp()); (_rt / "link").symlink_to("/etc"); os.environ["QUARTERDECK_PROJECT_ROOTS"] = str(_rt.resolve())
    check("a symlink inside an allowed root that leads out of it is refused", d.attach_api({"path": str(_rt / "link")})[0] == 400)
    os.environ.pop("QUARTERDECK_PROJECT_ROOTS")
    check("a log field can never break a log line", "\n" not in d.log_field("a\nb\r\u2028c") and d.log_field("x" * 999).__len__() == 120)
    check("a run argument cannot start with a dash (-Rx/y) or a space and still passes a plain one",
          not d.SAFE_VALUE.match("-Rx/y") and d.SAFE_VALUE.match("owner/repo") and d.SAFE_VALUE.match("12"))

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
    check("a write without the token is 403", code == 403 or code == 401)
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
    _c, _j, _ck = _pair(d.pair_mint())                                       # a start ends every session (round 6 L-3): the owner pairs again
    SESSION["cookie"] = _ck.split(";")[0]; SESSION["token"] = _j["token"]; tok["X-Quarterdeck-Token"] = _j["token"]
    _, st = jget("/api/state")
    check("state survives stopping and starting the server",
          any(i["id"] == kept for i in st["captures"]["items"]))

    call("POST", "/api/demo", {"on": True}, tok)
    code, body = call("GET", "/api/health")
    call("POST", "/api/demo", {"on": False}, tok)
    check("/api/health answers while Demo mode is on (qtdeck check runs during a rehearsal)",
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
    _c.request("GET", f"/api/mockup?brief={b1}&name=available-books", headers={"Host": f"127.0.0.1:{PORT}", "Cookie": SESSION["cookie"]})
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
    check("  an idea starts `qtdeck brief --idea ... --id ... --apply` by argv and leaves a drafting record the page can watch",
          code == 200 and B.id_ok(r["id"]) and spawned[-1][1:4] == ["brief", "--idea", "a page for my neighbourhood book swap"] and "--apply" in spawned[-1] and "--project" in spawned[-1]
          and jget(f"/api/brief?id={r['id']}")[1]["status"] == "drafting")
    code, r = pj("/api/brief/new", {"project": "tp", "issue": 12, "confirm": True})
    check("  an issue of a project with the duty on starts `qtdeck run tp brief --issue 12 --id ... --apply`", code == 200 and spawned[-1][1:6] == ["run", "tp", "brief", "--issue", "12"] and "--apply" in spawned[-1])
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
    # round 6 L-3: starting the dashboard ends every session, so a squatter that held the port while it was down keeps nothing
    _old_cookie, _old_token = SESSION["cookie"], SESSION["token"]
    check("L-3 before a start the paired cookie works", call("GET", "/api/state")[0] == 200)
    d.make_server(free_port()).server_close()                                # a start, on another port
    check("L-3 after a start the old cookie and token are refused, and a new link pairs again",
          call("GET", "/api/state")[0] == 401 and call("GET", "/api/session", headers={"X-Quarterdeck-Token": _old_token})[0] == 401
          and _pair(d.pair_mint())[0] == 200)
    _c, _j, _ck = _pair(d.pair_mint())
    SESSION["cookie"] = _ck.split(";")[0]; SESSION["token"] = _j["token"]
finally:
    stop(srv, thread)
    d.restore_state(saved)

print()
if FAILS:
    print(f"  {len(FAILS)} check(s) failed")
    sys.exit(1)
print("  all checks passed")
