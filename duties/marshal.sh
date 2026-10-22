#!/bin/bash
# marshal — the ship's police: read a pull request for security.
#
# The security crew (gunner, customs, gatekeeper) each read the diff from their own side. They are read only: no
# edit tools, no gh, no credentials. Three things are decided by the harness and not by any model:
#   1. A diff that touches one of the project's forbidden_paths is BLOCK, before any model runs. Encryption, key
#      rotation and migrations stay for a person.
#   2. A clean verdict needs all three seats to have reported. A seat that did not answer in the contract is not a
#      seat that found nothing.
#   3. Nothing is posted, filed or written without --apply.
#
#   qtdeck run <p> marshal --pr 218            report only
#   qtdeck run <p> marshal --pr 218 --apply    comment on the pull request and write the findings file
#
# Contract of each seat:
#   FINDINGS_JSON: [{"file","line","severity","title","body"}]     [] when clean
#   VERDICT: CLEAN | FINDINGS <n>
# What the duty records:
#   CLEAN | FINDINGS <n> | BLOCK <reason>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> marshal --pr <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/marshal-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
BASE=$(project_get "$PROJECT" default_branch main)
GH="${QUARTERDECK_GH:-gh}"
PER_SEAT="${QUARTERDECK_MAX_ITEMS:-8}"                 # findings each seat may bring: the cap on one run

APPLY=0 PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --pr)    PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    *) die "marshal: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$PR" =~ ^[0-9]+$ ]] || die "marshal needs a pull request: --pr <number>"

# Decisions on record, when this checkout has the Logkeeper's injector.
ADR_ON=0; ADR_BLOCK=""
if [ -f "$QUARTERDECK_DIR/bin/decisions.sh" ]; then source "$QUARTERDECK_DIR/bin/decisions.sh"; ADR_ON=1; fi

