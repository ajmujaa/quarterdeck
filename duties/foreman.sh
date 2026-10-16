#!/bin/bash
# foreman — turn a findings document into well-formed GitHub issues, deduplicated.
#
# Reads any markdown report (a review, an audit, a pile of notes), works out
# which items are discrete and actionable, checks each against what is already
# filed, and files the rest. The model decides what to file; this script does
# the filing.
#
# Contract:
#   ISSUES_JSON: [{"title","body","labels":[...]}, ...]        ([] if nothing new)
#   SKIPPED_JSON: [{"title","reason"}, ...]                    (already filed / not actionable)
#   RESULT: FILE <count> | NONE <reason>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> foreman --from <file>}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/foreman-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-tests and for a stand-in; lib.sh puts the real gh first on PATH

APPLY=0
FROM=""
ONE=0   # --one: the document is one batch of work, filed as exactly one issue
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --from)  FROM="${2:-}"; shift ;;
    --one)   ONE=1 ;;
    *) die "foreman: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[ -n "$FROM" ] || die "foreman needs a findings document: --from <file.md>"
FROM="${FROM/#\~/$HOME}"
[ -r "$FROM" ] || die "cannot read $FROM"

# Keyed by the document, not just the project: two findings documents can be
# filed at once (two fixes filing two different items in the same project),
# and only refiling the SAME document should wait.
acquire_lock "foreman-$PROJECT-$(basename "$FROM" | tr -c 'A-Za-z0-9._-' '_')"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-foreman-$(date +%s)"

# What is already filed. Given to the model so it can dedupe against reality
# rather than guess — the most common failure of an issue-filing agent is
# re-filing something that has been open for a month.
existing=$(guard 60 "$GH" issue list -R "$REPO" --state all --limit 100 \
  --json number,title,state --jq '[.[] | "#\(.number) [\(.state)] \(.title)"] | join("\n")' 2>>"$LOG_FILE")
[ -n "$existing" ] || existing="(none)"

working_on "filing from $(basename "$FROM")"
say "quarterdeck: reading $(basename "$FROM") against $REPO"

prompt="$(preamble "$PROJECT")

Below is a findings document and the list of issues already on the tracker.
Decide what deserves to be filed as a NEW issue.

File an item only when all of these hold:
- It is a concrete defect or a specific, bounded piece of work.
- It is not already covered by an open or closed issue below (read the titles
  carefully — a differently-worded duplicate is still a duplicate).
- It can be acted on without asking the user a question first.

Do not file: vague improvements, anything needing a product decision, or
several related symptoms that are really one root cause (file the root cause
once, and mention the symptoms in its body).

Write each issue the way a good engineer writes one: a title that states the
defect rather than the area, a body with what happens, where (file and line
when the document gives it), why it matters, and how to verify a fix. Do not
pad. Use the repo's existing label vocabulary only if you are sure of it;
otherwise leave labels empty.

