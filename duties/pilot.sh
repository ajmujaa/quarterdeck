#!/bin/bash
# pilot — take the app out and sail it.
#
# Builds a pull request's own head in a throwaway worktree, starts the app there, and has the QA crew (flowpilot,
# stormhand, wakewatcher) each write a plan: flows of plain steps with something to look for at the end of each.
# The harness validates every plan, then drives the app with a headless browser itself (bin/browse.mjs) and reports
# what happened. No model gets a browser, a shell, gh or credentials; the model writes data and the harness acts.
# Synthetic fixtures only: the plans are told to use invented names and amounts, and the browser can reach nothing
# but the app's own local address.
#
# It writes a findings document and nothing else. The Foreman files issues from that document.
#
#   qtdeck run <p> pilot --pr 218            report only
#   qtdeck run <p> pilot --pr 218 --apply    also write workspace/<p>-pilot-pr218.md and the findings file
#
# The project says how to start its app in config/projects.json:
#   "qa": {"start": "npm run dev -- --port $PORT", "ready": "/", "build": "npm run build", "env": {"SUPABASE_URL": "http://127.0.0.1:54321"}, "routes": ["/settings"]}
# (build, env and routes are optional).
# Routes: bin/routes.py chooses which paths the crew may open: "/", qa.routes, the routes this pull request touches, the framework's router
# files, a sitemap and the links on the home page, capped (QUARTERDECK_QA_ROUTES, default 8). Only same-origin paths on the local server are
# allowed; a flow that opens any other path is refused, external links are never followed and no derived route submits a form. The report
# lists the routes covered and not covered. qa.env is name -> value, SYNTHETIC values only, passed to the build and to the start command. The app
# runs in a clean environment: PATH, HOME, TMPDIR, LANG, PORT and qa.env, and nothing else. No .env file and none of the owner's own
# variables are read or passed on.
#
# Contract of each seat:
#   PLAN_JSON: [{"title","touches":[changed files],"steps":[{"op":"goto","path":"/"},{"op":"click","selector":"..."},...]}]
#   RESULT: PLAN <n> flow(s)
# What the duty records, decided by the harness from what the browser did:
#   PASSED | FAILED <n> | BLOCKED <reason>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> pilot --pr <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/pilot-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"
NODE="${QUARTERDECK_NODE:-node}"
BROWSE="${QUARTERDECK_BROWSE:-$QUARTERDECK_DIR/bin/browse.mjs}"
START=$(project_get "$PROJECT" qa.start)
READY=$(project_get "$PROJECT" qa.ready /)
BUILD=$(project_get "$PROJECT" qa.build)
PER_SEAT="${QUARTERDECK_MAX_ITEMS:-3}"                 # flows per seat: the cap on one run
QA_TIMEOUT="${QUARTERDECK_QA_TIMEOUT:-600}"            # the app and the browser together never outlive this
READY_WAIT="${QUARTERDECK_QA_READY_WAIT:-60}"

APPLY=0 PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --pr)    PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    *) die "pilot: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$PR" =~ ^[0-9]+$ ]] || die "pilot needs a pull request: --pr <number>"

