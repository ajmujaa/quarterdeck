#!/bin/bash
# assayer — test the metal, not the smith.
#
# Writes tests from the issue's acceptance checks (the purser's requirements), not from the shipwright's code. The
# model works in a worktree of the BASE branch, so it cannot see the change it is testing, and it may only add test
# files. The harness then decides which tests are worth keeping:
#   - each new test file must FAIL on the base branch (a test that passes before the fix proves nothing and is refused),
#   - and must PASS on the pull request's head (a test that fails there is either wrong or a real defect, and is
#     reported as such, never committed).
# Only tests that did both are committed, to a branch of their own off the pull request's head and opened as a pull request
# into the pull request's branch, so a person merges them. The builder never writes, picks or checks these tests.
#
# Needs two commands in config/projects.json: the project's whole suite as "test", and how to run ONE test file:
#   "test_file": "npx vitest run {file}"        ({file} is replaced by one validated path)
#
#   qtdeck run <p> assayer --issue 204                       write the tests, check they fail on the base; report only
#   qtdeck run <p> assayer --issue 204 --pr 218              also check they pass on the pull request's head
#   qtdeck run <p> assayer --issue 204 --pr 218 --apply      commit the ones that did both, on a branch, as a pull request
#
# Contract:
#   TESTS_JSON: [{"file":"path of the new test file","name":"what it asserts","accept":"the acceptance check it comes from"}]
#   RESULT: WRITTEN <n> test file(s) | NEEDS_HUMAN <reason> | NO_TESTS <reason>
# What the duty records, decided by the harness:
#   VERIFIED <n> | PENDING <reason> | REFUSED <reason> | NEEDS_HUMAN | NO_TESTS | BLOCKED
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> assayer --issue <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/assayer-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
BASE=$(project_get "$PROJECT" default_branch main)
GH="${QUARTERDECK_GH:-gh}"
TEST_FILE_CMD=$(project_get "$PROJECT" test_file)
MAX_FILES="${QUARTERDECK_MAX_ITEMS:-6}"                  # new test files in one run: the cap
MAX_LINES="${QUARTERDECK_ASSAYER_MAX_LINES:-600}"
RUN_SECS="${QUARTERDECK_CHECK_TIMEOUT:-900}"
# Test generation is mechanical work (the fleet policy puts it on Haiku). A caller that chose a model keeps its choice.
export QUARTERDECK_MODEL_PERSONA="${QUARTERDECK_MODEL_ASSAYER:-claude-haiku-4-5}"

APPLY=0 ISSUE="" PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --issue) ISSUE="${2:-}"; need_num "--issue" "$ISSUE"; shift ;;
    --pr)    PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    *) die "assayer: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$ISSUE" =~ ^[0-9]+$ ]] || die "assayer needs an issue: --issue <number>"
[ -z "$PR" ] || [[ "$PR" =~ ^[0-9]+$ ]] || die "assayer: --pr takes a pull request number"

