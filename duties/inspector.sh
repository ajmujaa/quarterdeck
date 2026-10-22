#!/bin/bash
# inspector — check that a pull request actually does what it claims.
#
# Nothing leaves the yard on a description of itself. The surveyor reviews a
# diff for defects; the inspector asks a narrower and harder question: does this
# change fix the thing it says it fixes, and how would anyone know?
#
# It builds the PR's own head in a throwaway worktree, runs the project's verify
# command there rather than believing a claim in the description, and reports a
# verdict with the test that would prove it. It writes nothing to the branch —
# the verdict goes on the pull request, and only with --apply.
#
#   qtdeck run <p> inspector --pr 218
#   qtdeck run <p> inspector --pr 218 --issue 204 --apply
#
# Contract:
#   TEST_JSON: {"exists":bool,"name":"","given":"","when":"","then":"","where":""}
#   RESULT: PROVEN <what proves it> | UNPROVEN <what is missing> | BROKEN <what fails>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> inspector --pr <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/inspector-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"
# Decisions on record, when this checkout has the Logkeeper's injector.
ADR_ON=0; ADR_BLOCK=""
if [ -f "$QUARTERDECK_DIR/bin/decisions.sh" ]; then source "$QUARTERDECK_DIR/bin/decisions.sh"; ADR_ON=1; fi
VERIFY=$(project_get "$PROJECT" verify)

APPLY=0 PR="" ISSUE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --pr)    PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    --issue) ISSUE="${2:-}"; need_num "--issue" "$ISSUE"; shift ;;
    *) die "inspector: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[ -n "$PR" ] || die "inspector needs a pull request: --pr <number>"

# Keyed by the PR, not just the project — matching the worktree below, which
# already isolates the build per PR. Two different PRs inspect side by side;
# the same PR twice still waits.
acquire_lock "inspector-$PROJECT-$PR"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-inspect-$PR"

meta=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json number,title,body,state,headRefName,isCrossRepository 2>>"$LOG_FILE") \
  || die "cannot read $REPO#$PR"
if why=$(fork_refuse "$meta"); then
  say "quarterdeck: BLOCKED — $why"; record_run "$PROJECT" inspector BLOCKED "#$PR — $why"; exit 0
fi
title=$(jq -r .title <<<"$meta")
body=$(jq -r .body <<<"$meta")
[ "$(jq -r .state <<<"$meta")" = OPEN ] || say "quarterdeck: note — #$PR is $(jq -r .state <<<"$meta")"

# The issue is the claim being tested. Take it from the flag, or from the usual
# closing keywords in the body — a PR that references no issue is still worth
# inspecting, just against its own description.
if [ -z "$ISSUE" ]; then
  ISSUE=$(grep -oiE '(closes|fixes|resolves)[[:space:]]+#([0-9]+)' <<<"$body" | grep -oE '[0-9]+' | head -1 || true)
fi
claim="$title

$body"
if [ -n "$ISSUE" ]; then
  if issue=$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json title,body \
             --template '{{.title}}{{"\n\n"}}{{.body}}' 2>>"$LOG_FILE"); then
    claim="THE PULL REQUEST SAYS
$title

$body

