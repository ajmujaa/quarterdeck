#!/bin/bash
# panel — put several crew members on the same question and make them disagree.
#
# One duty, any discipline. The roster comes from crew/*.md (discipline: design
# | dev | spec | qa), so adding a fourth developer or a third UI reviewer is a
# markdown file, never a change to this script.
#
# Round 1 each seat works alone, in parallel. Round 2 each seat reads what the
# others found and agrees, disputes or extends it. Then the dockmaster rules —
# resolving conflicts, merging duplicates, dropping what nobody could point at.
# The ruling is a document; the argument that produced it is kept in
# state/panels/ so the dashboard can show who was overruled and why.
#
#   quarterdeck run <p> panel --panel design [--target src/screens]
#   quarterdeck run <p> panel --panel dev    --issue 204
#   quarterdeck run <p> panel --panel spec   --idea "let people split a bill"
#
# Contract (per seat, then the chair):
#   ITEMS_JSON:   [{"area","severity","title","claim","where","why","action"}]
#   RESULT: ITEMS <n>
#   STANCES_JSON: [{"id","stance":"agree|dispute|extend","note"}]
#   RESULT: STANCES <n>
#   RULING_JSON:  [{"area","severity","title","claim","where","why","action",
#                   "support":[],"overruled":[],"note"}]
#   RESULT: RULED <n>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> panel --panel design}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/panel-$PROJECT.log"
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-tests and for a stand-in; lib.sh puts the real gh first on PATH

PANEL="" TARGET="" ISSUE="" IDEA="" FROM="" SEATS="" BRIEF_EXTRA="" RESUME=""
ROUNDS="${QUARTERDECK_PANEL_ROUNDS:-2}"
PER_SEAT="${QUARTERDECK_PANEL_MAX:-10}"
while [ $# -gt 0 ]; do
  case "$1" in
    --panel)  PANEL="${2:-}"; shift ;;
    --target|--path) TARGET="${2:-}"; shift ;;
    --issue)  ISSUE="${2:-}"; shift ;;
    --idea|--question) IDEA="${2:-}"; shift ;;
    --from)   FROM="${2:-}"; shift ;;
    --seats)  SEATS="$(tr ',' ' ' <<<"${2:-}")"; shift ;;
    --brief)  BRIEF_EXTRA="${2:-}"; shift ;;
    --rounds) ROUNDS="${2:-2}"; shift ;;
    --resume) RESUME="${2:-}"; shift ;;
    --apply)  : ;;  # accepted and ignored: a panel only ever writes a document
    *) die "panel: unknown argument '$1'" ;;
  esac
  shift
done
# --resume <panel-id>: a panel whose seats all argued but whose ruling never
# happened (a usage limit, a broken prompt) is ruled from its transcript. The
# seats' work was paid for; only the chair runs again.
if [ -n "$RESUME" ]; then
  [[ "$RESUME" =~ ^[A-Za-z0-9._-]+$ ]] || die "panel: --resume takes a panel id"
  RTX="$QUARTERDECK_HOME/state/panels/$RESUME.json"
  [ -f "$RTX" ] || die "panel: no panel called $RESUME"
  [ "$(jq -r .project "$RTX")" = "$PROJECT" ] || die "panel: $RESUME belongs to another project"
  [ "$(jq '(.items | length) > 0 and (.ruling | length) == 0' "$RTX")" = true ] \
    || die "panel: $RESUME has nothing to resume (no argument, or already ruled)"
  PANEL="$(jq -r .discipline "$RTX")"; TARGET="$(jq -r .subject "$RTX")"
  SEATS="$(jq -r '[.seats[].name] | join(" ")' "$RTX")"
  case "$(jq -r .mode "$RTX")" in
    findings) ;;
    plan) ISSUE="${TARGET#issue #}" ;;
    *) die "panel: only a findings or plan panel can be resumed" ;;
  esac
fi
[ -n "$PANEL" ] || die "panel: which panel? --panel design|dev|spec|qa"