acquire_lock "assayer-$PROJECT-$ISSUE"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-assay-$ISSUE"
WTB="$QUARTERDECK_HOME/workspace/wt-assay-base-${PROJECT}-${ISSUE}"
WTH="$QUARTERDECK_HOME/workspace/wt-assay-head-${PROJECT}-${ISSUE}"
TMP="$(mktemp -d)"
cleanup() {
  [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WTB" >/dev/null 2>&1 || true
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WTH" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap 'cleanup; release_lock' EXIT
blocked() { say "quarterdeck: BLOCKED — $1"; record_run "$PROJECT" assayer BLOCKED "#$ISSUE — $1"; exit 0; }
[ -n "$TEST_FILE_CMD" ] && [[ "$TEST_FILE_CMD" == *"{file}"* ]] || blocked "no \"test_file\" in the registry for $PROJECT (how to run one test file, with {file} in it): without it the harness cannot tell whether a test fails first"

meta=$(guard 60 "$GH" issue view "$ISSUE" -R "$REPO" --json number,title,body,state 2>>"$LOG_FILE") || die "cannot read $REPO#$ISSUE"
[ "$(jq -r .state <<<"$meta")" = OPEN ] || die "#$ISSUE is not open"
title=$(jq -r .title <<<"$meta"); body=$(jq -r .body <<<"$meta")
working_on "issue #$ISSUE — tests for: $title"
say "quarterdeck: assayer on $REPO#$ISSUE — $title"

# The acceptance checks: the purser's block when there is one (its marks are in bin/markers.py), else the whole issue.
checks=$(python3 "$QUARTERDECK_DIR/bin/markers.py" checks <<<"$body")

is_test_path() {
  case "$(tr '[:upper:]' '[:lower:]' <<<"$1")" in
    */test/*|test/*|*/tests/*|tests/*|*/__tests__/*|__tests__/*|*.test.*|*.spec.*|*_test.*|*_spec.*|*/test_*|test_*|*/spec/*|spec/*) return 0 ;;
  esac
  return 1
}
forbidden_hit() {
  local p="$1" f
  while read -r f; do
    [ -n "$f" ] || continue
    fp_hit "$p" "$f" && { printf '%s' "$f"; return 0; }
  done < <(jq -r --arg p "$PROJECT" '(.[$p].forbidden_paths // [])[]' "$PROJECTS_FILE")
  return 1
}
run_one() { # run_one <worktree> <file> — the project's own command for one test file; exit status is the answer
  local cmd="${TEST_FILE_CMD//\{file\}/$(printf '%q' "$2")}" rc=0
  project_exec check "$RUN_SECS" "$1" "$cmd" || rc=$?; printf '%s' "$EXEC_OUT" > "$TMP/run.out"   # a minimal environment, in the sandbox
  return $rc
}
refuse() { # refuse <reason>
  say "  REFUSED: $1"
  record_run "$PROJECT" assayer "$([ "$APPLY" = 1 ] && echo REFUSED || echo DRY-RUN)" "#$ISSUE — $([ "$APPLY" = 1 ] || echo 'would be REFUSED: ')$1"
  exit 0
}

# ---- the base branch, and only the base: the model cannot see the change it will be testing ---------------------------------
guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || log "fetch failed; using local $BASE"
worktree_at "$SOURCE_REPO_DIR" "$WTB" "origin/$BASE" || worktree_at "$SOURCE_REPO_DIR" "$WTB" "$BASE" || die "could not create a worktree at $WTB"
INPUTS_BEFORE="$(verify_inputs "$WTB")"
wt_mark "$WTB"

prompt="$(preamble "$PROJECT")

You are writing tests for one issue, from its acceptance checks alone. You are in a throwaway worktree of the project's
BASE branch: the change that is meant to satisfy the issue does not exist here, and you must not go looking for it. You
are not the person building it and you will not see their code. Write what the checks require, so that anyone's
implementation can be held to them.

$(printf '%s#%s: %s\n\nTHE ACCEPTANCE CHECKS\n%s\n' "$REPO" "$ISSUE" "$title" "$checks" | untrusted "issue title and acceptance checks")

Rules, enforced by the harness:
- Add NEW test files only, in the project's own test folders and style. Do not edit or delete any existing file, test or
  source. Do not add a dependency.
- One test file per acceptance check where that is natural; at most $MAX_FILES files in all.
- Each test must fail on the code as it is now (the feature is not there yet) and pass once the check is truly met. The
  harness runs every file you add on this base branch and refuses any that already passes: a test that passes before the
  change proves nothing.
- Test behaviour a person can observe, not how it is built. Use invented data only.
- At least one test exercises the behaviour: it does the action (click, type, call, run) and asserts what then happens. A test
  that only reads the source or the page and checks that an element, selector, id or string exists is never only that: it
  passes while the feature does nothing. The harness refuses a file that only does that.
- Run what you write if you can, to see it fail for the right reason: failing because the behaviour is missing, not because
  of a typo or a missing import.
- If the issue has no check you can turn into a test, or needs a decision first, write nothing and say so.

End your reply with exactly these two lines and nothing after them:
TESTS_JSON: <one-line JSON array of {\"file\":\"path of the new test file\",\"name\":\"what it asserts\",\"accept\":\"the acceptance check it comes from\"}>
RESULT: WRITTEN <n> test file(s)
  or, instead of both lines, the single line
RESULT: NEEDS_HUMAN <what must be decided>
  or
RESULT: NO_TESTS <why none can be written>"

result=$(claude_run "$WTB" "$prompt" \
  "Read,Edit,Write,Grep,Glob,Bash(npx*),Bash(npm run*),Bash(node*),Bash(python3*),Bash(pytest*)" \
  "WebFetch,WebSearch,Bash(git push*),Bash(git commit*),Bash(git checkout*),Bash(git reset*),Bash(gh *),Bash(rm -rf*),Bash(curl*),Bash(ssh*),Bash(npm publish*),Bash(npm install*)")
rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" assayer ERROR "#$ISSUE run failed"; die "assayer run failed"; }
for kind in NEEDS_HUMAN NO_TESTS; do
  if grep -q "^RESULT: $kind" <<<"$result"; then
    why=$(grep -o "^RESULT: $kind.*" <<<"$result" | tail -1 | sed "s/^RESULT: $kind *//")
    say "  $kind: $why"
    record_run "$PROJECT" assayer "$kind" "#$ISSUE — $why"
    exit 0
  fi
done
tests=$(grep -o '^TESTS_JSON: .*' <<<"$result" | tail -1 | sed 's/^TESTS_JSON: //')
if ! jq -e 'type == "array" and length > 0' <<<"$tests" >/dev/null 2>&1 || ! grep -q '^RESULT: WRITTEN' <<<"$result"; then
  record_run "$PROJECT" assayer ERROR "#$ISSUE unparseable contract"
  die "contract did not parse — nothing written"
fi

# ---- 1. what the model left in the worktree must be new test files, and nothing else ------------------------------------------------
_qd_pin "$WTB" || refuse "the worktree's .git file was changed, so nothing in it was trusted"
modified=$(safe_git -C "$WTB" -c core.quotepath=false diff --no-renames --name-only HEAD)
[ -z "$modified" ] || refuse "it changed existing file(s) ($(tr '\n' ' ' <<<"$modified")): the assayer only adds tests, it never edits what is there"
new=$(safe_git -C "$WTB" -c core.quotepath=false ls-files --others --exclude-standard | sort -u)
[ -n "$new" ] || refuse "it claimed to write tests and added no file"
[ "$(wc -l <<<"$new" | tr -d ' ')" -le "$MAX_FILES" ] || refuse "it added $(wc -l <<<"$new" | tr -d ' ') files; at most $MAX_FILES in one run"
lines=0
while read -r f; do
  [ -n "$f" ] || continue
  [[ "$f" =~ ^[A-Za-z0-9._/@-]+$ ]] && [[ "$f" != *..* ]] || refuse "the file name '$f' is not a plain path"
  is_test_path "$f" || refuse "$f is not a test file (the assayer may add test files only)"
  fp=$(forbidden_hit "$f") && refuse "$f is under the forbidden path $fp"
  jq -e --arg f "$f" 'any(.[]; .file == $f)' <<<"$tests" >/dev/null || refuse "$f was added but is not listed in the contract"
  lines=$((lines + $(wc -l < "$WTB/$f" | tr -d " ")))
done <<<"$new"
while read -r lf; do grep -qxF "$lf" <<<"$new" || refuse "the contract lists $lf, which was not added"; done < <(jq -r '.[].file' <<<"$tests")
[ "$lines" -le "$MAX_LINES" ] || refuse "the tests are $lines lines; at most $MAX_LINES"
why=$(printf '%s\n' "$new" | model_diff_gate "$PROJECT" "$WTB" "$INPUTS_BEFORE") || refuse "$why"

# ---- 2. each test must fail on the base ----------------------------------------------------------------------------------------------
keep=""; passed_on_base=""
while read -r f; do
  [ -n "$f" ] || continue
  if run_one "$WTB" "$f"; then passed_on_base="${passed_on_base:+$passed_on_base, }$f"
  else say "  fails on $BASE, as it should: $f"; keep="${keep:+$keep$'\n'}$f"; fi
done <<<"$new"
# #86: a file that only looks for a string or an element proves nothing about what the feature does
only_exists=""; kept2=""
while read -r f; do
  [ -n "$f" ] || continue
  if python3 "$QUARTERDECK_DIR/bin/behaviour.py" test "$WTB/$f"; then kept2="${kept2:+$kept2$'\n'}$f"; else only_exists="${only_exists:+$only_exists, }$f"; fi
done <<<"$keep"
[ -z "$only_exists" ] || say "  refused (it only checks that something exists, it does not exercise the behaviour): $only_exists"
keep="$kept2"
[ -z "$passed_on_base" ] || say "  refused (it already passes on $BASE, so it proves nothing): $passed_on_base"
[ -n "$keep" ] || [ -z "$only_exists" ] || refuse "every test it wrote only checks that something exists ($only_exists); at least one must exercise the behaviour"
[ -n "$keep" ] || refuse "no test fails on $BASE: every one already passes ($passed_on_base), so none proves anything"

if [ -z "$PR" ]; then
  say ""; say "quarterdeck: $(wc -l <<<"$keep" | tr -d ' ') test file(s) fail on $BASE. Nothing is committed without a pull request to check them against (--pr <n>)."
  record_run "$PROJECT" assayer "$([ "$APPLY" = 1 ] && echo PENDING || echo DRY-RUN)" "#$ISSUE — $(wc -l <<<"$keep" | tr -d ' ') test file(s) fail on $BASE; pass on the pull request's head not yet checked"
  exit 0
fi

# ---- 3. and pass on the pull request's head -------------------------------------------------------------------------------------------
pmeta=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json number,title,state,headRefOid,headRefName,isCrossRepository 2>>"$LOG_FILE") || die "cannot read $REPO#$PR"
sha=$(jq -r '.headRefOid // ""' <<<"$pmeta"); HEADBR=$(jq -r '.headRefName // ""' <<<"$pmeta")
guard 180 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "pull/$PR/head" 2>>"$LOG_FILE" || die "could not fetch pull/$PR/head"
worktree_at "$SOURCE_REPO_DIR" "$WTH" FETCH_HEAD || die "could not create a worktree at $WTH"
verified=""; failed_on_head=""
while read -r f; do
  [ -n "$f" ] || continue
  mkdir -p "$WTH/$(dirname "$f")"; cp "$WTB/$f" "$WTH/$f"
  if run_one "$WTH" "$f"; then say "  passes on the head of #$PR: $f"; verified="${verified:+$verified$'\n'}$f"
  else failed_on_head="${failed_on_head:+$failed_on_head$'\n'}$f"; say "  FAILS on the head of #$PR: $f"; fi
done <<<"$keep"
nver=$(grep -c . <<<"$verified" || true); nfail=$(grep -c . <<<"$failed_on_head" || true)

# A test that fails on the head is not committed. It is reported: the head does not meet that check, or the test is wrong.
if [ "$APPLY" = 1 ] && [ "${nfail:-0}" -gt 0 ]; then
  mkdir -p "$QUARTERDECK_HOME/state/findings"
  fj=$(while read -r f; do [ -n "$f" ] || continue
         jq -nc --arg f "$f" --arg a "$(jq -r --arg f "$f" '.[] | select(.file == $f) | .accept' <<<"$tests")" --arg n "$(jq -r --arg f "$f" '.[] | select(.file == $f) | .name' <<<"$tests")" \
            '{severity:"major", title:("The head does not meet an acceptance check: " + $n), body:("A test written from the issue alone, \($f), fails on this head and failed on the base.\nAcceptance check: \($a)\nEither the head does not do this yet, or the test is wrong. A person decides which."), file:"", line:0, paths:[], kind:"code", evidence:$f}'
       done <<<"$failed_on_head" | jq -sc 'to_entries | map(.value + {id: ("assayer-" + ((.key + 1) | tostring))})')
  jq -n --arg d assayer --arg p "$PROJECT" --argjson pr "$PR" --arg h "$sha" --arg at "$(date -u +%FT%TZ)" --argjson f "$fj" \
    '{duty:$d, project:$p, pr:$pr, head:$h, at:$at, verdict:("FINDINGS " + ($f | length | tostring)), findings:$f}' > "$QUARTERDECK_HOME/state/findings/${PROJECT}-pr${PR}-assayer.json"
fi
[ "${nver:-0}" -gt 0 ] || refuse "no test both fails on $BASE and passes on the head of #$PR ($nfail fail on the head$([ "$APPLY" = 1 ] && echo '; recorded as findings'))"

say ""
say "── $nver test file(s) fail on $BASE and pass on #$PR ──"
sed 's/^/  /' <<<"$verified" >&2
if [ "$APPLY" != 1 ]; then
  say ""; say "  (report only — re-run with --apply to commit them on a branch and open a pull request into #$PR's branch)"
  record_run "$PROJECT" assayer "DRY-RUN" "#$ISSUE — $nver would be VERIFIED against #$PR"
  exit 0
fi
[ "$(jq -r '.isCrossRepository // false' <<<"$pmeta")" = false ] && [[ "$HEADBR" =~ ^[A-Za-z0-9._/-]+$ ]] && [ "$HEADBR" != "$BASE" ] \
  || refuse "the pull request's branch is on a fork or is the trunk; the tests are not pushed there"

# ---- 4. commit only what did both, on a branch of its own off the head, and open a pull request into the head's branch ----------------
slug=$(tr '[:upper:]' '[:lower:]' <<<"$title" | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-30 | sed -E 's/-+$//')
BR="assay/${ISSUE}-${slug:-tests}"
safe_git -C "$SOURCE_REPO_DIR" ls-remote --exit-code --heads origin "$BR" >/dev/null 2>&1 \
  && refuse "$BR is already proposed; merge or close that pull request first"
safe_git -C "$WTH" checkout -q -B "$BR" 2>>"$LOG_FILE" || die "could not create branch $BR"
safe_git -C "$WTH" reset -q --hard "$sha" && safe_git -C "$WTH" clean -qfd
while read -r f; do [ -n "$f" ] || continue; mkdir -p "$WTH/$(dirname "$f")"; cp "$WTB/$f" "$WTH/$f"; safe_git -C "$WTH" add -- "$f"; done <<<"$verified"
[ "$(safe_git -C "$WTH" diff --cached --name-only | sort)" = "$(sort <<<"$verified")" ] || die "assayer: the commit would hold more than the verified tests; nothing committed"
commit_identity "$PROJECT" "$WTH" || die "no commit identity for $PROJECT: GitHub could not be asked for the account's no-reply address and the checkout has no user.email (set \"git\": {\"name\", \"email\"} in the registry)"
safe_git -C "$WTH" ${COMMIT_ID[@]+"${COMMIT_ID[@]}"} commit -q -m "$(printf 'test: acceptance checks of #%s\n\nEach test fails on %s and passes on the head of #%s.\nWritten from the issue alone by the Quarterdeck assayer, not by the builder.\n' "$ISSUE" "$BASE" "$PR")" || die "commit failed"
safe_git_guard 180 -C "$WTH" push -q origin "HEAD:refs/heads/$BR" 2>>"$LOG_FILE" || { record_run "$PROJECT" assayer ERROR "#$ISSUE push of $BR refused"; die "push failed"; }
pr_body="Tests written from the acceptance checks of #$ISSUE, by someone other than the builder.

$(sed 's/^/- `/; s/$/`/' <<<"$verified")

The harness ran every file on \`$BASE\` (each fails) and on the head of #$PR (each passes), and committed only those. Merging this adds them to #$PR's branch.

<sub>Quarterdeck assayer. The model wrote the tests from the issue alone; the harness decided which to keep. Nothing was merged.</sub>"
if url=$(gh_post 90 pr create -R "$REPO" --base "$HEADBR" --head "$BR" --title "test: acceptance checks of #$ISSUE" --body "$pr_body" 2>>"$LOG_FILE"); then
  say "  ✓ $url"
  record_run "$PROJECT" assayer VERIFIED "#$ISSUE — $nver test file(s) → $url" "$url"
else
  record_run "$PROJECT" assayer ERROR "#$ISSUE pushed $BR but the pull request failed"
  die "pushed $BR but could not open the pull request"
fi

exit
}
