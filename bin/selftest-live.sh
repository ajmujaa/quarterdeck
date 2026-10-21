#!/bin/bash
# Live work on the dashboard: Home's Running now strip, a project's Live work card and the Crew page (enabled agents first, the rest folded in Available (N) with an
# Enable button). The data is a throwaway Quarterdeck: two registered projects (alpha-app and beta-api, real git repositories, alpha with an extra worktree that
# carries a draft pull request and another with changes nobody works in), a repository that is no project (the Relay scratch source), fleet events written the way
# bin/fleet-hook.sh writes them (a session working, one waiting for the owner, one with no detail, one finished, one in a worktree of no project, one with hostile
# text), a duty that is running (a live lock), and a stack scan record that suggests three duties. gh is a stand-in that serves pull request fixtures; the model is never
# started; HOME is a temp folder; the data folder carries the .quarterdeck-home marker. No network, no port 7878, no real ~/.quarterdeck, ~/.claude or LaunchAgent.
#
#   1  livework.live_work() on its own: shape, ordering, "no detail reported", a session that matches no project, hook installed or not, the age of the last update
#   2  /api/state carries S.live with the same shape; the hook install and uninstall change hook_installed, not the sessions
#   3  the Enable path (POST /api/project/duties): confirm required, refusals like the other writes, only the duties list changes, one log line
#   4  Demo mode serves invented Relay data through the same function, and its writes stay untouched
#   5  the page under node, without a browser (bin/selftest-live.mjs)
#   6  the page in a headless browser (skipped, saying so, when this machine has none): bin/live-page.mjs
# QD_KEEP=1 keeps the throwaway folder; QD_KEEP_SHOTS=<folder> copies the pictures.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"; cp -R "$REAL"/duties/. "$T/duties/"
mkdir -p "$T/home" "$T/state/profiles" "$T/state/fleet-events" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
export QUARTERDECK_HOME="$T" T REAL PYTHONDONTWRITEBYTECODE=1 QUARTERDECK_DAILY_BUDGET=25; touch "$T/.quarterdeck-home"
unset CLAUDE_SETTINGS_FILE
DASH=""; SLEEPER=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -z "$SLEEPER" ] || kill "$SLEEPER" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

