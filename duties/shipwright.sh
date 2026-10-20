#!/bin/bash
# shipwright — take one issue to a branch and a pull request.
#
# The only duty that writes code, so the only one where the model gets Edit and
# Write — and it gets them inside a throwaway git worktree, never the real
# checkout. Publishing stays with the harness: it runs the project's own verify
# command itself rather than believing a claim, refuses a diff that touches a
# forbidden path, and only then commits, pushes and opens the PR.
#
# A LOCAL ticket (qtdeck ticket; the project needs no GitHub repo) is built the same way and ends differently: --ticket <n> commits on a local branch
# ticket/<n>-<slug> in the project's own checkout and STOPS. Nothing is pushed, no pull request is opened or looked up, and gh is not called. The
# ticket becomes "review", with the branch, and the message says how to read the change and how to throw it away.
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

APPLY=0 ISSUE="" PLAN="" TICKET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --issue) ISSUE="${2:-}"; need_num "--issue" "$ISSUE"; shift ;;
    --ticket) TICKET="${2:-}"; need_num "--ticket" "$TICKET"; shift ;;
    --plan)  PLAN="${2:-}"; shift ;;
    *) die "shipwright: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[ -z "$ISSUE" ] || [ -z "$TICKET" ] || die "shipwright: --issue and --ticket are two different jobs; give one"
[ -n "$ISSUE$TICKET" ] || die "shipwright needs an issue: --issue <number> (or --ticket <number> for a local ticket)"
REF="#$ISSUE"; KEY="$ISSUE"
[ -z "$TICKET" ] || { REF="ticket #$TICKET"; KEY="t$TICKET"; }
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
acquire_lock "shipwright-$PROJECT-$KEY"
if [ -n "$TICKET" ]; then
  # a local ticket: its text is in the data folder, nothing is read from GitHub
  ticket_load "$PROJECT" "$TICKET"
  export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$PROJECT")-ship-$KEY"
  meta=$(jq -c '{number: .id, title: .title, body: .body, state: "OPEN"}' <<<"$TK_JSON")
  TAKEN=""
else
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
fi
title=$(jq -r .title <<<"$meta")
body=$(jq -r .body <<<"$meta")
[ -z "$TICKET" ] || body="$TK_TEXT"

slug=$(tr '[:upper:]' '[:lower:]' <<<"$title" | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-40)
BRANCH="fix/${ISSUE}-${slug}"
[ -z "$TICKET" ] || BRANCH="ticket/${TICKET}-${slug:-ticket}"
WT="$QUARTERDECK_HOME/workspace/wt-${PROJECT}-${KEY}"
BASE_REF="origin/$BASE"