acquire_lock "marshal-$PROJECT-$PR"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-marshal-$PR"
WT="$QUARTERDECK_HOME/workspace/wt-marshal-${PROJECT}-${PR}"
TMP="$(mktemp -d)"
cleanup() {
  [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap 'cleanup; release_lock' EXIT

meta=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json number,title,body,state,headRefOid 2>>"$LOG_FILE") \
  || die "cannot read $REPO#$PR"
title=$(jq -r .title <<<"$meta" | python3 "$QUARTERDECK_DIR/bin/outscan.py" --redact); body=$(jq -r .body <<<"$meta"); sha=$(jq -r '.headRefOid // ""' <<<"$meta")
changed=$(guard 60 "$GH" pr diff "$PR" -R "$REPO" --name-only 2>>"$LOG_FILE") || die "cannot read the files $REPO#$PR changes"
working_on "PR #$PR — $title"
say "quarterdeck: marshal on $REPO#$PR — $title"

post() { # post <body> — a comment on the pull request, only with --apply
  [ "$APPLY" = 1 ] || return 0
  gh_post 60 pr comment "$PR" -R "$REPO" --body "$1" >/dev/null 2>>"$LOG_FILE" || { record_run "$PROJECT" marshal ERROR "could not comment on #$PR"; die "could not post"; }
}
save_findings() { # save_findings <verdict> <findings-json>
  mkdir -p "$QUARTERDECK_HOME/state/findings"
  jq -n --arg d marshal --arg p "$PROJECT" --argjson pr "$PR" --arg h "$sha" --arg at "$(date -u +%FT%TZ)" --arg v "$1" --argjson f "$2" \
    '{duty:$d, project:$p, pr:$pr, head:$h, at:$at, verdict:$v, findings:$f}' > "$QUARTERDECK_HOME/state/findings/${PROJECT}-pr${PR}-marshal.json"
}

# ---- 1. forbidden paths: decided here, before any model runs -------------------------------------------------
hits=""
while read -r forbidden; do
  [ -n "$forbidden" ] || continue
  # A literal prefix, not a regex; through the environment so awk does not read backslashes as escapes.
  while read -r f; do
    [ -n "$f" ] || continue
    fp_hit "$f" "$forbidden" && hits="${hits:+$hits, }$f ($forbidden)"
  done <<<"$changed"
done < <(jq -r --arg p "$PROJECT" '(.[$p].forbidden_paths // [])[]' "$PROJECTS_FILE")
if [ -n "$hits" ]; then
  reason="touches forbidden path(s): $hits. A person reviews this one; no model was asked."
  say "  BLOCK — $reason"
  post "**Marshal — #$PR**

**BLOCK.** This change $reason

<sub>Quarterdeck marshal. Decided by the harness from the project's forbidden paths, before any model ran. Nothing was merged.</sub>"
  [ "$APPLY" = 1 ] && save_findings "BLOCK" "$(jq -nc --arg r "$reason" '[{id:"marshal-block", severity:"critical", title:"Touches a forbidden path", body:$r, file:"", line:0, paths:[], kind:"code"}]')"
  record_run "$PROJECT" marshal "$([ "$APPLY" = 1 ] && echo BLOCK || echo DRY-RUN)" "#$PR — BLOCK: $reason" "https://github.com/$REPO/pull/$PR"
  exit 0
fi

# ---- 2. the security crew reads the head, read only -------------------------------------------------------------
guard 180 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "pull/$PR/head" 2>>"$LOG_FILE" || die "could not fetch pull/$PR/head"
worktree_at "$SOURCE_REPO_DIR" "$WT" FETCH_HEAD || die "could not create a worktree at $WT"
SEATS=$(crew_by_discipline security | tr '\n' ' '); SEATS="$(xargs <<<"$SEATS")"
[ -n "$SEATS" ] || die "marshal: no crew sits on the security panel (see: qtdeck crew)"
ADR_SPEC=""
if [ "$ADR_ON" = 1 ]; then
  adr_block "$PROJECT" "$BASE" "$changed" "$title
$body"
  ADR_SPEC=$'ADR: <cites ADR n | matches ADR n | searched <records>>\n'
fi

DIFF_TEXT="$(wt_diff "$WT" "origin/$BASE")"
PIDS=""
for seat in $SEATS; do
  (
    trap - EXIT
    export QUARTERDECK_RUN_ID="${QUARTERDECK_RUN_ID}-$seat"
    export QUARTERDECK_SEAT="$seat"   # its own billing setting, if any (bin/billing.py)
    m="$(crew_meta "$seat" model)"; [ -n "$m" ] && export QUARTERDECK_MODEL_PERSONA="$m"
    e="$(crew_meta "$seat" effort)"; [ -n "$e" ] && export QUARTERDECK_EFFORT_PERSONA="$e"
    pv="$(crew_meta "$seat" provider)"; [ -n "$pv" ] && export QUARTERDECK_PROVIDER_PERSONA="$pv"
    p="$(preamble "$PROJECT")

You are the ${seat} on the security crew. Your seat: $(crew_meta "$seat" seat).

$(crew_role "$seat")

--- THIS REVIEW ---

$(printf 'Pull request #%s of %s: %s\n\n%s\n' "$PR" "$REPO" "$title" "$body" | untrusted "pull request text")

The pull request is checked out around you at its head. Its diff follows (read by the harness; you have no git), and
these are the files it touches:
$changed

$(printf '%s\n' "$DIFF_TEXT" | untrusted "diff of pull request #$PR")

Read the change and the code around it from your own side only. The other seats cover theirs. Report defects this
diff introduces that weaken security or privacy, not pre-existing debt and not style. At most $PER_SEAT findings, fewer
if that is the honest number; zero is a normal and good outcome. You never need a real secret to judge code: if you
meet one, say where it is and do not repeat it.
${ADR_BLOCK:-}
End your reply with exactly these lines and nothing after them:
FINDINGS_JSON: <one-line JSON array; [] when clean. Each item: {\"file\":\"path from repo root\",\"line\":<line on the new side>,\"severity\":\"critical|major|minor\",\"title\":\"one short claim\",\"body\":\"markdown: the exact failure, then the fix\"}>
${ADR_SPEC}VERDICT: CLEAN
  or
VERDICT: FINDINGS <count>"
    out="$(claude_run "$WT" "$p")"; rc=$?
    printf '%s' "$out" > "$TMP/seat.$seat.txt"; echo "$rc" > "$TMP/seat.$seat.rc"
  ) &
  PIDS="$PIDS $!"
done
wait $PIDS

echo '[]' > "$TMP/findings.json"; missing=""
for seat in $SEATS; do
  rc="$(cat "$TMP/seat.$seat.rc" 2>/dev/null || echo 1)"
  [ "$rc" = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
  raw="$(grep -o '^FINDINGS_JSON: .*' "$TMP/seat.$seat.txt" 2>/dev/null | tail -1 | sed 's/^FINDINGS_JSON: //')"
  if [ "$rc" = 0 ] && jq -e 'type == "array"' <<<"$raw" >/dev/null 2>&1 \
     && grep -Eq '^VERDICT: (CLEAN|FINDINGS)' "$TMP/seat.$seat.txt" \
     && { [ "$ADR_ON" != 1 ] || [ -n "$(adr_line "$(cat "$TMP/seat.$seat.txt")")" ]; }; then
    jq --arg s "$seat" --argjson n "$PER_SEAT" --argjson prev "$(cat "$TMP/findings.json")" \
       '$prev + (.[0:$n] | map({file: (.file // ""), line: (.line // 0), severity: (.severity // "major"), title: (.title // "finding"), body: (.body // ""), seat: $s}))' \
       <<<"$raw" > "$TMP/findings.next" && mv "$TMP/findings.next" "$TMP/findings.json"
  else
    missing="${missing:+$missing, }$seat"
    log "marshal #$PR: $seat did not parse — logs/runs/${QUARTERDECK_RUN_ID}-$seat.json"
  fi
done

# One finding reported by two seats is one finding.
findings=$(jq -c 'group_by([.file, (.title | ascii_downcase)]) | map(.[0] + {seats: map(.seat) | unique})
                  | to_entries | map(.value + {id: ("marshal-" + ((.key + 1) | tostring)), paths: (if .value.file == "" then [] else [.value.file] end), kind: "code"})' "$TMP/findings.json")
n=$(jq length <<<"$findings")

# A clean verdict needs every seat. A seat that did not answer in the contract has not found nothing.
if [ -n "$missing" ] && [ "$n" = 0 ]; then
  say "  ERROR — $missing did not report in the contract, so this cannot be called clean. Nothing written."
  record_run "$PROJECT" marshal ERROR "#$PR — $missing did not report in the contract; no verdict, nothing written"
  die "marshal: an incomplete crew cannot return CLEAN"
fi
if [ "$n" = 0 ]; then verdict="CLEAN"; detail="all three seats found nothing"
else verdict="FINDINGS $n"; detail="$n finding(s)${missing:+; $missing did not report, so a clean verdict is not possible}"; fi

ADR_NOTE=""; [ "$ADR_ON" = 1 ] && ADR_NOTE=$'\nDecisions on record: '"$ADR_SEARCHED"
report="**Marshal — #$PR**

**$verdict.** $detail.
$(jq -r '.[] | "\n### \(.severity | ascii_upcase): \(.title)\n`\(.file):\(.line)` (\(.seats | join(", ")))\n\n\(.body)"' <<<"$findings")
${ADR_NOTE}

<sub>Quarterdeck marshal. The crew read the diff and nothing else; the harness decided the verdict. Nothing was merged.</sub>"
say ""; say "$report" >&2; say ""

if [ "$APPLY" != 1 ]; then
  say "quarterdeck: report only — pass --apply to comment on the pull request"
  record_run "$PROJECT" marshal "DRY-RUN" "#$PR — $verdict"
  exit 0
fi
post "$report"
save_findings "$verdict" "$findings"
record_run "$PROJECT" marshal "$verdict" "#$PR — $detail" "https://github.com/$REPO/pull/$PR"

exit
}
