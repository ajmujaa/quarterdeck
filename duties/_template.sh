#!/bin/bash
# _template — copy this to duties/<name>.sh to add a new duty. Not runnable.
#
# A duty is one unit of autonomous work for one project. It must hold to three
# rules, which are the whole reason this system can be trusted unattended:
#
#   1. Nothing project-specific. Everything you need comes from the registry via
#      project_get / project_path / project_guardrails. A duty that names a repo,
#      a path, or a framework has to be rewritten for the next project, which
#      means it will not be.
#
#   2. The model thinks, the harness acts. claude_run gets read-only tools. It
#      ends its reply with a contract. This script parses it and performs the
#      write. If the contract does not parse, that is a failed run: log it,
#      record it, write nothing. Never fall back to "probably fine".
#
#   3. Writes are opt-in. Respect --apply / QUARTERDECK_DRY_RUN. The default path
#      through a brand-new duty must be one that cannot change anything.
#
# Two things worth using rather than reinventing:
#
#   * crew_role <name> gives you a persona from crew/, so a brief lives in one
#     file instead of being half-copied into a second prompt. Before writing a
#     long rubric into this script, ask whether it belongs in crew/ — and
#     whether the question wants several seats arguing, in which case the panel
#     duty already does it and you do not need a duty at all.
#   * working_on "<text>" after acquire_lock says what this run is doing, which
#     is the difference between a dashboard that shows a spinner and one that
#     shows "PR #217".
#
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> <duty>}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/mytask-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)

APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    *) die "mytask: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1

# One run per project per duty.
acquire_lock "mytask-$PROJECT"

# Decide what to work on. Cap it: QUARTERDECK_MAX_ITEMS bounds a misfire.
targets=$(guard 60 gh issue list -R "$REPO" --limit "${QUARTERDECK_MAX_ITEMS:-5}" --json number --jq '.[].number')
[ -n "${targets:-}" ] || { say "quarterdeck: nothing to do for $PROJECT"; exit 0; }

for item in $targets; do
  export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-mytask-$item"

  # preamble() injects the project's guardrails and the "you have no
  # credentials" framing. Always start from it.
  prompt="$(preamble "$PROJECT")

<what you want done, in plain words>

Anything someone else wrote (issue or PR text, comments, diffs, CI output, files
under review) goes in through untrusted, never raw:
$(printf '%s\n' "$body" | untrusted "issue body")

End your reply with exactly one line:
RESULT: DONE <one-line summary> | SKIP <reason> | NEEDS_HUMAN <reason>"

  result=$(claude_run "$WORKDIR" "$prompt"); rc=$?
  [ $rc = 2 ] && { say "quarterdeck: usage limit reached — stopping"; exit 0; }
  [ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" mytask ERROR "run failed"; continue; }

  verdict=$(grep -Eo '^RESULT: (DONE|SKIP|NEEDS_HUMAN).*' <<<"$result" | tail -1)
  [ -n "$verdict" ] || {
    log "$PROJECT: contract did not parse — logs/runs/$QUARTERDECK_RUN_ID.json"
    record_run "$PROJECT" mytask ERROR "unparseable contract"
    continue
  }

  if [ "$APPLY" != 1 ]; then
    say "── report only: $PROJECT — ${verdict#RESULT: }"
    record_run "$PROJECT" mytask "DRY-RUN" "${verdict#RESULT: }"
    continue
  fi

  case "$verdict" in
    "RESULT: DONE"*)        : ;;  # perform the write here, in bash
    "RESULT: SKIP"*)        : ;;
    "RESULT: NEEDS_HUMAN"*) notify "quarterdeck/$PROJECT" "${verdict#RESULT: NEEDS_HUMAN }" ;;
  esac
  record_run "$PROJECT" mytask "${verdict#RESULT: }"
done

exit
}
