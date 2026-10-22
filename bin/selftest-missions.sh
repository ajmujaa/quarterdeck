#!/bin/bash
# Missions that tell the truth: a merged pull request is Merged (whatever started the fix), "already fixed" is Nothing to build and not a failure, and a finished
# or stopped mission has buttons that do what they say and nothing more. A real dashboard runs on a free port in a throwaway Quarterdeck (the program tree is
# copied, the data folder is a temp folder with the .quarterdeck-home marker, HOME is a temp folder), paired through its one-time link. gh is a stand-in that
# records every call and answers pull request states from files; there is no network, no real model, no GitHub account.
#
#   1  a fix with a pull request becomes merged or closed from what GitHub says, any panel (the issue panel too); open and "gh failed" change nothing;
#      a record the owner marked is never moved; opening a mission refreshes it at once
#   2  NO_CHANGE is state "nothing" with the reason in plain words; it is not blocked, not counted as needing you; the old-mission grouping with fixed dates
#   3  the actions are refused unpaired (401), with a wrong token or origin (403), without confirm where it is needed (400) and in Demo mode (400)
#   4  each action does what it says and nothing more: dismiss and undo, close the issue, try again, mark as merged
#   5  the page, in a headless browser (skipped, saying so, when this machine has none)
# QD_KEEP=1 keeps the throwaway folder; QD_KEEP_SHOTS=<folder> copies the pictures the page checks take there.
ST_PROVIDER=fake
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init planner purser panel shipwright
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
mkdir -p "$T/home" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
export QUARTERDECK_HOME="$T" REAL; touch "$T/.quarterdeck-home"
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT

st_repo
git -C "$T/work" checkout -q main
jq -n --arg w "$T/work" '
  def p($repo; $duties; $cycle): {repo:$repo, path:$w, summary:"a fixture", default_branch:"main", duties:$duties, guardrails:[], verify:"true", forbidden_paths:["secrets/"]} + (if $cycle then {cycle:true} else {} end);
  {tp: p("x/tp"; ["planner","purser","panel","shipwright"]; true), tb: p("x/tb"; ["planner","purser","panel","shipwright","brief"]; false)}' > "$T/config/projects.json"

# the gh stand-in: a pull request's state is the file ghdata/prstate-<number>.json (absent or gh-fail: gh fails); `issue close` is recorded and may be made to fail
cat > "$T/path/gh2" <<'GH'
#!/bin/bash
D="$QUARTERDECK_DIR"
case "$1 $2" in
  "pr view")     echo "gh $*" >> "$D/gh-calls"; [ -f "$D/gh-fail" ] && exit 1; f="$D/ghdata/prstate-${3##*/}.json"; [ -f "$f" ] || exit 1; cat "$f"; exit 0 ;;
  "issue close") echo "gh $*" >> "$D/gh-calls"; [ -f "$D/gh-closefail" ] && { echo "could not close" >&2; exit 1; }; exit 0 ;;
esac
exec "$D/path/gh" "$@"
GH
chmod +x "$T/path/gh2"; export QUARTERDECK_GH="$T/path/gh2"
echo '[]' > "$T/ghdata/issue-list.json"
export QUARTERDECK_FAKE_SCRIPT="$T/fake-script.json"; echo '[]' > "$QUARTERDECK_FAKE_SCRIPT"
export QUARTERDECK_DAILY_BUDGET=100 QUARTERDECK_CALL_BUDGET=0.01 QUARTERDECK_CYCLE_BUDGET=15

# the records: fix records as `qtdeck fix` leaves them, dates relative to now so the page's seven day rule is real
mkdir -p "$T/state/fixes" "$T/state/panels" "$T/state/cycles"
python3 - "$T" <<'PY'
import json, sys, time
T = sys.argv[1]
def at(days=0, minutes=0): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400 - minutes * 60))
def fix(panel, item, status, **kw):
    r = {"project": "tp", "panel": panel, "item": item, "title": kw.pop("title", "Fix number %s" % item), "kind": "change", "tier": "routine", "status": status, "step": None,
         "lock": "fix-tp-%s" % item, "fixrun": "fix-%s-%s" % (panel, item), "started": at(minutes=30), "finished": at(minutes=20), "issue": item if panel == "issue" else 1,
         "pr": None, "verdict": None, "detail": ""}
    r.update(kw); json.dump(r, open("%s/state/fixes/%s-%s.json" % (T, panel, item), "w"))