# What the app is started with: a clean environment plus the registry's qa.env (name -> value, synthetic values only). Nothing is read from a .env
# file or from the environment this was started from, so the app under check can neither see the owner's variables nor depend on them.
QAENV=$(jq -c --arg p "$PROJECT" '(.[$p].qa.env // {})' "$PROJECTS_FILE" 2>/dev/null || echo '{}')
QAENV_OK=0
jq -e 'type == "object" and all(to_entries[]; (.key | test("^[A-Za-z_][A-Za-z0-9_]*$")) and ((.key | test("^(QUARTERDECK_|PATH$|HOME$)")) | not) and ((.value | type) == "string" or (.value | type) == "number") and ((.value | tostring | length) <= 500))' <<<"$QAENV" >/dev/null 2>&1 && QAENV_OK=1
ENVA=(); while IFS= read -r kv; do [ -n "$kv" ] && ENVA[${#ENVA[@]}]="$kv"; done < <([ "$QAENV_OK" = 1 ] && jq -r 'to_entries[] | "\(.key)=\(.value | tostring)"' <<<"$QAENV")
CLEAN=("PATH=$PATH" "HOME=${HOME:-/tmp}" "TMPDIR=${TMPDIR:-/tmp}" "LANG=${LANG:-C}" "TERM=dumb")

# Decisions on record, when this checkout has the Logkeeper's injector.
ADR_ON=0; ADR_BLOCK=""
if [ -f "$QUARTERDECK_DIR/bin/decisions.sh" ]; then source "$QUARTERDECK_DIR/bin/decisions.sh"; ADR_ON=1; fi

acquire_lock "pilot-$PROJECT-$PR"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-pilot-$PR"

# The app and everything it started die with the run, whatever happens.
SERVER=""
WT="$QUARTERDECK_HOME/workspace/wt-pilot-${PROJECT}-${PR}"
EVID="$QUARTERDECK_HOME/state/pilot/${PROJECT}-pr${PR}"          # the run's own evidence, under the duty's own state
TMP="$(mktemp -d)"
cleanup() {
  [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0      # only the duty itself cleans up, never a subshell it started
  [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMP" ${PX_SCRATCH:+"$PX_SCRATCH"}
}
trap cleanup EXIT

# A command group that is killed as a group when its time is up or when it is told to stop, so an app that
# started helpers does not leave them behind. Run inline (not through a function) so $! is the group's own leader.
RUN_GROUP='setpgrp(0,0); my $t = shift @ARGV; my $pid = fork();
           if (!$pid) { exec @ARGV or exit 127 }
           my $stop = sub { $SIG{TERM} = "DEFAULT"; kill "TERM", -$$; exit 1 };
           $SIG{ALRM} = $stop; $SIG{TERM} = $stop; alarm $t; waitpid($pid, 0); exit($? >> 8)'

blocked() { # blocked <reason>
  say "quarterdeck: BLOCKED — $1"
  record_run "$PROJECT" pilot BLOCKED "#$PR — $1"
  exit 0
}

[ "$QAENV_OK" = 1 ] || blocked "qa.env in the registry is malformed: it must be an object of NAME: value (names of letters, digits and underscores, not QUARTERDECK_*, PATH or HOME; values text or numbers up to 500 characters)"
[ -n "$START" ] || blocked "no \"qa.start\" in the registry for $PROJECT: nothing says how to start the app"
command -v "$NODE" >/dev/null 2>&1 || blocked "node is not installed, so the browser driver cannot run"
[ -f "$BROWSE" ] || blocked "bin/browse.mjs is missing"

meta=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json number,title,body,state,headRefOid,isCrossRepository 2>>"$LOG_FILE") \
  || die "cannot read $REPO#$PR"
why=$(fork_refuse "$meta") && blocked "$why"
title=$(jq -r .title <<<"$meta"); body=$(jq -r .body <<<"$meta"); sha=$(jq -r '.headRefOid // ""' <<<"$meta")
changed=$(guard 60 "$GH" pr diff "$PR" -R "$REPO" --name-only 2>>"$LOG_FILE" || true)
working_on "PR #$PR — $title"
say "quarterdeck: pilot on $REPO#$PR — $title"

# ---- build the pull request's own head, not a branch name ---------------------------------------
guard 180 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "pull/$PR/head" 2>>"$LOG_FILE" || blocked "could not fetch pull/$PR/head"
worktree_at "$SOURCE_REPO_DIR" "$WT" FETCH_HEAD || blocked "could not create a worktree at $WT"
# The pull request's own build and start commands run as every project command does: a scratch HOME, no secrets, and on a Mac inside the sandbox
# (files private, writes in the worktree only, loopback network only). On Linux the app is started only on the owner's opt-in (qd_app_net_refused):
# refused here, before anything is built.
why=$(qd_app_net_refused) && blocked "$why"
px_prepare check "$WT" || blocked "${PX_WHY:-the macOS sandbox could not be applied}, and a pull request's code is never run without it"
if [ -n "$BUILD" ]; then
  say "  building: $BUILD  [sandbox: $RUN_SANDBOX]"
  (cd "$WT" && guard "${QUARTERDECK_CHECK_TIMEOUT:-900}" env -i "${PX_ENV[@]}" ${ENVA[@]+"${ENVA[@]}"} ${PX_PRE[@]+"${PX_PRE[@]}"} bash -c "$BUILD" >>"$LOG_FILE" 2>&1) || blocked "the build failed: $BUILD"
fi

# ---- start the app on a free local port ---------------------------------------------------------
listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
PORT=""
for _ in 1 2 3 4 5 6 7 8; do
  p=$((20000 + RANDOM % 20000)); listening "$p" || { PORT=$p; break; }
done
[ -n "$PORT" ] || blocked "no free local port to start the app on"
say "  starting the app on 127.0.0.1:$PORT"
rm -rf "$PX_SCRATCH"; px_prepare serve "$WT" || blocked "${PX_WHY:-the macOS sandbox could not be applied, and the code of a pull request is never run without it}"
env -i "${PX_ENV[@]}" ${ENVA[@]+"${ENVA[@]}"} PORT="$PORT" perl -e "$RUN_GROUP" "$QA_TIMEOUT" ${PX_PRE[@]+"${PX_PRE[@]}"} bash -c 'cd "$1" && exec bash -c "$2"' _ "$WT" "$START" >>"$LOG_FILE" 2>&1 &
SERVER=$!
up=0
for _ in $(seq 1 "$READY_WAIT"); do
  kill -0 "$SERVER" 2>/dev/null || break
  listening "$PORT" && { up=1; break; }
  sleep 1
done
[ "$up" = 1 ] || blocked "the app did not answer on its port within ${READY_WAIT}s: $START"
BASEURL="http://127.0.0.1:$PORT"

# ---- is it an app? Looked at before any model is asked for a plan --------------------------------------------------------------
# One picture of the first screen. If it is only an error or configuration screen, or blank, nothing below could mean anything: BLOCKED now.
rm -rf "$EVID"; mkdir -p "$EVID"
jq -n --arg b "$BASEURL" --arg r "$READY" '{base:$b, routes:[$r], widths:[1280], prefix:"preflight"}' > "$TMP/pre.json"
pre=$(guard 120 "$NODE" "$BROWSE" shoot "$TMP/pre.json" "$EVID/preflight" 2>>"$LOG_FILE"); prc=$?
jq -e 'type == "object"' <<<"$pre" >/dev/null 2>&1 || pre='{}'
if [ "$prc" = 3 ] || [ -n "$(jq -r '.error // empty' <<<"$pre")" ]; then blocked "$(jq -r '.error // "the browser driver failed"' <<<"$pre")"; fi
if [ -n "$(jq -r '.blocked.reason // empty' <<<"$pre")" ]; then
  blocked "$(jq -r '.blocked.reason' <<<"$pre") (screenshot: $(jq -r '.blocked.screenshot // ""' <<<"$pre")). If the app needs settings to start, give it synthetic ones in qa.env in config/projects.json."
fi

# ---- which routes may be sailed: derived from the checkout, the diff and the home page, capped --------------------------
printf '%s\n' "$changed" > "$TMP/changed.txt"
guard 30 curl -s -m 20 --max-filesize 2000000 "$BASEURL$READY" > "$TMP/home.html" 2>>"$LOG_FILE" || : > "$TMP/home.html"
jq -c --arg p "$PROJECT" '(.[$p].qa.routes // []) | if type == "array" then map(select(type == "string")) else [] end' "$PROJECTS_FILE" > "$TMP/explicit.json" 2>/dev/null || echo '[]' > "$TMP/explicit.json"
ROUTES=$(python3 "$QUARTERDECK_DIR/bin/routes.py" "$WT" "$TMP/changed.txt" "$TMP/home.html" "${QUARTERDECK_QA_ROUTES:-8}" "$TMP/explicit.json" "127.0.0.1:$PORT" 2>>"$LOG_FILE")
jq -e 'type == "array" and length > 0' <<<"$ROUTES" >/dev/null 2>&1 || ROUTES='["/"]'
say "  routes the crew may open: $(jq -r 'join(" ")' <<<"$ROUTES")"

# ---- the crew writes plans ---------------------------------------------------------------------------
SEATS=$(crew_by_discipline qa | tr '\n' ' '); SEATS="$(xargs <<<"$SEATS")"
[ -n "$SEATS" ] || die "pilot: no crew sits on the qa panel (see: qtdeck crew)"
ADR_SPEC=""
if [ "$ADR_ON" = 1 ]; then
  adr_block "$PROJECT" "$(project_get "$PROJECT" default_branch main)" "$changed" "$title
$body"
  ADR_SPEC=$'ADR: <cites ADR n | matches ADR n | searched <records>>\n'
fi

DSL='Each step is one JSON object. The only ops are:
  {"op":"goto","path":"/x"}              open a path of the app (a path only; no other address is reachable)
  {"op":"click","selector":"css or text=..."}
  {"op":"fill","selector":"...","value":"..."}
  {"op":"press","key":"Enter"}
  {"op":"expect_text","text":"...","selector":"optional css"}     the step that makes a flow mean something
  {"op":"expect_visible","selector":"..."}
  {"op":"expect_url","contains":"..."}
  {"op":"wait","ms":500}                 at most 3000
  {"op":"shot","name":"short-name"}
  {"op":"set_offline","on":true}         to take the network away and bring it back
At most 25 steps a flow. A flow with no expect_ step proves nothing and will be dropped as noise.'
PIDS=""
for seat in $SEATS; do
  (
    trap - EXIT        # a seat's subshell must not run the duty's cleanup (it would stop the app under the others)
    export QUARTERDECK_RUN_ID="${QUARTERDECK_RUN_ID}-$seat"
    m="$(crew_meta "$seat" model)"; [ -n "$m" ] && export QUARTERDECK_MODEL_PERSONA="$m"
    p="$(preamble "$PROJECT")

You are the ${seat} on the qa crew. Your seat: $(crew_meta "$seat" seat).

$(crew_role "$seat")

--- THIS RUN ---

$(printf 'Pull request #%s: %s\n\n%s\n' "$PR" "$title" "$body" | untrusted "pull request text")

Files this pull request changes:
$changed

Routes you may open (a goto to any other path is refused; start with the ones this pull request touches, and open as many as your flows honestly need):
$(jq -r '.[]' <<<"$ROUTES")
Never submit a form just to cover a route: open it, look at it, expect something on it.

The pull request is checked out around you and the app is running from it. You have read-only tools and you
cannot run it yourself: write the flows, and the harness will drive a real browser through them and report.
Use invented data only (made-up names, amounts and receipts), never a real person, account or sum of money.
Bring at most $PER_SEAT flows, fewer if that is the honest number.

$DSL
${ADR_BLOCK:-}
End your reply with exactly these lines and nothing after them:
PLAN_JSON: <one-line JSON array of {\"title\":\"what this flow shows\",\"touches\":[\"changed file that put it here\"],\"steps\":[...]}>
${ADR_SPEC}RESULT: PLAN <count> flow(s)"
    out="$(claude_run "$WT" "$p")"; rc=$?
    printf '%s' "$out" > "$TMP/seat.$seat.txt"; echo "$rc" > "$TMP/seat.$seat.rc"
  ) &
  PIDS="$PIDS $!"
done
wait $PIDS        # the seats only: a bare wait would also wait for the app

echo '[]' > "$TMP/flows.json"; heard=""
for seat in $SEATS; do
  rc="$(cat "$TMP/seat.$seat.rc" 2>/dev/null || echo 1)"
  [ "$rc" = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
  raw="$(grep -o '^PLAN_JSON: .*' "$TMP/seat.$seat.txt" 2>/dev/null | tail -1 | sed 's/^PLAN_JSON: //')"
  if [ "$rc" = 0 ] && jq -e 'type == "array"' <<<"$raw" >/dev/null 2>&1 \
     && grep -q '^RESULT: PLAN' "$TMP/seat.$seat.txt" \
     && { [ "$ADR_ON" != 1 ] || [ -n "$(adr_line "$(cat "$TMP/seat.$seat.txt")")" ]; }; then
    jq --arg s "$seat" --argjson n "$PER_SEAT" --argjson prev "$(cat "$TMP/flows.json")" \
       '$prev + (.[0:$n] | map(. + {seat: $s}))' <<<"$raw" > "$TMP/flows.next" && mv "$TMP/flows.next" "$TMP/flows.json"
    heard="$heard $seat"
  else
    say "  $seat: no usable plan (contract did not parse) — left out"
    log "pilot #$PR: $seat did not parse — logs/runs/${QUARTERDECK_RUN_ID}-$seat.json"
  fi
done
[ -n "$heard" ] || { record_run "$PROJECT" pilot ERROR "#$PR no seat gave a plan that parsed"; die "pilot: no plan parsed — nothing written"; }

jq -n --arg b "$BASEURL" --slurpfile f "$TMP/flows.json" '{base:$b, flows:$f[0]}' > "$TMP/plan.json"
EMPTY='{}'
chk=$("$NODE" "$BROWSE" check "$TMP/plan.json" 2>>"$LOG_FILE") || chk=""
jq -e 'type == "object"' <<<"$chk" >/dev/null 2>&1 || chk="$EMPTY"
# A goto may only open a route on the list. Anything else is refused here, whatever the driver would have allowed.
chk=$(jq --argjson r "$ROUTES" '(.valid // []) as $v
  | [$v[] | select(all(.steps[]; .op != "goto" or ((.path | sub("[?#].*$"; "") | if length > 1 then rtrimstr("/") else . end) as $p | $r | index($p))))] as $ok
  | . + {valid: $ok, errors: ((.errors // []) + [$v[] | select(. as $f | $ok | index($f) | not) | "\"\(.title)\" opens a path that is not on the route list"])}' <<<"$chk") || chk="$EMPTY"
if [ "$(jq '(.valid // []) | length' <<<"$chk")" = 0 ]; then
  record_run "$PROJECT" pilot ERROR "#$PR every flow was refused: $(jq -r '(.errors // []) | join("; ")' <<<"$chk" | cut -c1-200)"
  die "pilot: no valid flow — nothing written"
fi
[ "$(jq '.errors | length' <<<"$chk")" = 0 ] || say "  some flows were refused: $(jq -r '.errors | join("; ")' <<<"$chk")"
# From here the plan is only the flows the driver accepted, in the order it will run them.
jq --arg b "$BASEURL" '{base:$b, flows:.valid}' <<<"$chk" > "$TMP/plan.json"

# ---- the harness drives the browser -------------------------------------------------------------------------
say "  driving the app through $(jq '.flows | length' "$TMP/plan.json") flow(s)"
res=$(guard "$QA_TIMEOUT" "$NODE" "$BROWSE" run "$TMP/plan.json" "$EVID" 2>>"$LOG_FILE"); brc=$?
jq -e 'type == "object"' <<<"$res" >/dev/null 2>&1 || res='{}'
if [ "$brc" = 3 ] || [ -n "$(jq -r '.error // empty' <<<"$res")" ]; then
  blocked "$(jq -r '.error // "the browser driver failed"' <<<"$res")"
fi
# The app has to be an app first. An error or configuration screen, a blank page, or the same first-screen step failing in every flow means it could
# not start properly: that is BLOCKED, with the picture, never FAILED and never PASSED.
if [ -n "$(jq -r '.blocked.reason // empty' <<<"$res")" ]; then
  blocked "$(jq -r '.blocked.reason' <<<"$res") (screenshot: $(jq -r '.blocked.screenshot // ""' <<<"$res")). If the app needs settings to start, give it synthetic ones in qa.env in config/projects.json."
fi
[ "$(jq '.flows | length' <<<"$res")" -gt 0 ] || { record_run "$PROJECT" pilot ERROR "#$PR the browser driver returned nothing"; die "pilot: the browser driver returned nothing"; }

failed=$(jq -c '[.flows[] | select(.ok == false)]' <<<"$res")
nfail=$(jq 'length' <<<"$failed"); nflows=$(jq '.flows | length' <<<"$res")
if [ "$nfail" = 0 ]; then verdict="PASSED"; detail="$nflows flow(s) sailed"; else verdict="FAILED $nfail"; detail="$nfail of $nflows flow(s) failed"; fi

# ---- the findings document: steps to reproduce, and a screenshot path, per failure ---------------------------
render_steps() { # render_steps <flow-index> <failed-step> — the steps up to and including the one that failed
  jq -r --argjson i "$1" --argjson k "$2" '.flows[$i].steps[0:$k][] |
    (if .op == "goto" then "Open `\(.path)`"
     elif .op == "click" then "Click `\(.selector)`"
     elif .op == "fill" then "Type `\(.value)` into `\(.selector)`"
     elif .op == "press" then "Press \(.key)"
     elif .op == "expect_text" then "Expect to see \"\(.text)\""
     elif .op == "expect_visible" then "Expect `\(.selector)` to be visible"
     elif .op == "expect_url" then "Expect the address to contain `\(.contains)`"
     elif .op == "wait" then "Wait \(.ms) ms"
     elif .op == "shot" then "Take picture \(.name)"
     else "Network \(if .on then "off" else "on" end)" end)' "$TMP/plan.json" | nl -ba -w1 -s'. ' | sed 's/^/   /'
}
# Coverage: a route is covered when a step the browser actually ran opened it (a failed flow counts up to the step that failed).
COVERED=$(jq -nc --argjson r "$ROUTES" --slurpfile pl "$TMP/plan.json" --argjson rs "$res" '
  [range(0; ($rs.flows | length)) as $i | $rs.flows[$i] as $f | $pl[0].flows[$i].steps as $st
   | $st[0:(if $f.ok == false then ($f.failed_step // 0) else ($st | length) end)][] | select(.op == "goto")
   | .path | sub("[?#].*$"; "") | if length > 1 then rtrimstr("/") else . end | select(. as $p | $r | index($p))] | unique')
COVERAGE="Routes covered: $(jq -r 'if length == 0 then "none" else join(", ") end' <<<"$COVERED"). Not covered: $(jq -nr --argjson a "$ROUTES" --argjson c "$COVERED" '($a - $c) | if length == 0 then "none" else join(", ") end')."
DOC="$QUARTERDECK_HOME/workspace/${PROJECT}-pilot-pr${PR}.md"
report() {
  echo "# Pilot: #$PR $title"
  echo
  echo "_Head ${sha:0:12}. $nflows flow(s) from the qa crew, driven by the harness in a headless browser against a build of this head. Invented data only._"
  echo
  echo "**$verdict.** $detail."
  echo
  echo "$COVERAGE"
  # flows are in the plan in order; the browser's results keep that order, so a flow's index is its place in the plan
  idx=0
  while read -r f; do
    ok=$(jq -r .ok <<<"$f")
    if [ "$ok" = false ]; then
      echo
      echo "## FAIL: $(jq -r .title <<<"$f")"
      echo
      echo "Seat: $(jq -r .seat <<<"$f"). Failed at step $(jq -r .failed_step <<<"$f"): $(jq -r .message <<<"$f")"
      echo
      echo "Steps to reproduce:"
      render_steps "$idx" "$(jq -r .failed_step <<<"$f")"
      echo
      echo "Screenshot: \`$(jq -r '.screenshot // ""' <<<"$f")\`"
    fi
    idx=$((idx + 1))
  done < <(jq -c '.flows[]' <<<"$res")
  [ "$nfail" = 0 ] && { echo; echo "Flows:"; jq -r '.flows[] | "- \(.title) (\(.seat))"' <<<"$res"; }
  [ "$ADR_ON" = 1 ] && { echo; echo "Decisions on record: $ADR_SEARCHED"; }
}
say ""; report >&2; say ""

if [ "$APPLY" != 1 ]; then
  say "quarterdeck: report only — pass --apply to write the findings document"
  record_run "$PROJECT" pilot "DRY-RUN" "#$PR — $verdict"
  exit 0
fi

# the same findings, in the shape the Caulker reads
mkdir -p "$QUARTERDECK_HOME/state/findings"
report > "$DOC"
idx=0; fj='[]'
while read -r f; do
  if [ "$(jq -r .ok <<<"$f")" = false ]; then
    fj=$(jq -c --argjson f "$f" --argjson n "$(jq length <<<"$fj")" --arg steps "$(render_steps "$idx" "$(jq -r .failed_step <<<"$f")")" \
         '. + [{id: ("pilot-" + (($n + 1) | tostring)), severity: "major", title: ($f.title + " failed at step " + ($f.failed_step | tostring)),
                body: ("Steps to reproduce:\n" + $steps + "\n\n" + $f.message), file: ($f.touches[0] // ""), line: 0,
                paths: $f.touches, kind: "code", evidence: $f.screenshot}]' <<<"$fj")
  fi
  idx=$((idx + 1))
done < <(jq -c '.flows[]' <<<"$res")
jq -n --arg d pilot --arg p "$PROJECT" --argjson pr "$PR" --arg h "$sha" --arg at "$(date -u +%FT%TZ)" --arg v "$verdict" --argjson f "$fj" \
  '{duty:$d, project:$p, pr:$pr, head:$h, at:$at, verdict:$v, findings:$f}' > "$QUARTERDECK_HOME/state/findings/${PROJECT}-pr${PR}-pilot.json"
say "quarterdeck: findings document written to $(basename "$DOC")"
record_run "$PROJECT" pilot "$verdict" "#$PR — $detail. $COVERAGE" "https://github.com/$REPO/pull/$PR"

exit
}