cleanup_wt() { safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap 'cleanup_wt' EXIT

if [ -n "$TICKET" ]; then
  working_on "ticket #$TICKET: $title"
  say "quarterdeck: shipwright on $PROJECT, local ticket #$TICKET: $title"
else
  working_on "issue #$ISSUE — $title"
  say "quarterdeck: shipwright on $REPO#$ISSUE — $title"
fi

# A branch that already holds a build of this ticket is the owner's to review or throw away; building again would reset it.
if [ -n "$TICKET" ] && safe_git -C "$SOURCE_REPO_DIR" rev-parse --verify -q "refs/heads/$BRANCH" >/dev/null 2>&1; then
  ahead=$(safe_git -C "$SOURCE_REPO_DIR" rev-list --count "$BASE..$BRANCH" 2>/dev/null || echo 0)
  if [ "${ahead:-0}" != 0 ]; then
    record_run "$PROJECT" shipwright REFUSED "$REF: the branch $BRANCH already holds a build"
    die "refused: the branch $BRANCH already holds an earlier build of this ticket. Review it (git -C $SOURCE_REPO_DIR diff $BASE...$BRANCH) or throw it away (git -C $SOURCE_REPO_DIR branch -D $BRANCH), then run this again"
  fi
fi

# Always branch from the freshest base, never from whatever the working copy
# happens to be sitting on.
guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || log "fetch failed; using local $BASE"
cleanup_wt
if ! safe_git -C "$SOURCE_REPO_DIR" worktree add -q --detach "$WT" "origin/$BASE" 2>>"$LOG_FILE"; then
  BASE_REF="$BASE"
  safe_git -C "$SOURCE_REPO_DIR" worktree add -q --detach "$WT" "$BASE" 2>>"$LOG_FILE" \
    || die "could not create a worktree at $WT"
fi
worktree_pin "$WT" || die "could not pin the worktree's .git file"
# -B, not -b: a previous dry run on this issue leaves the branch behind, and a
# re-run should start again from base rather than refuse to run at all.
safe_git -C "$WT" checkout -q -B "$BRANCH" 2>>"$LOG_FILE" || die "could not create branch $BRANCH"

# A worktree has no node_modules, so any verify command that needs them fails
# for a reason that has nothing to do with the change. Borrow the real one.
# Recorded (<wt>.nmlink) the way worktree_at does it, or the check sandbox would not let the link in (round 6).
worktree_nm_borrow "$SOURCE_REPO_DIR" "$WT"

# Terraform (ticket #101): a plan item whose Where field is one folder (`infra/net/`) lets the builder change the *.tf files, and the *.tfvars
# files without a secret-looking value, under that folder (bin/protect.py decides, at the gate). The folder must be in the checkout before the
# model runs. The harness then runs terraform fmt and validate itself, and the infra duty reviews the diff.
TF_FOLDERS="" TF_PLUGINS=""
if [ -n "$PLAN" ]; then
  tf_named=$(python3 "$QUARTERDECK_DIR/bin/protect.py" folders --plan "$PLAN") || die "shipwright: could not read the plan's Where fields"
  TF_FOLDERS=$(python3 "$QUARTERDECK_DIR/bin/protect.py" folders --plan "$PLAN" --root "$WT") || die "shipwright: could not check the plan's folders"
  if [ "$tf_named" != "$TF_FOLDERS" ]; then
    record_run "$PROJECT" shipwright REFUSED "$REF: the plan names a folder that is not a plain folder in the checkout: $(tr '\n' ' ' <<<"$tf_named")"
    die "refused: the plan names a folder ($(tr '\n' ' ' <<<"$tf_named" | sed 's/ $//')) that is not a plain folder in the checkout; a folder Where must already exist, inside the project, with no link in it"
  fi
  TF_PLUGINS=$(project_get "$PROJECT" terraform_plugin_dir)
fi

# What the verify command is made of, before the model has touched anything (see model_diff_gate).
INPUTS_BEFORE="$(verify_inputs "$WT")"

# Baseline every gate the project declares BEFORE touching anything. A repo
# with pre-existing failures would otherwise block every change on faults it
# already had.
say "  baselining local checks"
BASE_CHECKS="$(run_checks "$PROJECT" "$WT")"
[ -z "$TF_FOLDERS" ] || BASE_CHECKS="$BASE_CHECKS${BASE_CHECKS:+
}$(tf_checks "$WT" "$TF_PLUGINS" $TF_FOLDERS)"
wt_mark "$WT"          # what git ignores now (the node_modules link, build output): the gate examines every ignored file added after this
CHECK_LIST="$(jq -rs 'map(select(.name | startswith("terraform ") | not)) | if length == 0 then "" else map("  " + .cmd + "   (currently exit " + (.rc|tostring) + ")") | join("\n") end' <<<"$BASE_CHECKS")"

# Issue 121, QUARTERDECK_BUILD_FOCUS=on: the files the plan names, up front, and a rule to stop once the checks pass. Turns, not wording,
# are what a build costs; a builder that knows where to start and when it is done takes fewer of them.
FOCUS=""
if [ "${QUARTERDECK_BUILD_FOCUS:-off}" = on ]; then
  where_files="$(grep -oE '^\*\*Where\.\*\* `[^`]+`' <<<"$PLAN_TEXT" | sed -E 's/^\*\*Where\.\*\* `//; s/`$//' | sort -u | sed 's/^/    /')"
  FOCUS="${where_files:+- Start from the files the ruling names, and read others only when these show you must:
$where_files
}- Stop as soon as the change is made and the issue's acceptance checks and the
  checks below pass. Do not keep exploring, polishing, or re-running what passed."
fi

if [ -n "$TICKET" ]; then
  WHAT_TO_DO="Build this one ticket. You are in a throwaway worktree on branch $BRANCH; edit
files here freely. Do not commit, push, or open anything — the harness does that
after it has checked your work (and only on a local branch)."
  SUBJECT_HEAD="ticket #$TICKET of $PROJECT"
  SUBJECT_BLOCK=$(printf '%s\n\n%s\n' "$title" "$body" | untrusted "ticket text")
