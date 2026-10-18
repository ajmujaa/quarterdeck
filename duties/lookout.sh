#!/bin/bash
# lookout — watch the screen from the masthead.
#
# Captures the screens ITSELF: builds a pull request's head in a throwaway worktree, starts the app, and has the
# harness's own headless browser (bin/browse.mjs) take one picture per route at phone, tablet and desktop width
# (390, 768 and 1280). It takes the same pictures of the trunk, as the nearest existing screen. The lookout (a crew seat
# on the design panel) then judges those pictures against the project's design notes and that nearest screen. It never
# reviews a picture the author attached or linked: the author's own images are removed from what it is told, and a
# finding that names any picture the harness did not capture makes the whole reply unparseable.
#
# The pictures are the duty's own evidence, taken from a build of the pull request under the duty's own state. They are
# not the owner's screen. Read only for the model; nothing is posted or written without --apply.
#
#   qtdeck run <p> lookout --pr 218            report only
#   qtdeck run <p> lookout --pr 218 --apply    comment on the pull request, write the findings document and file
#
# The project says how to start its app, and which routes and notes to use, in config/projects.json:
#   "qa": {"start": "npm run dev -- --port $PORT", "build": "npm run build", "env": {"SUPABASE_URL": "http://127.0.0.1:54321"}}
# qa.env is name -> value, SYNTHETIC values only, passed to the build and the start command. The app runs in a clean environment (PATH, HOME, TMPDIR,
# LANG, PORT and qa.env only): no .env file and none of the owner's own variables are read or passed on.
#   "lookout": {"routes": ["/", "/settings"], "notes": "docs/design.md"}      (routes default to "/")
#
# Contract:
#   FINDINGS_JSON: [{"route","width","image","severity","title","body","file"}]     [] when clean; image is a harness picture
#   VERDICT: CLEAN | FINDINGS <n>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> lookout --pr <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/lookout-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
BASE=$(project_get "$PROJECT" default_branch main)
GH="${QUARTERDECK_GH:-gh}"
NODE="${QUARTERDECK_NODE:-node}"
BROWSE="${QUARTERDECK_BROWSE:-$QUARTERDECK_DIR/bin/browse.mjs}"
START=$(project_get "$PROJECT" qa.start)
BUILD=$(project_get "$PROJECT" qa.build)
NOTES_PATH=$(project_get "$PROJECT" lookout.notes)
ALLROUTES=$(jq -c --arg p "$PROJECT" '.[$p].lookout.routes // ["/"]' "$PROJECTS_FILE")
ROUTES=$(jq -c '.[0:5]' <<<"$ALLROUTES")                 # at most five routes: the cap on one run
WIDTHS='[390,768,1280]'                                  # phone, tablet, desktop
PER_RUN="${QUARTERDECK_MAX_ITEMS:-8}"                        # findings in one run
QA_TIMEOUT="${QUARTERDECK_QA_TIMEOUT:-600}"
READY_WAIT="${QUARTERDECK_QA_READY_WAIT:-60}"

APPLY=0 PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --pr)    PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    *) die "lookout: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$PR" =~ ^[0-9]+$ ]] || die "lookout needs a pull request: --pr <number>"

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

