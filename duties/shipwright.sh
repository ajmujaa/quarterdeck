#!/bin/bash
# shipwright — take one issue to a branch and a pull request.
#
# The only duty that writes code, so the only one where the model gets Edit and
# Write — and it gets them inside a throwaway git worktree, never the real
# checkout. Publishing stays with the harness: it runs the project's own verify
# command itself rather than believing a claim, refuses a diff that touches a
# forbidden path, and only then commits, pushes and opens the PR.
#
# Contract:
#   RESULT: FIXED <one-line summary> | NEEDS_HUMAN <reason> | NO_CHANGE <reason>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> shipwright --issue <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/shipwright-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
GH="${QUARTERDECK_GH:-gh}"   # a seam for the self-tests and for a stand-in; lib.sh puts the real gh first on PATH
BASE=$(project_get "$PROJECT" default_branch main)
PLAN_TEXT=""

APPLY=0 ISSUE="" PLAN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --issue) ISSUE="${2:-}"; need_num "--issue" "$ISSUE"; shift ;;
    --plan)  PLAN="${2:-}"; shift ;;
    *) die "shipwright: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[ -n "$ISSUE" ] || die "shipwright needs an issue: --issue <number>"
# A plan is a dev panel's ruling: three seats argued the approach and the
# dockmaster settled it. Handed one, the builder implements that decision rather
# than re-deciding it alone — which is the whole point of having held the panel.
if [ -n "$PLAN" ]; then
  [ -f "$PLAN" ] || die "shipwright: no such plan: $PLAN"
  PLAN_TEXT="$(cat "$PLAN")"
fi

# Keyed by the issue, not just the project — matching the worktree below,
# which already isolates the build per issue. Two different issues on the
# same project build side by side; the same issue twice still waits.
acquire_lock "shipwright-$PROJECT-$ISSUE"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-ship-$ISSUE"

meta=$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json number,title,body,state 2>>"$LOG_FILE") \
  || die "cannot read $REPO#$ISSUE"
[ "$(jq -r .state <<<"$meta")" = OPEN ] || die "#$ISSUE is not open"

# Someone may already be on it — you, another agent, or an earlier run of this. A pull
# request that says it closes this issue means the work is taken; opening a
# second one beside it is how two agents end up fixing the same bug twice.
TAKEN=$(guard 60 "$GH" pr list -R "$REPO" --state open --limit 100 \
          --json number,headRefName,closingIssuesReferences \
          --jq "[.[] | select(any(.closingIssuesReferences[]?; .number == $ISSUE))
                 | \"#\\(.number) (\\(.headRefName))\"] | join(\", \")" 2>>"$LOG_FILE" || true)
if [ -n "$TAKEN" ]; then
  say "quarterdeck: #$ISSUE already has an open pull request — $TAKEN. Not opening a second."
  record_run "$PROJECT" shipwright TAKEN "#$ISSUE already has $TAKEN"
  exit 0
fi
title=$(jq -r .title <<<"$meta")
body=$(jq -r .body <<<"$meta")

slug=$(tr '[:upper:]' '[:lower:]' <<<"$title" | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-40)
BRANCH="fix/${ISSUE}-${slug}"
WT="$QUARTERDECK_HOME/workspace/wt-${PROJECT}-${ISSUE}"

