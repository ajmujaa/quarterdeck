#!/bin/bash
# surveyor — read a pull request and post findings as review comments.
#
# Contract: the model ends its reply with exactly two lines.
#   FINDINGS_JSON: [{"file","line","severity","title","body"}, ...]   ([] if clean)
#   VERDICT: CLEAN | FINDINGS <count>
# Nothing is posted unless both parse. The model never touches GitHub.
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> surveyor}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/surveyor-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"
# Decisions on record, when this checkout has the Logkeeper's injector.
ADR_ON=0; ADR_BLOCK=""
if [ -f "$QUARTERDECK_DIR/bin/decisions.sh" ]; then source "$QUARTERDECK_DIR/bin/decisions.sh"; ADR_ON=1; fi

APPLY=0
PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --pr) PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    *) die "surveyor: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1

# Keyed by the PR when one is named (two fixes on the same project, on
# different PRs, each get their own review); a sweep of every open PR has no
# single target, so it keeps one project-wide "sweep" lock — the same as
# today, just named. A sweep and a fix's own targeted review could in theory
# both land on the same PR; that is rare enough, and posts only a second
# comment rather than losing anything, that it is left alone here.
if [ -n "$PR" ]; then
  acquire_lock "surveyor-$PROJECT-$PR"
else
  acquire_lock "surveyor-$PROJECT-sweep"
fi

# Pick the work: one named PR, or every open PR not yet reviewed at its head SHA.
if [ -n "$PR" ]; then
  targets="$PR"
else
  targets=$(guard 60 "$GH" pr list -R "$REPO" --state open --limit "${QUARTERDECK_MAX_ITEMS:-5}" --json number --jq '.[].number' 2>>"$LOG_FILE")
fi
[ -n "${targets:-}" ] || { say "quarterdeck: no open pull requests on $REPO"; log "$PROJECT: nothing to review"; exit 0; }

SEEN="$QUARTERDECK_HOME/state/reviewed.json"
[ -f "$SEEN" ] || echo '{}' > "$SEEN"

for num in $targets; do
  meta=$(guard 60 "$GH" pr view "$num" -R "$REPO" --json number,title,headRefOid,state 2>>"$LOG_FILE") || {
    log "$PROJECT#$num: could not read PR"; continue; }
  sha=$(jq -r .headRefOid <<<"$meta")
  title=$(jq -r .title <<<"$meta")
  key="$REPO#$num@${sha:0:12}"

  # A report-only pass remembers what it read, or a report-only schedule
  # re-reads every open PR at the same commit every time it fires — a model call
  # each, producing nothing anyone sees. An --apply run still reviews anything
  # only ever seen in report-only mode, because nothing was posted for it.
  if [ "$APPLY" = 1 ]; then seen='has($k) and ((.[$k].dry // false) | not)'; else seen='has($k)'; fi
  if [ -z "$PR" ] && jq -e --arg k "$key" "$seen" "$SEEN" >/dev/null; then
    log "$PROJECT#$num: already reviewed at $sha"; continue
  fi

  working_on "PR #$num — $title"
  say "quarterdeck: reviewing $REPO#$num — $title"
  export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-${num}-${sha:0:8}"

  # The harness picks the records of decisions this review is shown, from the paths in the diff and the words in the title.
  ADR_SPEC=""; ADR_NOTE=""
  if [ "$ADR_ON" = 1 ]; then
    adr_block "$PROJECT" "$(project_get "$PROJECT" default_branch main)" \
      "$(guard 60 "$GH" pr diff "$num" -R "$REPO" --name-only 2>>"$LOG_FILE" || true)" "$title"
    ADR_SPEC=$'ADR: <cites ADR n | matches ADR n | searched <records>>\n'
  fi

  prompt="$(preamble "$PROJECT")

Review pull request #$num of $REPO at depth ${QUARTERDECK_REVIEW_EFFORT:-medium}.

The diff is below, read by the harness (you have no gh and no git). Read the surrounding
code in the working folder before judging anything. Report only defects this diff introduces: a wrong result, a crash, a
security or data-integrity hole, a broken contract with another part of the
system. Pre-existing debt, style preference and refactor wishes are not
findings. Prefer three real findings over ten padded ones; zero is a normal and
good outcome.
${ADR_BLOCK:-}
$(pr_diff_text "$REPO" "$num" | untrusted "diff of pull request #$num")