else
  WHAT_TO_DO="Fix this one issue. You are in a throwaway worktree on branch $BRANCH; edit
files here freely. Do not commit, push, or open anything — the harness does that
after it has checked your work."
  SUBJECT_HEAD="$REPO#$ISSUE"
  SUBJECT_BLOCK=$(printf '%s\n\n%s\n' "$title" "$body" | untrusted "issue text")
fi
prompt="$(preamble "$PROJECT")

$WHAT_TO_DO

=== $SUBJECT_HEAD ===
$SUBJECT_BLOCK
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
${TF_FOLDERS:+=== TERRAFORM ===
This item changes Terraform in $(tr '\n' ' ' <<<"$TF_FOLDERS")and nowhere else. You may change only *.tf files there,
and *.tfvars files that hold no secret value. You have no shell; the harness runs terraform fmt and validate itself
after you stop, and an infrastructure review reads your change. Nobody here runs a plan or an apply: a person does.
- Never write a secret value into a file: refer to a secret store or a variable without a default.
- Never edit a backend block, a provider version or a module source, state files, .terraform/ or the lock file.
- Prefer a moved block to a rename. Never remove prevent_destroy, deletion_protection or a retention setting.
- Keep the files formatted the way terraform fmt formats them.
=== END TERRAFORM ===
}
How to work:
- Read enough of the surrounding code to be sure of the cause. Fix the cause,
  not the symptom, and check whether other call sites have the same problem.
- Make the smallest change that actually fixes it. Do not reformat, refactor
  neighbouring code, or fix unrelated things you notice — say so in your summary
  instead.
- Do not add a dependency.
${FOCUS:+$FOCUS
}$([ -n "$CHECK_LIST" ] && echo "- Before you finish, run every one of these and read what they say:
$CHECK_LIST
  That is their state on an untouched tree, so any failure already there is not
  yours. The harness runs all of them again after you stop and refuses the
  change if any gets worse — finding that out yourself now is cheaper.")
- If the $([ -n "$TICKET" ] && echo ticket || echo issue) is unclear, wrong, or needs a product decision, make no change
  and say so. That is a good outcome, not a failure.

End your reply with exactly one line:
RESULT: FIXED <one-line summary of the change>
  or
RESULT: NEEDS_HUMAN <what you need decided>
  or
RESULT: NO_CHANGE <why nothing should change>"

# A Terraform builder gets no shell (ticket #101): a model that cannot run terraform cannot be talked into a plan or an apply.
TOOLS="Read,Edit,Write,Grep,Glob,Bash(npx tsc*),Bash(npm run*),Bash(node*)"
[ -z "$TF_FOLDERS" ] || TOOLS="Read,Edit,Write,Grep,Glob"
result=$(claude_run "$WT" "$prompt" "$TOOLS" \
  "WebFetch,WebSearch,Bash(git push*),Bash(git commit*),Bash(git checkout*),Bash(git reset*),Bash(gh *),Bash(rm -rf*),Bash(curl*),Bash(ssh*),Bash(npm publish*),Bash(npm install*)")
rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — worktree discarded"; exit 0; }
# The turn cap (QUARTERDECK_MAX_TURNS_SHIPWRIGHT): nothing is checked or committed; what the model had done stays in the worktree for a person.
if [ $rc = 4 ]; then
  say "quarterdeck: NEEDS_HUMAN: ran out of turns — nothing committed; partial work kept in $WT"
  trap - EXIT
  notify "quarterdeck/$PROJECT $REF" "ran out of turns"
  record_run "$PROJECT" shipwright NEEDS_HUMAN "$REF ran out of turns (cap ${QUARTERDECK_MAX_TURNS_SHIPWRIGHT:-${QUARTERDECK_MAX_TURNS:-}}); partial work kept in $WT, nothing committed"
  exit 0
fi
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" shipwright ERROR "$REF run failed"; die "run failed"; }

verdict=$(grep -Eo '^RESULT: (FIXED|NEEDS_HUMAN|NO_CHANGE).*' <<<"$result" | tail -1)
[ -n "$verdict" ] || {
  log "$REF: contract did not parse: logs/runs/$QUARTERDECK_RUN_ID.json"
  record_run "$PROJECT" shipwright ERROR "$REF unparseable contract"
  die "contract did not parse — nothing pushed"
}
summary="${verdict#RESULT: }"

case "$verdict" in
  "RESULT: NEEDS_HUMAN"*|"RESULT: NO_CHANGE"*)
    say ""; say "  $summary"
    notify "quarterdeck/$PROJECT $REF" "$summary"
    record_run "$PROJECT" shipwright "${verdict#RESULT: }" "$REF"
    exit 0 ;;