# A panel's discipline decides what it produces. Three shapes cover the
# lifecycle: findings on something that exists, a plan for something about to be
# built, a specification for something not yet decided.
# A decision panel exists for hard-to-reverse calls, which the fleet's model
# policy puts on Opus at xhigh — every seat, whatever it runs on elsewhere.
# A caller that already chose (a fix routing by tier) keeps its choice.
if [ "$PANEL" = decision ] && [ -z "${QUARTERDECK_MODEL_OVERRIDE:-}" ]; then
  export QUARTERDECK_MODEL_OVERRIDE="${QUARTERDECK_TIER_HARD:-default}" QUARTERDECK_EFFORT_OVERRIDE=xhigh
fi

case "$PANEL" in
  design)    MODE=findings ;;
  dev)       MODE=plan ;;
  spec)      MODE=spec ;;
  backlog)   MODE=backlog ;;
  decision)  MODE=decision ;;
  *)         MODE=findings ;;
esac

[ -n "$SEATS" ] || SEATS="$(crew_by_discipline "$PANEL" | tr '\n' ' ')"
SEATS="$(xargs <<<"$SEATS")"
[ -n "$SEATS" ] || die "panel: no crew for '$PANEL' (see: quarterdeck crew)"
set -- $SEATS
[ $# -ge 2 ] || die "panel: '$PANEL' has only $# seat(s); a panel of one is just a duty"
crew_exists dockmaster || die "panel: crew/dockmaster.md is missing — nobody can rule"

# Keyed by the issue when planning one (two fixes on the same project, on
# different issues, can each have their own dev panel running); otherwise by
# discipline, so two design panels don't overlap but a design panel and
# someone's dev panel do not block each other either. A dev panel's plan file
# is named after $ISSUE, so this also happens to be exactly the scope in which
# two writers really would collide.
acquire_lock "panel-$PROJECT-${ISSUE:-$PANEL}"
STAMP="$(date +%Y-%m-%d)"
PANEL_ID="${RESUME:-${PROJECT}-${PANEL}-$(date +%s)}"
TX="$QUARTERDECK_HOME/state/panels/$PANEL_ID.json"
mkdir -p "$QUARTERDECK_HOME/state/panels"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# ---- what the panel is looking at -------------------------------------------
# The harness gathers the target itself rather than trusting each seat to fetch
# it: three seats reading three different versions of an issue is not a panel.
REPO="$(project_get "$PROJECT" repo)"
case "$MODE" in
  plan)
    [ -n "$ISSUE" ] || die "panel --panel dev: which issue? --issue <number>"
    BRIEF="$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json number,title,body,labels \
             --template '#{{.number}} {{.title}}{{"\n\n"}}{{.body}}' 2>/dev/null)" \
      || die "panel: could not read issue #$ISSUE in $REPO"
    SUBJECT="issue #$ISSUE"
    OUT="$QUARTERDECK_HOME/workspace/${PROJECT}-plan-${ISSUE}.md"
    ;;
  decision)
    if [ -n "$FROM" ]; then
      [ -f "$FROM" ] || die "panel: no such file: $FROM"
      BRIEF="$(cat "$FROM")"; SUBJECT="$(head -1 "$FROM" | sed 's/^#* *//')"
    else
      [ -n "$IDEA" ] || die "panel --panel decision: --question \"should we ...\" or --from <file>"
      BRIEF="$IDEA"; SUBJECT="$IDEA"
    fi
    slug="$(tr '[:upper:] ' '[:lower:]-' <<<"${SUBJECT:0:44}" | tr -cd 'a-z0-9-' | sed 's/-*$//')"
    [ "${#SUBJECT}" -gt 44 ] && slug="${slug%-*}"
    OUT="$QUARTERDECK_HOME/workspace/${PROJECT}-decision-${slug:-$STAMP}.md"
    ;;
  spec)
    if [ -n "$FROM" ]; then
      [ -f "$FROM" ] || die "panel: no such file: $FROM"
      BRIEF="$(cat "$FROM")"; SUBJECT="$(basename "$FROM")"
    else
      [ -n "$IDEA" ] || die "panel --panel spec: --idea \"...\" or --from <file>"
      BRIEF="$IDEA"; SUBJECT="$IDEA"
    fi
    # Cut to whole words: a filename ending "...expense-betwee" is one you
    # retype wrong when you hand it to the foreman.
    slug="$(tr '[:upper:] ' '[:lower:]-' <<<"${SUBJECT:0:44}" | tr -cd 'a-z0-9-' | sed 's/-*$//')"
    [ "${#SUBJECT}" -gt 44 ] && slug="${slug%-*}"
    OUT="$QUARTERDECK_HOME/workspace/${PROJECT}-spec-${slug:-$STAMP}.md"
    ;;
  backlog)
    # The seats must argue about the same list, so the harness fetches it once.
    # The board if the project has one, the open issues either way.
    board_num=$(project_get "$PROJECT" 'board.number')
    board_owner=$(project_get "$PROJECT" 'board.owner')
    if [ -n "$board_num" ] && [ -n "$board_owner" ]; then
      BRIEF="$(python3 "$QUARTERDECK_DIR/bin/board.py" text "$board_owner" "$board_num" "$REPO" 2>>"$LOG_FILE")"
    fi
    issues="$(guard 90 "$GH" issue list -R "$REPO" --state open --limit 60 \
              --json number,title,labels,updatedAt,comments \
              --template '{{range .}}#{{.number}} {{.title}} ({{len .comments}} comment(s), updated {{timeago .updatedAt}}){{"\n"}}{{end}}' 2>>"$LOG_FILE")"
    BRIEF="${BRIEF:+$BRIEF

}OPEN ISSUES
${issues:-(none)}"
    SUBJECT="${TARGET:-what to do next}"
    OUT="$QUARTERDECK_HOME/workspace/${PROJECT}-backlog-${STAMP}.md"
    ;;
  *)
    BRIEF=""
    SUBJECT="${TARGET:-the whole interface}"
    OUT="$QUARTERDECK_HOME/workspace/${PROJECT}-panel-${PANEL}-${STAMP}.md"
    ;;
