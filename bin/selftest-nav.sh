#!/bin/bash
# Navigation on the dashboard: the address holds the page, the project scope and the open mission, so Back, Forward, a reload and a pasted link work.
# A real dashboard runs on a free port in a throwaway Quarterdeck (the program tree is copied, the data folder is a temp folder with the
# .quarterdeck-home marker, HOME is a temp folder), paired through its one-time link. No network, no model, no GitHub: nothing here calls any of them.
# The data folder is seeded with two projects, a finished design panel, two cycles (one awaiting review, one that had nothing to build) and a failed run,
# and holds one invented add-on (bin/ext_tide.py with its page script, loaded through the same hooks any add-on uses).
#
#   1  the address as served: the page is the same for every path and the hash never reaches the server
#   2  the page, in a headless browser (skipped, saying so, when this machine has none), on the seeded data folder and again in Demo mode:
#      five pages and Back four times, Forward, reload, project scope, a mission and Back, a deep link, hostile addresses, the pairing hash gone,
#      Esc in the Brain, polling adds no entry, the scope chip on every page where a scope applies (and none on the pages of the person), mission steps by kind, the trajectory on Projects, the add-on label and scope
# QD_KEEP=1 keeps the throwaway folder; QD_KEEP_SHOTS=<folder> copies the pictures the page checks take there.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
mkdir -p "$T/home" "$T/state/panels" "$T/state/cycles" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
export QUARTERDECK_HOME="$T" T REAL PYTHONDONTWRITEBYTECODE=1; touch "$T/.quarterdeck-home"
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT

# ---- the seeded data folder ----
mkdir -p "$T/alpha-app" "$T/beta-api"
cat > "$T/config/projects.json" <<JSON
{"alpha-app": {"repo": "x/alpha-app", "path": "$T/alpha-app", "summary": "a made-up app", "default_branch": "main", "duties": ["panel"], "guardrails": [], "verify": "true", "cycle": true},
 "beta-api": {"repo": "x/beta-api", "path": "$T/beta-api", "summary": "a made-up api", "default_branch": "main", "duties": ["panel"], "guardrails": [], "verify": "true"}}
JSON
python3 - <<'PY'
import json, os
from datetime import datetime, timezone, timedelta
T = os.environ["T"]
now = datetime.now(timezone.utc)
iso = lambda m: (now - timedelta(minutes=m)).isoformat().replace("+00:00", "Z")
json.dump({"id": "20261001-0900-design-alpha-app", "project": "alpha-app", "discipline": "design", "mode": "review", "subject": "the settings page", "headline": "Three things worth fixing on the settings page",
           "status": "done", "phase": "ruled", "started": iso(90), "finished": iso(80), "seats": [{"name": "a"}, {"name": "b"}], "items": [], "stances": [],
           "ruling": [{"title": f"Fix {n}", "kind": "change", "tier": "routine", "claim": "c", "where": "w", "action": "a", "severity": "minor"} for n in (1, 2, 3)]},
          open(T + "/state/panels/20261001-0900-design-alpha-app.json", "w"))
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
json.dump([{"at": iso(30), "project": "beta-api", "duty": "surveyor", "verdict": "ERROR", "detail": "the checks would not start"}], open(T + "/state/runs.json", "w"))
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
QD_EXT.views.push({id: "tide", place: "tide", label: "Tide", ic: "box", title: "Tide", sub: "An invented add-on for the navigation test.", render: () => `<div class="card"><p>Tide is quiet.</p></div>`});
JS

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi
newlink() { QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link; }

# ---- 1. the address as served ----
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
HOME_URL="http://127.0.0.1:$PORT/"
CSP=$(curl -s -D - -o /dev/null "$HOME_URL" | grep -i '^content-security-policy' | tr -d '\r')
ck "the page is served at / and at /index.html, and the same page for a request that has a hash in it (the hash is never sent)" '[ "$(curl -s "$HOME_URL" | sed "s/nonce[=-][^ >]*//g" | md5sum)" = "$(curl -s "${HOME_URL}index.html" | sed "s/nonce[=-][^ >]*//g" | md5sum)" ] && [ "$(code "${HOME_URL}#/projects/mission/x")" = 200 ]'
ck "the router is served as an asset next to the page, as an ES module" '[ "$(code "${HOME_URL}assets/route.js")" = 200 ] && curl -s "${HOME_URL}assets/route.js" | grep -q "export function parseHash"'
ck "the Content-Security-Policy is the same as before: scripts from this server and the nonce only, no unsafe-inline and no unsafe-eval for scripts" 'grep -q "script-src .self. .nonce-" <<<"$CSP" && ! grep -Eq "script-src[^;]*(unsafe-inline|unsafe-eval)" <<<"$CSP"'
ck "no inline script without the nonce and no inline handler attribute in the page (the router adds none)" 'python3 - "$REAL/dashboard/index.html" <<PY
import re, sys
h = open(sys.argv[1]).read()
tags = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", h)
bad = [t for t in tags if "nonce=\"__QUARTERDECK_NONCE__\"" not in t]
handlers = re.findall(r"<[a-zA-Z][^>]*\son(?:click|load|error|hashchange|popstate|change|input)=", h)
sys.exit(1 if bad or handlers else 0)
PY'
ck "an unpaired request for the state is refused" '[ "$(code "${HOME_URL}api/state")" = 401 ]'

# ---- 2. the page ----
# st_have_browser asks bin/browse.mjs, which keeps Chromium's renderer sandbox on and so cannot start as root in a container; the page driver here
# launches the way bin/a11y-check.mjs does, so it is asked as well. When neither can start a browser the page checks are skipped, saying so.
page_run() { # page_run <mode>: the driver prints "ok ...", "FAIL ..." or "skip ..." lines; each is one check
  local out rc nf
  out=$(QD_LINK="$(newlink)" QD_MODE="$1" QD_SHOTS="$T/shots" QD_T="$T" node "$REAL/bin/nav-page.mjs" 2>&1 | tee -a "${QD_PAGE_LOG:-/dev/null}"); rc=${PIPESTATUS[0]}
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
if st_have_browser || node "$REAL/bin/nav-page.mjs" probe >/dev/null 2>&1; then
  mkdir -p "$T/shots"
  page_run real
  page_run demo
  # Demo mode is the server's flag: put it back, so the data folder is as it was
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
  st_skip_browser "the page checks (Back, Forward, reload, deep links, the scope chip, the trajectory, the add-on) are not run"
fi

st_done
