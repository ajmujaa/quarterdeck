#!/bin/bash
# Home and Projects on the dashboard: Home is the person (the next action, Your day, Brain dump, the fleet timeline, Recently finished, Budget today and one count
# line that links to Projects); Projects is where the work is (an overview of every project, then the pages of one project). The project scope lives in the
# address, and only the pages where it means something show a scope box.
# A real dashboard runs on a free port in a throwaway Quarterdeck (the program tree is copied, the data folder is a temp folder with the
# .quarterdeck-home marker, HOME is a temp folder), paired through its one-time link. gh is a stand-in that serves a pull request fixture and records every call;
# the model is never started. No network, no real model, no GitHub: nothing here calls any of them.
# The data folder is seeded with two registered projects, runs (one failed), spend rows that name their project, a design panel, two cycles (one waiting for
# review), a local ticket, a pull request fixture, a survey profile (the stack sentence), and one invented add-on with an alert and a page of its own.
#
#   1  the state document carries one overview entry per project, counted from the seeded files (spend, runs, needs you, missions, stack)
#   2  the page, in a headless browser (skipped, saying so, when this machine has none), on the seeded data folder and again in Demo mode: Home has exactly its
#      five things and one count line, Projects shows one card per project, Open filters the tabs, the address holds the scope (Back, Forward, reload, the old
#      #/work/ spelling), the scope box exists only where it applies, Calm keeps working, a phone width has no sideways scroll, no console error
# QD_KEEP=1 keeps the throwaway folder; QD_KEEP_SHOTS=<folder> copies the pictures the page checks take there.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
mkdir -p "$T/home" "$T/state/panels" "$T/state/cycles" "$T/state/profiles" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
export QUARTERDECK_HOME="$T" T REAL PYTHONDONTWRITEBYTECODE=1 QUARTERDECK_DAILY_BUDGET=25; touch "$T/.quarterdeck-home"
export PATH="$T/path:$PATH"
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT

# ---- the seeded data folder ----
mkdir -p "$T/alpha-app" "$T/beta-api"
cat > "$T/config/projects.json" <<JSON
{"alpha-app": {"repo": "x/alpha-app", "path": "$T/alpha-app", "summary": "a made-up app", "default_branch": "main", "duties": ["panel"], "guardrails": ["Never touch the payments folder", "Keep the first paint under one second"], "verify": "true", "cycle": true},
 "beta-api": {"repo": "x/beta-api", "path": "$T/beta-api", "summary": "a made-up api", "default_branch": "main", "duties": ["panel"], "guardrails": [], "verify": "true"}}