pr = lambda n: "https://github.com/x/tp/pull/%d" % n
fix("issue", 7, "pr", pr=pr(70), title="Merged on GitHub, still open here", verdict="PROVEN")
fix("issue", 8, "pr", pr=pr(71), title="Closed on GitHub")
fix("issue", 9, "pr", pr=pr(72), title="Still open on GitHub")
fix("issue", 10, "pr", pr=pr(73), title="GitHub cannot be asked")
fix("pnl1", 1, "pr", pr=pr(74), title="A panel item, merged")
fix("issue", 15, "pr", pr=pr(75), title="The owner marked this one", source="owner")
fix("issue", 17, "pr", pr=pr(77), title="Merged, seen when opened")
fix("issue", 19, "pr", pr=pr(79), title="To mark as merged")
fix("issue", 11, "blocked", title="Already fixed on main", detail="NO_CHANGE already fixed on main in 4f2a9c1e " + chr(8212) + " #11")
fix("issue", 12, "blocked", title="The title already matches", detail="NO_CHANGE the title already matches the issue " + chr(8212) + " #12")
fix("issue", 13, "failed", title="Stopped weeks ago", detail="the shipwright could not build it", started=at(days=20, minutes=5), finished=at(days=20))
fix("issue", 14, "failed", title="Stopped today", detail="the shipwright ran out of budget")
fix("issue", 16, "blocked", title="Stopped, to be closed", detail="NO_CHANGE already fixed on main in 9ab3c4d " + chr(8212) + " #16")
fix("issue", 20, "failed", title="Stopped, to try again", detail="the build did not pass its tests")
fix("issue", 21, "failed", title="Stopped, on a project with the brief duty", detail="the build did not pass its tests", project="tb")
json.dump({"id": "pnl1", "project": "tp", "discipline": "dev", "status": "done", "started": at(minutes=60), "finished": at(minutes=50), "subject": "a fixture panel",
           "ruling": [{"title": "Item one", "kind": "change", "tier": "routine"}, {"title": "Item two", "kind": "change", "tier": "routine"}], "seats": []}, open(T + "/state/panels/pnl1.json", "w"))
fix("pnl1", 2, "failed", title="Item two", detail="the build failed")
json.dump({"kind": "cycle", "id": "cyc-tp-5-1700000000", "project": "tp", "issue": 5, "title": "A cycle that stopped", "apply": True, "status": "failed",
           "stages": [], "started": at(minutes=40), "finished": at(minutes=30), "cost": 0.5, "final": "a stage failed"}, open(T + "/state/cycles/cyc-tp-5-1700000000.json", "w"))