cleanup_wt() { safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap 'cleanup_wt' EXIT

working_on "issue #$ISSUE — $title"
say "quarterdeck: shipwright on $REPO#$ISSUE — $title"

# Always branch from the freshest base, never from whatever the working copy
# happens to be sitting on.
guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || log "fetch failed; using local $BASE"
cleanup_wt
safe_git -C "$SOURCE_REPO_DIR" worktree add -q --detach "$WT" "origin/$BASE" 2>>"$LOG_FILE" \
  || safe_git -C "$SOURCE_REPO_DIR" worktree add -q --detach "$WT" "$BASE" 2>>"$LOG_FILE" \
  || die "could not create a worktree at $WT"
worktree_pin "$WT" || die "could not pin the worktree's .git file"
# -B, not -b: a previous dry run on this issue leaves the branch behind, and a
# re-run should start again from base rather than refuse to run at all.
safe_git -C "$WT" checkout -q -B "$BRANCH" 2>>"$LOG_FILE" || die "could not create branch $BRANCH"

# A worktree has no node_modules, so any verify command that needs them fails
# for a reason that has nothing to do with the change. Borrow the real one.
# Recorded (<wt>.nmlink) the way worktree_at does it, or the check sandbox would not let the link in (round 6).
worktree_nm_borrow "$SOURCE_REPO_DIR" "$WT"

# What the verify command is made of, before the model has touched anything (see model_diff_gate).
INPUTS_BEFORE="$(verify_inputs "$WT")"

# Baseline every gate the project declares BEFORE touching anything. A repo
# with pre-existing failures would otherwise block every change on faults it
# already had.
say "  baselining local checks"
BASE_CHECKS="$(run_checks "$PROJECT" "$WT")"
wt_mark "$WT"          # what git ignores now (the node_modules link, build output): the gate examines every ignored file added after this
CHECK_LIST="$(jq -rs 'if length == 0 then "" else map("  " + .cmd + "   (currently exit " + (.rc|tostring) + ")") | join("\n") end' <<<"$BASE_CHECKS")"

prompt="$(preamble "$PROJECT")

Fix this one issue. You are in a throwaway worktree on branch $BRANCH; edit
files here freely. Do not commit, push, or open anything — the harness does that
after it has checked your work.

=== $REPO#$ISSUE ===
$(printf '%s\n\n%s\n' "$title" "$body" | untrusted "issue text")
=== END ===

${PLAN_TEXT:+=== THE RULING OF THE DEV PANEL — IMPLEMENT THIS ===
A dev panel argued this out and the dockmaster ruled. It is a decision that has
already been made, not a suggestion: implement it. If you find while building
that the ruling is wrong — it does not compile, it contradicts the code, it
cannot work — stop and say so with NEEDS_HUMAN rather than quietly building
something else.

$PLAN_TEXT
=== END OF RULING ===
}
How to work:
- Read enough of the surrounding code to be sure of the cause. Fix the cause,
  not the symptom, and check whether other call sites have the same problem.
- Make the smallest change that actually fixes it. Do not reformat, refactor
  neighbouring code, or fix unrelated things you notice — say so in your summary
  instead.
- Do not add a dependency.
$([ -n "$CHECK_LIST" ] && echo "- Before you finish, run every one of these and read what they say:
$CHECK_LIST
  That is their state on an untouched tree, so any failure already there is not
  yours. The harness runs all of them again after you stop and refuses the
  change if any gets worse — finding that out yourself now is cheaper.")
- If the issue is unclear, wrong, or needs a product decision, make no change
  and say so. That is a good outcome, not a failure.

End your reply with exactly one line:
RESULT: FIXED <one-line summary of the change>
  or
RESULT: NEEDS_HUMAN <what you need decided>
  or
RESULT: NO_CHANGE <why nothing should change>"

result=$(claude_run "$WT" "$prompt" \
  "Read,Edit,Write,Grep,Glob,Bash(npx tsc*),Bash(npm run*),Bash(node*)" \
  "WebFetch,WebSearch,Bash(git push*),Bash(git commit*),Bash(git checkout*),Bash(git reset*),Bash(gh *),Bash(rm -rf*),Bash(curl*),Bash(ssh*),Bash(npm publish*),Bash(npm install*)")
rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — worktree discarded"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" shipwright ERROR "#$ISSUE run failed"; die "run failed"; }

verdict=$(grep -Eo '^RESULT: (FIXED|NEEDS_HUMAN|NO_CHANGE).*' <<<"$result" | tail -1)
[ -n "$verdict" ] || {
  log "#$ISSUE: contract did not parse — logs/runs/$QUARTERDECK_RUN_ID.json"
  record_run "$PROJECT" shipwright ERROR "#$ISSUE unparseable contract"
  die "contract did not parse — nothing pushed"
}
summary="${verdict#RESULT: }"

case "$verdict" in
  "RESULT: NEEDS_HUMAN"*|"RESULT: NO_CHANGE"*)
    say ""; say "  $summary"
    notify "quarterdeck/$PROJECT #$ISSUE" "$summary"
    record_run "$PROJECT" shipwright "${verdict#RESULT: }" "#$ISSUE"
    exit 0 ;;
esac

# ---- the harness checks the work itself -------------------------------------

# Final paths of everything changed, one per line. Not `status --porcelain`:
# its second field is a rename's OLD name, so a file moved into a forbidden
# path was checked under the name it left.
changed=$(wt_changed "$WT") || { record_run "$PROJECT" shipwright REFUSED "#$ISSUE — the worktree's .git file was changed"; die "refused: the worktree's .git file was changed"; }
[ -n "$changed" ] || {
  say "  claimed FIXED but changed nothing"
  record_run "$PROJECT" shipwright ERROR "#$ISSUE claimed FIXED with an empty diff"
  die "empty diff"
}

