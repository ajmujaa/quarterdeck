#!/bin/bash
# Agent sources (round 4, level 2): the form's back end (bin/agentsources.py) against a fake local server. A copy of the program in a temp folder, a fake HOME,
# a data folder and a secrets folder of their own (the file credential store); nothing real is read or written (no port 7878, no ~/.quarterdeck, no ~/.config,
# no keychain). The fake server listens on 127.0.0.1 on a port the system picks; the https path is only checked as an address rule, no real https server is used.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT
fails=0
P="$T/prog"; mkdir -p "$P" "$T/home" "$T/secrets"
for d in bin config duties crew packs providers dashboard; do [ -d "$REAL/$d" ] && cp -R "$REAL/$d" "$P/"; done
rm -rf "$P/config/projects.json" "$P"/bin/__pycache__ "$P"/bin/integrations/__pycache__
QH="$T/data"; mkdir -p "$QH"; chmod 700 "$QH"; : > "$QH/.quarterdeck-home"
export HOME="$T/home" QUARTERDECK_HOME="$QH" QUARTERDECK_SECRETS_DIR="$T/secrets" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$P/bin"
unset QUARTERDECK_DIR PROJECTS_FILE
export QD_TEST_DATA="$QH" QD_TEST_SECRETS="$T/secrets"

python3 - <<'PY'
import json, os, re, stat, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ok_n, bad_n = 0, 0
def ck(label, cond, detail=""):
    global ok_n, bad_n
    if cond:
        ok_n += 1
        print("  ok    " + label)
    else:
        bad_n += 1
        print("  FAIL  " + label + ((" :: " + str(detail)[:300]) if detail else ""))

TOKEN = "tok-SECRET-9f3a71c2"
MARKUP = '<img src=x onerror=alert(1)> Relay & <b>nightly</b>'
HITS = {"other": []}

class Other(BaseHTTPRequestHandler):                      # a second "host" a redirect points at: it must never be called
    def do_GET(self):
        HITS["other"].append(self.headers.get("Authorization"))
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass

other = ThreadingHTTPServer(("127.0.0.1", 0), Other)
threading.Thread(target=other.serve_forever, daemon=True).start()

class H(BaseHTTPRequestHandler):
    def _json(self, doc, code=200):
        body = json.dumps(doc).encode()
        try:
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except OSError:
            pass                                          # the reader stopped early (the oversize reply): not an error here
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/good":
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self._json({"error": "no"}, 401)
            return self._json({"data": {"agents": [
                {"name": MARKUP, "status": "RUNNING", "updated_at": "2026-01-05T08:00:00Z", "summary": "3 of 10 done\nsecond line", "private_note": "do-not-keep-me"},
                {"name": "Relay report", "status": "completed", "updated_at": 1767600000, "summary": "x" * 500},
                {"name": "Relay sync", "status": "error", "updated_at": "yesterday-ish", "summary": ""},
                {"name": "Relay odd", "status": "banana"},
                {"status": "running"},
                "not an object"]}, "api_key": "do-not-keep-either"})
        if p == "/redirect":
            self.send_response(302); self.send_header("Location", "http://127.0.0.1:%d/x" % other.server_address[1]); self.end_headers(); return
        if p == "/big":
            return self._json({"data": {"agents": [{"name": "n" * 100, "status": "running"}] * 4000}})
        if p == "/notjson":
            body = b"<html>hello</html>"
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if p == "/nolist":
            return self._json({"other": 1})
        if p == "/slow":
            time.sleep(3); return self._json({"data": {"agents": []}})
        if p == "/boom":
            return self._json({}, 500)
        self._json({}, 404)
    def log_message(self, *a): pass

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
BASE = "http://127.0.0.1:%d" % PORT

QH, SEC = Path(os.environ["QD_TEST_DATA"]), Path(os.environ["QD_TEST_SECRETS"])
assert str(QH).startswith(os.environ["HOME"].rsplit("/", 1)[0]) and "7878" not in BASE
import agentsources as A
from integrations import common, manifest
import livework, fleetview