THE ISSUE IT CLAIMS TO FIX (#$ISSUE)
$issue"
  fi
fi

working_on "PR #$PR — $title"
say "quarterdeck: inspector on $REPO#$PR — $title"

WT="$QUARTERDECK_HOME/workspace/wt-inspect-${PROJECT}-${PR}"
cleanup_wt() { safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap 'cleanup_wt; release_lock' EXIT

# Build the pull request's own head, not the branch name — a fork's branch does
# not exist locally, and refs/pull/N/head always does.
guard 180 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "pull/$PR/head" 2>>"$LOG_FILE" \
  || die "could not fetch pull/$PR/head"
worktree_at "$SOURCE_REPO_DIR" "$WT" FETCH_HEAD || die "could not create a worktree at $WT"

# Run the project's own check here rather than trusting the description or a
# green tick on a stale commit.
verify_out="not configured" verify_rc="-"
if [ -n "$VERIFY" ]; then
  say "  running: $VERIFY"
  project_exec check 900 "$WT" "$VERIFY"; verify_rc=$?; verify_out=$EXEC_OUT      # the pull request's own code: minimal environment, sandboxed
  verify_out=$(tail -40 <<<"$verify_out")
  say "  verify exit $verify_rc"
fi

# What the pull request's own checks on GitHub say. The local check above
# proves it builds here; these are the gates it has to pass to be merged and
# deployed, and they fail for reasons no local check can see — a preview that
# will not deploy, a runner the change broke. Read by the harness, so the model
# is told the facts rather than left to fetch them.
CI_JSON=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json statusCheckRollup 2>>"$LOG_FILE" || echo '{}')
ci() { jq -r --argjson want "$1" '[.statusCheckRollup[]?
        | ((.conclusion // .state // .status // "") | ascii_upcase) as $s
        | select($want | index([$s]))] ' <<<"$CI_JSON"; }
# GitHub's summary drops the description of a commit status, and the
# description is the part that says why — "GitHub couldn't verify an account for
# the commit" is a diagnosis, "FAILURE" is not. So fetch every description a
# failing status has carried on this commit, from the status history.
HEAD_SHA=$(guard 30 "$GH" pr view "$PR" -R "$REPO" --json headRefOid --jq .headRefOid 2>>"$LOG_FILE" || true)
CI_WHY='{}'
[ -n "$HEAD_SHA" ] && CI_WHY=$(guard 30 "$GH" api "repos/$REPO/commits/$HEAD_SHA/statuses" --jq '
    [.[] | select(.state == "failure" or .state == "error") | {context, description}]
    | group_by(.context) | map({key: .[0].context,
        value: ([.[].description | select(. != null and . != "")] | unique | join(" · "))})
    | from_entries' 2>>"$LOG_FILE" || echo '{}')
jq -e 'type == "object"' <<<"$CI_WHY" >/dev/null 2>&1 || CI_WHY='{}'
CI_FAILING=$(ci '["FAILURE","ERROR","CANCELLED","TIMED_OUT","ACTION_REQUIRED"]' \
             | jq -r --argjson why "$CI_WHY" 'map((.name // .context) as $n
                 | "\($n) — \($why[$n] // .description // .conclusion // .state)") | join("\n")')
CI_PENDING=$(ci '["PENDING","IN_PROGRESS","QUEUED","WAITING","EXPECTED"]' | jq -r 'map(.name // .context) | join(", ")')
CI_PASSING=$(ci '["SUCCESS","NEUTRAL","SKIPPED"]' | jq -r 'length')
say "  checks on GitHub: $CI_PASSING passing${CI_FAILING:+, failing: $(tr '\n' ';' <<<"$CI_FAILING")}${CI_PENDING:+, still running: $CI_PENDING}"

ADR_SPEC=""
if [ "$ADR_ON" = 1 ]; then
  adr_block "$PROJECT" "$(project_get "$PROJECT" default_branch main)" \
    "$(guard 60 "$GH" pr diff "$PR" -R "$REPO" --name-only 2>>"$LOG_FILE" || true)" "$claim"
  ADR_SPEC=$'ADR: <cites ADR n | matches ADR n | searched <records>>\n'
fi

prompt="$(preamble "$PROJECT")

$(crew_role inspector)

--- THIS INSPECTION ---

You are looking at the working tree of pull request #$PR, checked out at its own
head. The change is already applied around you, and its diff is below (read by the harness; you have no git).

$(wt_diff "$WT" "origin/$(project_get "$PROJECT" default_branch main)" | untrusted "diff of pull request #$PR")

$(printf '%s\n' "$claim" | untrusted "pull request and issue text")

The project's verify command was run here by the harness, before you saw it:
  command : ${VERIFY:-none configured}
  exit    : $verify_rc
  output  :
$(printf '%s\n' "$verify_out" | untrusted "output of the verify command")

The pull request's own checks on GitHub, read by the harness:
  passing       : $CI_PASSING
$(printf 'failing       : %s\nstill running : %s\n' "${CI_FAILING:-none}" "${CI_PENDING:-none}" | untrusted "CI check names and descriptions")

A failing check is evidence. Say whether it fails because of this change — the
code is wrong — or because of something outside it: the pipeline, an account,
a flaky runner. Use its description to name the cause when it tells you. A pull
request whose own checks fail is not PROVEN, whatever the reason, and the
harness will not let it be.

Answer one question: if this merges, is the thing it claims to fix actually
fixed? Read the code as it now stands and trace the failing path the issue
describes. A description of a fix is not a fix, and a passing type-check is not
evidence that a behaviour changed.

Decide between:
- PROVEN   — you traced the path and the defect cannot occur any more, or a test
             in this diff would fail without the change. Say which.
- UNPROVEN — it plausibly works but nothing here demonstrates it. This is the
             common and correct answer for a change with no test. Say exactly
             what would settle it.
- BROKEN   — it does not fix the issue, fixes only part of it, or breaks
             something else. Say what, with a file and the failing case.

Then describe the one test that would have caught the original defect — whether
or not this PR contains it. Use the repo's existing test style and name a real
path. If the change genuinely does not warrant a test, say so with exists=true
and explain in \"then\".

${ADR_BLOCK:-}
End your reply with exactly these lines and nothing after them:
TEST_JSON: <one-line JSON object {\"exists\":true|false,\"name\":\"what the test is called\",\"given\":\"the starting state\",\"when\":\"the action\",\"then\":\"the assertion\",\"where\":\"the file it belongs in\"}>
${ADR_SPEC}RESULT: PROVEN <one line> | UNPROVEN <one line> | BROKEN <one line>"

result=$(claude_run "$WT" "$prompt"); rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing posted"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" inspector ERROR "run failed on #$PR"; die "inspector run failed"; }

testjson=$(grep -o 'TEST_JSON: .*' <<<"$result" | tail -1 | sed 's/^TEST_JSON: //')
verdict=$(grep -Eo '^RESULT: (PROVEN|UNPROVEN|BROKEN) .*' <<<"$result" | tail -1 | sed 's/^RESULT: //')
jq -e 'type == "object"' <<<"$testjson" >/dev/null 2>&1 || testjson=""
ADR_NOTE=""
if [ "$ADR_ON" = 1 ]; then
  adr=$(adr_line "$result")
  [ -n "$adr" ] && ADR_NOTE=$'\n_Decisions on record_: '"$ADR_SEARCHED"$'. '"${adr#ADR: }"
  [ -n "$adr" ] || verdict=""
fi
[ -n "$verdict" ] || {
  record_run "$PROJECT" inspector ERROR "unparseable contract on #$PR"
  die "contract did not parse — nothing posted (see logs/runs/$QUARTERDECK_RUN_ID.json)"; }

state=${verdict%% *}
detail=${verdict#* }

# A rule, not a request: nothing is PROVEN while its own checks are red.
if [ "$state" = PROVEN ] && [ -n "$CI_FAILING" ]; then
  state=UNPROVEN
  detail="$detail — but its own checks fail: $(tr '\n' ';' <<<"$CI_FAILING" | sed 's/;$//; s/;/; /g')"
fi

body_out="**Inspection — #$PR**

**$state.** $detail

_Verify_: \`${VERIFY:-none configured}\` exited \`$verify_rc\` on this branch.
_Checks on GitHub_: $CI_PASSING passing${CI_FAILING:+ · **failing:** $(tr '\n' ';' <<<"$CI_FAILING" | sed 's/;$//; s/;/; /g')}${CI_PENDING:+ · still running: $CI_PENDING}${ADR_NOTE}"
if [ -n "$testjson" ] && [ "$(jq -r '.exists' <<<"$testjson")" = false ]; then
  body_out="$body_out

**The test that would settle it** — \`$(jq -r '.where' <<<"$testjson")\`
- *given* $(jq -r '.given' <<<"$testjson")
- *when* $(jq -r '.when' <<<"$testjson")
- *then* $(jq -r '.then' <<<"$testjson")"
fi
body_out="$body_out

<sub>Quarterdeck inspector. The harness ran the check; the model read the code. Neither merged anything.</sub>"

say ""
say "  $state — $detail"
say ""

if [ "$APPLY" = 1 ]; then
  if gh_post 60 pr comment "$PR" -R "$REPO" --body "$body_out" >/dev/null 2>>"$LOG_FILE"; then
    say "quarterdeck: verdict posted to $REPO#$PR"
    record_run "$PROJECT" inspector "$state" "#$PR — $detail" "https://github.com/$REPO/pull/$PR"
  else
    record_run "$PROJECT" inspector ERROR "could not comment on #$PR"
    die "could not post the verdict"
  fi
else
  say "$body_out"
  say ""
  say "quarterdeck: report only — pass --apply to post this on the pull request"
  record_run "$PROJECT" inspector "DRY-RUN" "#$PR — $state: $detail"
fi

exit
}
