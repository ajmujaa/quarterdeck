#!/bin/bash
# harbourmaster — keep the project board honest about what is actually happening.
#
# The harbourmaster controls what moves in and out of the port. This duty does
# the same for a GitHub project board, in two phases that are deliberately
# different in kind:
#
#   1. RECONCILE, with no model at all. A closed issue belongs in Done; an issue
#      with an open pull request belongs in review; an open issue missing from
#      the board belongs on it. These are facts GitHub already knows, and paying
#      a model to restate them would be slower, dearer and less reliable than
#      three lines of jq.
#   2. JUDGE, with the model. Which backlog items are actually ready to start,
#      what has stalled, whether too much is in progress at once, which tickets
#      nobody could pick up cold. None of that is computable.
#
# Column names are not hardcoded: they come from the project's board.status map
# in the registry, falling back to matching the board's own option names. A
# board with different columns works without touching this file.
#
#   quarterdeck run <p> harbourmaster            # report the drift
#   quarterdeck run <p> harbourmaster --apply    # move things
#   quarterdeck run <p> harbourmaster --sync-only --apply   # facts only, no model
#
# Contract:
#   MOVES_JSON: [{"item_id","number","to","why"}]
#   NOTES_JSON: [{"number","note"}]
#   RESULT: BOARD <moves> move(s), <notes> note(s) | CLEAN
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> harbourmaster}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/harbourmaster-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)

APPLY=0 SYNC_ONLY=0
CEILING="${QUARTERDECK_BOARD_MAX:-25}"
while [ $# -gt 0 ]; do
  case "$1" in
    --apply)     APPLY=1 ;;
    --sync-only) SYNC_ONLY=1 ;;
    --max)       CEILING="${2:-25}"; shift ;;
    *) die "harbourmaster: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1

BOARD_NUM=$(project_get "$PROJECT" 'board.number')
BOARD_OWNER=$(project_get "$PROJECT" 'board.owner')
[ -n "$BOARD_NUM" ] && [ -n "$BOARD_OWNER" ] || die "harbourmaster: '$PROJECT' has no board in the registry. Add:
  \"board\": { \"number\": <n>, \"owner\": \"<github user or org>\" }"

acquire_lock "harbourmaster-$PROJECT"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-board-$(date +%s)"
working_on "board #$BOARD_NUM"
say "quarterdeck: harbourmaster reading $REPO project #$BOARD_NUM"

SNAP=$(mktemp); trap 'rm -f "$SNAP"' EXIT
NOTES_DOC="$QUARTERDECK_HOME/workspace/${PROJECT}-board-$(date +%Y-%m-%d).md"
python3 "$QUARTERDECK_DIR/bin/board.py" snapshot "$BOARD_OWNER" "$BOARD_NUM" "$REPO" > "$SNAP" 2>>"$LOG_FILE" \
  || die "could not read the board (see $LOG_FILE)"
jq -e '.items' "$SNAP" >/dev/null 2>&1 || die "the board snapshot did not parse"

# ---- what each column is called on THIS board --------------------------------
# The registry may name them; otherwise match the board's own options. A column
# that cannot be identified disables the rules that need it rather than guessing.
column() { # column <meaning> <fallback-pattern>
  local named; named=$(project_get "$PROJECT" "board.status.$1")
  if [ -n "$named" ]; then printf '%s' "$named"; return; fi
  jq -r --arg re "$2" '[.fields[] | select(.name == "Status") | .options[].name]
                       | map(select(test($re; "i"))) | first // empty' "$SNAP"
}
C_DONE=$(column done '^done|complete|shipped')
C_REVIEW=$(column review 'review')
C_TODO=$(column todo '^backlog|^todo|^triage')
C_DOING=$(column doing 'progress|doing')
say "  columns: done='${C_DONE:-?}' review='${C_REVIEW:-?}' todo='${C_TODO:-?}' doing='${C_DOING:-?}'"

