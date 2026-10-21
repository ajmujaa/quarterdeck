#!/bin/bash
# The caulker is the one new duty that edits code, so what it may NOT do is what is asserted: change a file no finding
# names, edit a test to make code pass, touch a forbidden path, make a check worse, push anywhere but the pull request's
# own branch, or run more than three cycles. Run against stand-ins for the model (which edits a throwaway worktree
# through a hook) and gh, and a real git repository of invented files.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_skip_if_nested_sandbox selftest-caulker
st_init caulker
st_repo
st_pr 1 feat-bug src/calc.js $'// GOOD\nfunction add(a, b) { return a - b }\n' tests/calc.test.js $'assert(add(1, 2) === 3)\n' lib/crypto/key.js $'export const k = 1\n' src/other.js $'x\n'
sha() { jq -r .headRefOid "$T/ghdata/pr-1.json"; }
refs() { git -C "$T/origin.git" for-each-ref --format='%(refname) %(objectname)' | sort; }
st_registry '["caulker"]' '{"verify":"grep -q GOOD src/calc.js","forbidden_paths":["lib/crypto/"]}'
SHA=$(sha)
mkfind() { # mkfind <duty> <verdict> <findings-json> [head]
  mkdir -p "$T/state/findings"
  jq -n --arg d "$1" --arg v "$2" --argjson f "$3" --arg h "${4:-$SHA}" '{duty:$d, project:"tp", pr:1, head:$h, verdict:$v, findings:$f}' > "$T/state/findings/tp-pr1-$1.json"
}
FIND='[{"id":"surveyor-1","severity":"major","title":"add subtracts","body":"add returns a - b. It must add.","file":"src/calc.js","line":2,"paths":["src/calc.js"],"kind":"code"}]'
hook() { printf '#!/bin/bash\n%s\n' "$1" > "$T/claude-hook"; chmod +x "$T/claude-hook"; }
OKREPLY='FIXES_JSON: [{"id":"surveyor-1","status":"fixed","note":"now adds"}]
RESULT: SEALED add now adds its arguments'
fresh() { git -C "$T/origin.git" update-ref refs/heads/feat-bug "$(jq -r .headRefOid "$T/ghdata/pr-1.json")"; rm -rf "$T/state/cycles" "$T/state/findings" "$T/gh-calls" "$T"/body-*; : > "$T/claude-calls"; st_noreplies; rm -f "$T/claude-hook"; }

# ---- sealing what was found ------------------------------------------------------------------------------------------
fresh; mkfind surveyor "FINDINGS 1" "$FIND"; st_reply default "$OKREPLY"; hook "sed 's/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js"
before=$(refs)
st_duty caulker --pr 1
ck "report only: shows what it would change and pushes, posts and records nothing" 'grep -q "src/calc.js" <<<"$OUT" && [ "$(refs)" = "$before" ] && no_gh_writes && [ "$(last_verdict)" = DRY-RUN ] && [ ! -f "$T/state/cycles/tp-pr1.json" ]'
st_duty caulker --pr 1 --apply
after=$(refs)
ck "--apply commits the change and pushes it to the pull request's own branch" '[ "$(last_verdict)" = SEALED ] && [ "$(git -C "$T/origin.git" rev-parse refs/heads/feat-bug)" != "$SHA" ] && [ "$(git -C "$T/origin.git" show refs/heads/feat-bug:src/calc.js | grep -c "a + b")" = 1 ]'
changed_refs=$(diff <(echo "$before") <(echo "$after") | grep -c '^[<>]')
ck "  and no other ref moved: the trunk and the PR head ref are untouched" '[ "$changed_refs" = 2 ] && [ "$(git -C "$T/origin.git" rev-parse refs/heads/main)" = "$(grep " " <<<"$before" | grep "refs/heads/main " | cut -d" " -f2)" ] && [ "$(git -C "$T/origin.git" rev-parse refs/pull/1/head)" = "$SHA" ]'
ck "  the commit names the findings and says it never approves its own work" 'git -C "$T/origin.git" log -1 --format=%B refs/heads/feat-bug | grep -q "Findings: surveyor-1" && git -C "$T/origin.git" log -1 --format=%B refs/heads/feat-bug | grep -q "never approves"'
ck "  the cycle is counted by the harness, with what the caulker said" 'jq -e ".cycles == 1 and .history[0].outcome == \"SEALED\" and .history[0].notes[0].status == \"fixed\"" "$T/state/cycles/tp-pr1.json" >/dev/null'
ck "  it comments once, and never writes a verdict file of its own" '[ "$(grep -c "^gh pr comment" "$T/gh-calls")" = 1 ] && [ ! -f "$T/state/findings/tp-pr1-caulker.json" ]'
ck "  no pull request was created, merged or approved" '! grep -qE "^gh pr (create|merge|review)" "$T/gh-calls"'
ck "the model is Sonnet by default: a seal is routine work" '[ "$(jq -r .model "$T/claude-calls" | head -1)" = claude-sonnet-5 ]'
ck "the model is given edit tools but nothing that publishes" 'jq -e ".allow | contains(\"Edit\")" "$T/claude-calls" >/dev/null && jq -e ".deny | contains(\"Bash(git push\") and contains(\"Bash(git commit\") and contains(\"Bash(gh \")" "$T/claude-calls" >/dev/null'
ck "  the findings reach it as data to check, with the files it may change" 'grep -q "claims made by other agents" "$T/claude-calls" && grep -q "files you may change: src/calc.js" "$T/claude-calls"'