for n, state, extra in ((70, "MERGED", {"mergedAt": "2026-03-02T10:00:00Z", "mergeCommit": {"oid": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"}}), (71, "CLOSED", {}), (72, "OPEN", {}),
                        (74, "MERGED", {"mergedAt": "2026-03-03T10:00:00Z", "mergeCommit": {"oid": "b1b2c3d4e5f6"}}), (75, "MERGED", {"mergedAt": "2026-03-04T10:00:00Z"}), (77, "OPEN", {}), (79, "OPEN", {})):
    json.dump({"state": state, **extra}, open("%s/ghdata/prstate-%d.json" % (T, n), "w"))
PY

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
export QD_PORT="$PORT" T
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi
sleep 3   # the dashboard's own first look at GitHub (its scheduler) is over; what follows is what these checks cause
: > "$T/gh-calls"

cat > "$T/qc.py" <<'PY'
import http.client, json, os, re, subprocess, sys, time
PORT, T = int(os.environ["QD_PORT"]), os.environ["T"]
ORIGIN = "http://127.0.0.1:%d" % PORT
def chk(label, cond): print(("ok " if cond else "FAIL ") + label)
def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None: h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
    c.request(method, path, body=data, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    try: j = json.loads(raw)
    except ValueError: j = {"raw": raw.decode("replace")}
    return r.status, j, r.getheader("Set-Cookie") or ""
def pair():
    link = subprocess.run([sys.executable, T + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
    st, j, ck = req("POST", "/api/pair", {"nonce": link.split("#pair=")[1]})
    return {"cookie": ck.split(";")[0], "token": j["token"]}
S = pair()
def get(path): return req("GET", path, headers={"Cookie": S["cookie"]})[:2]
def post(path, body, **over):
    h = {"Cookie": S["cookie"], "X-Quarterdeck-Token": S["token"], "Origin": ORIGIN}
    h.update(over)
    return req("POST", path, body, {k: v for k, v in h.items() if v is not None})[:2]
def act(mid, action, **kw): return post("/api/mission/action", dict({"id": mid, "action": action}, **kw))
def rec(name): return json.load(open("%s/state/fixes/%s.json" % (T, name)))
def ghcalls(): return open(T + "/gh-calls").read().splitlines() if os.path.exists(T + "/gh-calls") else []
def files():
    out = set()
    for root, _, names in os.walk(T):
        if "/home" in root[len(T):] or "/.git" in root: continue
        for n in names: out.add(os.path.join(root, n)[len(T):])
    return out
PY

pyck() { # pyck <file.py>: each "ok ..." / "FAIL ..." line of its output is one check; a block that crashes is one failed check
  local line n=0
  python3 "$1" > "$T/py.out" 2> "$T/py.err"; local prc=$?
  while IFS= read -r line; do
    case "$line" in
      ok\ *)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)); n=$((n + 1)) ;;
      FAIL\ *) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)); n=$((n + 1)) ;;
    esac
  done < "$T/py.out"
  if [ "$prc" != 0 ] || [ "$n" = 0 ]; then printf '  FAIL  a python block crashed (exit %s): %s\n' "$prc" "$(tail -3 "$T/py.err" | tr '\n' ' ')"; fails=$((fails + 1)); fi
}