esac

tx() { local t; t="$(mktemp)"; jq "$@" "$TX" > "$t" && mv "$t" "$TX"; }
if [ -z "$RESUME" ]; then   # rounds 1 and 2; a resumed panel reloads them instead
# The transcript exists from the first second, not at the end: a panel that is
# still arguing is exactly what the dashboard most wants to show.
jq -n --arg id "$PANEL_ID" --arg p "$PROJECT" --arg d "$PANEL" --arg m "$MODE" \
      --arg s "$SUBJECT" --arg at "$(date -u +%FT%TZ)" --argjson r "$ROUNDS" \
      --args '{id:$id, project:$p, discipline:$d, mode:$m, subject:$s, started:$at,
               rounds:$r, phase:"round 1", status:"running",
               seats:($ARGS.positional|map({name:., items:null, ok:null})),
               items:[], stances:[], ruling:[], doc:null, verdict:null}' \
      $SEATS > "$TX"

working_on "$PANEL panel: $SUBJECT"
say "quarterdeck: $PANEL panel on $SUBJECT — $# seats: $SEATS"

# ---- the brief every seat gets ----------------------------------------------
case "$MODE" in
  findings) ASK="Inspect what this project already has and report what is wrong with it${TARGET:+, restricted to: $TARGET}.
You cannot run the app, so judge what the code necessarily produces, and say
plainly when something needs a device to confirm rather than asserting it." ;;
  plan)     ASK="Decide how this issue should be implemented. Do not write the code —
argue the approach. Read enough of the codebase to be concrete about which
files and which existing helpers are involved.

THE ISSUE
$(printf '%s\n' "$BRIEF" | untrusted "issue text")" ;;
  backlog)  ASK="Decide what this project should do next, and say what it is not doing.

You are not inventing work: rank what already exists, merge what is duplicated,
and name what should be closed. Read the codebase when you need to know whether
something is already built, already half-built, or no longer applies.

