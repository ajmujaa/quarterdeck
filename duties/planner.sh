#!/bin/bash
# planner — turn the open backlog into a sprint plan a person reads, and moves nothing.
#
# The sailing master plans the passage. Given the project's open Backlog and Ready issues (with the
# purser's requirements where they exist), the model puts them in an order that respects their
# dependencies, sizes each one S, M or L with a one-sentence reason, says what could run in parallel,
# what needs a decision first, and what to leave out, and proposes which of them fit the capacity the
# owner named. It never writes a cost: the harness prices each item from this project's own finished
# cycle records and fix runs (bin/plan.py), and says "unknown (no measurement yet)" when there are none.
#
# What it writes, and where (only with --apply):
#   * a document, workspace/<project>-plan-<date>.md, in the data folder, not in the repository;
#   * state/plans/<id>.json, the same plan for machines, status "proposed".
# Nothing on the board or in GitHub changes. The cards move only after the owner approves:
#   qtdeck plan approve <project> <plan-id>
#   qtdeck plan apply   <project> <plan-id> [--apply]     # lists the moves; --apply makes them
# and then only through the board keeper's own move (bin/board.py to), one card at a time.
#
#   qtdeck run <p> planner                          # report only: prints the plan, writes nothing
#   qtdeck run <p> planner --apply                  # writes the document and the plan record
#   qtdeck run <p> planner --capacity 5             # at most 5 items in the sprint
#   qtdeck run <p> planner --budget 40 --apply      # at most $40 of expected model cost (needs measured cost)
#
# A second mode drafts TICKETS from a plain request (no board needed; a project with no GitHub repo can use it):
#
#   qtdeck ticket new <p> "build me a page"        # the same as: planner --request "..."  (report only: prints the draft and keeps it as a draft)
#   qtdeck ticket new <p> "..." --apply            # files it: GitHub issues when the project has a repo (foreman's filing, gh_post's credential
#                                                  # scan, a title already on the tracker is skipped), local tickets (state/tickets) when it has none
#   qtdeck ticket new <p> "..." --apply --local    # local tickets even when a repo is set
#   qtdeck ticket file <p> <draft-id> [--apply]    # files a draft kept earlier (planner --file-draft <id>: no model call)
#
# The model reads the project (Read, Grep, Glob, inside the working folder) and gets the request as untrusted data. It writes text; the harness
# checks every field (bin/tickets.py validate_draft) and writes nothing when the reply does not parse. It never gets gh or a credential.
#   TICKETS_JSON: {"tickets":[{"title","body","acceptance":["..."]}]}
#   RESULT: DRAFTED <n> tickets | NOTHING_TO_DRAFT
#
# Contract (the sprint plan):
#   PLAN_JSON: {"plan":[{"issue","size":"S|M|L","reason","depends_on":[],"parallel_ok":bool,
#                        "needs_decision":"" ,"why_now"}],"sprint":[issue...],"left_out":[{"issue","reason"}]}
#   RESULT: PLANNED <n> items | NOTHING_TO_PLAN
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text. The group closes
# on the last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> planner}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/planner-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-test: lib.sh puts the real gh first on PATH
PLAN="$QUARTERDECK_DIR/bin/plan.py"