acquire_lock "lookout-$PROJECT-$PR"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-lookout-$PR"
SERVER=""
WT="$QUARTERDECK_HOME/workspace/wt-lookout-${PROJECT}-${PR}"
WTB="$QUARTERDECK_HOME/workspace/wt-lookout-base-${PROJECT}-${PR}"
EVID="$QUARTERDECK_HOME/state/lookout/${PROJECT}-pr${PR}"        # the pictures: this duty's own evidence, under its own state
TMP="$(mktemp -d)"
cleanup() {
  [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0
  [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WTB" >/dev/null 2>&1 || true
  rm -rf "$TMP" ${PX_SCRATCH:+"$PX_SCRATCH"}
}
trap cleanup EXIT

# The app and everything it starts are killed as a group when time is up or the run ends. Run inline so $! is the leader.
RUN_GROUP='setpgrp(0,0); my $t = shift @ARGV; my $pid = fork();
           if (!$pid) { exec @ARGV or exit 127 }
           my $stop = sub { $SIG{TERM} = "DEFAULT"; kill "TERM", -$$; exit 1 };
           $SIG{ALRM} = $stop; $SIG{TERM} = $stop; alarm $t; waitpid($pid, 0); exit($? >> 8)'
blocked() { say "quarterdeck: BLOCKED — $1"; record_run "$PROJECT" lookout BLOCKED "#$PR — $1"; exit 0; }
listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

[ "$QAENV_OK" = 1 ] || blocked "qa.env in the registry is malformed: it must be an object of NAME: value (names of letters, digits and underscores, not QUARTERDECK_*, PATH or HOME; values text or numbers up to 500 characters)"
[ -n "$START" ] || blocked "no \"qa.start\" in the registry for $PROJECT: nothing says how to start the app"
command -v "$NODE" >/dev/null 2>&1 || blocked "node is not installed, so the browser driver cannot run"
[ -f "$BROWSE" ] || blocked "bin/browse.mjs is missing"

meta=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json number,title,body,state,headRefOid,isCrossRepository 2>>"$LOG_FILE") || die "cannot read $REPO#$PR"
why=$(fork_refuse "$meta") && blocked "$why"
title=$(jq -r .title <<<"$meta" | python3 "$QUARTERDECK_DIR/bin/outscan.py" --redact); sha=$(jq -r '.headRefOid // ""' <<<"$meta")
# What the author wrote, minus every picture they attached or linked: the lookout does not see those.
body=$(jq -r .body <<<"$meta" | python3 -c '
import re, sys
t = sys.stdin.read()
t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
t = re.sub(r"<img[^>]*>", "", t, flags=re.I)
t = re.sub(r"https?://[^ )\"]+\.(png|jpe?g|gif|webp|svg)([?#][^ )\"]*)?", "[picture the author supplied: not shown]", t, flags=re.I)
sys.stdout.write(t)')
changed=$(guard 60 "$GH" pr diff "$PR" -R "$REPO" --name-only 2>>"$LOG_FILE" || true)
working_on "PR #$PR — $title"
say "quarterdeck: lookout on $REPO#$PR — $title"

# ---- start an app from a worktree, shoot it, stop it ---------------------------------------------------------------
shoot_from() { # shoot_from <worktree> <prefix> -> fills $EVID/<prefix>/ ; returns 1 if the app never answered
  local wt="$1" prefix="$2" port="" up=0 p
  for _ in 1 2 3 4 5 6 7 8; do p=$((20000 + RANDOM % 20000)); listening "$p" || { port=$p; break; }; done
  [ -n "$port" ] || return 1
  [ -z "${PX_SCRATCH:-}" ] || rm -rf "$PX_SCRATCH"
  px_prepare serve "$wt" || return 1                   # the sandbox's write rule is this worktree's own: head and base each get theirs
  env -i "${PX_ENV[@]}" ${ENVA[@]+"${ENVA[@]}"} PORT="$port" perl -e "$RUN_GROUP" "$QA_TIMEOUT" ${PX_PRE[@]+"${PX_PRE[@]}"} bash -c 'cd "$1" && exec bash -c "$2"' _ "$wt" "$START" >>"$LOG_FILE" 2>&1 &
  SERVER=$!
  for _ in $(seq 1 "$READY_WAIT"); do kill -0 "$SERVER" 2>/dev/null || break; listening "$port" && { up=1; break; }; sleep 1; done
  if [ "$up" = 1 ]; then
    jq -n --arg b "http://127.0.0.1:$port" --argjson r "$ROUTES" --argjson w "$WIDTHS" --arg p "$prefix" '{base:$b, routes:$r, widths:$w, prefix:$p}' > "$TMP/spec-$prefix.json"
    guard "$QA_TIMEOUT" "$NODE" "$BROWSE" shoot "$TMP/spec-$prefix.json" "$EVID/$prefix" > "$TMP/shots-$prefix.json" 2>>"$LOG_FILE"
    [ "$?" = 3 ] && echo 3 > "$TMP/nobrowser"
  fi
  kill "$SERVER" 2>/dev/null; wait "$SERVER" 2>/dev/null; SERVER=""
  [ "$up" = 1 ]
}

rm -rf "$EVID"; mkdir -p "$EVID/head" "$EVID/base"
guard 180 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "pull/$PR/head" 2>>"$LOG_FILE" || blocked "could not fetch pull/$PR/head"
worktree_at "$SOURCE_REPO_DIR" "$WT" FETCH_HEAD || blocked "could not create a worktree at $WT"
why=$(qd_app_net_refused) && blocked "$why"            # on Linux the app is started only on the owner's opt-in: refused before anything is built
px_prepare check "$WT" || blocked "${PX_WHY:-the macOS sandbox could not be applied}, and a pull request's code is never run without it"
if [ -n "$BUILD" ]; then
  say "  building: $BUILD  [sandbox: $RUN_SANDBOX]"
  (cd "$WT" && guard "${QUARTERDECK_CHECK_TIMEOUT:-900}" env -i "${PX_ENV[@]}" ${ENVA[@]+"${ENVA[@]}"} ${PX_PRE[@]+"${PX_PRE[@]}"} bash -c "$BUILD" >>"$LOG_FILE" 2>&1) || blocked "the build failed: $BUILD"
fi
say "  taking the pictures from the head of #$PR"
shoot_from "$WT" head || blocked "the app did not answer on its port within ${READY_WAIT}s: $START"
if [ -f "$TMP/nobrowser" ] || [ -n "$(jq -r '.error // empty' "$TMP/shots-head.json" 2>/dev/null)" ]; then
  blocked "$(jq -r '.error // "the browser driver failed"' "$TMP/shots-head.json" 2>/dev/null)"
fi
# Every picture an error or configuration screen, or blank: the app did not render, and a picture of that is not a screen to judge. BLOCKED,
# never CLEAN, and no model is asked. (Some pictures failing and some not is told to the lookout below, and the failed ones are not judged.)
if [ -n "$(jq -r '.blocked.reason // empty' "$TMP/shots-head.json" 2>/dev/null)" ]; then
  blocked "$(jq -r '.blocked.reason' "$TMP/shots-head.json") (picture: $(jq -r '.blocked.screenshot // ""' "$TMP/shots-head.json")). If the app needs settings to start, give it synthetic ones in qa.env in config/projects.json."
fi
HEADSHOTS=$(jq -r '.shots[] | select(.file != "" and (.unusable // "") == "") | "\(.route)\t\(.width)\t\(.file)"' "$TMP/shots-head.json" 2>/dev/null)
NOTAPP=$(jq -r '.shots[] | select(.file != "" and (.unusable // "") != "") | "  route \(.route), width \(.width): \(.unusable)"' "$TMP/shots-head.json" 2>/dev/null)
[ -n "$HEADSHOTS" ] || blocked "the browser took no picture of any route"
COVERED=$(awk -F'\t' '!s[$1]++ {print $1}' <<<"$HEADSHOTS" | jq -R . | jq -sc .)
COVERAGE=$(jq -nr --argjson a "$ALLROUTES" --argjson c "$COVERED" '"Routes covered: " + ($c | join(", ")) + ". Not covered: " + (($a - $c) | if length == 0 then "none" else join(", ") end) + "."')

# The same routes on the trunk, as the nearest existing screen. If the trunk will not start, say so and go on without.
guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || true
BASESHOTS=""
if worktree_at "$SOURCE_REPO_DIR" "$WTB" "origin/$BASE" || worktree_at "$SOURCE_REPO_DIR" "$WTB" "$BASE"; then
  say "  and from the trunk, as the nearest existing screen"
  shoot_from "$WTB" base && BASESHOTS=$(jq -r '.shots[] | select(.file != "" and (.unusable // "") == "") | "\(.route)\t\(.width)\t\(.file)"' "$TMP/shots-base.json" 2>/dev/null)
fi

# ---- the lookout judges the harness's pictures -------------------------------------------------------------------------
notes=""
if [ -n "$NOTES_PATH" ] && [[ "$NOTES_PATH" =~ ^[A-Za-z0-9._/-]+$ ]] && [[ "$NOTES_PATH" != *..* ]] && [ -f "$WT/$NOTES_PATH" ]; then
  notes=$(head -c 20000 "$WT/$NOTES_PATH")
fi
ln -s "$WT" "$EVID/code" 2>/dev/null || true               # the code is readable from where the pictures are
ADR_SPEC=""
if [ "$ADR_ON" = 1 ]; then
  adr_block "$PROJECT" "$BASE" "$changed" "$title
$body"
  ADR_SPEC=$'ADR: <cites ADR n | matches ADR n | searched <records>>\n'
fi
listing() { awk -F'\t' '{ printf "  route %s, width %s: %s\n", $1, $2, $3 }' <<<"$1"; }

if [ -n "$BASESHOTS" ]; then BASEBLOCK="The same routes on the trunk, the nearest screens that already exist:
$(listing "$BASESHOTS")"
else BASEBLOCK="The trunk could not be started, so there are no pictures of the nearest existing screen. Say that you could not compare."; fi

prompt="$(preamble "$PROJECT")

You are the lookout on the design crew. Your seat: $(crew_meta lookout seat).

$(crew_role lookout)

--- THIS WATCH ---

$(printf 'Pull request #%s: %s\n\n%s\n' "$PR" "$title" "$body" | untrusted "pull request text")

Files this pull request changes:
$changed

The harness built the head of this pull request, started the app and took these pictures itself, at phone (390), tablet
(768) and desktop (1280) width. Open each with Read and look at it:
$(listing "$HEADSHOTS")
${NOTAPP:+
These pictures show only an error or a blank screen, so the app did not render there. They are not given to you and cannot be cited:
$(printf '%s\n' "$NOTAPP" | untrusted "what the screens show")
}$BASEBLOCK
The project's design notes${NOTES_PATH:+ ($NOTES_PATH)}:
$(printf '%s\n' "${notes:-(the project has no design notes registered)}" | untrusted "the project's design notes")

The author's own pictures, if any, have been taken out of the text above and you must not look for them. A finding must
name one of the harness's pictures listed here, exactly as written. The source is readable under code/ from your working
directory. Report at most $PER_RUN findings, fewer if that is the honest number; zero is a normal outcome.
${ADR_BLOCK:-}
End your reply with exactly these lines and nothing after them:
FINDINGS_JSON: <one-line JSON array; [] when clean. Each item: {\"route\":\"/x\",\"width\":390,\"image\":\"<one of the harness pictures above>\",\"severity\":\"critical|major|minor\",\"title\":\"one short claim\",\"body\":\"what is wrong in that picture and where, then the fix\",\"file\":\"source file to change, or empty\"}>
${ADR_SPEC}VERDICT: CLEAN
  or
VERDICT: FINDINGS <count>"

result=$(claude_run "$EVID" "$prompt" "Read,Grep,Glob"); rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" lookout ERROR "#$PR run failed"; die "lookout run failed"; }

raw=$(grep -o '^FINDINGS_JSON: .*' <<<"$result" | tail -1 | sed 's/^FINDINGS_JSON: //')
vline=$(grep -Eo '^VERDICT: (CLEAN|FINDINGS[ 0-9]*)' <<<"$result" | tail -1)
adr=""; ADR_NOTE=""
if [ "$ADR_ON" = 1 ]; then adr=$(adr_line "$result"); ADR_NOTE=$'\nDecisions on record: '"$ADR_SEARCHED"$'. '"${adr#ADR: }"; fi
if ! jq -e 'type == "array"' <<<"$raw" >/dev/null 2>&1 || [ -z "$vline" ] || { [ "$ADR_ON" = 1 ] && [ -z "$adr" ]; }; then
  record_run "$PROJECT" lookout ERROR "#$PR unparseable contract"
  die "contract did not parse — nothing written (see logs/runs/$QUARTERDECK_RUN_ID.json)"
fi

# Every finding must name a picture THIS run captured. Anything else (an author's picture, a path outside the evidence
# folder, a picture that is not there) means the reply cannot be trusted, and nothing is written.
EVROOT=$(cd "$EVID" && pwd -P)
outside=""
while read -r img; do
  [ -n "$img" ] || continue
  real=$(cd "$(dirname "$img")" 2>/dev/null && pwd -P)/$(basename "$img")
  if [ ! -f "$img" ] || [[ "$real" != "$EVROOT/head/"* && "$real" != "$EVROOT/base/"* ]] || ! grep -qF "$img" <<<"$HEADSHOTS
$BASESHOTS"; then outside="${outside:+$outside, }$img"; fi
done < <(jq -r '.[].image // ""' <<<"$raw")
if [ -n "$outside" ]; then
  say "  refused: a finding names a picture the harness did not capture: $outside"
  record_run "$PROJECT" lookout ERROR "#$PR a finding named a picture the harness did not capture"
  die "lookout: a finding named a picture the harness did not capture — nothing written"
fi

findings=$(jq -c --argjson n "$PER_RUN" '[.[0:$n][] | {route: (.route // ""), width: (.width // 0), image: .image, severity: (.severity // "major"), title: (.title // "finding"), body: (.body // ""), file: (.file // "")}]
  | to_entries | map(.value + {id: ("lookout-" + ((.key + 1) | tostring)), paths: (if .value.file == "" then [] else [.value.file] end), kind: "code", evidence: .value.image, line: 0})' <<<"$raw")
n=$(jq length <<<"$findings")
if [ "$n" = 0 ]; then verdict="CLEAN"; detail="no finding in $(wc -l <<<"$HEADSHOTS" | tr -d ' ') picture(s)"; else verdict="FINDINGS $n"; detail="$n finding(s)"; fi
[ -z "$BASESHOTS" ] && detail="$detail; the trunk could not be started, so nothing was compared"

report="**Lookout — #$PR**

**$verdict.** $detail. Pictures taken by the harness from the head ${sha:0:12}, at 390, 768 and 1280. $COVERAGE
$(jq -r '.[] | "\n### \(.severity | ascii_upcase): \(.title)\n`\(.route)` at \(.width) px, picture: `\(.image)`\n\n\(.body)"' <<<"$findings")
$ADR_NOTE

<sub>Quarterdeck lookout. The harness took every picture; the lookout judged them. Nothing was merged.</sub>"
say ""; say "$report" >&2; say ""

if [ "$APPLY" != 1 ]; then
  say "quarterdeck: report only — pass --apply to comment and write the findings document"
  record_run "$PROJECT" lookout "DRY-RUN" "#$PR — $verdict"
  exit 0
fi
DOC="$QUARTERDECK_HOME/workspace/${PROJECT}-lookout-pr${PR}.md"
printf '%s\n' "$report" > "$DOC"
mkdir -p "$QUARTERDECK_HOME/state/findings"
jq -n --arg d lookout --arg p "$PROJECT" --argjson pr "$PR" --arg h "$sha" --arg at "$(date -u +%FT%TZ)" --arg v "$verdict" --argjson f "$findings" \
  '{duty:$d, project:$p, pr:$pr, head:$h, at:$at, verdict:$v, findings:$f}' > "$QUARTERDECK_HOME/state/findings/${PROJECT}-pr${PR}-lookout.json"
gh_post 60 pr comment "$PR" -R "$REPO" --body "$report" >/dev/null 2>>"$LOG_FILE" || { record_run "$PROJECT" lookout ERROR "could not comment on #$PR"; die "could not post"; }
record_run "$PROJECT" lookout "$verdict" "#$PR — $detail" "https://github.com/$REPO/pull/$PR"

exit
}