esac

# ---- the harness checks the work itself -------------------------------------

# Final paths of everything changed, one per line. Not `status --porcelain`:
# its second field is a rename's OLD name, so a file moved into a forbidden
# path was checked under the name it left.
changed=$(wt_changed "$WT") || { record_run "$PROJECT" shipwright REFUSED "$REF: the worktree's .git file was changed"; die "refused: the worktree's .git file was changed"; }
[ -n "$changed" ] || {
  say "  claimed FIXED but changed nothing"
  record_run "$PROJECT" shipwright ERROR "$REF claimed FIXED with an empty diff"
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
    record_run "$PROJECT" shipwright REFUSED "$REF touched $forbidden"
    die "refused: the change touches $forbidden"
  fi
done < <(jq -r --arg p "$PROJECT" '(.[$p].forbidden_paths // [])[]' "$PROJECTS_FILE")

# A model-made change to CI, dependencies, tool config or the verify command's own inputs is refused BEFORE any check runs: the checks
# are the next thing the harness executes, and what they run is exactly what such a change would control.
if ! why=$(printf '%s\n' "$changed" | model_diff_gate "$PROJECT" "$WT" "$INPUTS_BEFORE" "$PLAN"); then
  say "  REFUSED: $why"
  record_run "$PROJECT" shipwright REFUSED "$REF: $why"
  die "refused: $why"
fi

say "  re-running local checks"
AFTER_CHECKS="$(run_checks "$PROJECT" "$WT")"
[ -z "$TF_FOLDERS" ] || AFTER_CHECKS="$AFTER_CHECKS${AFTER_CHECKS:+
}$(tf_checks "$WT" "$TF_PLUGINS" $TF_FOLDERS)"
# The checks ran project code that may write in the worktree: the gate again, on what is there now (S1), before anything can be committed.
if ! why=$(post_checks_gate "$PROJECT" "$WT" "$INPUTS_BEFORE" "$changed" "$PLAN"); then
  say "  REFUSED: $why"
  record_run "$PROJECT" shipwright REFUSED "$REF: $why"
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
  record_run "$PROJECT" shipwright REFUSED "$REF: $(jq -r '[.[].name] | join(", ")' <<<"$REGRESSIONS") got worse"
  die "refused: nothing is committed when a local check regresses"
fi

# Terraform: the infra duty reviews exactly what passed (the staged tree, as a commit object no branch points at) against the packs that fit,
# the AWS pack among them. Its report is shown here and goes into the pull request; it is experimental and it is a second opinion, not a gate.
INFRA_REPORT=""
if [ -n "$TF_FOLDERS" ]; then
  say "  infrastructure review (experimental)"
  tf_base=$(safe_git -C "$WT" rev-parse HEAD) && tf_tree=$(safe_git -C "$WT" write-tree) \
    && tf_head=$(safe_git -C "$WT" -c user.name=quarterdeck -c user.email=quarterdeck@example.com commit-tree "$tf_tree" -p "$tf_base" -m "shipwright review of $REF") \
    || tf_head=""
  tf_rep=$(mktemp "$QUARTERDECK_HOME/workspace/infra-review.XXXXXX")
  if [ -n "$tf_head" ] && QUARTERDECK_PROJECT="$PROJECT" QUARTERDECK_WORKDIR="$SOURCE_REPO_DIR" bash "$QUARTERDECK_DIR/duties/infra.sh" --diff "$tf_base" --head "$tf_head" --report-to "$tf_rep" >>"$LOG_FILE" 2>&1 && [ -s "$tf_rep" ]; then
    INFRA_REPORT=$(cat "$tf_rep")
  else
    INFRA_REPORT="**The infrastructure review did not complete** (see the infra log). Nothing was reviewed; read the change yourself. No plan was run by Quarterdeck."
  fi
  rm -f "$tf_rep"
  say ""; say "$INFRA_REPORT"