# Guardrails stated as prose in the registry are also enforced mechanically
# here, because a prompt is a request and this is a rule.
while read -r forbidden; do
  [ -n "$forbidden" ] || continue
  # A literal prefix, not a regex: a '.' or '[' in a path must mean itself (fp_hit, which also matches "X/" against the bare name X).
  hit=""; while IFS= read -r f; do [ -n "$f" ] && fp_hit "$f" "$forbidden" && { hit=1; break; }; done <<<"$changed"
  if [ -n "$hit" ]; then
    say "  REFUSED: touched a forbidden path ($forbidden)"
    record_run "$PROJECT" shipwright REFUSED "#$ISSUE touched $forbidden"
    die "refused: the change touches $forbidden"
  fi
done < <(jq -r --arg p "$PROJECT" '(.[$p].forbidden_paths // [])[]' "$PROJECTS_FILE")

# A model-made change to CI, dependencies, tool config or the verify command's own inputs is refused BEFORE any check runs: the checks
# are the next thing the harness executes, and what they run is exactly what such a change would control.
if ! why=$(printf '%s\n' "$changed" | model_diff_gate "$PROJECT" "$WT" "$INPUTS_BEFORE" "$PLAN"); then
  say "  REFUSED: $why"
  record_run "$PROJECT" shipwright REFUSED "#$ISSUE — $why"
  die "refused: $why"
fi

say "  re-running local checks"
AFTER_CHECKS="$(run_checks "$PROJECT" "$WT")"
# The checks ran project code that may write in the worktree: the gate again, on what is there now (S1), before anything can be committed.
if ! why=$(post_checks_gate "$PROJECT" "$WT" "$INPUTS_BEFORE" "$changed" "$PLAN"); then
  say "  REFUSED: $why"
  record_run "$PROJECT" shipwright REFUSED "#$ISSUE — $why"
  die "refused: $why"
fi
REGRESSIONS="$(check_regressions "$BASE_CHECKS" "$AFTER_CHECKS")"
if [ "$(jq length <<<"$REGRESSIONS")" != 0 ]; then
  say ""
  say "  REFUSED: the change makes a local check worse"
  jq -r '.[] | "    \(.name): \(.why)  —  \(.cmd)"' <<<"$REGRESSIONS" >&2
  jq -r '.[0].tail' <<<"$REGRESSIONS" | tail -12 | sed 's/^/      /' >&2
  say ""
  say "  worktree kept for inspection: $WT"
  trap - EXIT
  record_run "$PROJECT" shipwright REFUSED "#$ISSUE — $(jq -r '[.[].name] | join(", ")' <<<"$REGRESSIONS") got worse"
  die "refused: nothing is committed when a local check regresses"
fi

say ""
say "── $REPO#$ISSUE — $summary ──"
safe_git -C "$WT" --no-pager diff --cached --stat | sed 's/^/  /' >&2

if [ "$APPLY" != 1 ]; then
  say ""
  say "  (report only — re-run with --apply to push and open a PR)"
  say "  worktree kept for inspection: $WT"
  trap - EXIT   # leave it so the diff can be read
  record_run "$PROJECT" shipwright "DRY-RUN" "#$ISSUE $summary"
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
safe_git -C "$WT" ${COMMIT_ID[@]+"${COMMIT_ID[@]}"} commit -q -m "$(printf 'fix: %s\n\nCloses #%s\n\nOpened by the Quarterdeck shipwright.\n' "$title" "$ISSUE")" \
  || die "commit failed"
safe_git_guard 180 -C "$WT" push -q -u origin "$BRANCH" 2>>"$LOG_FILE" || die "push failed"

pr_body=$(cat <<EOF
$summary

Closes #$ISSUE

---
<!-- quarterdeck:v1 duty=shipwright -->
Opened by the Quarterdeck shipwright.
**Checked locally before this branch was pushed**, in a throwaway worktree at this commit:

$(checks_summary "$AFTER_CHECKS")

Every one of those was also run on an untouched tree first, and the harness refuses to commit anything that makes one of them worse. That is the whole of what has been proven — it is not a claim that the change was exercised by hand or looked at in a browser.
EOF
)
if url=$(gh_post 90 pr create -R "$REPO" --base "$BASE" --head "$BRANCH" \
           --title "fix: $title" --body "$pr_body" 2>>"$LOG_FILE"); then
  say "  ✓ $url"
  record_run "$PROJECT" shipwright "PR" "#$ISSUE → $url" "$url"
else
  record_run "$PROJECT" shipwright ERROR "#$ISSUE pushed but PR failed"
  die "pushed $BRANCH but could not open the PR"
fi

exit
}