End your reply with exactly these lines and nothing after them:
FINDINGS_JSON: <one-line JSON array; [] when clean. Each item: {\"file\":\"path from repo root\",\"line\":<line on the NEW side of the diff>,\"severity\":\"critical|major|minor\",\"title\":\"one short claim\",\"body\":\"markdown: the failure scenario, then the fix\"}>
${ADR_SPEC}VERDICT: CLEAN
  or
VERDICT: FINDINGS <count>"

  result=$(claude_run "$WORKDIR" "$prompt"); rc=$?
  if [ $rc = 2 ]; then say "quarterdeck: usage limit reached — stopping, nothing written"; exit 0; fi
  [ $rc = 0 ] && [ -n "$result" ] || { log "$PROJECT#$num: run failed"; record_run "$PROJECT" surveyor ERROR "run failed on #$num"; continue; }

  findings=$(grep -o 'FINDINGS_JSON: .*' <<<"$result" | tail -1 | sed 's/^FINDINGS_JSON: //')
  jq -e 'type == "array"' <<<"$findings" >/dev/null 2>&1 || findings=""
  verdict=$(grep -Eo 'VERDICT: (CLEAN|FINDINGS[ 0-9]*)' <<<"$result" | tail -1)

  # An unparseable contract is a failed run, not a clean one. This is the line
  # that keeps a confused model from silently approving something.
  if [ "$ADR_ON" = 1 ]; then
    adr=$(adr_line "$result")
    [ -n "$adr" ] && ADR_NOTE=$'\n\nDecisions on record: '"$ADR_SEARCHED"$'. '"${adr#ADR: }"
  fi
  if [ -z "$findings" ] || [ -z "$verdict" ] || { [ "$ADR_ON" = 1 ] && [ -z "$adr" ]; }; then
    log "$PROJECT#$num: contract did not parse — see logs/runs/$QUARTERDECK_RUN_ID.json"
    say "quarterdeck: #$num — contract did not parse, nothing posted"
    record_run "$PROJECT" surveyor ERROR "unparseable contract on #$num"
    continue
  fi

  n=$(jq 'length' <<<"$findings")

  if [ "$APPLY" != 1 ]; then
    say ""
    say "── report only: $REPO#$num — $n finding(s) ──"
    [ "$n" -gt 0 ] && jq -r '.[] | "  [\(.severity)] \(.file):\(.line)\n      \(.title)"' <<<"$findings" >&2
    say "  (re-run with --apply to post)"
    record_run "$PROJECT" surveyor "DRY-RUN" "$n finding(s) on #$num"
    # Never overwrite a real review with a dry one. Guarded: a sweep and a
    # fix's own targeted review are different PRs but the same shared file, so
    # two of these finishing at once must not let one overwrite the other.
    _mark_seen() {
      local t; t=$(mktemp)
      jq --arg k "$key" --argjson n "$n" \
        'if has($k) then . else .[$k] = {verdict:"DRY-RUN", findings:$n, dry:true, at:(now|todate)} end' \
        "$SEEN" > "$t" && mv "$t" "$SEEN"
    }
    with_file_lock "$SEEN" _mark_seen
    continue
  fi

  if [ "$n" = 0 ]; then
    gh_post 60 pr comment "$num" -R "$REPO" \
      --body "Quarterdeck reviewed \`${sha:0:8}\` and found nothing worth raising.${ADR_NOTE}" >/dev/null 2>>"$LOG_FILE" \
      && say "quarterdeck: #$num clean — comment posted"
    record_run "$PROJECT" surveyor CLEAN "#$num"
  else
    body=$(jq -r '"Quarterdeck review — \(length) finding(s).\n\n" + (map("### \(.severity | ascii_upcase) — \(.title)\n`\(.file):\(.line)`\n\n\(.body)") | join("\n\n"))' <<<"$findings")
    body="$body$ADR_NOTE"
    if gh_post 60 pr comment "$num" -R "$REPO" --body "$body" >/dev/null 2>>"$LOG_FILE"; then
      say "quarterdeck: #$num — $n finding(s) posted"
      record_run "$PROJECT" surveyor "FINDINGS" "$n on #$num"
    else
      log "$PROJECT#$num: posting failed"
      record_run "$PROJECT" surveyor ERROR "post failed on #$num"
      continue
    fi
  fi

  # What the caulker reads: the same findings, as a file for this exact head (the other review duties write one too).
  mkdir -p "$QUARTERDECK_HOME/state/findings"
  jq -n --arg d surveyor --arg p "$PROJECT" --argjson pr "$num" --arg h "$sha" --arg at "$(date -u +%FT%TZ)" --arg v "${verdict#VERDICT: }" --argjson f "$findings" \
    '{duty:$d, project:$p, pr:$pr, head:$h, at:$at, verdict:$v,
      findings: ($f | to_entries | map(.value + {id: ("surveyor-" + ((.key + 1) | tostring)), kind: "code",
                                                  paths: (if (.value.file // "") == "" then [] else [.value.file] end)}))}' \
    > "$QUARTERDECK_HOME/state/findings/${PROJECT}-pr${num}-surveyor.json" 2>>"$LOG_FILE" || log "$PROJECT#$num: could not write the findings file"

  _mark_seen() {
    local t; t=$(mktemp)
    jq --arg k "$key" --arg v "${verdict#VERDICT: }" '.[$k] = {verdict:$v, at:(now|todate)}' "$SEEN" > "$t" && mv "$t" "$SEEN"
  }
  with_file_lock "$SEEN" _mark_seen
done

exit
}
