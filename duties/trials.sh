#!/bin/bash
# trials — write the test that reproduces a bug, and prove it reproduces it.
#
# Sea trials are where a claim about a vessel meets water. This duty takes an
# issue and produces one failing test: it writes the test, runs it, and requires
# it to FAIL on the current code. A test that passes before the fix exists
# proves nothing and is refused rather than committed.
#
# It pairs with the two duties either side of it. The inspector says what would
# settle a claim; trials writes it; the shipwright makes it go green:
#
#   quarterdeck run <p> trials     --issue 204 --apply    # a red test, on a branch
#   quarterdeck run <p> shipwright --issue 204 --apply    # make it green
#
# Requires a test command in the registry — a duty that cannot run what it
# writes is not a tester:
#   "test": "npx vitest run"
#
# Contract:
#   RESULT: REPRODUCED <what the test asserts>
#         | CANNOT_REPRODUCE <why the bug does not appear>
#         | NEEDS_HUMAN <what you need decided>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> trials --issue <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/trials-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-tests and for a stand-in; lib.sh puts the real gh first on PATH
BASE=$(project_get "$PROJECT" default_branch main)
TEST_CMD=$(project_get "$PROJECT" test)

APPLY=0 ISSUE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --issue) ISSUE="${2:-}"; need_num "--issue" "$ISSUE"; shift ;;
    *) die "trials: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[ -n "$ISSUE" ] || die "trials needs an issue: --issue <number>"
[ -n "$TEST_CMD" ] || die "trials: '$PROJECT' has no test command in the registry.
Add \"test\": \"<how this project runs its tests>\" to config/projects.json.
Without one there is nothing to run, and a test nobody runs is a comment."

acquire_lock "trials-$PROJECT"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-trials-$ISSUE"

meta=$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json number,title,body,state 2>>"$LOG_FILE") \
  || die "cannot read $REPO#$ISSUE"
[ "$(jq -r .state <<<"$meta")" = OPEN ] || die "#$ISSUE is not open"
title=$(jq -r .title <<<"$meta")
body=$(jq -r .body <<<"$meta")

slug=$(tr '[:upper:]' '[:lower:]' <<<"$title" | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-40)
BRANCH="test/${ISSUE}-${slug}"
WT="$QUARTERDECK_HOME/workspace/wt-trials-${PROJECT}-${ISSUE}"
cleanup_wt() { safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap 'cleanup_wt' EXIT

working_on "issue #$ISSUE — a test for: $title"
say "quarterdeck: trials on $REPO#$ISSUE — $title"

guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || log "fetch failed; using local $BASE"
worktree_at "$SOURCE_REPO_DIR" "$WT" "origin/$BASE" \
  || worktree_at "$SOURCE_REPO_DIR" "$WT" "$BASE" \
  || die "could not create a worktree at $WT"
safe_git -C "$WT" checkout -q -B "$BRANCH" 2>>"$LOG_FILE" || die "could not create branch $BRANCH"

# What the suite does before anything is added. A repo with failing tests would
# otherwise make every new test look like a successful reproduction.
say "  baseline: $TEST_CMD"
INPUTS_BEFORE="$(verify_inputs "$WT")"
project_exec check 900 "$WT" "$TEST_CMD"; base_rc=$?; base_out=$EXEC_OUT
wt_mark "$WT"
say "  baseline exit $base_rc"

prompt="$(preamble "$PROJECT")

$(crew_role inspector)

--- THESE TRIALS ---

Write ONE test that reproduces this bug on the current code. You are in a
throwaway worktree on branch $BRANCH; write test files here. Do not fix the bug,
do not touch application code, and do not commit — the harness runs your test
and does the rest.

=== $REPO#$ISSUE ===
$(printf '%s\n\n%s\n' "$title" "$body" | untrusted "issue text")
=== END ===

The whole point is that your test must FAIL right now, for the reason the issue
describes. A test that passes before the fix proves nothing and will be thrown
away by the harness rather than committed.

How to work:
- Read the code path the issue describes until you know the exact input or state
  that triggers it. If you cannot find it, say CANNOT_REPRODUCE and explain —
  that is a real and useful answer, and often means the issue is wrong.
- Write the test in this repo's existing style, in the place its tests live. If
  there is no existing test for this area, follow the nearest convention you can
  find rather than inventing a second one.
- Assert the behaviour, not the implementation. A test that asserts a function
  was called will survive the bug being fixed badly.
- Test files only. If reproducing it genuinely needs a seam that does not exist
  in the application code, do not add it — say NEEDS_HUMAN and describe the seam.
- The suite is run with: $TEST_CMD
  It exited $base_rc before you touched anything, so any failure already present
  is not yours.

End your reply with exactly one line:
RESULT: REPRODUCED <what the test asserts and why it fails today>
  or
RESULT: CANNOT_REPRODUCE <what you found instead>
  or
RESULT: NEEDS_HUMAN <what you need decided>"

result=$(claude_run "$WT" "$prompt" \
  "Read,Edit,Write,Grep,Glob,Bash(npx *),Bash(npm run*),Bash(node*)" \
  "WebFetch,WebSearch,Bash(git push*),Bash(git commit*),Bash(git checkout*),Bash(git reset*),Bash(gh *),Bash(rm -rf*),Bash(curl*),Bash(ssh*),Bash(npm publish*),Bash(npm install*)")
rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — worktree discarded"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" trials ERROR "run failed on #$ISSUE"; die "trials run failed"; }