fi

say ""
if [ -n "$TICKET" ]; then say "── $PROJECT ticket #$TICKET: $summary ──"; else say "── $REPO#$ISSUE: $summary ──"; fi
safe_git -C "$WT" --no-pager diff --cached --stat | sed 's/^/  /' >&2

if [ "$APPLY" != 1 ]; then
  say ""
  if [ -n "$TICKET" ]; then say "  (report only: re-run with --apply to commit it on the local branch $BRANCH)"
  else say "  (report only: re-run with --apply to push and open a PR)"; fi
  say "  worktree kept for inspection: $WT"
  trap - EXIT   # leave it so the diff can be read
  record_run "$PROJECT" shipwright "DRY-RUN" "$REF $summary"
  exit 0
fi

# ---- a local ticket ends here: one commit on a local branch, nothing pushed, no pull request -----------------------------------------------
if [ -n "$TICKET" ]; then
  # Whoever this checkout is configured as; GitHub is not asked (a local ticket never calls gh). A checkout with no identity gets a plain local one.
  COMMIT_ID=()
  tk_email=$(project_get "$PROJECT" git.email); tk_name=$(project_get "$PROJECT" git.name)
  if [ -n "$tk_email" ]; then COMMIT_ID=(-c "user.name=${tk_name:-$tk_email}" -c "user.email=$tk_email")
  elif [ -z "$(safe_git -C "$WT" config user.email || true)" ]; then COMMIT_ID=(-c user.name=Quarterdeck -c user.email=quarterdeck@localhost); fi
  safe_git -C "$WT" ${COMMIT_ID[@]+"${COMMIT_ID[@]}"} commit -q -m "$(printf 'build: %s\n\nTicket #%s\n\nBuilt by the Quarterdeck shipwright for a local ticket.\n' "$title" "$TICKET")" \
    || die "commit failed"
  checks_line=$(jq -rs 'map(.name + " exit " + (.rc|tostring)) | join(", ")' <<<"$AFTER_CHECKS")
  python3 "$TICKETS_PY" set "$PROJECT" "$TICKET" status=review "branch=$BRANCH" 2>>"$LOG_FILE" || log "could not mark ticket $TICKET as in review"
  say "  committed on the local branch $BRANCH (nothing was pushed, no pull request was opened)"
  say ""
  say "  review it:   git -C $SOURCE_REPO_DIR diff $BASE_REF...$BRANCH"
  say "  keep it:     git -C $SOURCE_REPO_DIR merge $BRANCH        (when you are happy with it)"
  say "  discard it:  git -C $SOURCE_REPO_DIR branch -D $BRANCH"
  say "  checks run:  ${checks_line:-none set}"
  if jq -es 'any(.[]; .rc == 127)' <<<"$AFTER_CHECKS" >/dev/null 2>&1; then
    say "  exit 127 means that command was not found. The crew never installs a project's tools: run its install step yourself (for example npm install), or change \"verify\" or \"build\" in the project's entry in $PROJECTS_FILE to a command that needs no install."
  fi
  say "  to open a pull request for it later: connect a repo with  qtdeck repo $PROJECT"
  record_run "$PROJECT" shipwright BRANCH "$REF → $BRANCH; checks: ${checks_line:-none set}"
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
DRAFT=()
if [ -n "$TF_FOLDERS" ]; then
  # Opened as a draft: a Terraform change is ready only when a person has read the review and the project's own plan, and applies it.
  DRAFT=(--draft)
  pr_body="$pr_body

**Terraform (experimental).** Quarterdeck ran no plan and holds no cloud credentials; the checks above are terraform fmt and validate only. Read the project's own CI plan, then apply through your own process.

$INFRA_REPORT"
fi
if url=$(gh_post 90 pr create -R "$REPO" --base "$BASE" --head "$BRANCH" \
           --title "fix: $title" --body "$pr_body" ${DRAFT[@]+"${DRAFT[@]}"} 2>>"$LOG_FILE"); then
  say "  ✓ $url"
  record_run "$PROJECT" shipwright "PR" "#$ISSUE → $url" "$url"
else
  record_run "$PROJECT" shipwright ERROR "#$ISSUE pushed but PR failed"
  die "pushed $BRANCH but could not open the PR"
fi

exit
}