APPLY=0 CAPACITY="-" BUDGET="-" APPLY_ARG=0 REQUEST="" FILE_DRAFT="" LOCAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --apply)    APPLY=1; APPLY_ARG=1 ;;
    --request)  REQUEST="${2:-}"; shift; [ -n "$REQUEST" ] || die "planner: --request takes the plain request (or - to read it from standard input)" ;;
    --file-draft) FILE_DRAFT="${2:-}"; shift; [[ "$FILE_DRAFT" =~ ^d[1-9][0-9]{0,8}$ ]] || die "planner: --file-draft takes a draft id like d1" ;;
    --local)    LOCAL=1 ;;
    --capacity) CAPACITY="${2:-}"; shift; [[ "$CAPACITY" =~ ^[1-9][0-9]*$ ]] || die "planner: --capacity takes a whole number of items" ;;
    --budget)   BUDGET="${2:-}"; shift; [[ "$BUDGET" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "planner: --budget takes dollars, e.g. 40" ;;
    *) die "planner: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1

# ---- tickets: a plain request becomes one to five drafted tickets; --apply files them ------------------------------------------------------
if [ -n "$REQUEST$FILE_DRAFT" ]; then
  [ -z "$REQUEST" ] || [ -z "$FILE_DRAFT" ] || die "planner: --request and --file-draft are two different jobs"
  [ "$CAPACITY$BUDGET" = "--" ] || die "planner: --capacity and --budget belong to the sprint plan, not to tickets"
  # Writing to GitHub needs the word --apply on this command. A machine default of QUARTERDECK_DRY_RUN=0 does not file tickets by itself.
  APPLY=$APPLY_ARG
  TK="$QUARTERDECK_DIR/bin/tickets.py"
  [ -f "$TK" ] || die "planner: bin/tickets.py is missing"
  acquire_lock "planner-$PROJECT-tickets"
  export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"${REPO:-$PROJECT}")-planner-tickets-$(date +%s)"
  TMP=$(mktemp -d); trap 'rm -rf "$TMP"; rm -rf "$QUARTERDECK_LOCK"' EXIT
  TO_GITHUB=0; [ -n "$REPO" ] && [ "$LOCAL" != 1 ] && TO_GITHUB=1

  _remember() { # called by file_issues for each issue made: <index> <url> <title>
    python3 "$TK" record-filed "$PROJECT" "$DID" "${2##*/}" "$2" "$3" 2>>"$LOG_FILE" || say "  (issue made, but not remembered in the ticket list: $3)"
  }
  file_draft() { # file_draft <draft-id>: lists what would be done, and does it with --apply; sets DID
    DID=$1
    local issues n made firstid
    if [ "$TO_GITHUB" != 1 ]; then
      if [ -z "$REPO" ]; then say "  no GitHub repo: saved as local tickets on this computer"; else say "  --local: saved as local tickets on this computer, not on GitHub"; fi
      if [ "$APPLY" != 1 ]; then
        python3 "$TK" file "$PROJECT" "$DID" >&2
        say "quarterdeck: report only: nothing was filed. Add --apply to save the tickets of draft $DID on this computer."
        record_run "$PROJECT" planner DRAFTED "draft $DID (report only, nothing filed)"
        return 0
      fi
      made=$(python3 "$TK" file "$PROJECT" "$DID" --apply 2>>"$LOG_FILE") || { record_run "$PROJECT" planner ERROR "could not save the local tickets"; die "planner: could not save the local tickets (see $LOG_FILE)"; }
      printf '%s\n' "$made" >&2
      firstid=$(sed -nE 's/^ *ticket ([0-9]+):.*/\1/p' <<<"$made" | head -1)
      record_run "$PROJECT" planner FILED "$(grep -c '^ *ticket ' <<<"$made") local ticket(s) from draft $DID"
      say ""
      say "quarterdeck: saved on this computer only; nothing went to GitHub."
      [ -z "$firstid" ] || say "  next: qtdeck cycle $PROJECT --ticket $firstid"
      return 0
    fi
    # GitHub: a title already on the tracker (any state) is not filed again; what is left goes through the foreman's filing, every post scanned
    local tracker gone
    tracker=$(existing_issues "$REPO" all) || tracker=""
    gone=$(printf '%s\n' "$tracker" | python3 "$TK" dedupe "$PROJECT" "$DID") || die "planner: could not compare the draft with the tracker"
    [ -z "$gone" ] || while IFS= read -r g; do say "  skip: already on the tracker as $g"; done <<<"$gone"
    if ! python3 "$TK" show --json "$PROJECT" "$DID" >/dev/null 2>&1; then
      say "quarterdeck: every ticket of the draft is already on the tracker: nothing to file"
      record_run "$PROJECT" planner NOTHING_TO_DRAFT "draft $DID: every ticket is already on the tracker"
      return 0
    fi
    issues=$(python3 "$TK" issues-json "$PROJECT" "$DID") || die "planner: could not read draft $DID"
    n=$(jq length <<<"$issues")
    say ""
    say "── $REPO, $n issue(s) to file ──"
    jq -r '.[] | "  file: \(.title)"' <<<"$issues" >&2
    if [ "$APPLY" != 1 ]; then
      say ""
      say "quarterdeck: report only: nothing was filed. Add --apply to file $n issue(s) on $REPO."
      record_run "$PROJECT" planner DRAFTED "draft $DID: $n issue(s) would be filed (report only)"
      return 0
    fi
    if ! issues_scan "$issues"; then
      record_run "$PROJECT" planner REFUSED "draft $DID: a ticket looks like it holds a credential; nothing was sent"
      exit 3
    fi
    file_issues "$REPO" "$issues" _remember; local rc=$?
    record_run "$PROJECT" planner FILED "$FILED of $n issue(s) from draft $DID on $REPO"
    say ""
    say "quarterdeck: filed $FILED issue(s) on $REPO"
    [ "$FILED" = 0 ] || say "  next: qtdeck cycle $PROJECT --issue $(jq -r '.[0].number' <<<"$MADE")"
    [ "$rc" = 0 ] || exit "$rc"
    [ "$FILED" = "$n" ] || say "  $((n - FILED)) ticket(s) stay in draft $DID: file them again with  qtdeck ticket file $PROJECT $DID --apply"
    return 0
  }

  if [ -n "$FILE_DRAFT" ]; then
    python3 "$TK" show --json "$PROJECT" "$FILE_DRAFT" >/dev/null || die "planner: there is no draft $FILE_DRAFT for $PROJECT (see: qtdeck ticket list $PROJECT)"
    file_draft "$FILE_DRAFT"
    exit 0
  fi

  if [ "$REQUEST" = - ]; then REQUEST=$(head -c 9000); fi
  printf '%s' "$REQUEST" | python3 "$TK" check-request > "$TMP/request" || die "planner: that request cannot be used (plain text, at most 2000 characters)"
  working_on "drafting tickets"
  say "quarterdeck: planner drafting tickets for $PROJECT"

  gh_titles="(none)"
  if [ "$TO_GITHUB" = 1 ]; then
    t=$(existing_issues "$REPO" open | sed -E 's/ \[[A-Z_]+\]//'); [ -z "$t" ] || gh_titles="$t"
  fi
  prompt="$(preamble "$PROJECT")