# ---- what the harness refuses ---------------------------------------------------------------------------------------
reject_case() { # reject_case <label> <hook> <expected text in the detail> [findings-json]
  fresh; mkfind surveyor "FINDINGS 1" "${4:-$FIND}"; st_reply default "$OKREPLY"; hook "$2"
  local b a; b=$(refs); st_duty caulker --pr 1 --apply; a=$(refs); EXP="$3"
  ck "$1: REJECTED, nothing pushed, and the attempt still counts" '[ "$(last_verdict)" = REJECTED ] && grep -q "$EXP" <<<"$(last_detail)" && [ "$a" = "$b" ] && [ "$(jq .cycles "$T/state/cycles/tp-pr1.json")" = 1 ] && [ "$( (grep -c "^gh pr comment" "$T/gh-calls" 2>/dev/null || true) | head -1)" = 0 ]'
}
reject_case "a file no finding names is changed" "sed 's/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js; echo y > src/other.js" "src/other.js, which no finding names"
reject_case "a new file is added" "sed 's/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js; echo y > src/brandnew.js" "src/brandnew.js, which no finding names"
reject_case "a test is edited to make the code pass" "sed 's/=== 3/=== 99/' tests/calc.test.js > tests/calc.test.js.t && mv tests/calc.test.js.t tests/calc.test.js" "the test tests/calc.test.js" '[{"id":"surveyor-1","severity":"major","title":"t","body":"b","file":"tests/calc.test.js","line":1,"paths":["tests/calc.test.js"],"kind":"code"}]'
reject_case "a local check gets worse" "sed 's/GOOD/BAD/; s/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js" "makes a local check worse"
reject_case "the change is larger than a seal" "seq 1 400 | sed 's/^/\/\/ /' >> src/calc.js" "a seal is under 300"
fresh; mkfind surveyor "FINDINGS 1" '[{"id":"surveyor-1","severity":"major","title":"t","body":"b","file":"tests/calc.test.js","line":1,"paths":["tests/calc.test.js"],"kind":"test"}]'
st_reply default 'FIXES_JSON: [{"id":"surveyor-1","status":"fixed","note":"the assertion was wrong"}]
RESULT: SEALED the test asserted the wrong sum'
hook "sed 's/=== 3/=== 3 \&\& true/' tests/calc.test.js > tests/calc.test.js.t && mv tests/calc.test.js.t tests/calc.test.js"
st_duty caulker --pr 1 --apply
ck "a test may be changed when a finding names that test as the defect" '[ "$(last_verdict)" = SEALED ]' 
fresh; mkfind surveyor "FINDINGS 1" '[{"id":"marshal-1","severity":"critical","title":"weak key","body":"b","file":"lib/crypto/key.js","line":1,"paths":["lib/crypto/key.js"],"kind":"code"}]'
st_reply default "$OKREPLY"; hook "echo y > lib/crypto/key.js"
st_duty caulker --pr 1 --apply
ck "a finding that points under a forbidden path is REFUSED before any model is asked" '[ "$(last_verdict)" = REFUSED ] && [ ! -s "$T/claude-calls" ]'
fresh; mkfind surveyor "FINDINGS 1" '[{"id":"pilot-1","severity":"major","title":"flow failed","body":"b","file":"","line":0,"paths":[],"kind":"code"}]'
st_reply default "$OKREPLY"
st_duty caulker --pr 1 --apply
ck "a finding that names no file leaves nothing the caulker may change: NEEDS_HUMAN, no model" '[ "$(last_verdict)" = NEEDS_HUMAN ] && [ ! -s "$T/claude-calls" ]'
fresh; mkfind pilot "FAILED 1" '[{"id":"pilot-1","severity":"major","title":"flow failed","body":"b","file":"","line":0,"paths":[],"kind":"code"}]'; mkfind surveyor "FINDINGS 1" "$FIND"
st_reply default "$OKREPLY"; hook "sed 's/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js"
st_duty caulker --pr 1 --apply
ck "a finding with no file does not take the actionable ones down with it: the model sees only the finding that names a file, and its fix is pushed" '[ "$(last_verdict)" = SEALED ] && grep -q "surveyor-1" "$T/claude-calls" && ! grep -q "pilot-1" "$T/claude-calls" && grep -q "name no file and are left to a person: pilot-1" <<<"$OUT"'

