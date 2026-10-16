#!/bin/bash
# bosun — walk the deck.
#
# Reports drift; never writes to any repository. The HARNESS runs every check with plain commands (bin/deck.py, git, and one
# read of the pull request and issue lists) and the model only ranks what the harness found and puts each in one line:
#   - stale branches: merged, with a closed pull request, or untouched for N days with no open pull request;
#   - dead environment variables: read in code but defined nowhere in the repository, or defined in an example env file
#     and never read (real .env files are never opened);
#   - drift between the docs and the code: a README or doc naming a file, command, flag or variable that no longer exists;
#   - unused scripts and config keys;
#   - open issues whose pull request has already merged;
#   - TODO and FIXME older than N days (by git blame).
# The model cannot add a finding: it ranks the harness's findings by id, and anything else it says is thrown away.
#
# Findings go into a dated report under state/bosun/ (mode 0600). With --apply, ONE summary issue per project is created or updated
# (never one per finding). Nothing else is written anywhere: no branch is deleted, no file edited, nothing pushed. Deleting a stale
# branch is the owner's decision. It walks only the registered project's own repository, from a throwaway worktree of its base branch.
# It runs at most once a day (--again to walk again by hand), and ships with no schedule set.
#
#   quarterdeck run <p> bosun                 report only: the state report, no issue
#   quarterdeck run <p> bosun --apply         also create or update the summary issue
#   quarterdeck run <p> bosun --stale 30 --todo 60 --again
#
# Contract:
#   RANKED_JSON: [{"id":"<finding id>","action":"one line"}, ...]     most important first; only ids the harness gave
#   SUMMARY: <one line>
# What the duty records:   DECK CLEAR | DECK <n>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> bosun}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/bosun-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
BASE=$(project_get "$PROJECT" default_branch main)
GH="${QUARTERDECK_GH:-gh}"
DECK="${QUARTERDECK_DECK:-$QUARTERDECK_DIR/bin/deck.py}"
MAX="${QUARTERDECK_BOSUN_MAX_ITEMS:-40}"                # findings in one report and one issue: the per-run cap (QUARTERDECK_MAX_ITEMS is 5 fleet-wide, too small for a report)
STALE="${QUARTERDECK_BOSUN_STALE_DAYS:-60}"
TODO_DAYS="${QUARTERDECK_BOSUN_TODO_DAYS:-90}"
TITLE="Quarterdeck bosun: deck report"                 # one summary issue per project, found by this exact title

APPLY=0 AGAIN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --again) AGAIN=1 ;;
    --stale) STALE="${2:-60}"; shift ;;
    --todo)  TODO_DAYS="${2:-90}"; shift ;;
    *) die "bosun: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$STALE" =~ ^[0-9]+$ ]] && [[ "$TODO_DAYS" =~ ^[0-9]+$ ]] || die "bosun: --stale and --todo take a number of days"