# ---- phase 1: the facts, no model --------------------------------------------
FACTS=$(jq -c --arg done "$C_DONE" --arg review "$C_REVIEW" --arg todo "$C_TODO" '
  [ .items[]
    | select(.number != null and .item_id != null)
    | if   ($done   != "" and .state == "CLOSED" and .status != $done)
      then {item_id, number, from: .status, to: $done,  why: "the issue is closed"}
      elif ($todo   != "" and .state == "OPEN"   and .status == $done)
      then {item_id, number, from: .status, to: $todo,  why: "marked done but the issue is open again"}
      elif ($review != "" and .state == "OPEN"   and (.open_prs | length) > 0 and .status != $review)
      then {item_id, number, from: .status, to: $review,
            why: ("open pull request " + ([.open_prs[].number | "#" + tostring] | join(", ")))}
      else empty end ]' "$SNAP")
ADDS=$(jq -c '[.missing_from_board[] | {number, title, url}]' "$SNAP")
# A reconciliation that fails to compute must not read as "nothing to do": that
# is the difference between a clean board and a broken query.
jq -e 'type == "array"' <<<"$FACTS" >/dev/null 2>&1 && jq -e 'type == "array"' <<<"$ADDS" >/dev/null 2>&1 \
  || { record_run "$PROJECT" harbourmaster ERROR "could not reconcile the board"; die "the reconciliation did not compute — nothing changed"; }
n_facts=$(jq length <<<"$FACTS"); n_adds=$(jq length <<<"$ADDS")

say ""
if [ "$n_facts" = 0 ] && [ "$n_adds" = 0 ]; then
  say "  the board already agrees with the repository"
else
  jq -r '.[] | "  #\(.number)  \(.from // "—") → \(.to)   (\(.why))"' <<<"$FACTS" >&2
  jq -r '.[] | "  #\(.number)  not on the board — \(.title[0:70])"' <<<"$ADDS" >&2
fi

# ---- phase 2: the judgement --------------------------------------------------
MOVES='[]' NOTES='[]'
if [ "$SYNC_ONLY" = 0 ]; then
  say ""
  say "  — asking the harbourmaster what the facts cannot settle"
  BOARD_TEXT=$(python3 "$QUARTERDECK_DIR/bin/board.py" text "$BOARD_OWNER" "$BOARD_NUM" "$REPO" 2>>"$LOG_FILE")
  STATUSES=$(jq -r '[.fields[] | select(.name == "Status") | .options[].name] | join(" | ")' "$SNAP")

  prompt="$(preamble "$PROJECT")

$(crew_role harbourmaster)

--- THIS BOARD ---

$(printf '%s\n' "$BOARD_TEXT" | untrusted "board items")

--- ALREADY HANDLED, DO NOT REPEAT ---

The harness has already worked out every move that follows from the repository
state, and will make these itself:
$(jq -r 'if length == 0 then "  (none — the board matches the repository)" else (.[] | "  #\(.number): \(.from // "—") → \(.to), because \(.why)") end' <<<"$FACTS")
$(jq -r 'if length == 0 then "" else (.[] | "  #\(.number) will be added to the board") end' <<<"$ADDS")

--- YOUR JOB ---

Everything above is settled. Your job is the part that needs judgement:

- Which items should move for a reason the repository cannot show? A backlog
  item that is well-formed and unblocked and should be ready to start; an item
  started so long ago it should go back; a column that flatters reality.
- What is stalled, and which of finish / put back / close it needs.
- Is too much in progress at once for one person?
- Which items could nobody pick up cold — no acceptance criteria, or three
  pieces of work in one ticket?

Read the repository to check anything you are unsure of. Propose at most
${QUARTERDECK_MAX_ITEMS:-5} moves: this is a shared board and a wrong move costs
someone their place. Columns available: $STATUSES.

A note is worth more than a move where you are not certain. If the board is in
good shape, say so and move nothing — that is a real answer.

End your reply with exactly these three lines and nothing after them:
MOVES_JSON: <one-line JSON array of {\"item_id\":\"the PVTI_... id\",\"number\":<issue number>,\"to\":\"a column name from the list above\",\"why\":\"one sentence\"}>
NOTES_JSON: <one-line JSON array of {\"number\":<issue number or 0 for the board as a whole>,\"note\":\"what someone should do about it\"}>
RESULT: BOARD <moves> move(s), <notes> note(s)
  or
RESULT: CLEAN"

  result=$(claude_run "$WORKDIR" "$prompt"); rc=$?
  if [ $rc = 2 ]; then
    say "quarterdeck: usage limit reached — applying the facts only"
  elif [ $rc != 0 ] || [ -z "$result" ]; then
    say "quarterdeck: the judgement pass failed — applying the facts only"
    log "$PROJECT: harbourmaster model call failed"
  else
    m=$(grep -o 'MOVES_JSON: .*' <<<"$result" | tail -1 | sed 's/^MOVES_JSON: //')
    n=$(grep -o 'NOTES_JSON: .*' <<<"$result" | tail -1 | sed 's/^NOTES_JSON: //')
    jq -e 'type == "array"' <<<"$m" >/dev/null 2>&1 && MOVES="$m"
    jq -e 'type == "array"' <<<"$n" >/dev/null 2>&1 && NOTES="$n"
    if [ "$MOVES" = '[]' ] && [ "$NOTES" = '[]' ] && ! grep -q '^RESULT: CLEAN' <<<"$result"; then
      log "$PROJECT: harbourmaster contract did not parse — logs/runs/$QUARTERDECK_RUN_ID.json"
      say "  the judgement contract did not parse — applying the facts only"
    fi
    # A proposed column that does not exist on this board is dropped, not
    # invented: the model names columns, the board owns them.
    MOVES=$(jq -c --argjson valid "$(jq -c '[.fields[] | select(.name=="Status") | .options[].name]' "$SNAP")" \
              --argjson cap "${QUARTERDECK_MAX_ITEMS:-5}" \
              '[.[] | select(.to as $t | $valid | index($t))] | .[0:$cap]' <<<"$MOVES")
  fi
  say ""
  jq -r '.[] | "  #\(.number)  → \(.to)   (\(.why))"' <<<"$MOVES" >&2
  jq -r '.[] | "  note \(if .number == 0 then "(board)" else "#" + (.number|tostring) end): \(.note)"' <<<"$NOTES" >&2
fi

ALL_MOVES=$(jq -c -s 'add' <(printf '%s' "$FACTS") <(printf '%s' "$MOVES"))
n_moves=$(jq length <<<"$ALL_MOVES")
n_notes=$(jq length <<<"$NOTES")

# ---- apply --------------------------------------------------------------------
if [ "$APPLY" = 0 ]; then
  say ""
  say "quarterdeck: report only — $n_moves move(s), $n_adds addition(s), $n_notes note(s)"
  say "  pass --apply to move things on the board; notes are written either way"
  record_run "$PROJECT" harbourmaster "DRY-RUN" "$n_moves move(s), $n_adds add(s), $n_notes note(s) on board #$BOARD_NUM"
  exit 0
fi

applied=0 failed=0
while read -r line; do
  [ -n "$line" ] || continue
  id=$(jq -r .item_id <<<"$line"); to=$(jq -r .to <<<"$line"); num=$(jq -r .number <<<"$line")
  if [ "$applied" -ge "$CEILING" ]; then
    say "  ceiling of $CEILING reached — run again for the rest"; break
  fi
  if guard 60 python3 "$QUARTERDECK_DIR/bin/board.py" move "$BOARD_OWNER" "$BOARD_NUM" "$id" Status "$to" >/dev/null 2>>"$LOG_FILE"; then
    applied=$((applied + 1)); say "  #$num → $to"
  else
    failed=$((failed + 1)); log "$PROJECT: could not move #$num to $to"
  fi
done < <(jq -c '.[]' <<<"$ALL_MOVES")

added=0
while read -r line; do
  [ -n "$line" ] || continue
  url=$(jq -r .url <<<"$line"); num=$(jq -r .number <<<"$line")
  if guard 60 python3 "$QUARTERDECK_DIR/bin/board.py" add "$BOARD_OWNER" "$BOARD_NUM" "$url" >/dev/null 2>>"$LOG_FILE"; then
    added=$((added + 1)); say "  #$num added to the board"
  else
    log "$PROJECT: could not add #$num"
  fi
done < <(jq -c '.[]' <<<"$ADDS")

# Notes stay on this machine. They are model prose, and model prose posted to
# GitHub is how a guardrail gets broken by accident: the first real run of this
# duty proposed a note quoting a price from the project's own memory, which this
# project's rules forbid putting in an issue. So the only thing this duty writes
# to GitHub is a column change it computed from GitHub's own data. Everything a
# model said goes in a document, and a human decides what to do with it.
noted=0
if [ "$n_notes" -gt 0 ]; then
  {
    echo "# ${PROJECT} — board notes, $(date +%Y-%m-%d)"
    echo
    echo "From the harbourmaster on project board #$BOARD_NUM, after $applied move(s)."
    echo "These are judgements, not facts, and nothing here was posted anywhere."
    echo
    jq -r '.[] | "## " + (if .number == 0 then "The board itself" else "#" + (.number|tostring) end) + "\n\n" + .note + "\n"' <<<"$NOTES"
  } > "$NOTES_DOC"
  noted=$n_notes
  say "  $noted note(s) written to $(basename "$NOTES_DOC")"
fi

say ""
say "quarterdeck: $applied move(s), $added addition(s), $noted note(s) on board #$BOARD_NUM"
[ "$failed" -gt 0 ] && say "  $failed move(s) failed — see $LOG_FILE"
record_run "$PROJECT" harbourmaster "SYNCED" "$applied move(s), $added add(s), $noted note(s)" \
  "https://github.com/users/$BOARD_OWNER/projects/$BOARD_NUM"

exit
}