# ---- nothing to do, and an unparseable reply -----------------------------------------------------------------------------
fresh; mkfind surveyor "FINDINGS 1" "$FIND" "0000000000000000000000000000000000000000"; st_reply default "$OKREPLY"
st_duty caulker --pr 1 --apply
ck "findings about an older head are not open: nothing to seal, no model" '[ "$(last_verdict)" = NOTHING ] && [ ! -s "$T/claude-calls" ]'
fresh; mkfind pilot "PASSED" '[]'; mkfind surveyor CLEAN '[]'
st_duty caulker --pr 1 --apply
ck "clean verdicts leave nothing open" '[ "$(last_verdict)" = NOTHING ]'
fresh; mkfind surveyor "FINDINGS 1" "$FIND"; st_reply default 'I fixed it, trust me.'; hook "sed 's/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js"
b=$(refs); st_duty caulker --pr 1 --apply
ck "an unparseable reply is an ERROR run that pushes and posts nothing" '[ "$(last_verdict)" = ERROR ] && [ "$(refs)" = "$b" ] && no_gh_writes'
ck "  and it still counts as a cycle, so a loop of bad replies ends" '[ "$(jq .cycles "$T/state/cycles/tp-pr1.json")" = 1 ]'

# ---- three cycles, then a person ---------------------------------------------------------------------------------------------
fresh; mkfind surveyor "FINDINGS 1" "$FIND"; st_reply default "$OKREPLY"; hook "sed 's/a - b/a + b/' src/calc.js > src/calc.js.t && mv src/calc.js.t src/calc.js"
mkdir -p "$T/state/cycles"
jq -n '{pr:1, cycles:3, needs_human:false, history:[
  {cycle:1, outcome:"SEALED", summary:"used plus", notes:[{id:"surveyor-1",status:"fixed",note:"now adds"}], head:"a", at:"t"},
  {cycle:2, outcome:"SEALED", summary:"used plus again", notes:[{id:"surveyor-1",status:"disagree",note:"the finding is about a different line"}], head:"b", at:"t"},
  {cycle:3, outcome:"SEALED", summary:"third try", notes:[], head:"c", at:"t"}]}' > "$T/state/cycles/tp-pr1.json"