# gh: serves ghdata/prs-<owner>-<name>.json, filtered by --head when asked; records every call
cat > "$T/path/gh" <<'GH'
#!/bin/bash
echo "gh $*" >> "$QUARTERDECK_DIR/gh-calls"
[ "$1 $2" = "pr list" ] || exit 0
repo=""; head=""
while [ $# -gt 0 ]; do case "$1" in -R) repo="$2" ;; --head) head="$2" ;; esac; shift; done
f="$QUARTERDECK_DIR/ghdata/prs-${repo//\//-}.json"
[ -f "$f" ] || { echo '[]'; exit 0; }
if [ -n "$head" ]; then jq -c --arg h "$head" '[.[] | select(.headRefName == $h)] | .[0:1]' "$f"; else cat "$f"; fi
GH
chmod +x "$T/path/gh"

# ---- the fixture: repositories, worktrees, events, a lock, the registry, a scan record ----
G="git -c user.name=fixture -c user.email=fixture@example.invalid"
for r in alpha-app beta-api scratch; do mkdir -p "$T/$r" && git -C "$T/$r" init -q -b main && echo "# $r" > "$T/$r/README.md" && git -C "$T/$r" add README.md && $G -C "$T/$r" commit -q -m init; done
git -C "$T/alpha-app" worktree add -q "$T/alpha-feat" -b feat/export 2>/dev/null
git -C "$T/alpha-app" worktree add -q "$T/alpha-spike" -b spike/probe 2>/dev/null
echo "work in progress" > "$T/alpha-spike/notes.txt"
cat > "$T/config/projects.json" <<JSON
{"alpha-app": {"repo": "x/alpha-app", "path": "$T/alpha-app", "summary": "a made-up app", "default_branch": "main", "duties": ["panel", "shipwright"], "guardrails": ["Never touch the payments folder"], "verify": "true"},
 "beta-api": {"repo": "x/beta-api", "path": "$T/beta-api", "summary": "a made-up api", "default_branch": "main", "duties": ["panel"], "guardrails": [], "verify": "true"}}
JSON
cat > "$T/config/fleet.local.json" <<JSON
{"sources": [{"id": "relay-scratch", "kind": "repo-agents", "path": "$T/scratch", "title": "Relay scratch"}]}
JSON
python3 - <<'PY'
import json, os, time
T = os.environ["T"]
now = time.time()
def ev(file, rows):
    with open(f"{T}/state/fleet-events/{file}.jsonl", "w") as f:
        for ago, kind, sess, wt, br, agent in rows:
            f.write(json.dumps({"t": now - ago * 60, "event": kind, "session": sess, "worktree": wt, "branch": br, "agent": agent}) + "\n")
EVIL = "<img src=x onerror=alert(1)>" + "y" * 200
ev("alpha-app", [
    (10, "session_start", "sess-work", "alpha-feat", "feat/export", ""), (4, "prompt", "sess-work", "alpha-feat", "feat/export", ""), (3, "agent_start", "sess-work", "alpha-feat", "feat/export", "reviewer"),
    (21, "session_start", "sess-wait", "alpha-app", "main", ""), (20, "prompt", "sess-wait", "alpha-app", "main", ""), (19, "stop", "sess-wait", "alpha-app", "main", ""),
    (2, "session_start", "sess-bare", "alpha-app", "main", ""),
    (100, "session_start", "sess-done", "alpha-old", "old/branch", ""), (90, "session_end", "sess-done", "alpha-old", "old/branch", ""),
])
ev("beta-api", [(2, "session_start", "sess-beta", "beta-api", "main", ""), (1, "prompt", "sess-beta", "beta-api", "main", "")])
ev("relay-scratch", [(50, "session_start", "sess-other", "scratch", "main", ""), (49, "prompt", "sess-other", "scratch", "main", ""), (48, "stop", "sess-other", "scratch", "main", ""),
                     (6, "session_start", "sess-evil", "scratch", EVIL, ""), (5, "prompt", "sess-evil", "scratch", EVIL, "")])
pr = lambda n, title, head, draft: {"number": n, "title": title, "state": "OPEN", "isDraft": draft, "headRefName": head, "reviewDecision": "", "statusCheckRollup": [], "updatedAt": "2026-10-20T10:00:00Z", "mergedAt": None}
json.dump([pr(12, "Add export", "feat/export", True)], open(f"{T}/ghdata/prs-x-alpha-app.json", "w"))
json.dump([], open(f"{T}/ghdata/prs-x-beta-api.json", "w"))
json.dump({"duty_reasons": {"surveyor": {"on": False, "suggested": True, "why": "it reads pull requests and the stack has tests"},
                            "inspector": {"on": False, "suggested": True, "why": "it checks a pull request against its issue"},
                            "marshal": {"on": False, "suggested": True, "why": "the stack handles user input"},
                            "panel": {"on": True, "suggested": False, "why": "on by default"}}, "suggested": ["surveyor", "inspector", "marshal"]},
          open(f"{T}/state/profiles/alpha-app.attach.json", "w"))
PY
# a duty that is running: a lock whose process is alive
sleep 600 & SLEEPER=$!
mkdir -p "$T/state/shipwright-alpha-app.lock" && echo "$SLEEPER" > "$T/state/shipwright-alpha-app.lock/pid" && echo "issue #7, Add export" > "$T/state/shipwright-alpha-app.lock/what"
# the sessions hook, installed into the temp HOME's settings by its own installer
if command -v jq >/dev/null 2>&1; then bash "$T/bin/fleet-hook.sh" install >/dev/null 2>&1; fi
ck "the hook installer wrote its entry into the temp HOME's settings and nowhere else" '[ ! -s "$T/home/.claude/settings.json" ] || grep -q "fleet-hook.sh" "$T/home/.claude/settings.json"'
cp "$T/config/projects.json" "$T/registry.before"

# ---- 1. live_work() on its own ----
cat > "$T/unit-check.py" <<'PY'
import json, os, sys, time
T = os.environ["T"]
sys.path.insert(0, T + "/bin")
import livework, fleetview
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:400]))
now = time.time()
ev = lambda rows: [{"t": now - a * 60, "event": k, "session": s, "worktree": w, "branch": b, "agent": g} for a, k, s, w, b, g in rows]
sess = fleetview.build_sessions(ev([(10, "session_start", "s-work", "wt1", "feat/a", ""), (4, "prompt", "s-work", "wt1", "feat/a", ""), (3, "agent_start", "s-work", "wt1", "feat/a", "reviewer"),
                                    (21, "session_start", "s-wait", "wt2", "main", ""), (20, "prompt", "s-wait", "wt2", "main", ""), (19, "stop", "s-wait", "wt2", "main", ""),
                                    (2, "session_start", "s-bare", "wt3", "main", ""), (100, "session_start", "s-done", "wt4", "old", ""), (90, "session_end", "s-done", "wt4", "old", "")]), now)