verdict=$(grep -Eo '^RESULT: (REPRODUCED|CANNOT_REPRODUCE|NEEDS_HUMAN) .*' <<<"$result" | tail -1 | sed 's/^RESULT: //')
[ -n "$verdict" ] || { record_run "$PROJECT" trials ERROR "unparseable contract on #$ISSUE"
  die "contract did not parse — nothing written (see logs/runs/$QUARTERDECK_RUN_ID.json)"; }
state=${verdict%% *}; detail=${verdict#* }

if [ "$state" != REPRODUCED ]; then
  say ""; say "  $state — $detail"
  record_run "$PROJECT" trials "$state" "#$ISSUE — $detail"
  exit 0
fi

# ---- the harness checks the work itself --------------------------------------
# Final paths of everything changed, one per line. Not `status --porcelain`:
# its second field is a rename's OLD name, so a file moved into a forbidden
# path was checked under the name it left.
changed=$(wt_changed "$WT") || { record_run "$PROJECT" trials REFUSED "#$ISSUE — the worktree's .git file was changed"; die "refused: the worktree's .git file was changed"; }
[ -n "$changed" ] || { record_run "$PROJECT" trials ERROR "#$ISSUE — claimed a test but wrote nothing"
  die "it reported REPRODUCED and changed no files — nothing committed"; }

# Test files only. This is stated in the prompt as a request; here it is a rule.
offenders=$(grep -vE '(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.[jt]sx?$|(\.(test|spec)|_test|(^|/)test_[^/]*)\.py$|_test\.(go|exs)$|Tests?\.(cs|java|kt)$' <<<"$changed" || true)
if [ -n "$offenders" ]; then
  say "  it changed files that are not tests:"; sed 's/^/    /' <<<"$offenders" >&2
  record_run "$PROJECT" trials BLOCKED "#$ISSUE — touched application code"
  die "a tester may only write tests — nothing committed"
fi

# A test may not smuggle in a change to CI, dependencies, tool config or the test command itself (it is about to be executed).
if ! why=$(printf '%s\n' "$changed" | model_diff_gate "$PROJECT" "$WT" "$INPUTS_BEFORE"); then
  say "  REFUSED: $why"
  record_run "$PROJECT" trials REFUSED "#$ISSUE — $why"
  die "refused: $why"
fi

say ""
say "  running the new test: $TEST_CMD"
project_exec check 900 "$WT" "$TEST_CMD"; new_rc=$?; new_out=$EXEC_OUT
# The new test ran project code that may write in the worktree: the gate again, on what is there now (S1).
if ! why=$(post_checks_gate "$PROJECT" "$WT" "$INPUTS_BEFORE" "$changed"); then
  say "  REFUSED: $why"
  record_run "$PROJECT" trials REFUSED "#$ISSUE — $why"
  die "refused: $why"
fi
say "  exit $new_rc (baseline was $base_rc)"

# The proof: the suite must be worse than it was. A new test that passes on
# unfixed code is describing behaviour that already works.
if [ "$new_rc" = 0 ]; then
  say ""
  say "  the new test passes on unfixed code, so it does not reproduce anything."
  say "  worktree kept for inspection: $WT"
  trap - EXIT
  record_run "$PROJECT" trials "NOT-RED" "#$ISSUE — the test passed before any fix"
  exit 0
fi

files=$(tr '\n' ' ' <<<"$changed")
say "  red as required — $files"

if [ "$APPLY" = 0 ]; then
  say ""
  safe_git -C "$WT" diff --cached --stat | sed 's/^/    /' >&2
  say ""
  say "quarterdeck: report only — pass --apply to push the branch and open the pull request"
  say "  worktree kept for inspection: $WT"
  trap - EXIT
  record_run "$PROJECT" trials "DRY-RUN" "#$ISSUE — reproduced: $detail"
  exit 0
fi

# post_checks_gate staged exactly what passed (and checked the staged blobs); nothing is staged again here
# Commit as whoever this checkout is configured as — the same identity as
# every other commit on the repository. A made-up "quarterdeck" address is not a
# GitHub account, and Vercel refuses to deploy a preview for a commit it cannot
# tie to one: both of Quarterdeck's first open pull requests were blocked for
# exactly that, while every human one deployed. Quarterdeck stays credited in the
# message and the pull request body.
commit_identity "$PROJECT" "$WT" || die "no commit identity for $PROJECT: GitHub could not be asked for the account's no-reply address and the checkout has no user.email (set \"git\": {\"name\", \"email\"} in the registry)"
safe_git -C "$WT" ${COMMIT_ID[@]+"${COMMIT_ID[@]}"} commit -q -m "test: reproduce #$ISSUE — $title

$detail

This test fails on $BASE and should pass once #$ISSUE is fixed.

Written by the Quarterdeck trials duty." 2>>"$LOG_FILE" \
  || { record_run "$PROJECT" trials ERROR "#$ISSUE — commit failed"; die "could not commit"; }

safe_git_guard 120 -C "$WT" push -q -u origin "$BRANCH" --force-with-lease 2>>"$LOG_FILE" \
  || { record_run "$PROJECT" trials ERROR "#$ISSUE — push failed"; die "could not push $BRANCH"; }

if url=$(gh_post 90 pr create -R "$REPO" --base "$BASE" --head "$BRANCH" --draft \
    --title "test: reproduce #$ISSUE — $title" \
    --body "Reproduces #$ISSUE.

$detail

\`$TEST_CMD\` exits \`$base_rc\` on \`$BASE\` and \`$new_rc\` with this test, so the failure is this test and not a pre-existing one. It is a draft on purpose: it is **meant to be red** until #$ISSUE is fixed.

Files: \`$files\`

<!-- quarterdeck:v1 duty=trials -->
<sub>Quarterdeck trials. The model wrote the test; the harness ran it and refused to commit one that passed.</sub>" 2>>"$LOG_FILE"); then
  say ""; say "quarterdeck: $url"
  record_run "$PROJECT" trials "REPRODUCED" "#$ISSUE — $detail" "$url"
else
  record_run "$PROJECT" trials ERROR "#$ISSUE — branch pushed, pull request failed"
  die "pushed $BRANCH but could not open the pull request"
fi

exit
}