# ---- 1. what GitHub says about the pull request --------------------------------------------------------------------------------------------
cat > "$T/t1.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
sys.path.insert(0, T + "/bin")
import dashboard as d
n = d.sync_fix_status(force=True)
chk("the scheduled pass writes what GitHub changed: a merged pull request on an issue-panel record becomes merged", rec("issue-7")["status"] == "merged")
r = rec("issue-7")
chk("  with its time and merge commit, and the record says it was GitHub that said so", r["merged"] == "2026-03-02T10:00:00Z" and r["merge_commit"] == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2" and r["source"] == "github" and r["issue"] == 7 and r["pr"].endswith("/70"))
chk("a closed pull request becomes closed", rec("issue-8")["status"] == "closed")
chk("an open one stays pr, and so does one whose state gh cannot give", rec("issue-9")["status"] == "pr" and rec("issue-10")["status"] == "pr")
chk("a record from a real panel reconciles too (the same pass, no ruling needed)", rec("pnl1-1")["status"] == "merged")
chk("a record the owner marked is never moved, even when GitHub says merged", rec("issue-15")["status"] == "pr" and rec("issue-15")["source"] == "owner")
open(T + "/gh-fail", "w").close()
before = {k: rec(k) for k in ("issue-9", "issue-10", "issue-17")}
d._pr_checked.clear(); d._sync_pr_records()
os.remove(T + "/gh-fail")
chk("when gh fails the records are as they were", all(rec(k) == v for k, v in before.items()))
open(T + "/ghdata/prstate-77.json", "w").write('{"state": "MERGED", "mergedAt": "2026-03-05T10:00:00Z"}')
t0 = time.time(); st, m = get("/api/mission?id=fix:issue%2317")
chk("opening the mission refreshes it at once: a pull request that merged since is Merged, with no wait for the next scheduled pass", st == 200 and m["state"] == "done" and m["detail"]["title"] == "Merged" and m["fix_status"] == "merged" and time.time() - t0 < 5)
chk("  the Review step is done, nothing says Awaiting you, and the pull request is in the evidence", m["pipeline"][4]["state"] == "done" and m["pipeline"][4]["note"] == "Merged" and "Awaiting" not in json.dumps(m) and m["evidence"]["pr"].endswith("/77") and m["merged"]["by"] == "github")
open(T + "/gh-fail", "w").close(); d._pr_checked.clear()
t0 = time.time(); st, m = get("/api/mission?id=fix:issue%2310")
os.remove(T + "/gh-fail")
chk("opening a mission when gh fails is quiet: the old state, a 200, and no long wait", st == 200 and m["state"] == "awaiting" and time.time() - t0 < 5 and rec("issue-10")["status"] == "pr")
st, m = get("/api/mission?id=fix:issue%239")
chk("a pull request that is open stays Awaiting you", m["state"] == "awaiting" and m["detail"]["title"] == "Waiting for you")
post("/api/demo", {"on": True}); g0 = len(ghcalls())
get("/api/mission?id=fix:issue%2319"); get("/api/mission?id=fix:wayfarer-web%231")
post("/api/demo", {"on": False})
chk("Demo mode never calls gh", len(ghcalls()) == g0)
st, j = get("/api/state")
chk("the state document carries the merged record as merged, and the Needs you count no longer includes it", j["fixes"]["issue#7"]["status"] == "merged" and j["fixes"]["issue#7"]["mstate"] == "done")
PY
PYTHONPATH="$T/bin" pyck "$T/t1.py"

# ---- 2. Nothing to build, and old missions --------------------------------------------------------------------------------------------------
cat > "$T/t2.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
sys.path.insert(0, T + "/bin")
import dashboard as d
st, m = get("/api/mission?id=fix:issue%2311")
chk("NO_CHANGE is state nothing, titled Nothing to build, with the reason in plain words and the commit", st == 200 and m["state"] == "nothing" and m["detail"] == {"title": "Nothing to build", "body": "Already fixed on main in 4f2a9c1e."} and m["nothing"]["commit"] == "4f2a9c1e")
chk("  it is not blocked: no blocker, no blocked step, and no 'Open it to see why' words from the server", m["blocker"] is None and not any(n["state"] == "blocked" for n in m["pipeline"]) and "Blocked" not in json.dumps(m))
chk("  the steps that did not happen are Skipped, with the reason", all(n["state"] in ("done", "skipped") for n in m["pipeline"]) and any(n["state"] == "skipped" and "nothing to build" in n["note"] for n in m["pipeline"]))
st, m2 = get("/api/mission?id=fix:issue%2312")
chk("  without a commit the model's one line is used, capital first, clipped, and no dash from the record", m2["state"] == "nothing" and m2["detail"]["body"] == "The title already matches the issue." and chr(8212) not in json.dumps(m2["detail"]))
st, a = get("/api/mission?id=fix:issue%2314")
chk("a real stop is still blocked, with its cause", a["state"] == "blocked" and a["blocker"] and "budget" in a["blocker"]["cause"])
st, S0 = get("/api/state")
fx = S0["fixes"]
chk("the state document gives each fix its mission word: nothing for NO_CHANGE, blocked for the real stops, awaiting, done", fx["issue#11"]["mstate"] == "nothing" and fx["issue#12"]["mstate"] == "nothing"
    and fx["issue#14"]["mstate"] == "blocked" and fx["issue#13"]["mstate"] == "blocked" and fx["issue#9"]["mstate"] == "awaiting" and fx["issue#8"]["mstate"] == "done")
o = [x for x in S0["overview"] if x["name"] == "tp"][0]
live = [k for k, r in fx.items() if r["project"] == "tp" and r["mstate"] in ("blocked", "awaiting", "running") and k != "issue#13"]
chk("Projects counts: nothing-to-build is not open (not needing you), and the stop from weeks ago is not counted either", o["missions_open"] >= len(live) and not any(fx[k]["mstate"] == "nothing" for k in live)
    and o["missions_open"] == len(live) + len([c for c in S0["cycles"] if c["project"] == "tp" and c["mstate"] in ("blocked", "awaiting", "running")]) + len([p for p in S0["panels"] if p["project"] == "tp" and False]))
chk("  and the project is not red because of it (its state comes from what needs you, not from these)", o["state"] != "blocked")
# the old-mission rule, with fixed dates
NOW = d.datetime(2026, 2, 20, 12, 0, tzinfo=d.timezone.utc)
chk("a mission is old after seven days: 2026-02-12 is old on 2026-02-20, 2026-02-14 is not, none is not", d.mission_is_old("2026-02-12T11:00:00Z", NOW) and not d.mission_is_old("2026-02-14T00:00:00Z", NOW) and not d.mission_is_old(None, NOW) and not d.mission_is_old("2026-02-13T12:00:00Z", NOW))
fixes = {"a#1": {"project": "p", "panel": "a", "item": 1, "status": "failed", "finished": "2026-02-01T00:00:00Z", "started": "2026-02-01T00:00:00Z"},
         "a#2": {"project": "p", "panel": "a", "item": 2, "status": "failed", "finished": "2026-02-19T00:00:00Z"},
         "a#3": {"project": "p", "panel": "a", "item": 3, "status": "pr", "finished": "2026-01-01T00:00:00Z"},
         "a#4": {"project": "p", "panel": "a", "item": 4, "status": "blocked", "detail": "NO_CHANGE already there", "finished": "2026-02-19T00:00:00Z"},
         "a#5": {"project": "p", "panel": "a", "item": 5, "status": "failed", "finished": "2026-02-19T00:00:00Z"}}
ov = lambda dis: d.project_overview({"p": {}}, [], [], [], fixes, [], [], [], [], [], "", "", None, dis, NOW)[0]
chk("overview, fixed dates: of five fixes only the recent stop and the dismissed-free recent one count as open (an old stop and an old waiting one do not, nothing does not)", ov(None)["missions_open"] == 2 and ov(None)["missions_done"] == 1)
chk("  a dismissed mission is not counted as open either", ov({"fix:a#2": {"at": "x"}})["missions_open"] == 1)
PY
PYTHONPATH="$T/bin" pyck "$T/t2.py"

# ---- 3. who may press what -----------------------------------------------------------------------------------------------------------------
cat > "$T/t3.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
ACTS = [("fix:issue#13", "dismiss", {}), ("fix:issue#13", "undo", {}), ("fix:issue#11", "close_issue", {"confirm": True}), ("fix:issue#14", "retry", {"confirm": True}), ("fix:issue#19", "mark_merged", {})]
P = "/api/mission/action"
files0, gh0 = files(), ghcalls()
chk("unpaired, every action is 401", all(req("POST", P, dict({"id": m, "action": a}, **k))[0] == 401 for m, a, k in ACTS))
chk("a cookie without this tab's token is 403, and so is a wrong token", all(post(P, dict({"id": m, "action": a}, **k), **{"X-Quarterdeck-Token": None})[0] == 403 and post(P, dict({"id": m, "action": a}, **k), **{"X-Quarterdeck-Token": "nope"})[0] == 403 for m, a, k in ACTS))
chk("a foreign origin, and another port on localhost, are 403", all(post(P, dict({"id": m, "action": a}, **k), Origin="http://evil.example")[0] == 403 and post(P, dict({"id": m, "action": a}, **k), Origin="http://127.0.0.1:%d" % (PORT + 1))[0] == 403 for m, a, k in ACTS))
chk("none of those changed anything: no new file, no gh call", files() == files0 and ghcalls() == gh0 and not os.path.exists(T + "/state/dismissed-missions.json"))
st, j = act("fix:issue#11", "close_issue")
chk("close the issue without confirm is a 400 that says confirm, and calls nothing", st == 400 and "confirm" in j["error"] and not [l for l in ghcalls() if "issue close" in l])
st, j = act("fix:issue#14", "retry")
chk("try again without confirm is a 400 that says confirm, and starts nothing", st == 400 and "confirm" in j["error"] and not os.path.exists(T + "/logs/fix-tp.log"))
chk("a bad action, a bad id and an unknown mission are 400s", act("fix:issue#14", "explode")[0] == 400 and act("", "dismiss")[0] == 400 and act("fix:issue#999", "dismiss")[0] == 400 and post(P, {"id": ["x"], "action": "dismiss"})[0] == 400)
post("/api/demo", {"on": True}); files1, gh1 = files(), ghcalls()
got = [post(P, dict({"id": m, "action": a}, **k)) for m, a, k in ACTS + [("fix:issue#41", "dismiss", {}), ("fix:issue#41", "close_issue", {"confirm": True})]]
st, dm = get("/api/mission?id=fix:issue%2341")
st, ds = get("/api/state")
post("/api/demo", {"on": False})
chk("Demo mode answers every action 400 'Demo mode: nothing is changed.' and does nothing", all(s == 400 and j["error"] == "Demo mode: nothing is changed." for s, j in got) and files() == files1 and ghcalls() == gh1)
chk("  the made-up world has its own examples: a NO_CHANGE one (state nothing, Nothing to build)", st == 200 and dm["state"] == "nothing" and dm["detail"]["title"] == "Nothing to build")
chk("  and a merged fix, an old stopped one (three weeks) and a dismissed one, the dismissed list naming it", any(f["status"] == "merged" for f in ds["fixes"].values()) and ds["fixes"]["issue#12"]["status"] == "failed" and "fix:issue#18" in ds["dismissed_missions"])
PY
pyck "$T/t3.py"

# ---- 3d. small refusals: a note that is too long, a folder that is a file, an id that does not exist, a credential that is not one line of text -----
cat > "$T/t3d.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
st, j = post("/api/capture", {"text": "b" * 1001})
chk("a note over 1000 characters is refused, not cut", st == 400 and "1000" in j.get("error", ""))
st, j = post("/api/capture", {"text": "a\u0000b\u0007c"})
chk("control characters are removed from a note", st == 200 and j.get("text", j.get("note", {}).get("text")) == "abc")
import tempfile
home = tempfile.mkdtemp(); open(home + "/README.md", "w").write("x")
with open(T + "/config/quarterdeck.env", "a") as f: f.write("\nQUARTERDECK_PROJECT_ROOTS=\"${QUARTERDECK_PROJECT_ROOTS:-" + home + "}\"\n")
st, j = post("/api/newproject", {"name": "f1", "folder": home + "/README.md", "confirm": True})
chk("a new project in a folder path that is a file says so with a 400", st == 400 and "file" in j.get("error", ""))
st, j = get("/api/cycle/estimate?project=nope")
chk("a cycle estimate for a project that does not exist is a 400", st == 400)
st, j = post("/api/schedule", {"id": "zzzz", "delete": True})
chk("deleting a schedule that does not exist is a 404", st == 404)
st, j = post("/api/agent-sources", {"action": "remove", "id": "zork", "confirm": True})
chk("removing an agent source that does not exist is a 404", st == 404)
st, j = post("/api/agent-sources", {"action": "add", "name": "a\u0000b", "confirm": True})
chk("an agent source name with a control character says so", st == 400 and "control" in j.get("error", ""))
for v in ("xoxp-\u0000-1", 123):
    st, j = post("/api/connections", {"action": "credential", "id": "slack", "key": "SLACK_USER_TOKEN", "value": v, "confirm": True})
    chk("a credential value %r is refused" % (v,), st == 400)
import shutil; shutil.rmtree(home, ignore_errors=True)
PY
pyck "$T/t3d.py"


# ---- 4. each action does what it says and nothing more -----------------------------------------------------------------------------------------
cat > "$T/t4.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
sys.path.insert(0, T + "/bin")
import hashlib
fixdir = lambda: {n: open(T + "/state/fixes/" + n, "rb").read() for n in os.listdir(T + "/state/fixes")}
files0, gh0, fx0 = files(), ghcalls(), fixdir()
st, j = act("fix:issue#13", "dismiss")
chk("dismiss: a stopped mission is dismissed (200)", st == 200 and j == {"id": "fix:issue#13", "dismissed": True})
new = files() - files0
chk("  it wrote only the dismissed list and the one log line, in the data folder; gh was not called; no fix record changed", new <= {"/state/dismissed-missions.json", "/logs/missions.log"} and "/state/dismissed-missions.json" in new and ghcalls() == gh0 and fixdir() == fx0)
mode = oct(os.stat(T + "/state/dismissed-missions.json").st_mode & 0o777)
chk("  the file is private (0600) and holds the mission id and a time, nothing from the issue", mode == "0o600" and list(json.load(open(T + "/state/dismissed-missions.json"))) == ["fix:issue#13"])
line = open(T + "/logs/missions.log").read().strip().splitlines()[-1]
chk("  the log line has the action, the project and the mission id, and no issue text", re.fullmatch(r"\S+ dismiss project=tp mission=fix:issue#13", line) is not None)
st, m = get("/api/mission?id=fix:issue%2313"); st, s = get("/api/state")
chk("  the mission is still reachable by its address and says it is dismissed; the state lists it", m["dismissed"] is True and "fix:issue#13" in s["dismissed_missions"])
st, j = act("fix:issue#13", "undo")
chk("undo brings it back (and a second undo is a 400)", st == 200 and j["dismissed"] is False and "fix:issue#13" not in json.load(open(T + "/state/dismissed-missions.json")) and act("fix:issue#13", "undo")[0] == 400)
chk("a mission still waiting for you (a pull request open) cannot be dismissed", act("fix:issue#9", "dismiss")[0] == 400 and "fix:issue#9" not in json.load(open(T + "/state/dismissed-missions.json")))
act("fix:issue#13", "dismiss")
# close the issue
gh0 = len(ghcalls())
st, j = act("fix:issue#14", "close_issue", confirm=True)
chk("close the issue refuses a mission that is not 'Nothing to build' (400), and calls nothing", st == 400 and len(ghcalls()) == gh0)
open(T + "/gh-closefail", "w").close()
st, j = act("fix:issue#11", "close_issue", confirm=True)
os.remove(T + "/gh-closefail")
chk("when GitHub refuses, the answer is 409 with its reason and the record is not marked closed", st == 409 and "could not close" in j["error"] and "issue_closed" not in rec("issue-11"))
g1 = len(ghcalls())
st, j = act("fix:issue#11", "close_issue", confirm=True)
closes = [l for l in ghcalls()[g1:] if l.startswith("gh issue close")]
chk("after an explicit yes it calls gh issue close exactly once, for that issue and repo, with the fixed comment (the commit, no model text)", st == 200 and j["closed"] == 11 and len(closes) == 1
    and closes[0] == "gh issue close 11 -R x/tp --comment Closing this: it was already fixed on main in 4f2a9c1e. Closed from Quarterdeck at the owner's request.")
n_close = len([l for l in ghcalls() if l.startswith("gh issue close")])
chk("  it is recorded in the mission and the log, and a second press is refused without a second call", rec("issue-11")["issue_closed"] and get("/api/mission?id=fix:issue%2311")[1]["issue_closed"] and act("fix:issue#11", "close_issue", confirm=True)[0] == 409
    and len([l for l in ghcalls() if l.startswith("gh issue close")]) == n_close and "close_issue project=tp mission=fix:issue#11" in open(T + "/logs/missions.log").read())
# mark as merged
r0 = rec("issue-19")
st, j = act("fix:issue#19", "mark_merged")
chk("mark as merged is refused (409) while GitHub does not say merged, and the record is as it was", st == 409 and "does not say" in j["error"] and rec("issue-19") == r0)
open(T + "/ghdata/prstate-79.json", "w").write('{"state": "MERGED", "mergedAt": "2026-03-06T10:00:00Z", "mergeCommit": {"oid": "c1c2c3c4c5c6"}}')
st, j = act("fix:issue#19", "mark_merged")
chk("when GitHub says merged it writes merged with source 'owner' (a manual override later syncs never undo)", st == 200 and rec("issue-19")["status"] == "merged" and rec("issue-19")["source"] == "owner" and rec("issue-19")["merge_commit"] == "c1c2c3c4c5c6")
chk("  and a record that is merged already is refused (400)", act("fix:issue#19", "mark_merged")[0] == 400 and act("fix:issue#7", "mark_merged")[0] == 400)
# try again
st, j = act("fix:issue#11", "retry", confirm=True)
chk("try again is refused on 'Nothing to build' (it did not stop) and on a merged mission", st == 400 and act("fix:issue#7", "retry", confirm=True)[0] == 400)
with open(T + "/state/spend.jsonl", "a") as f:
    f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "project": "tp", "duty": "x", "cost": 500}) + "\n")