srcs = [{"id": "alpha", "title": "Relay", "project": "alpha", "last_event": now - 120, "sessions": sess,
         "worktrees": [{"name": "wt1", "branch": "feat/a", "main": False, "stage": "draft", "activity": "active", "changed": 0, "last_commit_ago": 300, "touched_ago": 200,
                        "pr": {"number": 5, "title": "T", "state": "open", "draft": True}}]}]
duties = [{"status": "running", "project": "alpha", "duty": "shipwright", "what": "issue #7", "since": "2026-10-20T10:00:00Z"}, {"status": "idle", "project": "alpha", "duty": "panel"}]
L = livework.live_work(srcs, duties, {"alpha": {"repo": "x/alpha"}}, now=now, installed=True, install_command="cmd")
it = L["items"]
KEYS = {"kind", "project", "source", "branch", "worktree", "agent", "doing", "since", "minutes", "waiting_on_owner", "state", "pr"}
chk("live_work returns exactly items, worktrees, updated_at, hook_installed, install_command and sources", set(L) == {"items", "worktrees", "updated_at", "hook_installed", "install_command", "sources"}, set(L))
chk("every item has exactly the documented fields", all(set(i) == KEYS for i in it), [set(i) ^ KEYS for i in it])
chk("sessions and duties are told apart: 4 sessions and 1 duty, the idle duty is not listed", sorted(i["kind"] for i in it) == ["duty", "session", "session", "session", "session"], [i["kind"] for i in it])
chk("order: working first (the duty and the session), then the one waiting for the owner, then the quiet one, finished last", [i["state"] for i in it] == ["working", "working", "idle", "idle", "finished"] and it[2]["waiting_on_owner"] and not it[3]["waiting_on_owner"], [(i["state"], i["waiting_on_owner"]) for i in it])
w = next(i for i in it if i["worktree"] == "wt1")
chk("a working session names its agent and what it is doing from the hook's events, and carries its draft pull request", w["agent"] == "reviewer" and w["doing"] == "Running the reviewer agent" and w["pr"] == {"number": 5, "draft": True, "url": "https://github.com/x/alpha/pull/5"}, w)
bare = next(i for i in it if i["worktree"] == "wt3")
chk("a session the hook told nothing about says no detail reported, for the agent and for what it is doing", bare["agent"] == "no detail reported" and bare["doing"] == "no detail reported" and not bare["waiting_on_owner"] and bare["pr"] is None, bare)
d = next(i for i in it if i["kind"] == "duty")
chk("a duty is named by its duty and shows the run's own words, with no branch and no pull request", d["agent"] == "shipwright" and d["doing"] == "issue #7" and d["branch"] == "" and d["pr"] is None and d["state"] == "working" and not d["waiting_on_owner"], d)
chk("minutes counts from when the state began (4 minutes since the prompt, 19 since the stop)", w["minutes"] in (3, 4) and next(i for i in it if i["worktree"] == "wt2")["minutes"] in (19, 20), [i["minutes"] for i in it])
chk("the worktree carries the session working in it and its pull request; last activity is the newer of commit and touch", L["worktrees"][0]["session"]["state"] == "working" and L["worktrees"][0]["pr"]["draft"] is True and L["worktrees"][0]["last_activity_ago"] == 200, L["worktrees"])
chk("updated_at is the newest event, as a UTC time", L["updated_at"] and abs(time.time() - __import__("calendar").timegm(time.strptime(L["updated_at"], "%Y-%m-%dT%H:%M:%SZ")) - 120) < 5, L["updated_at"])
srcs2 = [{**srcs[0], "id": "other", "project": "nope", "worktrees": []}]
L2 = livework.live_work(srcs2, [], {"alpha": {}}, now=now, installed=True)
chk("a session that cannot be tied to a registered project has the empty project (shown under Other)", L2["items"] and all(i["project"] == "" for i in L2["items"]) and L2["sources"][0]["project"] == "", L2["sources"])
chk("an event file that does not exist is no sessions, not an invented one", livework.live_work([{"id": "a", "project": "alpha", "sessions": None, "worktrees": [], "last_event": None}], [], {"alpha": {}}, now=now)["items"] == [])
home = os.environ["HOME"]
chk("with no settings file the hook is not installed, and a settings file without the hook says the same", livework.hook_installed(home + "/none.json") is False and not (open(home + "/s.json", "w").write("{}") and livework.hook_installed(home + "/s.json")))
open(home + "/s2.json", "w").write(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/x/bin/fleet-hook.sh"}]}]}}))
chk("a settings file that lists the hook script is installed; a broken settings file is not installed and does not throw", livework.hook_installed(home + "/s2.json") is True and not (open(home + "/bad.json", "w").write("{not json") and livework.hook_installed(home + "/bad.json")))
empty = livework.live_work([], [], {}, now=now, installed=False, install_command="cmd")
chk("nothing running and no hook: empty items, no update time, hook_installed false, the command is carried", empty["items"] == [] and empty["updated_at"] is None and empty["hook_installed"] is False and empty["install_command"] == "cmd", empty)
PY
report() { # report <python script>: its ok/FAIL lines become checks
  local line
  while IFS= read -r line; do
    case "$line" in
      "ok "*) printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
      *) [ -z "$line" ] || { printf '  FAIL  a check crashed: %s\n' "$line"; fails=$((fails + 1)); } ;;
    esac
  done
}
report < <(python3 "$T/unit-check.py" 2>&1)