MAP = {"list": "data.agents", "name": "name", "status": "status", "last_run": "updated_at", "detail": "summary"}
def form(name, path, token=None, **kw):
    return {"name": name, "url": BASE + path, "token": token, "map": dict(MAP), **kw}

# ---- the address rules -------------------------------------------------------------------------------------------------------------------------
def bad_url(u):
    try:
        A.check_url(u); return False
    except A.SourceError:
        return True
refused = [u for u in ("http://example.com/x", "http://127.0.0.1/x", "http://127.0.0.1:0/x", "http://127.0.0.1:99999/x", "http://localhost:80/x", "http://127.0.0.2:80/x",
                       "http://127.0.0.1:80@evil.example.com/x", "ftp://example.com/x", "file:///etc/passwd", "//example.com", "https://", "https://u:pw@example.com/x",
                       "https://example.com/x?api_key=abc", "https://example.com/x#frag", "https://example.com/a b", "javascript:alert(1)", "", "https://example.com:99999/")
           if not bad_url(u)]
ck("only https, or http://127.0.0.1:<port>, is accepted: every other address is refused", not refused, refused)
ck("an https address and a tunnel address are accepted", not bad_url("https://agents.example.com/api/tasks") and not bad_url("http://127.0.0.1:8081/api/agents?limit=5"))

# ---- add: config without secrets, token in the credential store ---------------------------------------------------------------------------------
try:
    src = A.add(form("Relay agents", "/good", TOKEN))
    added = True
except Exception as e:
    added, src = False, str(e)
ck("a source is added from the form's fields", added, src)
cfgp = QH / "config" / "agent-sources.json"
mode = lambda p: stat.S_IMODE(p.stat().st_mode)
ck("config/agent-sources.json is mode 0600 and holds the name, address and field map but no token", cfgp.is_file() and mode(cfgp) == 0o600
   and TOKEN not in cfgp.read_text() and json.loads(cfgp.read_text())["sources"][0]["map"]["list"] == "data.agents")
envp = SEC / "integrations.env"
ck("the token is in the credential store (the private file, mode 0600) under AGENT_SOURCE_TOKEN@<id>, quoted like the others",
   envp.is_file() and mode(envp) == 0o600 and ('AGENT_SOURCE_TOKEN@%s="%s"' % (src["id"], TOKEN)) in envp.read_text())
ck("the same store reads it back for the request, and a second source gets its own", A._token(src["id"]) == TOKEN and A._token("nobody") == "")
for bad in (dict(form("x", "/good"), url="http://example.com/x"), dict(form("", "/good")), dict(form("y", "/good"), map={"list": "a b", "name": "n", "status": "s"}),
            dict(form("y", "/good"), map={"list": "", "name": "", "status": "s"}), dict(form("y", "/good"), token=5)):
    try:
        A.add(bad); bad["_ok"] = True
    except ValueError:
        pass
ck("a bad name, address, path or token is refused with a reason and adds nothing", len(A.load()) == 1)
dup = A.add(form("Relay agents", "/good"))
ck("a second source with the same name gets its own id", dup["id"] != src["id"] and len(A.load()) == 2)
A.remove(dup["id"])

# ---- reading: the field map, text only, nothing else kept --------------------------------------------------------------------------------------
started = A.kick(spawn=False, now=1_800_000_000)
snap = A.read_snapshot(src["id"])
ck("kick reads a due source and writes state/agent-sources/<id>/snapshot.json (mode 0600) ", started == [src["id"]] and snap and snap["ok"] is True
   and mode(QH / "state" / "agent-sources" / src["id"] / "snapshot.json") == 0o600, snap)
ag = (snap or {}).get("agents") or []
ck("four agents were kept (the row without a name and the one that is not an object were dropped)", len(ag) == 4, [a["name"] for a in ag])
ck("markup in a name is kept as the same characters, to be shown as text", ag and ag[0]["name"] == MARKUP)
ck("status words map to running, done, failed, unknown", [a["status"] for a in ag] == ["running", "done", "failed", "unknown"], [a["status"] for a in ag])
ck("a detail is one line cut to 200 characters; a time becomes ISO, or short text when it cannot be read", ag[0]["detail"] == "3 of 10 done second line" and len(ag[1]["detail"]) == 200
   and ag[0]["last_run"] == "2026-01-05T08:00:00Z" and ag[1]["last_run"].startswith("2026-01-") and ag[2]["last_run"] == "" and ag[2]["last_run_text"] == "yesterday-ish", ag[:3])