st, j = act("fix:issue#14", "retry", confirm=True)
rows = [l for l in open(T + "/state/spend.jsonl") if '"cost": 500' not in l]; open(T + "/state/spend.jsonl", "w").writelines(rows)
chk("with today's budget spent try again says so (409) and starts nothing", st == 409 and "budget" in j["error"] and not os.path.exists(T + "/logs/fix-tp.log"))
st, j = act("fix:issue#14", "retry", confirm=True)
chk("try again on a fix from an issue starts the fix pipeline for that issue (the same path as Start work)", st == 200 and j["started"] == "fix tp --issue 14")
time.sleep(1)
st, j = act("cycle:cyc-tp-5-1700000000", "retry", confirm=True)
chk("try again on a stopped cycle starts a cycle for that issue through the guarded start (the opt-in and the confirm rules apply)", st == 200 and j["started"] == "cycle tp --issue 5")
st, j = act("fix:pnl1#2", "retry", confirm=True)
chk("try again on a panel item queues that item for the panel's project, as Fix this does", st == 200 and "--panel pnl1 --item 2" in j["started"])
chk("every one of those is in the log, by action, project and id only", all(x in open(T + "/logs/missions.log").read() for x in ("retry project=tp mission=fix:issue#14", "retry project=tp mission=cycle:cyc-tp-5-1700000000", "mark_merged project=tp mission=fix:issue#19"))
    and "Fix number" not in open(T + "/logs/missions.log").read() and "budget" not in open(T + "/logs/missions.log").read())
