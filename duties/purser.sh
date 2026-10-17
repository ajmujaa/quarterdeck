#!/bin/bash
# purser — turn a backlog issue into something a stranger could start cold.
#
# The purser keeps the ship's papers: what was agreed, and what was not. Given
# one issue it reads the issue and the code it touches, and either writes the
# requirements — each one an observable behaviour with an acceptance check a
# stranger could run, plus what is out of scope — or says what a person must
# settle first. It is the step between "someone wrote a ticket" and
# `quarterdeck fix --issue`, which builds from whatever the issue says.
#
# What it writes, and where:
#   * The requirements go into the issue BODY, between two markers, and nowhere
#     else. The builder, the dev panel and the inspector read the body and never
#     the comments, so a requirement posted as a comment would be invisible to
#     the work it exists to steer. Running this again replaces the block; the
#     text above it is never touched.
#   * The same text is kept as a local document, so it can be read without
#     opening GitHub, and so a NEEDS_HUMAN answer has somewhere to live.
#   * The card moves Backlog -> Ready, and only from Backlog: analysing an issue
#     someone is already working on must not pull it backwards.
#
#   quarterdeck run <p> purser --issue 204            # report only
#   quarterdeck run <p> purser --issue 204 --apply    # write it, move the card
#
# Contract:
#   REQUIREMENTS_JSON: {"summary","requirements":[{"what","accept"}],"out_of_scope":[]}
#   RESULT: READY <n> requirement(s)
#     or
#   RESULT: NEEDS_HUMAN <what must be decided, or how to split it, first>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> purser --issue <n>}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/purser-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-test: lib.sh puts the real gh first on PATH

ISSUE="" APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue) ISSUE="${2:-}"; need_num "--issue" "$ISSUE"; shift ;;
    --apply) APPLY=1 ;;
    *) die "purser: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$ISSUE" =~ ^[0-9]+$ ]] || die "purser: which issue? --issue <number>"

acquire_lock "purser-$PROJECT"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-purser-$ISSUE-$(date +%s)"

meta=$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json number,title,body,state 2>>"$LOG_FILE") \
  || die "purser: could not read issue #$ISSUE in $REPO"
[ "$(jq -r .state <<<"$meta")" = OPEN ] || die "purser: #$ISSUE is not open"
title=$(jq -r .title <<<"$meta")
body=$(jq -r .body <<<"$meta")
working_on "issue #$ISSUE — $title"
say "quarterdeck: purser on $REPO#$ISSUE — $title"

MARK_OPEN='<!-- quarterdeck:requirements -->'
MARK_CLOSE='<!-- /quarterdeck:requirements -->'
# The issue with our own block taken out, and nothing else touched. A block with
# only one marker (someone edited it) is left exactly as it is rather than
# guessed at: better a stale duplicate than a deleted paragraph.
without_block() {
  python3 -c 'import re,sys; print(re.sub(r"\n*<!-- quarterdeck:requirements -->.*?<!-- /quarterdeck:requirements -->\n*", "\n", sys.stdin.read(), flags=re.S).strip())'
}

prompt="$(preamble "$PROJECT")

$(crew_role purser)

--- THE ISSUE ---

$(printf '#%s %s\n\n%s\n' "$ISSUE" "$title" "$body" | untrusted "issue text")

--- YOUR JOB ---

Decide whether a stranger could start this issue cold, then say what they would
be building. Read the code the issue touches before you write anything: a
requirement that names a screen, a function or a file that does not exist is
worse than none.

If it can be started, write its requirements. Each one is an observable
behaviour — the trigger and the result — and an acceptance check someone else
could run without asking the author what they meant. At most 8. Say WHAT must be
true, not how to build it: choosing the approach is the developers' job, and a
requirement that prescribes it takes their choice away. Then list what a reader
would assume is included and is not. If the issue already has a Requirements
section from an earlier pass, improve it rather than starting over.

When the change adds or alters something a person operates (a button, a link, a
field, a menu), one requirement says it can be reached and used with the
keyboard alone and shows a visible focus indicator while focused. Its acceptance
check is one a person can run: press Tab until it is focused, see the
indicator, then activate it with Enter or Space. This is a requirement, not an
extra: a control that cannot be seen or reached by keyboard is not finished.

At least one acceptance check exercises the behaviour: it names the action (press,
type, call, run) and what must then be seen or returned. A check that only says an
element, selector, id or string exists is never only that: it passes while the
feature does nothing. Write the existence check only beside one that does something.

If it cannot be started — it is really several pieces of work, it hinges on a
product or pricing decision only a person can make, it is research or an epic
with no code to write, or you cannot tell what done looks like — do NOT invent
requirements to fill the gap. Say exactly what has to be decided or how it
should be split, and stop. That is a real answer.

Everything you write in the contract is posted into the issue. Do not repeat
anything the hard rules above forbid putting in an issue.

End your reply with exactly these two lines and nothing after them:
REQUIREMENTS_JSON: <one-line JSON {\"summary\":\"one or two sentences: what this is for\",\"requirements\":[{\"what\":\"...\",\"accept\":\"...\"}],\"out_of_scope\":[\"...\"]}>
RESULT: READY <n> requirement(s)
  or, instead of both lines, the single line
RESULT: NEEDS_HUMAN <what must be decided or split first>"

result=$(claude_run "$WORKDIR" "$prompt"); rc=$?
case $rc in
  0) : ;;
  2) say "quarterdeck: usage limit reached — nothing written"; exit 0 ;;
  3) say "quarterdeck: stopped at the per-call cap — nothing written"; record_run "$PROJECT" purser ERROR "#$ISSUE hit the per-call cap"; exit 1 ;;
  *) record_run "$PROJECT" purser ERROR "#$ISSUE the model call failed"; exit 1 ;;