text = (QH / "state" / "agent-sources" / src["id"] / "snapshot.json").read_text()
ck("only the mapped fields are stored: nothing else of the reply, not the body, not the token", "do-not-keep" not in text and "api_key" not in text and "private_note" not in text and TOKEN not in text
   and set(ag[0]) == {"name", "status", "last_run", "last_run_text", "detail"})
ck("a second kick inside 60 seconds asks nothing; after 60 seconds it asks again", A.kick(spawn=False, now=1_800_000_030) == [] and A.kick(spawn=False, now=1_800_000_061) == [src["id"]])

# ---- Fleet and Home ---------------------------------------------------------------------------------------------------------------------------
fs = [s for s in fleetview.snapshot({"sources": [], "errors": []})["sources"] if s["kind"] == "agent-source"]
ck("the Fleet snapshot lists the source under its name, from the snapshot only", len(fs) == 1 and fs[0]["title"] == "Relay agents" and len(fs[0]["agents"]) == 4 and fs[0]["error"] == "")
live = livework.live_work([], [], {}, now=1_800_000_100, installed=True, agent_sources=fs)
run = [i for i in live["items"] if i["kind"] == "source"]
ck("only the agent whose status is running shows in Running now, with its source's name", len(run) == 1 and run[0]["agent"] == MARKUP and run[0]["source_title"] == "Relay agents" and run[0]["state"] == "working"
   and run[0]["doing"] == "3 of 10 done second line", run)
import dashboard as D
st = D.build_state()
ck("the dashboard's state carries the running agent in S.live", any(i.get("kind") == "source" and i["agent"] == MARKUP for i in st["live"]["items"]))
view = A.settings_view()
ck("the Connections page data says whether a token is saved and never carries it", view["sources"][0]["token"] is True and TOKEN not in json.dumps(view) and len(view["presets"]) == 2
   and all("example.com" in p["url"] or "127.0.0.1" in p["url"] for p in view["presets"]) and view["sources"][0]["state"] == "ok")

# ---- trouble: unreachable, wrong token, redirect, oversize, not JSON, no list, slow, server error -------------------------------------------------------
def one(path, token=TOKEN, **kw):
    s = A.add(dict(form("T" + path.strip("/"), path, token), **kw))
    snap = A.refresh(s)
    A.remove(s["id"])
    return snap
r = one("/redirect")
ck("a redirect is not followed: it is said in plain words and the other host was never called", r["ok"] is False and "another address" in r["error"] and HITS["other"] == [], (r["error"], HITS))
r = one("/big")
ck("a reply over 256 KB is not read", r["ok"] is False and "256 KB" in r["error"] and r["agents"] == [], r["error"])
r = one("/notjson")
ck("a reply that is not JSON says so", r["ok"] is False and "not JSON" in r["error"], r["error"])
r = one("/nolist")
ck("a reply without the mapped list says which path is wrong", r["ok"] is False and "data.agents" in r["error"], r["error"])
r = one("/good", token="wrong-token-value")
ck("a refused token says so, and the message holds neither token", r["ok"] is False and "refused the token" in r["error"] and "wrong-token-value" not in r["error"] and TOKEN not in r["error"], r["error"])
r = one("/boom")
ck("a server error says the source is having trouble", r["ok"] is False and "having trouble" in r["error"], r["error"])
A.TIMEOUT = 1
t0 = time.time(); r = one("/slow"); took = time.time() - t0
A.TIMEOUT = 10
ck("a slow source gives up at the timeout", r["ok"] is False and "did not answer" in r["error"] and took < 2.5, (r["error"], took))
import socket
s0 = socket.socket(); s0.bind(("127.0.0.1", 0)); dead = s0.getsockname()[1]; s0.close()
gone = A.add({"name": "Relay gone", "url": "http://127.0.0.1:%d/x" % dead, "map": dict(MAP)})
A.refresh(gone)
r = A.read_snapshot(gone["id"])
ck("an unreachable source says so in plain words and the rest keeps working", r["ok"] is False and r["error"].startswith("Could not reach it") and r["agents"] == [])
fs2 = {s["title"]: s for s in A.fleet_sources()}
ck("the Fleet row of an unreachable source carries the sentence; a good one beside it is unchanged", fs2["Relay gone"]["error"] and fs2["Relay agents"]["error"] == "" and len(fs2["Relay agents"]["agents"]) == 4)
# a source that worked and then fails keeps its last list, marked as old
good = A.read_snapshot(src["id"])
src2 = dict(A.load()[0]); A.TIMEOUT = 1
broken = dict(src2, url=BASE + "/boom")
snap_b = A.refresh(broken, now=good["attempted_at"] + 100)
A.TIMEOUT = 10
ck("a source that fails after working keeps what it last reported, with the time it last worked", snap_b["ok"] is False and len(snap_b["agents"]) == 4 and snap_b["ok_at"] == good["ok_at"])
A.remove(gone["id"])