# ---- the dashboard ----
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
export PORT
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi
newlink() { QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link; }

cat > "$T/api-lib.py" <<'PY'
import http.client, json, os, subprocess, sys, time
PORT, T = int(os.environ["PORT"]), os.environ["T"]
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:500]))
def raw(m, p, h=None, b=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    d = json.dumps(b).encode() if b is not None else None
    hh = dict(h or {})
    if d is not None: hh.update({"Content-Type": "application/json", "Content-Length": str(len(d))})
    c.request(m, p, body=d, headers=hh); r = c.getresponse(); body = r.read(); c.close(); return r.status, body, r.getheader("Set-Cookie") or ""
link = subprocess.run([sys.executable, T + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
st, body, ck = raw("POST", "/api/pair", b={"nonce": link.split("#pair=")[1]})
TOK, COOKIE = json.loads(body)["token"], ck.split(";")[0]
def get(p):
    st, body, _ = raw("GET", p, {"Cookie": COOKIE}); return st, json.loads(body)
def post(p, b):
    st, body, _ = raw("POST", p, {"Cookie": COOKIE, "X-Quarterdeck-Token": TOK, "Origin": "http://127.0.0.1:%d" % PORT}, b); return st, json.loads(body)
def state_with_trees(tries=40):
    for _ in range(tries):
        S = get("/api/state")[1]
        if S["live"]["worktrees"]: return S
        time.sleep(0.5)
    return S
PY

# ---- 2. /api/state ----
cat > "$T/state-check.py" <<'PY'
import os
exec(open(os.environ["T"] + "/api-lib.py").read())
S = state_with_trees()
L = S["live"]
it = L["items"]
KEYS = {"kind", "project", "source", "branch", "worktree", "agent", "doing", "since", "minutes", "waiting_on_owner", "state", "pr"}
chk("/api/state carries live with items, worktrees, updated_at, hook_installed, install_command and sources", set(L) == {"items", "worktrees", "updated_at", "hook_installed", "install_command", "sources"}, set(L))
chk("  every item has the documented fields, and the hook is installed in the temp HOME", all(set(i) == KEYS for i in it) and L["hook_installed"] is True, [set(i) ^ KEYS for i in it])
chk("  the install command names the hook script in this Quarterdeck", L["install_command"].startswith("bash ") and L["install_command"].endswith("bin/fleet-hook.sh install"), L["install_command"])
by = {(i["kind"], i["worktree"] or i["agent"]): i for i in it}
w = by.get(("session", "alpha-feat"))
chk("a session working in alpha-app's worktree: reviewer, running the reviewer agent, its draft pull request #12 with the address", bool(w) and w["project"] == "alpha-app" and w["agent"] == "reviewer" and w["state"] == "working" and w["pr"] == {"number": 12, "draft": True, "url": "https://github.com/x/alpha-app/pull/12"}, w)
wait = next((i for i in it if i["worktree"] == "alpha-app" and i["doing"] == "Finished its turn"), None)
chk("  the session whose turn finished is idle and waiting for the owner", bool(wait) and wait["state"] == "idle" and wait["waiting_on_owner"] is True and wait["agent"] == "no detail reported", wait)
bare = next((i for i in it if i["worktree"] == "alpha-app" and i["doing"] == "no detail reported"), None)
chk("  the session that only opened says no detail reported and is not waiting on the owner", bool(bare) and bare["agent"] == "no detail reported" and bare["waiting_on_owner"] is False and bare["state"] == "idle", bare)
done = next((i for i in it if i["worktree"] == "alpha-old"), None)
chk("  the session that ended is finished", bool(done) and done["state"] == "finished", done)
b = next((i for i in it if i["project"] == "beta-api"), None)
chk("  beta-api has its own session, working, with no detail on the agent", bool(b) and b["state"] == "working" and b["agent"] == "no detail reported" and b["doing"] == "Answering a prompt", b)
d = next((i for i in it if i["kind"] == "duty"), None)
chk("a running duty comes from the live lock: shipwright on alpha-app, with the run's own words", bool(d) and d["project"] == "alpha-app" and d["agent"] == "shipwright" and d["doing"] == "issue #7, Add export" and d["state"] == "working" and d["pr"] is None, d)
oth = [i for i in it if i["source"] == "relay-scratch"]
chk("sessions in a repository that is no registered project have the empty project, which the page shows under Other", len(oth) == 2 and all(i["project"] == "" for i in oth), oth)
ev = next((i for i in oth if "<img" in i["branch"]), None)
chk("text from an event is carried as text and clipped (80 characters for a branch): it stays data for the page to escape", bool(ev) and len(ev["branch"]) <= 80, ev and len(ev["branch"]))
order = [(i["state"], i["waiting_on_owner"]) for i in it]
rank = [0 if s == "working" else 1 if (s == "idle" and w_) else 2 if s == "idle" else 3 for s, w_ in order]
chk("ordering: working first, then waiting for the owner, then the quiet ones, finished last", rank == sorted(rank), order)
chk("updated_at is the newest event: under 2 minutes old", L["updated_at"] and time.time() - __import__("calendar").timegm(time.strptime(L["updated_at"], "%Y-%m-%dT%H:%M:%SZ")) < 130, L["updated_at"])
tr = {(t["project"], t["name"]): t for t in L["worktrees"]}
f = tr.get(("alpha-app", "alpha-feat"))
chk("the worktree with the draft pull request carries it, and the session working in it", bool(f) and f["pr"]["number"] == 12 and f["pr"]["draft"] is True and f["session"]["state"] == "working" and f["branch"] == "feat/export" and f["stage"] == "draft", f)
sp = tr.get(("alpha-app", "alpha-spike"))
chk("a worktree with changes nobody works in has no session (the page says nobody working in it)", bool(sp) and sp["session"] is None and sp["changed"] >= 1 and sp["stage"] == "working" and sp["pr"] is None, sp)
chk("projects carry the scan's suggestions that are still off, with its reasons", next(p for p in S["projects"] if p["name"] == "alpha-app")["suggested"] == [
    {"duty": "inspector", "why": "it checks a pull request against its issue"}, {"duty": "marshal", "why": "the stack handles user input"}, {"duty": "surveyor", "why": "it reads pull requests and the stack has tests"}]
    and next(p for p in S["projects"] if p["name"] == "beta-api")["suggested"] == [], [p["suggested"] for p in S["projects"]])
chk("the fleet document is still not in /api/state: only the live summary is", "fleet" not in S and "sources" not in S, [k for k in S if "fleet" in k])
import subprocess
subprocess.run(["bash", T + "/bin/fleet-hook.sh", "uninstall"], capture_output=True)
L2 = get("/api/state")[1]["live"]
chk("after the hook is removed from the settings, hook_installed is false and the sessions already seen are still listed", L2["hook_installed"] is False and len(L2["items"]) == len(it) and L2["updated_at"] == L["updated_at"], (L2["hook_installed"], len(L2["items"]), len(it)))
subprocess.run(["bash", T + "/bin/fleet-hook.sh", "install"], capture_output=True)
chk("and installing it again brings it back", get("/api/state")[1]["live"]["hook_installed"] is True)
PY
report < <(python3 "$T/state-check.py" 2>&1)

# ---- 3. the Enable path ----
cat > "$T/enable-check.py" <<'PY'
import os
exec(open(os.environ["T"] + "/api-lib.py").read())
REG = T + "/config/projects.json"
reg = lambda: json.load(open(REG))
before = reg()
st, j = post("/api/project/duties", {"project": "alpha-app", "add": ["marshal"]})
chk("Enable without confirm is refused, naming confirm, and nothing changes", st == 400 and "confirm" in j["error"] and reg() == before, (st, j))
st, j = post("/api/project/duties", {"project": "alpha-app", "add": ["nonesuch"], "confirm": True})
chk("an unknown duty is refused with a reason", st == 400 and j.get("error") and reg() == before, (st, j))
st, j = post("/api/project/duties", {"project": "no-such-project", "add": ["marshal"], "confirm": True})
chk("an unregistered project is refused", st == 400 and reg() == before, (st, j))
st, j = post("/api/project/duties", {"project": "alpha-app", "add": "marshal", "confirm": True})
chk("add must be a list of duty names", st == 400 and reg() == before, (st, j))
st, j = post("/api/project/duties", {"project": "alpha-app", "add": ["never merge"], "confirm": True})
chk("the standing rules are not duties and cannot be enabled or disabled", st == 400 and reg() == before, (st, j))
st, j = post("/api/project/duties", {"project": "alpha-app", "add": ["marshal"], "confirm": True})
after = reg()
chk("Enable with confirm turns the duty on and answers with the new list", st == 200 and "marshal" in j["duties"] and after["alpha-app"]["duties"] == ["panel", "shipwright", "marshal"], (st, j))
strip = lambda r: {k: {kk: vv for kk, vv in v.items() if kk != "duties"} for k, v in r.items()}
chk("the registry changed only the duties list: every other field of both projects is as it was, and beta-api is untouched", strip(after) == strip(before) and after["beta-api"] == before["beta-api"], after)
chk("the registry file is private (0600)", oct(os.stat(REG).st_mode & 0o777) == "0o600", oct(os.stat(REG).st_mode & 0o777))
log = open(T + "/logs/quarterdeck.log").read()
chk("one log line names the project and the duty, and nothing else", log.count("duties alpha-app: on marshal") == 1, log[-300:])
S = get("/api/state")[1]
pa = next(p for p in S["projects"] if p["name"] == "alpha-app")
chk("the state shows the duty as on and no longer suggested; the others are still suggested", "marshal" in pa["duties"] and [x["duty"] for x in pa["suggested"]] == ["inspector", "surveyor"], pa)
chk("the new agent is listed as an agent of the project (idle, never run)", any(a["project"] == "alpha-app" and a["duty"] == "marshal" and a["status"] == "idle" for a in S["agents"]))
open(T + "/registry.after", "w").write(open(REG).read())
PY
report < <(python3 "$T/enable-check.py" 2>&1)

# ---- 4. Demo mode ----
cat > "$T/demo-check.py" <<'PY'
import os
exec(open(os.environ["T"] + "/api-lib.py").read())
H = {"Cookie": COOKIE, "X-Quarterdeck-Token": TOK, "Origin": "http://127.0.0.1:%d" % PORT}
REG = T + "/config/projects.json"
b4 = open(REG).read()
st, body, _ = raw("POST", "/api/demo", H, {"on": True})
S = get("/api/state")[1]
L = S["live"]
chk("Demo mode answers with live work from invented Relay sessions, through the same function", st == 200 and L["items"] and L["hook_installed"] is True and {s["title"] for s in L["sources"]} == {"Relay"} and all(i["project"].startswith("wayfarer") or i["project"] == "" for i in L["items"]), L["sources"])
chk("  it has a working session, one waiting for the owner, a draft pull request, a duty and a session under Other", any(i["kind"] == "session" and i["state"] == "working" for i in L["items"]) and any(i["waiting_on_owner"] for i in L["items"])
    and any(i["pr"] and i["pr"]["draft"] for i in L["items"]) and any(i["kind"] == "duty" for i in L["items"]) and any(i["kind"] == "session" and i["project"] == "" for i in L["items"]), [(i["kind"], i["state"], i["project"]) for i in L["items"]])
chk("  none of it is the real data: no alpha-app, no beta-api, no real session", not any(i["project"] in ("alpha-app", "beta-api") for i in L["items"]) and not any(t["project"] in ("alpha-app", "beta-api") for t in L["worktrees"]))
chk("  the made-up projects carry made-up suggestions for the Crew page", any(p["suggested"] for p in S["projects"]))
st, j = post("/api/project/duties", {"project": "wayfarer-web", "add": ["joiner"], "confirm": True})
chk("Demo's Enable is refused, saying nothing is changed, and the real registry is untouched", st == 400 and "Demo" in j["error"] and open(REG).read() == b4, (st, j))
st, body, _ = raw("POST", "/api/demo", H, {"on": False})
chk("Demo mode is off again and the real live data is back", st == 200 and any(i["project"] == "alpha-app" for i in get("/api/state")[1]["live"]["items"]))
PY
report < <(python3 "$T/demo-check.py" 2>&1)

# ---- 5. the page under node ----
if command -v node >/dev/null 2>&1; then
  out=$(node "$REAL/bin/selftest-live.mjs" 2>&1); rc=$?
  ck "the page under node: lines, escaping, empty and no-hook wording, Available (N), sessions and duties counted apart ($(printf '%s' "$out" | tail -1 | cut -c1-100))" '[ "$rc" = 0 ]'
else
  st_skip "the page under node: node is not installed"
fi

# ---- 6. the page in a browser ----
page_run() { # page_run <mode>
  local out rc nf
  out=$(QD_LINK="$(newlink)" QD_MODE="$1" QD_SHOTS="$T/shots" QD_T="$T" node "$REAL/bin/live-page.mjs" 2>&1 | tee -a "${QD_PAGE_LOG:-/dev/null}"); rc=${PIPESTATUS[0]}
  printf '%s\n' "$out" | while IFS= read -r line; do
    case "$line" in
      "ok "*) printf '  ok    %s\n' "${line#ok }" ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }" ;;
      "skip "*) printf '  skip  %s\n' "${line#skip }" ;;
    esac
  done
  passed=$((passed + $(printf '%s\n' "$out" | grep -c '^ok ')))
  nf=$(printf '%s\n' "$out" | grep -c '^FAIL '); fails=$((fails + nf))
  if [ "$rc" != 0 ] && [ "$nf" = 0 ]; then printf '  FAIL  the page test crashed (exit %s): %s\n' "$rc" "$(printf '%s\n' "$out" | tail -3 | tr '\n' ' ')"; fails=$((fails + 1)); fi
}
if command -v node >/dev/null 2>&1 && { st_have_browser || node "$REAL/bin/live-page.mjs" probe >/dev/null 2>&1; }; then
  mkdir -p "$T/shots"
  page_run real
  page_run demo
  report < <(python3 - <<'PY'
import os
exec(open(os.environ["T"] + "/api-lib.py").read())
H = {"Cookie": COOKIE, "X-Quarterdeck-Token": TOK, "Origin": "http://127.0.0.1:%d" % PORT}
st, body, _ = raw("POST", "/api/demo", H, {"on": False})
print("ok" if st == 200 else "FAIL", "(Demo mode is switched off again)")
PY
)
  [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
else
  st_skip_browser "the page checks (the Running now strip, a project's Live work, the Crew page with Available and Enable, Calm, a phone width) are not run"
fi

st_done