esac
[ -n "$result" ] || { record_run "$PROJECT" purser ERROR "#$ISSUE empty reply"; exit 1; }

DOC="$QUARTERDECK_HOME/workspace/${PROJECT}-requirements-${ISSUE}.md"

if grep -q '^RESULT: NEEDS_HUMAN' <<<"$result"; then
  why=$(grep -o '^RESULT: NEEDS_HUMAN.*' <<<"$result" | tail -1 | sed 's/^RESULT: NEEDS_HUMAN *//')
  {
    echo "# #$ISSUE — $title"
    echo
    echo "The purser could not write requirements for this yet. Nothing was posted to the issue."
    echo
    echo "**Needs a person.** $why"
  } > "$DOC"
  say "  needs a person: $why"
  say "  written to $(basename "$DOC")"
  record_run "$PROJECT" purser NEEDS_HUMAN "#$ISSUE — $why"
  exit 0
fi

# Anything else must be a READY with a contract that parses. A reply that does
# not is a failed run that writes nothing; never "probably fine".
json=$(grep -o '^REQUIREMENTS_JSON: .*' <<<"$result" | tail -1 | sed 's/^REQUIREMENTS_JSON: //')
if ! grep -q '^RESULT: READY' <<<"$result" || ! jq -e '
      (.requirements | type == "array" and length > 0)
      and all(.requirements[]; (.what | type == "string" and length > 0) and (.accept | type == "string" and length > 0))' \
      <<<"${json:-null}" >/dev/null 2>&1; then
  log "$PROJECT: purser contract did not parse — logs/runs/$QUARTERDECK_RUN_ID.json"
  say "quarterdeck: the purser's reply did not parse — nothing written"
  record_run "$PROJECT" purser ERROR "#$ISSUE unparseable contract"
  exit 1
fi
json=$(jq -c '.requirements |= .[0:8]' <<<"$json")
# #86: a check that only looks for a thing (grep for an id, the string is on the page) passes while the feature does nothing.
# At least one acceptance check has to make the thing do something and say what then happens.
acts=0
while IFS= read -r a; do printf '%s' "$a" | python3 "$QUARTERDECK_DIR/bin/behaviour.py" accept && acts=1; done < <(jq -r '.requirements[].accept' <<<"$json")
if [ "$acts" = 0 ]; then
  log "$PROJECT: purser: every acceptance check only looks for something to exist — logs/runs/$QUARTERDECK_RUN_ID.json"
  say "quarterdeck: every acceptance check only proves that something exists (a grep, a selector, a string); at least one has to exercise the behaviour — nothing written"
  record_run "$PROJECT" purser ERROR "#$ISSUE acceptance checks only prove existence"
  exit 1
fi
n=$(jq '.requirements | length' <<<"$json")

block=$(jq -r --arg o "$MARK_OPEN" --arg c "$MARK_CLOSE" '
  $o + "\n## Requirements\n\n"
  + "_Written by Quarterdeck'"'"'s purser from the issue and the code. Edit freely; running the analysis again replaces this section._\n\n"
  + (if (.summary // "") != "" then .summary + "\n\n" else "" end)
  + ([.requirements | to_entries[] | "\(.key + 1). \(.value.what)\n   - **Accept when:** \(.value.accept)"] | join("\n"))
  + (if ((.out_of_scope // []) | length) > 0 then "\n\n**Out of scope**\n" + ([.out_of_scope[] | "- " + .] | join("\n")) else "" end)
  + "\n" + $c' <<<"$json")
{ echo "# #$ISSUE — $title"; echo; echo "$block"; } > "$DOC"
say "  $n requirement(s), written to $(basename "$DOC")"

if [ "$APPLY" != 1 ]; then
  say ""
  sed 's/^/  /' <<<"$block" >&2
  say ""
  say "quarterdeck: report only — pass --apply to add this to the issue and move its card to Ready"
  record_run "$PROJECT" purser "DRY-RUN" "#$ISSUE — $n requirement(s)"
  exit 0
fi

# The issue may have been edited while the model was thinking. Read it again
# and rebuild from that, so a change made in the meantime is not overwritten.
fresh=$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json body --jq .body 2>>"$LOG_FILE") \
  || { record_run "$PROJECT" purser ERROR "#$ISSUE could not re-read the issue"; exit 1; }
# (No EXIT trap for the temp file: acquire_lock's trap releases the lock, and a
# second trap would replace it.)
tmp=$(mktemp)
printf '%s\n\n%s\n' "$(without_block <<<"$fresh")" "$block" > "$tmp"
gh_post 60 issue edit "$ISSUE" -R "$REPO" --body-file "$tmp" >/dev/null 2>>"$LOG_FILE"; rc=$?
rm -f "$tmp"
[ $rc = 0 ] || { record_run "$PROJECT" purser ERROR "#$ISSUE could not update the issue"; die "purser: could not update #$ISSUE (see $LOG_FILE)"; }
say "  requirements added to #$ISSUE"

# The card moves only out of Backlog: an issue already being worked on is not
# pulled back to Ready by being analysed.
moved=""
if [ -n "$(project_get "$PROJECT" board.number)" ]; then
  from=$(guard 60 python3 "$QUARTERDECK_DIR/bin/board.py" to "$(project_get "$PROJECT" board.owner)" \
           "$(project_get "$PROJECT" board.number)" "$ISSUE" ready "$(project_get "$PROJECT" board.status)" todo \
           2>>"$LOG_FILE") || from=""
  [ -n "$from" ] && { moved=", card moved from $from to Ready"; say "  card: $from → ready"; }
fi

record_run "$PROJECT" purser READY "#$ISSUE — $n requirement(s)$moved" "https://github.com/$REPO/issues/$ISSUE"
exit
}