# ---- the dashboard's endpoint and the logs -------------------------------------------------------------------------------------------------------
code, body = D.agent_sources_api({"action": "add", **form("Relay two", "/good", TOKEN)})
ck("adding needs the owner's confirm", code == 400 and "confirm" in body["error"])
code, body = D.agent_sources_api({"action": "add", "confirm": True, **form("Relay two", "/good", TOKEN)})
ck("adding with a confirm works and answers with the id only", code == 200 and set(body) == {"id", "name"}, (code, body))
code, body = D.agent_sources_api({"action": "add", "confirm": True, **form("Relay bad", "/good", TOKEN, url="http://example.com/")})
ck("a bad address is a 400 with the reason", code == 400 and "https" in body["error"])
time.sleep(0.3)
two = body_id = None
for s in A.load():
    if s["name"] == "Relay two":
        two = s
code, body = D.agent_sources_api({"action": "remove", "confirm": True, "id": two["id"]})
ck("removing deletes the entry, the token and the snapshots", code == 200 and body == {"removed": True} and all(s["id"] != two["id"] for s in A.load())
   and ("@%s=" % two["id"]) not in envp.read_text() and not (QH / "state" / "agent-sources" / two["id"]).exists())

def tree_has(root, needle):
    hits = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = Path(dp) / f
            try:
                if needle.encode() in p.read_bytes():
                    hits.append(str(p))
            except OSError:
                pass
    return hits
leak = [h for h in tree_has(QH, TOKEN)] + [h for h in tree_has(Path(os.environ["HOME"]), TOKEN)]
ck("the token is in no file of the data folder (config, state, logs) or the fake home; only the credential store holds it", not leak, leak)
ck("the credential store holds it, and nowhere else under the secrets folder", [h for h in tree_has(SEC, TOKEN)] == [str(envp)])
log = QH / "logs" / "connections.log"
ck("the connections log names the action and the source id, never the address or token", log.is_file() and "agent-source-add" in log.read_text() and TOKEN not in log.read_text() and BASE not in log.read_text())
ck("known_keys carries the token key, so moving credentials between the file and the Keychain carries the tokens too", common.AGENT_SOURCE_KEY in manifest.known_keys() and src["id"] in common.agent_source_ids())
_html = (Path(os.environ["QD_TEST_DATA"]).parent / "prog" / "dashboard" / "index.html").read_text()
_fa = _html[_html.index("function fleetAgentSource("):_html.index("function viewFleet(")]
ck("the page shows a source's text as text: the Fleet rows pass name, detail, times and the error through esc(), and the Running now row passes the agent and source names through esc()",
   all(x in _fa for x in ("esc(a.name)", "esc(a.detail)", "esc(when)", "esc(s.error)", "esc(s.title)")) and "esc(i.agent)" in _html and "esc(i.source_title || i.source)" in _html)
print("\n  %d ok, %d failed" % (ok_n, bad_n))
sys.exit(1 if bad_n else 0)
PY
rc=$?
[ "$rc" = 0 ] && echo "  all checks passed" || { echo "  checks failed"; exit 1; }