acquire_lock "bosun-$PROJECT"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-bosun"
WT="$QUARTERDECK_HOME/workspace/wt-bosun-${PROJECT}"
TMP="$(mktemp -d)"
cleanup() {
  [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0
  git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

# At most once a day.
OUTDIR="$QUARTERDECK_HOME/state/bosun"
STAMP="$OUTDIR/$PROJECT.last"
NOW=$(date +%s)
if [ "$AGAIN" != 1 ] && [ -f "$STAMP" ] && [ $(( NOW - $(cat "$STAMP" 2>/dev/null || echo 0) )) -lt 72000 ]; then
  say "quarterdeck: the bosun already walked $PROJECT in the last 20 hours (--again to walk it again)"
  record_run "$PROJECT" bosun NOTHING "already walked in the last 20 hours"
  exit 0
fi
working_on "walking the deck of $PROJECT"
say "quarterdeck: bosun on $REPO"

# ---- the harness walks the deck ---------------------------------------------------------------------------------------------------------
guard 120 git -C "$SOURCE_REPO_DIR" fetch -q origin 2>>"$LOG_FILE" || log "fetch failed; walking what is local"   # remote-tracking refs only
BASEREF="origin/$BASE"; git -C "$SOURCE_REPO_DIR" rev-parse -q --verify "$BASEREF" >/dev/null || BASEREF="$BASE"
worktree_at "$SOURCE_REPO_DIR" "$WT" "$BASEREF" || die "could not create a worktree at $WT"

skipped=""
prs=$(guard 90 "$GH" pr list -R "$REPO" --state all --limit 200 --json number,state,headRefName,mergedAt,closingIssuesReferences 2>>"$LOG_FILE") || prs=""
jq -e 'type == "array"' <<<"$prs" >/dev/null 2>&1 || { prs='[]'; skipped="${skipped:+$skipped; }pull requests could not be listed (gh), so the branch and issue checks that need them were limited"; }
oi=$(guard 90 "$GH" issue list -R "$REPO" --state open --limit 200 --json number,title 2>>"$LOG_FILE") || oi=""
jq -e 'type == "array"' <<<"$oi" >/dev/null 2>&1 || { oi='[]'; skipped="${skipped:+$skipped; }open issues could not be listed (gh)"; }
printf '%s' "$prs" > "$TMP/prs.json"; printf '%s' "$oi" > "$TMP/issues.json"

run() { python3 "$DECK" "$@" 2>>"$LOG_FILE" | jq -c '.findings // []' 2>/dev/null || echo '[]'; }
{
  run branches --repo "$SOURCE_REPO_DIR" --base "$BASEREF" --days "$STALE" --now "$NOW" --prs "$TMP/prs.json"
  run envvars --tree "$WT"
  run docs --tree "$WT"
  run unused --tree "$WT"
  run issues --issues "$TMP/issues.json" --prs "$TMP/prs.json"
  run todos --tree "$WT" --repo "$SOURCE_REPO_DIR" --ref "$BASEREF" --days "$TODO_DAYS" --now "$NOW"
} | jq -s 'add' > "$TMP/all.json"
jq -e 'type == "array"' "$TMP/all.json" >/dev/null 2>&1 || echo '[]' > "$TMP/all.json"

# Harmful kinds first, then the tidy-ups; capped. Ids are the harness's, assigned here.
total=$(jq length "$TMP/all.json")
jq -c --argjson n "$MAX" '
  (["doc drift","dead environment variable","open issue already fixed","stale branch","old TODO","unused script","unused config key"]) as $order
  | map(.kind as $k | . + {p: (($order | index($k)) // 99)}) | sort_by(.p) | .[0:$n]
  | to_entries | map(.value + {id: ("f" + ((.key + 1) | tostring))} | del(.p))' "$TMP/all.json" > "$TMP/findings.json"
n=$(jq length "$TMP/findings.json")
more=$(( total - n ))

mkdir -p "$OUTDIR"; chmod 700 "$OUTDIR" 2>/dev/null || true
REPORT="$OUTDIR/${PROJECT}-$(date +%Y-%m-%d).md"

# ---- the model ranks them; it cannot add one ----------------------------------------------------------------------------------------------
if [ "$n" = 0 ]; then
  summary="Nothing found on the deck."; ranked="$TMP/findings.json"
else
  prompt="$(preamble "$PROJECT")

You are the deckhand. $(crew_role deckhand)

--- THIS WALK ---

The harness walked the deck of $REPO with plain commands and found the $n item(s) below$([ "$more" -gt 0 ] && echo " ($more more were cut by the cap)"). Each has an id. Rank them, most important first,
and give each a one-line action. You may not add, merge or drop one: only the ids below count, and anything else you write is thrown away.
$([ -n "$skipped" ] && echo "
Checks that could not run: $skipped")

$(jq -r '.[] | "\(.id) [\(.kind)] \(.where)\n    evidence: \(.evidence)\n    default action: \(.action)"' "$TMP/findings.json" | untrusted "findings quoting the repository's files")

You have read-only tools and the repository is checked out around you at its base branch. Do not open any environment file other than an example.

End your reply with exactly these two lines and nothing after them:
RANKED_JSON: <one-line JSON array of {\"id\":\"<finding id>\",\"action\":\"one line, an imperative sentence\"}, most important first>
SUMMARY: <one line: what is wrong and what is merely untidy>"
  result=$(claude_run "$WT" "$prompt"); rc=$?
  [ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
  [ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" bosun ERROR "the model call failed"; die "bosun run failed"; }
  rk=$(grep -o '^RANKED_JSON: .*' <<<"$result" | tail -1 | sed 's/^RANKED_JSON: //')
  summary=$(grep -o '^SUMMARY: .*' <<<"$result" | tail -1 | sed 's/^SUMMARY: //' | tr -d '\r' | cut -c1-300)
  if ! jq -e 'type == "array" and all(.[]; type == "object" and (.id | type == "string") and ((.action // "") | type == "string"))' <<<"$rk" >/dev/null 2>&1 || [ -z "$summary" ]; then
    record_run "$PROJECT" bosun ERROR "unparseable contract"
    die "contract did not parse — nothing written (see logs/runs/$QUARTERDECK_RUN_ID.json)"
  fi
  # The harness's findings, in the model's order; unknown ids ignored; anything it left out follows; the action is one clean line.
  jq -c --argjson r "$rk" '
    . as $f | ($r | map(select(.id as $i | $f | any(.id == $i))) | unique_by(.id)) as $rank
    | ($rank | map(.id)) as $ids
    | ([$rank[] | .id as $i | ($f[] | select(.id == $i)) + {action: ((.action // "") | gsub("[\r\n\t]+"; " ") | .[0:200])}]
       + [$f[] | select(.id as $i | $ids | index($i) | not)])
    | map(.action = (if (.action // "") == "" then "Look at it." else .action end))' "$TMP/findings.json" > "$TMP/ranked.json" || cp "$TMP/findings.json" "$TMP/ranked.json"
  ranked="$TMP/ranked.json"
fi

# ---- the report (the duty's own state, mode 0600), and only then the one summary issue ----------------------------------------------------------
verdict="DECK CLEAR"; [ "$n" = 0 ] || verdict="DECK $n"
body_for() { # body_for <findings-file>
  echo "## Deck report: $PROJECT, $(date +%Y-%m-%d)"
  echo
  echo "**$verdict.** $summary"
  [ -z "$skipped" ] || { echo; echo "_Checks that could not run: ${skipped}._"; }
  [ "$n" = 0 ] || {
    echo
    echo "| # | kind | where | evidence | suggested action |"
    echo "|---|---|---|---|---|"
    jq -r 'to_entries[] | "| \(.key + 1) | \(.value.kind) | `\(.value.where | gsub("[|`\n]"; " "))` | \(.value.evidence | gsub("[|\n]"; " ")) | \(.value.action | gsub("[|\n]"; " ")) |"' "$1"
  }
  [ "$more" -le 0 ] || { echo; echo "_$more more finding(s) were cut by the cap of $MAX; the next walk will show them._"; }
  echo
  echo "<sub>Quarterdeck bosun. The harness found every item with plain checks; the model only ranked them and wrote the one-line actions. Nothing was deleted, edited or pushed, and nothing will be: every action here is for a person to take.</sub>"
}
( umask 077; body_for "$ranked" > "$REPORT" ); chmod 600 "$REPORT" 2>/dev/null || true
say ""; body_for "$ranked" >&2; say ""
say "quarterdeck: report written to ${REPORT#$QUARTERDECK_HOME/}"
echo "$NOW" > "$STAMP"

if [ "$APPLY" != 1 ]; then
  say "quarterdeck: report only — pass --apply to create or update the one summary issue"
  record_run "$PROJECT" bosun "DRY-RUN" "$verdict — report written, no issue"
  exit 0
fi
existing=$(guard 60 "$GH" issue list -R "$REPO" --state open --limit 100 --json number,title --jq "[.[] | select(.title == \"$TITLE\")] | first | .number // empty" 2>>"$LOG_FILE" || true)
body_for "$ranked" | head -c 60000 > "$TMP/issue-body.md"
if [ -n "$existing" ]; then
  guard 60 "$GH" issue edit "$existing" -R "$REPO" --body-file "$TMP/issue-body.md" >/dev/null 2>>"$LOG_FILE" \
    || { record_run "$PROJECT" bosun ERROR "could not update issue #$existing"; die "could not update the summary issue"; }
  record_run "$PROJECT" bosun DECK "${verdict#DECK } — summary issue #$existing updated" "https://github.com/$REPO/issues/$existing"
elif [ "$n" = 0 ]; then
  record_run "$PROJECT" bosun DECK "CLEAR — no summary issue to update, none created"
else
  url=$(guard 60 "$GH" issue create -R "$REPO" --title "$TITLE" --body-file "$TMP/issue-body.md" 2>>"$LOG_FILE") \
    || { record_run "$PROJECT" bosun ERROR "could not create the summary issue"; die "could not create the summary issue"; }
  record_run "$PROJECT" bosun DECK "${verdict#DECK } — summary issue created" "$url"
fi

exit
}