THE BOARD AND THE OPEN ISSUES
$(printf '%s\n' "$BRIEF" | untrusted "board items and open issue titles")" ;;
  decision)  ASK="Settle this question, and leave a record someone can act on and argue
with in a year.

THE QUESTION
$(printf '%s\n' "$BRIEF" | untrusted "question")

Read the codebase before you take a position — what already exists constrains
this more than any principle does. Name the options that were actually on the
table, including doing nothing, and say what each costs. Then take one.

The two things that matter most, and that people skip:
- Which parts of this are expensive to reverse. Spend the argument there.
- What would have to become true for this decision to be wrong. If you cannot
  name that, you have stated a preference and called it a decision." ;;
  spec)     ASK="Turn this into something that could be built. It is a rough note, not a
specification. Read the codebase to know what already exists before proposing
anything, and say when the note conflicts with what is there.

THE NOTE
$(printf '%s\n' "$BRIEF" | untrusted "note")" ;;
esac

# "What is the question" is not specific to a discipline, so it lands in every
# mode's brief rather than being another flag each mode has to know about.
if [ -n "$BRIEF_EXTRA" ]; then
  ASK="$ASK

WHAT PROMPTED THIS REVIEW
$BRIEF_EXTRA

That is the complaint, not your conclusion. Check whether it holds before you
agree with it, and say so plainly if you think it is wrong."
fi

case "$MODE" in
  decision) ITEM_AREAS='decision | option rejected | consequence | risk | reversibility' ;;
  *)        ITEM_AREAS='<one or two words: the category this falls in>' ;;
esac
ITEM_SHAPE='{"area":"'"$ITEM_AREAS"'","severity":"critical|major|minor","title":"one short claim","claim":"what is true, in one or two sentences","where":"file:line, or file, or the part of the journey","why":"what it costs and to whom","action":"the concrete change you propose"}'

# ---- round 1: every seat alone, at the same time -----------------------------
for seat in $SEATS; do
  (
    export QUARTERDECK_RUN_ID="${PANEL_ID}-r1-$seat"
    m="$(crew_meta "$seat" model)"; [ -n "$m" ] && export QUARTERDECK_MODEL_PERSONA="$m"
    e="$(crew_meta "$seat" effort)"; [ -n "$e" ] && export QUARTERDECK_EFFORT_PERSONA="$e"
    p="$(preamble "$PROJECT")

You are the ${seat} on a $PANEL panel. Your seat: $(crew_meta "$seat" seat).

$(crew_role "$seat")

--- THIS PANEL ---

$ASK

Other seats are looking at the same thing from their own angle right now. Do not
try to cover their ground or soften your position to fit theirs — you will each
read the others' findings in the next round and argue it out there. Bring at
most $PER_SEAT items, fewer if that is the honest number.

End your reply with exactly these two lines and nothing after them:
ITEMS_JSON: <one-line JSON array of $ITEM_SHAPE>
RESULT: ITEMS <count>"
    out="$(claude_run "$WORKDIR" "$p")"; rc=$?
    printf '%s' "$out" > "$TMP/r1.$seat.txt"; echo "$rc" > "$TMP/r1.$seat.rc"
  ) &
done
wait

# Parse what came back. A seat that failed or spoke gibberish is dropped with a
# note rather than failing the panel: two seats that argued is still a panel,
# and silently pretending a seat attended is how a transcript starts lying.
: > "$TMP/items.json"; echo '[]' > "$TMP/items.json"
present=""; absent=""
for seat in $SEATS; do
  rc="$(cat "$TMP/r1.$seat.rc" 2>/dev/null || echo 1)"
  raw="$(grep -o 'ITEMS_JSON: .*' "$TMP/r1.$seat.txt" 2>/dev/null | tail -1 | sed 's/^ITEMS_JSON: //')"
  if [ "$rc" = 0 ] && jq -e 'type == "array"' <<<"$raw" >/dev/null 2>&1; then
    n="$(jq 'length' <<<"$raw")"
    jq --arg s "$seat" --argjson prev "$(cat "$TMP/items.json")" \
       '[$prev[], (. | to_entries | map(.value + {id: ($s + "-" + ((.key+1)|tostring)), seat: $s}))[]]' \
       <<<"$raw" > "$TMP/items.next" && mv "$TMP/items.next" "$TMP/items.json"
    present="$present $seat"
    tx --arg s "$seat" --argjson n "$n" '.seats |= map(if .name == $s then .items = $n | .ok = true else . end)'
    say "  $seat — $n item(s)"
  else
    absent="$absent $seat"
    tx --arg s "$seat" '.seats |= map(if .name == $s then .items = 0 | .ok = false else . end)'
    [ "$rc" = 2 ] && say "  $seat — usage limit, seat empty" || say "  $seat — no usable answer (logs/runs/${PANEL_ID}-r1-$seat.json)"
  fi