$([ "$ONE" = 1 ] && echo "This document is ONE batch of related work that will be built on one
branch and reviewed as one pull request. File it as exactly one issue: a title
naming the batch, and a body with a checklist, one line per item, each keeping
its file and line. Leave out any item that is already filed or not a change,
and say so in SKIPPED_JSON.
")
=== ALREADY ON THE TRACKER ===
$(printf '%s\n' "$existing" | untrusted "issue tracker titles")

=== FINDINGS DOCUMENT ($(basename "$FROM")) ===
$(untrusted "findings document" < "$FROM")
=== END ===

End your reply with exactly these three lines and nothing after them:
ISSUES_JSON: <one-line JSON array of {\"title\":\"...\",\"body\":\"markdown\",\"labels\":[]}; [] if nothing new>
SKIPPED_JSON: <one-line JSON array of {\"title\":\"...\",\"reason\":\"...\"} for items you deliberately did not file>
RESULT: FILE <count>
  or
RESULT: NONE <reason>"

result=$(claude_run "$WORKDIR" "$prompt"); rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing filed"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" foreman ERROR "run failed"; die "foreman run failed"; }

issues=$(grep -o 'ISSUES_JSON: .*'  <<<"$result" | tail -1 | sed 's/^ISSUES_JSON: //')
skipped=$(grep -o 'SKIPPED_JSON: .*' <<<"$result" | tail -1 | sed 's/^SKIPPED_JSON: //')
verdict=$(grep -Eo '^RESULT: (FILE [0-9]+|NONE.*)' <<<"$result" | tail -1)

jq -e 'type == "array"' <<<"$issues"  >/dev/null 2>&1 || issues=""
jq -e 'type == "array"' <<<"$skipped" >/dev/null 2>&1 || skipped="[]"

if [ -z "$issues" ] || [ -z "$verdict" ]; then
  log "$PROJECT: contract did not parse — logs/runs/$QUARTERDECK_RUN_ID.json"
  record_run "$PROJECT" foreman ERROR "unparseable contract"
  die "contract did not parse — nothing filed (see logs/runs/$QUARTERDECK_RUN_ID.json)"
fi

# A batch is one issue, whatever the model returned: the harness, not the model,
# decides how many pull requests a batch becomes.
# If it returned several anyway, they are folded into the first rather than
# dropped, so no item of the batch goes missing between document and issue.
[ "$ONE" = 1 ] && issues=$(jq -c 'if length > 1 then [.[0] + {body: (map("## " + .title + "\n\n" + .body) | join("\n\n"))}] else . end' <<<"$issues")
n=$(jq 'length' <<<"$issues")
ns=$(jq 'length' <<<"$skipped")

say ""
say "── $REPO — $n to file, $ns skipped ──"
[ "$ns" -gt 0 ] && jq -r '.[] | "  skip: \(.title)\n        \(.reason)"' <<<"$skipped" >&2
[ "$n" -gt 0 ] && jq -r '.[] | "  file: \(.title)"' <<<"$issues" >&2

if [ "$APPLY" != 1 ]; then
  say ""
  say "  (report only — re-run with --apply to file them)"
  record_run "$PROJECT" foreman "DRY-RUN" "$n to file, $ns skipped"
  exit 0
fi

filed=0
made='[]'   # what this document actually became, so it can be traced back
while read -r item; do
  [ -n "$item" ] || continue
  title=$(jq -r .title <<<"$item")
  body=$(jq -r .body <<<"$item")
  labels=$(jq -r '(.labels // []) | join(",")' <<<"$item")
  # Labels that don't exist make `gh issue create` fail outright and lose the
  # issue, so they are best-effort: retry once without them.
  if url=$(guard 60 "$GH" issue create -R "$REPO" --title "$title" --body "$body" \
             ${labels:+--label "$labels"} 2>>"$LOG_FILE"); then
    :
  elif url=$(guard 60 "$GH" issue create -R "$REPO" --title "$title" --body "$body" 2>>"$LOG_FILE"); then
    log "filed without labels: $title"
  else
    log "FAILED to file: $title"
    say "  ✗ $title"
    continue
  fi
  filed=$((filed + 1))
  made=$(jq -c --arg u "$url" --arg t "$title" \
           '. + [{number: ($u | split("/") | last | tonumber? // 0), url: $u, title: $t}]' <<<"$made")
  say "  ✓ $url  $title"
done < <(jq -c '.[]' <<<"$issues")

# Record which document became which issues. Without this nobody can answer the
# only question that matters when looking at a report weeks later — "did we
# ever do anything about this?" — and the dashboard had no way to show it.
if [ "$filed" -gt 0 ]; then
  FILED_LEDGER="$QUARTERDECK_HOME/state/filed.json"
  [ -f "$FILED_LEDGER" ] || echo '[]' > "$FILED_LEDGER"
  # Two foremen can finish at once now (different documents, same project), so
  # the read-then-write below is guarded — otherwise the second to write wins
  # and the first's entry is lost, not merged.
  _append_filed() {
    local t; t=$(mktemp)
    jq --arg p "$PROJECT" --arg d "$(basename "$FROM")" --arg r "$REPO" --argjson m "$made" \
       '. + [{project: $p, document: $d, repo: $r, issues: $m, at: (now|todate)}] | .[-200:]' \
       "$FILED_LEDGER" > "$t" && mv "$t" "$FILED_LEDGER"
  }
  with_file_lock "$FILED_LEDGER" _append_filed
fi

record_run "$PROJECT" foreman "FILED" "$filed issue(s) from $(basename "$FROM")"
say ""
say "quarterdeck: filed $filed issue(s) on $REPO"

exit
}