b=$(refs); st_duty caulker --pr 1
ck "after three cycles with a finding still open, report-only says it would hand over, and changes nothing" 'grep -q "needs a person" <<<"$OUT" && [ "$(refs)" = "$b" ] && no_gh_writes && [ ! -s "$T/claude-calls" ]'
st_duty caulker --pr 1 --apply
ck "--apply labels the pull request needs-human, once, and asks no model" 'grep -q "^gh pr edit 1 .*--add-label needs-human" "$T/gh-calls" && [ ! -s "$T/claude-calls" ] && [ "$(last_verdict)" = NEEDS_HUMAN ]'
ck "  and the comment states both positions: the reviewer and what the caulker did" 'cat "$T"/body-* | grep -qF "Reviewer (surveyor, major):** add subtracts" && cat "$T"/body-* | grep -q "What the caulker did" && cat "$T"/body-* | grep -q "the finding is about a different line"'
ck "  and it pushed nothing" '[ "$(refs)" = "$b" ]'
rm -f "$T/gh-calls"; : > "$T/claude-calls"
st_duty caulker --pr 1 --apply
ck "  a later run does nothing: no second label, no comment, no model" '! grep -qE "pr edit|pr comment" "$T/gh-calls" 2>/dev/null && [ ! -s "$T/claude-calls" ]'
fresh; mkfind surveyor "FINDINGS 1" "$FIND"; st_reply default 'no contract here'
for i in 1 2 3; do st_duty caulker --pr 1 --apply; done
calls=$(wc -l < "$T/claude-calls" | tr -d ' '); : > "$T/claude-calls"
st_duty caulker --pr 1 --apply
ck "three attempts that never parse use up the cycles: the fourth asks no model and hands the pull request to a person" '[ "$calls" = 3 ] && [ ! -s "$T/claude-calls" ] && [ "$(last_verdict)" = NEEDS_HUMAN ] && grep -q "add-label needs-human" "$T/gh-calls" && [ "$(jq .cycles "$T/state/cycles/tp-pr1.json")" = 3 ]'

# ---- never the trunk, never a fork -------------------------------------------------------------------------------------------------
fresh; mkfind surveyor "FINDINGS 1" "$FIND"; st_reply default "$OKREPLY"
jq '.isCrossRepository = true' "$T/ghdata/pr-1.json" > "$T/x" && mv "$T/x" "$T/ghdata/pr-1.json"
st_duty caulker --pr 1 --apply
ck "a pull request from a fork is NEEDS_HUMAN: the harness pushes only to a branch of the repository" '[ "$(last_verdict)" = NEEDS_HUMAN ] && [ ! -s "$T/claude-calls" ]'
jq '.isCrossRepository = false | .headRefName = "main"' "$T/ghdata/pr-1.json" > "$T/x" && mv "$T/x" "$T/ghdata/pr-1.json"
fresh; mkfind surveyor "FINDINGS 1" "$FIND"; st_reply default "$OKREPLY"
st_duty caulker --pr 1 --apply
ck "a pull request whose branch is the trunk is REFUSED, and no model is asked" '[ "$(last_verdict)" = REFUSED ] && [ ! -s "$T/claude-calls" ]'
jq '.headRefName = "feat-bug"' "$T/ghdata/pr-1.json" > "$T/x" && mv "$T/x" "$T/ghdata/pr-1.json"

# ---- structure ------------------------------------------------------------------------------------------------------------------------------
ck "the duty is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/duties/caulker.sh" && [ "$(tail -c 3 "$REAL/duties/caulker.sh" | tr -d "\n")" = "}" ]'
ck "the only push in the duty is an explicit refspec to one branch, never forced" '[ "$(grep -cE "(safe_git|SAFE_GIT).* push" "$REAL/duties/caulker.sh" | tr -d " ")" -ge 1 ] && ! grep -E "push.*(--force|-f |--force-with-lease|\+HEAD)" "$REAL/duties/caulker.sh" | grep -v "^#" | grep -q . && grep -q "HEAD:refs/heads/\$BRANCH" "$REAL/duties/caulker.sh"'
st_done