done
present="$(xargs <<<"$present")"; absent="$(xargs <<<"$absent")"
[ -n "$present" ] || { tx '.status="failed" | .verdict="no seat answered"'; record_run "$PROJECT" panel ERROR "$PANEL: no seat answered"; die "panel: no seat answered — nothing written"; }
set -- $present
[ $# -ge 2 ] || { tx '.status="failed" | .verdict="only one seat answered"'; record_run "$PROJECT" panel ERROR "$PANEL: only one seat answered"; die "panel: only one seat answered — that is a duty, not a panel"; }

ITEMS="$(cat "$TMP/items.json")"
TOTAL="$(jq 'length' <<<"$ITEMS")"
tx --argjson i "$ITEMS" '.items = $i'
[ "$TOTAL" = 0 ] && {
  tx --arg at "$(date -u +%FT%TZ)" '.status="done" | .phase="closed" | .finished=$at | .verdict="clean"'
  say "quarterdeck: the $PANEL panel found nothing"
  record_run "$PROJECT" panel CLEAN "$PANEL: nothing found on $SUBJECT"; exit 0; }

# ---- round 2: the seats read each other -------------------------------------
STANCES='[]'
if [ "$ROUNDS" -ge 2 ] && [ "$TOTAL" -gt 1 ]; then
  tx '.phase = "round 2"'
  say "  — round 2: $TOTAL item(s) go back to the floor"
  BOARD="$(jq -r '.[] | "[\(.id)] (\(.seat), \(.severity)) \(.title)\n    \(.claim)\n    where: \(.where)\n    proposes: \(.action)"' <<<"$ITEMS")"
  for seat in $present; do
    (
      export QUARTERDECK_RUN_ID="${PANEL_ID}-r2-$seat"
      m="$(crew_meta "$seat" model)"; [ -n "$m" ] && export QUARTERDECK_MODEL_PERSONA="$m"
    e="$(crew_meta "$seat" effort)"; [ -n "$e" ] && export QUARTERDECK_EFFORT_PERSONA="$e"
      p="$(preamble "$PROJECT")

You are the ${seat} on a $PANEL panel, and the panel has reported back. Your
seat: $(crew_meta "$seat" seat).

$(crew_role "$seat")

--- WHAT THE PANEL BROUGHT BACK ---

$(printf '%s\n' "$BOARD" | untrusted "seat findings")

--- YOUR JOB NOW ---

Go through the items from the OTHER seats. Skip your own ($seat-*) unless you
now think you were wrong, in which case say so — conceding is a result.

For each one you have something to say about:
- agree   — you checked and it holds. Add evidence if you have some they missed.
- dispute — you checked and it does not hold, or it holds but the proposed
            action is wrong. Say what you actually found, with a file, and what
            should happen instead. This is the valuable one; use it when it is
            true rather than being agreeable.
- extend  — it holds but it is bigger, or smaller, or has a consequence they did
            not follow. Say the part they missed.

Verify before you take a position: open the file, read the code path. A stance
you cannot defend with something you actually looked at is worse than silence.
Stay silent on items outside your seat's competence — the dockmaster is reading
this to resolve conflicts, not to count votes.

End your reply with exactly these two lines and nothing after them:
STANCES_JSON: <one-line JSON array of {\"id\":\"the item id\",\"stance\":\"agree|dispute|extend\",\"note\":\"one or two sentences, with a file where you have one\"}>
RESULT: STANCES <count>"
      out="$(claude_run "$WORKDIR" "$p")"; rc=$?
      printf '%s' "$out" > "$TMP/r2.$seat.txt"; echo "$rc" > "$TMP/r2.$seat.rc"
    ) &
  done
  wait
  for seat in $present; do
    rc="$(cat "$TMP/r2.$seat.rc" 2>/dev/null || echo 1)"
    raw="$(grep -o 'STANCES_JSON: .*' "$TMP/r2.$seat.txt" 2>/dev/null | tail -1 | sed 's/^STANCES_JSON: //')"
    if [ "$rc" = 0 ] && jq -e 'type == "array"' <<<"$raw" >/dev/null 2>&1; then
      STANCES="$(jq --arg s "$seat" --argjson prev "$STANCES" '[$prev[], (map(. + {by: $s}))[]]' <<<"$raw")"
      say "  $seat — $(jq 'length' <<<"$raw") stance(s)"
    else
      say "  $seat — no usable stances"
    fi
  done
  tx --argjson s "$STANCES" '.stances = $s'
fi

else
  ITEMS="$(jq -c .items "$TX")"; STANCES="$(jq -c '.stances // []' "$TX")"
  TOTAL="$(jq 'length' <<<"$ITEMS")"
  present="$(jq -r '[.seats[] | select(.ok == true) | .name] | join(" ")' "$TX")"
  absent="$(jq -r '[.seats[] | select(.ok != true) | .name] | join(" ")' "$TX")"
  tx '.status = "running" | .verdict = null'
  say "quarterdeck: resuming $PANEL_ID — $TOTAL item(s), $(jq length <<<"$STANCES") stance(s), ruling only"
fi

# ---- the ruling --------------------------------------------------------------
tx '.phase = "ruling"'
say "  — dockmaster ruling"
DISPUTED="$(jq -r '[.[] | select(.stance == "dispute")] | length' <<<"$STANCES")"

FLOOR="$(jq -r '.[] | "[\(.id)] (\(.seat), \(.severity)) \(.title)\n    \(.claim)\n    where: \(.where)\n    why: \(.why)\n    proposes: \(.action)"' <<<"$ITEMS")"
ARGUMENT="$(jq -r 'if length == 0 then "No seat responded to another." else (.[] | "[\(.id)] \(.by) \(.stance | ascii_upcase): \(.note)") end' <<<"$STANCES")"

case "$MODE" in
  findings) SHAPE="a findings document" ;;
  plan)     SHAPE="an implementation plan the builder will follow literally" ;;
  spec)     SHAPE="a specification someone could build from" ;;
  backlog)  SHAPE="a ranked decision about what to do next, with what is being cut named explicitly" ;;
  decision) SHAPE="a decision record: what was chosen, what it rules out, and what would overturn it" ;;