$(crew_role purser)

--- WHAT THE OWNER ASKS FOR ---

$(untrusted "the owner's request" < "$TMP/request")

--- WHAT IS KNOWN ABOUT THE PROJECT AND ITS TICKETS ---

$(python3 "$TK" context "$PROJECT" | untrusted "project facts and existing tickets")

$(printf '%s\n' "$gh_titles" | untrusted "open issue titles")

--- YOUR JOB ---

Turn the request into ONE to FIVE tickets. Read the project first (you may read, search and list files here) so each ticket names things that
exist. A ticket is one change that someone could build on one branch and a person could review: smaller is better, and a request that is one
change is one ticket. For each ticket write:
- title: one line, at most 120 characters, saying what will be true when it is done;
- body: what to build and why, in plain sentences, at most 4000 characters;
- acceptance: one to eight checks, each an observable behaviour a person could try (press, type, open, run) and the result they must see.
  A check that only says something exists is not enough on its own.

Do not repeat a ticket already listed above, local or open on the tracker. Plain text only: no HTML comments, no @mentions, no shell commands,
no file paths you have not seen in the project, and nothing that looks like a secret. If the request is not something a ticket can describe, or
it is already covered, say so and stop. That is a real answer.

End your reply with exactly these two lines and nothing after them:
TICKETS_JSON: <one-line JSON {\"tickets\":[{\"title\":\"...\",\"body\":\"...\",\"acceptance\":[\"...\"]}]}>
RESULT: DRAFTED <n> tickets
  or, instead of both lines, the single line
RESULT: NOTHING_TO_DRAFT"

  result=$(claude_run "$WORKDIR" "$prompt" "Read,Grep,Glob"); rc=$?
  case $rc in
    0) : ;;
    2) say "quarterdeck: usage limit reached — nothing written"; exit 0 ;;
    3) say "quarterdeck: stopped at the per-call cap: nothing written"; record_run "$PROJECT" planner ERROR "ticket draft: hit the per-call cap"; exit 1 ;;
    *) record_run "$PROJECT" planner ERROR "ticket draft: the model call failed"; exit 1 ;;
  esac
  [ -n "$result" ] || { record_run "$PROJECT" planner ERROR "ticket draft: empty reply"; exit 1; }
  if grep -q '^RESULT: NOTHING_TO_DRAFT' <<<"$result" && ! grep -q '^TICKETS_JSON: ' <<<"$result"; then
    say "quarterdeck: the planner found nothing to draft from that request"
    record_run "$PROJECT" planner NOTHING_TO_DRAFT "no ticket drafted"
    exit 0
  fi
  json=$(grep -o '^TICKETS_JSON: .*' <<<"$result" | tail -1 | sed 's/^TICKETS_JSON: //')
  if ! grep -q '^RESULT: DRAFTED' <<<"$result" || [ -z "$json" ] \
     || ! printf '%s' "$json" | python3 "$TK" validate > "$TMP/draft.json" 2> "$TMP/why"; then
    log "$PROJECT: ticket draft refused: logs/runs/$QUARTERDECK_RUN_ID.json"
    say "quarterdeck: the planner's reply was refused — nothing written"
    sed 's/^/  /' "$TMP/why" >&2 2>/dev/null
    record_run "$PROJECT" planner ERROR "ticket draft refused: $(head -1 "$TMP/why" 2>/dev/null | sed 's/^ *//' | cut -c1-120)"
    exit 1
  fi
  did=$(python3 "$TK" draft-save "$PROJECT" "$TMP/request" < "$TMP/draft.json" 2>>"$LOG_FILE") \
    || { record_run "$PROJECT" planner ERROR "could not keep the draft"; die "planner: could not keep the draft (see $LOG_FILE)"; }
  python3 "$TK" show --bare "$PROJECT" "$did"
  say ""
  say "  draft $did saved; nothing was filed"
  if [ "$APPLY" != 1 ]; then
    record_run "$PROJECT" planner DRAFTED "draft $did: $(jq '.tickets | length' "$TMP/draft.json") ticket(s) (report only, nothing filed)"
    say "  file it:      qtdeck ticket file $PROJECT $did --apply$([ -z "$REPO" ] || echo ' (or add --local to keep it on this computer)')"
    say "  or change it: ask again with  qtdeck ticket new $PROJECT \"...\"   and remove this one with  qtdeck ticket remove $PROJECT $did"
    exit 0
  fi
  file_draft "$did"
  exit 0