PY
pyck "$T/t4.py"

# ---- 5. the page ---------------------------------------------------------------------------------------------------------------------------
if st_have_browser || node "$REAL/bin/missions-page.mjs" probe >/dev/null 2>&1; then
  mkdir -p "$T/shots"
  # the earlier blocks changed some records; the page sees these: issue-12 dismissed, issue-13 stopped weeks ago, issue-16 and issue-20 untouched
  printf '{"fix:issue#12": {"at": "2026-03-01T00:00:00Z"}}' > "$T/state/dismissed-missions.json"
  : > "$T/gh-calls"
  LINK=$(QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link)
  OUT=$(QD_LINK="$LINK" QD_SHOTS="$T/shots" QD_T="$T" node "$REAL/bin/missions-page.mjs" 2>&1); RC=$?
  printf '%s\n' "$OUT" | while IFS= read -r line; do
    case "$line" in
      "ok "*) printf '  ok    %s\n' "${line#ok }" ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }" ;;
      "skip "*) printf '  skip  %s\n' "${line#skip }" ;;
    esac
  done
  passed=$((passed + $(printf '%s\n' "$OUT" | grep -c '^ok ')))
  nf=$(printf '%s\n' "$OUT" | grep -c '^FAIL '); fails=$((fails + nf))
  if [ "$RC" != 0 ] && [ "$nf" = 0 ]; then printf '  FAIL  the page test crashed (exit %s): %s\n' "$RC" "$(printf '%s\n' "$OUT" | tail -3 | tr '\n' ' ')"; fails=$((fails + 1)); fi
  [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
else
  st_skip_browser "the page checks (the mission page, the buttons, Hide handled, the old group) are not run"
fi

st_done