esac

ruling_prompt="$(preamble "$PROJECT")

You are the dockmaster. You chaired a $PANEL panel on: $SUBJECT.
Seats present: $present.${absent:+ Seats that did not report: $absent.}

$(crew_role dockmaster)

--- WHAT EACH SEAT BROUGHT ---

$(printf '%s\n' "$FLOOR" | untrusted "seat findings")

--- WHAT THEY SAID TO EACH OTHER ---

$(printf '%s\n' "$ARGUMENT" | untrusted "seat stances")

--- YOUR RULING ---

Produce $SHAPE. Rule on every item above: keep it, merge it into another, or
drop it. Where a seat disputed an item, you must decide — do not carry both
positions forward. Where you keep something that was disputed, say why the
dispute failed. Where you drop something, it simply does not appear.

Scale the ruling to what was asked. Keep an item only when the subject itself
needs it, or when leaving it out would make the change unsafe or impossible to
test. A small subject (one control, one file, one or two acceptance checks)
earns a handful of items at most: if more than five survive, you are ruling on
the neighbourhood and not on the subject. A finding about nearby code that the
subject does not need is dropped, or merged into one item that says it belongs
to a separate subject.

You may read the codebase to settle a factual disagreement, and you should when
two seats contradict each other about what the code does.

For each item you keep, record which seats supported it and which you overruled.