JSON
python3 - <<'PY'
import json, os, sys
from datetime import datetime, timezone, timedelta
T = os.environ["T"]
sys.path.insert(0, T + "/bin")
now = datetime.now(timezone.utc)
iso = lambda m: (now - timedelta(minutes=m)).isoformat().replace("+00:00", "Z")
mid = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
since_mid = max(0, int((datetime.now().astimezone() - mid).total_seconds() // 60))
today_min = max(0, min(5, since_mid // 2))                         # a row that is certainly after local midnight, whatever time the suite runs
json.dump({"id": "20261001-0900-design-alpha-app", "project": "alpha-app", "discipline": "design", "mode": "review", "subject": "the settings page", "headline": "Three things worth fixing on the settings page",
           "status": "done", "phase": "ruled", "started": iso(90), "finished": iso(80), "seats": [{"name": "a"}, {"name": "b"}], "items": [], "stances": [],
           "ruling": [{"title": f"Fix {n}", "kind": "change", "tier": "routine", "claim": "c", "where": "w", "action": "a", "severity": "minor"} for n in (1, 2, 3)]},
          open(T + "/state/panels/20261001-0900-design-alpha-app.json", "w"))
json.dump({"id": "20261002-0900-dev-beta-api", "project": "beta-api", "discipline": "dev", "mode": "review", "subject": "the orders endpoint", "headline": "The orders endpoint is sound",
           "status": "done", "phase": "ruled", "started": iso(190), "finished": iso(180), "seats": [{"name": "a"}], "items": [], "stances": [], "ruling": []},
          open(T + "/state/panels/20261002-0900-dev-beta-api.json", "w"))
def stage(i, title, duty, state, verdict, cost):
    return {"id": i, "title": title, "duty": duty, "state": state, "verdict": verdict, "detail": "", "cost": cost, "url": "", "runs": ["r"], "started": iso(60), "finished": iso(59)}
base = {"kind": "cycle", "project": "alpha-app", "apply": True, "cost": 2.5, "seconds": 300, "notes": [], "started": iso(70), "finished": iso(60)}
json.dump({**base, "id": "cyc-alpha-app-7-1", "issue": 7, "title": "Add a Reset button", "status": "awaiting-review", "final": "The pull request is open with no open findings.", "pr": "https://github.com/x/alpha-app/pull/9",
           "stages": [stage("purser", "Purser", "purser", "done", "READY", 0.5), stage("panel", "Dev panel", "panel", "done", "RULED", 1.0), stage("shipwright", "Shipwright", "shipwright", "done", "PR", 0.8),
                      {"id": "human", "title": "Human review", "duty": "human", "state": "waiting", "verdict": "WAITING", "cost": 0, "runs": [], "detail": ""}]},
          open(T + "/state/cycles/cyc-alpha-app-7-1.json", "w"))
json.dump({**base, "id": "cyc-alpha-app-8-1", "issue": 8, "title": "Rename a label", "status": "nothing", "final": "There was nothing to build.", "pr": None, "started": iso(50), "finished": iso(45),
           "stages": [stage("purser", "Purser", "purser", "done", "READY", 0.5), stage("panel", "Dev panel", "panel", "done", "RULED", 1.0)]},
          open(T + "/state/cycles/cyc-alpha-app-8-1.json", "w"))
runs = [{"at": iso(300), "project": "beta-api", "duty": "shipwright", "verdict": "PR", "detail": "#3 → https://github.com/x/beta-api/pull/12", "url": "https://github.com/x/beta-api/pull/12"},
        {"at": iso(200), "project": "alpha-app", "duty": "surveyor", "verdict": "CLEAN", "detail": "#9 0 finding(s)"},
        {"at": iso(45), "project": "beta-api", "duty": "surveyor", "verdict": "CLEAN", "detail": "#12 0 finding(s)"},
        {"at": iso(30), "project": "alpha-app", "duty": "shipwright", "verdict": "ERROR", "detail": "the checks would not start"}]
json.dump(runs, open(T + "/state/runs.json", "w"))
def spend(minutes, project, cost, duty="shipwright"):
    return {"at": iso(minutes), "project": project, "duty": duty, "model": "sonnet", "turns": 5, "cost": cost, "billing": "plan", "provider": "claude", "cost_known": True}
rows = [spend(today_min, "alpha-app", 1.25), spend(3 * 1440, "alpha-app", 2.0), spend(today_min, "beta-api", 0.5), spend(10 * 1440, "alpha-app", 40.0), spend(today_min, "", 9.0, "panel")]
open(T + "/state/spend.jsonl", "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
json.dump({"stack": {"summary": "Python with FastAPI, tests by pytest"}}, open(T + "/state/profiles/alpha-app.json", "w"))
import tickets
tickets.local_add("alpha-app", [{"title": "Add a reset button", "body": "A button that sets the counter back to zero.", "acceptance": ["Press Reset and the counter shows 0"]}])
json.dump([{"number": 9, "title": "Add a Reset button", "url": "https://github.com/x/alpha-app/pull/9", "headRefName": "qd/reset", "headRefOid": "abc123", "baseRefName": "main", "createdAt": iso(65),
            "isDraft": False, "body": "Closes #7", "closingIssuesReferences": [], "reviewDecision": "", "statusCheckRollup": [{"conclusion": "SUCCESS", "name": "ci"}], "additions": 12, "deletions": 2,
            "changedFiles": 2, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN"}], open(T + "/ghdata/pr-list.json", "w"))
json.dump([], open(T + "/ghdata/issue-list.json", "w"))
PY
# one invented add-on, through the same hooks any add-on uses: a Python file with install(core) and a page script
cat > "$T/bin/ext_tide.py" <<'PY'
ADDON_NAME = "Tide"
def install(core):
    def attention(ack):
        key = "tide:nightly-sync"
        return [{"id": key, "source": "tide", "label": "Tide · nightly sync", "place": "tide", "severity": "BLOCKED", "text": "The nightly sync has not run since yesterday.",
                 "at": core.iso(core.now_utc()), "stale": False, "acknowledged": key in ack}]
    core.EXT["attention"].append(attention)
    core.EXT["scripts"].append("/assets/ext-tide.js")
PY
cat > "$T/dashboard/assets/ext-tide.js" <<'JS'
// an invented add-on: one place with one page
QD_EXT.places.push({id: "tide", label: "Tide", ic: "box", badge: () => 0, tabs: [["tide", "Tide", "box"]]});
QD_EXT.views.push({id: "tide", place: "tide", label: "Tide", ic: "box", title: "Tide", sub: "An invented add-on for the Projects test.", render: () => `<div class="card"><p>Tide is quiet.</p></div>`});
JS

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi
newlink() { QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link; }

# ---- 1. the state document ----
cat > "$T/state-check.py" <<'PY'
import http.client, json, os, subprocess, sys
PORT, T = int(os.environ["PORT"]), os.environ["T"]
def req(m, p, h=None, b=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    d = json.dumps(b).encode() if b is not None else None
    hh = dict(h or {})
    if d is not None: hh.update({"Content-Type": "application/json", "Content-Length": str(len(d))})
    c.request(m, p, body=d, headers=hh); r = c.getresponse(); raw = r.read(); c.close(); return r.status, raw, r.getheader("Set-Cookie") or ""
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:300]))
link = subprocess.run([sys.executable, T + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
st, raw, ck = req("POST", "/api/pair", b={"nonce": link.split("#pair=")[1]})
tok = json.loads(raw)["token"]
st, raw, _ = req("GET", "/api/state", {"Cookie": ck.split(";")[0]})
S = json.loads(raw)
ov = {o["name"]: o for o in S.get("overview", [])}
a, b = ov.get("alpha-app", {}), ov.get("beta-api", {})
chk("the state carries one overview entry per registered project", sorted(ov) == ["alpha-app", "beta-api"] and len(S["projects"]) == 2, list(ov))
chk("  alpha-app: one thing needs the owner (the failed run), the state is blocked, the top item is that run's text", a.get("needs") == 1 and a.get("state") == "blocked" and "checks would not start" in (a.get("top") or {}).get("text", ""), a)
chk("  beta-api: nothing needs the owner and it is idle", b.get("needs") == 0 and b.get("top") is None and b.get("state") == "idle", b)
chk("  last run is the newest ledger row of the project, with duty and verdict", (a.get("last_run") or {}).get("duty") == "shipwright" and a["last_run"]["verdict"] == "ERROR" and (b.get("last_run") or {}).get("duty") == "surveyor", [a.get("last_run"), b.get("last_run")])
chk("  spend comes from the spend ledger rows that name the project (today, and seven days; a ten day old row and a row with no project are not counted)",
    a.get("spend_today") == 1.25 and a.get("spend_week") == 3.25 and b.get("spend_today") == 0.5 and b.get("spend_week") == 0.5, [a.get("spend_today"), a.get("spend_week"), b.get("spend_today"), b.get("spend_week")])
chk("  missions: alpha-app has one open (the cycle waiting for review) and two finished; beta-api none open and one finished", (a.get("missions_open"), a.get("missions_done")) == (1, 2) and (b.get("missions_open"), b.get("missions_done")) == (0, 1), [a, b])
chk("  the stack sentence comes from the survey profile; a project that was never surveyed has none", a.get("stack") == "Python with FastAPI, tests by pytest" and b.get("stack") == "", [a.get("stack"), b.get("stack")])
chk("  the add-on's alert is not any project's: it is in the inbox, with no project", any(x.get("source") == "tide" and not x.get("project") for x in S["inbox"]) and a["needs"] + b["needs"] == len([x for x in S["inbox"] if x.get("project") and not x.get("acknowledged")]))
PY
OUTS=$(PORT="$PORT" T="$T" python3 "$T/state-check.py" 2>&1)
while IFS= read -r line; do
  case "$line" in
    "ok "*) printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
    "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    *) [ -z "$line" ] || { printf '  FAIL  the state check crashed: %s\n' "$line"; fails=$((fails + 1)); } ;;
  esac
done <<<"$OUTS"

# ---- 2. the page ----
page_run() { # page_run <mode>: the driver prints "ok ...", "FAIL ..." or "skip ..." lines; each is one check
  local out rc nf
  out=$(QD_LINK="$(newlink)" QD_MODE="$1" QD_SHOTS="$T/shots" QD_T="$T" node "$REAL/bin/projects-page.mjs" 2>&1 | tee -a "${QD_PAGE_LOG:-/dev/null}"); rc=${PIPESTATUS[0]}
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
if st_have_browser || node "$REAL/bin/projects-page.mjs" probe >/dev/null 2>&1; then
  mkdir -p "$T/shots"
  page_run real
  page_run demo
  cat > "$T/demo-off.py" <<'PY'
import http.client, json, os, subprocess, sys
PORT, T = int(os.environ["PORT"]), os.environ["T"]
link = subprocess.run([sys.executable, T + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
def req(m, p, b=None, h=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30); d = json.dumps(b).encode() if b is not None else None
    hh = dict(h or {});
    if d is not None: hh.update({"Content-Type": "application/json", "Content-Length": str(len(d))})
    c.request(m, p, body=d, headers=hh); r = c.getresponse(); raw = r.read(); c.close(); return r.status, raw, r.getheader("Set-Cookie") or ""
st, raw, ck = req("POST", "/api/pair", {"nonce": link.split("#pair=")[1]})
tok = json.loads(raw)["token"]
st, raw, _ = req("POST", "/api/demo", {"on": False}, {"Cookie": ck.split(";")[0], "X-Quarterdeck-Token": tok, "Origin": "http://127.0.0.1:%d" % PORT})
print("ok" if st == 200 else "FAIL", "Demo mode is off again")
PY
  OFF=$(PORT="$PORT" python3 "$T/demo-off.py")
  ck "(Demo mode is switched off again)" 'grep -q "^ok" <<<"$OFF"'
  [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
else
  st_skip_browser "the page checks (Home's five things, the Projects overview, Open, the scope in the address, Calm, a phone width) are not run"
fi

st_done
