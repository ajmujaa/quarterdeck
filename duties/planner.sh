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
#   quarterdeck plan approve <project> <plan-id>
#   quarterdeck plan apply   <project> <plan-id> [--apply]     # lists the moves; --apply makes them
# and then only through the board keeper's own move (bin/board.py to), one card at a time.
#
#   quarterdeck run <p> planner                          # report only: prints the plan, writes nothing
#   quarterdeck run <p> planner --apply                  # writes the document and the plan record
#   quarterdeck run <p> planner --capacity 5             # at most 5 items in the sprint
#   quarterdeck run <p> planner --budget 40 --apply      # at most $40 of expected model cost (needs measured cost)
#
# Contract:
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

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> planner}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/planner-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-test: lib.sh puts the real gh first on PATH
PLAN="$QUARTERDECK_DIR/bin/plan.py"

APPLY=0 CAPACITY="-" BUDGET="-"
while [ $# -gt 0 ]; do
  case "$1" in
    --apply)    APPLY=1 ;;
    --capacity) CAPACITY="${2:-}"; shift; [[ "$CAPACITY" =~ ^[1-9][0-9]*$ ]] || die "planner: --capacity takes a whole number of items" ;;
    --budget)   BUDGET="${2:-}"; shift; [[ "$BUDGET" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "planner: --budget takes dollars, e.g. 40" ;;
    *) die "planner: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1

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

result=$(claude_run "$WORKDIR" "$prompt" "Read,Grep,Glob,Bash(git log*)"); rc=$?
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
say "  read it, then:  quarterdeck plan approve $PROJECT $id"
record_run "$PROJECT" planner PLANNED "$n items, $s in the sprint — plan $id"
exit
}