Label every item you keep with two judgements. Code acts on them without
reading the text again, so choose deliberately:
  kind — what the item IS:
    change     a change to make to the code now
    decision   a choice already made; nothing to build ('keep X', 'use Y for Z')
    invariant  a rule future work must preserve; nothing to build today
    deferral   deliberately not now; name what would bring it back
  tier — for a change, how much judgement building it takes (use routine for
  anything that is not a change):
    mechanical  a string, a value, a class name, a label; no design choice
    routine     a contained fix in one component, clear from the item itself
    intricate   several files or components, or a real choice of approach
    hard        hard to reverse: data shape, auth, money, encryption, security

End your reply with exactly these three lines and nothing after them:
HEADLINE: <the panel's answer in one line, at most 60 characters, no file names — what someone should take away, e.g. the shared Modal fails three of its callers>
RULING_JSON: <one-line JSON array of {\"kind\":\"change|decision|invariant|deferral\",\"tier\":\"mechanical|routine|intricate|hard\",\"area\":\"\",\"severity\":\"critical|major|minor\",\"title\":\"\",\"claim\":\"\",\"where\":\"\",\"why\":\"\",\"action\":\"\",\"support\":[\"seat\"],\"overruled\":[\"seat\"],\"note\":\"how you settled it, or empty if nobody argued\"}>
RESULT: RULED <count>"

# A prompt is built by string interpolation, and a stray quote in one silently
# changes what bash parses — `bash -n` sees nothing wrong. Check the thing we
# actually depend on before spending a model call on it.
case "${ruling_prompt:-}" in
  *RULING_JSON*) : ;;
  *) tx '.status="failed" | .verdict="the ruling prompt did not build"'
     record_run "$PROJECT" panel ERROR "$PANEL: ruling prompt malformed"
     die "the ruling prompt did not build — the argument is kept in $TX" ;;
esac

export QUARTERDECK_RUN_ID="${PANEL_ID}-ruling"
m="$(crew_meta dockmaster model)"; [ -n "$m" ] && export QUARTERDECK_MODEL_PERSONA="$m"
e="$(crew_meta dockmaster effort)"; [ -n "$e" ] && export QUARTERDECK_EFFORT_PERSONA="$e"
result="$(claude_run "$WORKDIR" "$ruling_prompt")"; rc=$?
[ $rc = 2 ] && { tx '.status="stalled" | .verdict="usage limit before the ruling"'; say "quarterdeck: usage limit before the ruling — the argument is kept in $TX"; exit 0; }
HEADLINE="$(grep -o 'HEADLINE: .*' <<<"$result" | tail -1 | sed 's/^HEADLINE: //' | cut -c1-80)"
RULING="$(grep -o 'RULING_JSON: .*' <<<"$result" | tail -1 | sed 's/^RULING_JSON: //')"
jq -e 'type == "array"' <<<"$RULING" >/dev/null 2>&1 || {
  tx '.status="failed" | .verdict="the ruling did not parse"'
  record_run "$PROJECT" panel ERROR "$PANEL: ruling did not parse"
  die "the ruling did not parse — the argument is kept in $TX (raw: logs/runs/${PANEL_ID}-ruling.json)"; }

# The labels steer what a fix costs, so a missing or invented one is replaced
# with the safe default rather than trusted: on a findings or plan panel an
# unlabelled item is a routine change; on a spec, decision or backlog panel it
# is a decision, which is never auto-built.
case "$MODE" in findings|plan) dk=change ;; *) dk=decision ;; esac
RULING="$(jq -c --arg dk "$dk" 'map(
    .kind = (if (.kind | IN("change","decision","invariant","deferral")) then .kind else $dk end)
  | .tier = (if (.tier | IN("mechanical","routine","intricate","hard")) then .tier else "routine" end))' <<<"$RULING")"