fi

BOARD_NUM=$(project_get "$PROJECT" 'board.number')
BOARD_OWNER=$(project_get "$PROJECT" 'board.owner')
[ -n "$BOARD_NUM" ] && [ -n "$BOARD_OWNER" ] || die "planner: '$PROJECT' has no board in the registry. Add:
  \"board\": { \"number\": <n>, \"owner\": \"<github user or org>\" }"

acquire_lock "planner-$PROJECT"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-planner-$(date +%s)"
working_on "sprint plan for board #$BOARD_NUM"
say "quarterdeck: planner reading $REPO project #$BOARD_NUM"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"; rm -rf "$QUARTERDECK_LOCK"' EXIT
python3 "$QUARTERDECK_DIR/bin/board.py" snapshot "$BOARD_OWNER" "$BOARD_NUM" "$REPO" > "$TMP/snap.json" 2>>"$LOG_FILE" \
  || die "planner: could not read the board (see $LOG_FILE)"
jq -e '.items' "$TMP/snap.json" >/dev/null 2>&1 || die "planner: the board snapshot did not parse"

: > "$TMP/issues.jsonl"
for n in $(python3 "$PLAN" eligible "$TMP/snap.json"); do
  guard 60 "$GH" issue view "$n" -R "$REPO" --json number,title,body,state,labels 2>>"$LOG_FILE" \
    | jq -c 'select(.state == "OPEN")' >> "$TMP/issues.jsonl"
done
if [ ! -s "$TMP/issues.jsonl" ]; then
  say "quarterdeck: nothing to plan — no open issue in Backlog or Ready"
  record_run "$PROJECT" planner NOTHING_TO_PLAN "no open issue in Backlog or Ready"
  exit 0
fi
python3 "$PLAN" context "$TMP/snap.json" "$TMP/issues.jsonl" "$QUARTERDECK_HOME" "$PROJECT" > "$TMP/ctx.json" 2>>"$LOG_FILE" \
  || die "planner: could not build the planning context (see $LOG_FILE)"
if [ "$BUDGET" != "-" ] && [ "$(jq -r .has_cost "$TMP/ctx.json")" != true ]; then
  die "planner: --budget needs measured cost, and no run of this project is measured yet. Use --capacity <n> instead."
fi
n_items=$(jq '.items | length' "$TMP/ctx.json")
say "  $n_items open item(s) in Backlog or Ready; $(jq '.runs | length' "$TMP/ctx.json") measured run(s) to price from"

BOARD_TEXT=$(jq -r .board_text "$TMP/ctx.json")
COST_TEXT=$(jq -r .cost_text "$TMP/ctx.json")
LIMITS="No stated limit: propose the sprint you would stand behind."
[ "$CAPACITY" != "-" ] && LIMITS="The owner's capacity is $CAPACITY item(s): the sprint holds at most that many."
[ "$BUDGET" != "-" ] && LIMITS="$LIMITS The owner's budget is \$$BUDGET of expected model cost; the harness counts the high end of each size's measured range."

prompt="$(preamble "$PROJECT")

$(crew_role sailing-master)

--- THE BACKLOG ---

$(printf '%s\n' "$BOARD_TEXT" | untrusted "board items and issue text")

--- WHAT IS KNOWN ABOUT COST ---

$COST_TEXT

--- YOUR JOB ---

Plan the next sprint from the items above (only items listed with a [column] can be planned).
$LIMITS

For each item you plan: size it S, M or L with ONE sentence that says what decided it, after reading
the code the issue touches; list the issues it depends on (from the issue text or the code, never
invented); say whether it can run alongside the others; say why now; and, if a person must settle
something before it can start (a vague scope, a product choice, a missing answer), write that question
in needs_decision, otherwise an empty string. An item with a needs_decision is never put in the sprint.
Order the plan so every item comes after what it depends on. The sprint is the part of the plan that
fits the stated limit, taken in plan order. Items you do not plan go in left_out with a reason.
Write no dollar figure anywhere: the harness prices the plan from measured runs.

If nothing can usefully be planned, say so and stop. That is a real answer.

End your reply with exactly these two lines and nothing after them:
PLAN_JSON: <one-line JSON {\"plan\":[{\"issue\":12,\"size\":\"S\",\"reason\":\"...\",\"depends_on\":[],\"parallel_ok\":true,\"needs_decision\":\"\",\"why_now\":\"...\"}],\"sprint\":[12],\"left_out\":[{\"issue\":9,\"reason\":\"...\"}]}>
RESULT: PLANNED <n> items
  or, instead of both lines, the single line
RESULT: NOTHING_TO_PLAN"

result=$(claude_run "$WORKDIR" "$prompt" "Read,Grep,Glob"); rc=$?
case $rc in
  0) : ;;
  2) say "quarterdeck: usage limit reached — nothing written"; exit 0 ;;
  3) say "quarterdeck: stopped at the per-call cap — nothing written"; record_run "$PROJECT" planner ERROR "hit the per-call cap"; exit 1 ;;
  *) record_run "$PROJECT" planner ERROR "the model call failed"; exit 1 ;;
esac
[ -n "$result" ] || { record_run "$PROJECT" planner ERROR "empty reply"; exit 1; }

if grep -q '^RESULT: NOTHING_TO_PLAN' <<<"$result" && ! grep -q '^PLAN_JSON: ' <<<"$result"; then
  say "quarterdeck: the planner found nothing worth planning"
  record_run "$PROJECT" planner NOTHING_TO_PLAN "$n_items open item(s), none worth planning"
  exit 0
fi

# Anything else must be a PLANNED with a plan the harness accepts. A reply that fails is a failed run
# that writes nothing; never "probably fine".
json=$(grep -o '^PLAN_JSON: .*' <<<"$result" | tail -1 | sed 's/^PLAN_JSON: //')
if ! grep -q '^RESULT: PLANNED' <<<"$result" || [ -z "$json" ] \
   || ! printf '%s' "$json" | python3 "$PLAN" check "$TMP/ctx.json" "$CAPACITY" "$BUDGET" > "$TMP/plan.json" 2> "$TMP/why"; then
  log "$PROJECT: planner reply refused — logs/runs/$QUARTERDECK_RUN_ID.json"
  say "quarterdeck: the planner's reply was refused — nothing written"
  sed 's/^/  /' "$TMP/why" >&2 2>/dev/null
  record_run "$PROJECT" planner ERROR "plan refused: $(head -1 "$TMP/why" 2>/dev/null | cut -c1-120)"
  exit 1
fi
n=$(jq '.plan | length' "$TMP/plan.json"); s=$(jq '.sprint | length' "$TMP/plan.json")

if [ "$APPLY" != 1 ]; then
  say ""
  python3 "$PLAN" render "$TMP/plan.json" >&2
  say "quarterdeck: report only — $n item(s) planned, $s in the sprint. Pass --apply to write the document and the plan record."
  record_run "$PROJECT" planner PLANNED "$n items, $s in the sprint (report only, nothing written)"
  exit 0
fi

doc=$(python3 "$PLAN" save "$QUARTERDECK_HOME" "$TMP/plan.json" 2>>"$LOG_FILE") \
  || { record_run "$PROJECT" planner ERROR "could not write the plan"; die "planner: could not write the plan (see $LOG_FILE)"; }
id=$(jq -r .id "$TMP/plan.json")
say "  plan $id written to $(basename "$doc")"
say "  read it, then:  qtdeck plan approve $PROJECT $id"
record_run "$PROJECT" planner PLANNED "$n items, $s in the sprint — plan $id"
exit
}