KEPT="$(jq 'length' <<<"$RULING")"

# ---- the document ------------------------------------------------------------
# The harness renders it. Seats return structured data only, so changing how a
# ruling reads never means touching a prompt.
{
  case "$MODE" in
    findings) echo "# ${PROJECT} — ${PANEL} panel, ${STAMP}" ;;
    plan)     echo "# ${PROJECT} — implementation plan for issue #${ISSUE}" ;;
    spec)     echo "# ${PROJECT} — specification: ${SUBJECT}" ;;
    backlog)  echo "# ${PROJECT} — what to do next, ${STAMP}" ;;
    decision) echo "# ${PROJECT} — decision: ${SUBJECT}" ;;
  esac
  echo
  [ -n "$HEADLINE" ] && { echo "**${HEADLINE}**"; echo; }
  echo "Ruled by the dockmaster after a ${PANEL} panel on \`${SUBJECT}\`."
  echo "Seats: ${present// /, }.${absent:+ Did not report: ${absent// /, }.}"
  echo "${TOTAL} item(s) raised, ${DISPUTED} disputed, ${KEPT} kept."
  echo
  jq -r '
    def sev: if .severity=="critical" then 0 elif .severity=="major" then 1 else 2 end;
    # Sorted by severity to read, numbered by position in the ruling: the number
    # is what `quarterdeck fix --item` and the dashboard use, so it is what people
    # quote. Renumbering after the sort sent a PR citing the wrong items.
    to_entries | sort_by(.value | sev) | .[] |
    "## \(.key + 1). \(.value.title)\n" +
    "\n_\(.value.severity) · \(.value.area) · " +
      (if (.value.support|length) > 0 then "raised by \(.value.support | join(", "))" else "raised by the panel" end) +
      (if (.value.overruled|length) > 0 then " · overruled: \(.value.overruled | join(", "))" else "" end) + "_\n" +
    "\n\(.value.claim)\n" +
    "\n**Where.** `\(.value.where)`\n" +
    "\n**Why it matters.** \(.value.why)\n" +
    "\n**Do this.** \(.value.action)\n" +
    (if (.value.note // "") != "" then "\n> Ruling: \(.value.note)\n" else "" end)
  ' <<<"$RULING"
  echo
  echo "---"
  echo
  echo "_Quarterdeck ${PANEL} panel \`${PANEL_ID}\`. The full argument, including what was"
  echo "dropped and who was overruled, is in \`state/panels/${PANEL_ID}.json\`._"
} > "$OUT"

tx --argjson r "$RULING" --arg doc "$OUT" --arg at "$(date -u +%FT%TZ)" --arg v "$KEPT kept" \
   --arg h "$HEADLINE" \
   '.ruling = $r | .doc = $doc | .finished = $at | .status = "done" | .phase = "closed" | .verdict = $v
    | .headline = (if $h == "" then null else $h end)'

say ""
jq -r '.[] | "  [\(.severity)] \(.area) — \(.title)"' <<<"$RULING" >&2
say ""
say "quarterdeck: $KEPT item(s) ruled from $TOTAL raised ($DISPUTED disputed)"
say "  $OUT"
say ""
case "$MODE" in
  findings) say "  file them with:"; say "  quarterdeck run $PROJECT foreman --from \"$OUT\" --apply" ;;
  plan)     say "  build it with:";  say "  quarterdeck run $PROJECT shipwright --issue $ISSUE --plan \"$OUT\" --apply" ;;
  spec)     say "  turn it into issues with:"; say "  quarterdeck run $PROJECT foreman --from \"$OUT\" --apply" ;;
  backlog)  say "  the board keeps itself honest separately:"; say "  quarterdeck run $PROJECT harbourmaster --apply" ;;
  decision) say "  build it with:"; say "  quarterdeck run $PROJECT panel --panel spec --from \"$OUT\"" ;;
esac

record_run "$PROJECT" panel "RULED" "$PANEL: $KEPT of $TOTAL on $SUBJECT" ""

exit
}
