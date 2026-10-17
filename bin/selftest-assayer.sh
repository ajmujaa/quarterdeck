#!/bin/bash
# The assayer's promise is that the tests come from someone other than the builder and that the harness keeps only a test
# that failed on the base and passes on the head. Run against stand-ins for the model (which writes files into a worktree
# through a hook) and gh, a real git repository, and real python test files run by the registry's own command.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init assayer
st_repo
st_file calc.py $'def add(a, b):\n    return a - b\n'
st_file docs/readme.txt $'plain\n'
st_commit "base"
PR_TITLE="Fix add" PR_BODY="Closes #7" st_pr 3 feat-fix calc.py $'def add(a, b):\n    return a + b  # HEADONLY-MARKER\n'
BODY=$'Unrelated chatter that is not an acceptance check.\n\n<!-- quarterdeck:requirements -->\n## Requirements\n\n1. Adding two numbers returns their sum\n   - **Accept when:** add(1, 2) equals 3\n<!-- /quarterdeck:requirements -->\n'
st_issue 7 "Add returns the sum" "$BODY"
st_registry '["assayer"]' '{"test_file":"PYTHONPATH=. python3 {file}","forbidden_paths":["lib/crypto/"]}'
refs() { git -C "$T/origin.git" for-each-ref --format='%(refname) %(objectname)' | sort; }
hook() { printf '#!/bin/bash\n%s\n' "$1" > "$T/claude-hook"; chmod +x "$T/claude-hook"; }
fresh() { rm -rf "$T/state/findings" "$T"/body-* "$T/gh-calls"; : > "$T/claude-calls"; st_noreplies; rm -f "$T/claude-hook"; }
W='TESTS_JSON: [{"file":"tests/test_add.py","name":"add returns the sum","accept":"add(1, 2) equals 3"}]
RESULT: WRITTEN 1 test file(s)'
GOODTEST='mkdir -p tests; printf "from calc import add\nassert add(1, 2) == 3\n" > tests/test_add.py'

# ---- the registry must say how to run one file ----------------------------------------------------------------------------------
st_registry '["assayer"]' '{}'; fresh; st_reply default "$W"
st_duty assayer --issue 7
ck "no test_file command: BLOCKED with the reason, and no model was asked" '[ "$(last_verdict)" = BLOCKED ] && grep -q "test_file" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
st_registry '["assayer"]' '{"test_file":"PYTHONPATH=. python3 {file}","forbidden_paths":["lib/crypto/"]}'

# ---- the model writes from the issue alone, on the base ------------------------------------------------------------------------------
fresh; st_reply default "$W"; hook "$GOODTEST"
before=$(refs); st_duty assayer --issue 7 --pr 3
ck "the prompt has the acceptance checks, and only them when the purser's block is there" 'grep -q "add(1, 2) equals 3" "$T/claude-calls" && ! grep -q "Unrelated chatter" "$T/claude-calls"'
ck "the model never sees the builder's work: the head's code is not in anything it was given" '! grep -q "HEADONLY-MARKER" "$T/claude-calls" && ! grep -qE "pull/3|feat-fix" "$T/claude-calls"'
ck "the model may write files but publish nothing, and is Haiku by default (test generation is mechanical)" 'jq -e ".allow | contains(\"Write\")" "$T/claude-calls" >/dev/null && jq -e ".deny | contains(\"Bash(git push\") and contains(\"Bash(gh \")" "$T/claude-calls" >/dev/null && [ "$(jq -r .model "$T/claude-calls" | head -1)" = claude-haiku-4-5 ]'
ck "report only: the test fails on the base and passes on the head, so it would be VERIFIED; nothing is committed, pushed or posted" 'grep -q "fails on main, as it should" <<<"$OUT" && grep -q "passes on the head of #3" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ] && grep -q "would be VERIFIED" <<<"$(last_detail)" && [ "$(refs)" = "$before" ] && no_gh_writes'
fresh; st_reply default "$W"; hook "$GOODTEST"; before=$(refs)
st_duty assayer --issue 7 --pr 3 --apply
ck "--apply: the test is committed on a branch off the head of the pull request, and nothing else is in the commit" '[ "$(last_verdict)" = VERIFIED ] && [ "$(git -C "$T/origin.git" diff --name-only refs/pull/3/head assay/7-add-returns-the-sum)" = "tests/test_add.py" ]'
ck "  a pull request is opened INTO the pull request's branch, never the trunk, and nothing was merged" 'grep -q "^gh pr create .*--base feat-fix --head assay/7-add-returns-the-sum" "$T/gh-calls" && ! grep -qE "^gh pr (merge|review)" "$T/gh-calls"'
ck "  the trunk, the pull request's own branch and its head ref did not move" '[ "$(git -C "$T/origin.git" rev-parse main)" = "$(grep " " <<<"$before" | grep "refs/heads/main " | cut -d" " -f2)" ] && [ "$(git -C "$T/origin.git" rev-parse refs/heads/feat-fix)" = "$(grep "refs/heads/feat-fix " <<<"$before" | cut -d" " -f2)" ] && [ "$(git -C "$T/origin.git" rev-parse refs/pull/3/head)" = "$(grep "refs/pull/3/head " <<<"$before" | cut -d" " -f2)" ]'
ck "  the commit says the builder did not write it" 'git -C "$T/origin.git" log -1 --format=%B assay/7-add-returns-the-sum | grep -q "not by the builder"'

# ---- the harness refuses a test that does not fail first ---------------------------------------------------------------------------------
fresh; st_reply default "$W"; hook 'mkdir -p tests; printf "from calc import add\nassert True\n" > tests/test_add.py'; before=$(refs)
st_duty assayer --issue 7 --pr 3 --apply
ck "a test that already passes on the base is REFUSED and never committed" '[ "$(last_verdict)" = REFUSED ] && grep -q "already passes" <<<"$(last_detail)" && [ "$(refs)" = "$before" ] && no_gh_writes'
fresh; st_reply default "$W"; hook 'mkdir -p tests; printf "from calc import add\nassert add(1, 2) == 4\n" > tests/test_add.py'; before=$(refs)
st_duty assayer --issue 7 --pr 3 --apply
ck "a test that fails on the head too is not committed; it is recorded as a finding for a person" '[ "$(last_verdict)" = REFUSED ] && [ "$(refs)" = "$before" ] && no_gh_writes && jq -e ".duty == \"assayer\" and (.findings | length) == 1 and (.findings[0].title | contains(\"does not meet an acceptance check\"))" "$T/state/findings/tp-pr3-assayer.json" >/dev/null'
fresh; st_reply default "$W"; hook "$GOODTEST"; before=$(refs)
st_duty assayer --issue 7 --apply
ck "without a pull request nothing can be verified on a head: PENDING, nothing committed, nothing posted" '[ "$(last_verdict)" = PENDING ] && [ "$(refs)" = "$before" ] && no_gh_writes'
fresh; st_reply default "$W"; hook "$GOODTEST"; before=$(refs)
st_duty assayer --issue 7 --pr 3 --apply
ck "a second run while the first branch is still a pull request is REFUSED and pushes nothing" '[ "$(last_verdict)" = REFUSED ] && grep -q "already proposed" <<<"$(last_detail)" && [ "$(refs)" = "$before" ] && ! grep -q "^gh pr create" "$T/gh-calls"'
git -C "$T/origin.git" update-ref -d refs/heads/assay/7-add-returns-the-sum
fresh; st_reply default 'TESTS_JSON: [{"file":"tests/test_a.py","name":"a","accept":"a"},{"file":"tests/test_b.py","name":"b","accept":"b"}]
RESULT: WRITTEN 2 test file(s)'; hook 'mkdir -p tests; printf "from calc import add\nassert add(1, 2) == 3\n" > tests/test_a.py; printf "assert True\n" > tests/test_b.py'
st_duty assayer --issue 7 --pr 3 --apply
ck "of two tests only the one that failed first is kept" '[ "$(last_verdict)" = VERIFIED ] && [ "$(git -C "$T/origin.git" diff --name-only refs/pull/3/head assay/7-add-returns-the-sum)" = "tests/test_a.py" ]'

# ---- what it may not write ---------------------------------------------------------------------------------------------------------------------
refused() { # refused <label> <hook> <detail text> [reply]
  fresh; st_reply default "${4:-$W}"; hook "$2"; local b; b=$(refs); st_duty assayer --issue 7 --pr 3 --apply; EXP="$3"
  ck "$1: REFUSED, nothing committed or posted" '[ "$(last_verdict)" = REFUSED ] && grep -q "$EXP" <<<"$(last_detail)" && [ "$(refs)" = "$b" ] && no_gh_writes'
}
refused "it edits an existing source file" "$GOODTEST; echo '# touched' >> calc.py" "changed existing file"
refused "it edits an existing file that is not code" "$GOODTEST; echo x >> docs/readme.txt" "changed existing file"
refused "it adds a file that is not a test" "$GOODTEST; echo 'x = 1' > helper.py" "is not a test file" 'TESTS_JSON: [{"file":"tests/test_add.py","name":"n","accept":"a"},{"file":"helper.py","name":"n","accept":"a"}]
RESULT: WRITTEN 2 test file(s)'
refused "it adds a test the contract does not list" "$GOODTEST; printf 'assert False\n' > tests/test_extra.py" "not listed in the contract"
refused "the contract lists a file that was not added" "$GOODTEST" "which was not added" 'TESTS_JSON: [{"file":"tests/test_add.py","name":"n","accept":"a"},{"file":"tests/test_ghost.py","name":"n","accept":"a"}]
RESULT: WRITTEN 2 test file(s)'
refused "a test file name with a space or a shell character" "mkdir -p tests; printf 'assert False\n' > 'tests/test a;b.py'" "not a plain path" 'TESTS_JSON: [{"file":"tests/test a;b.py","name":"n","accept":"a"}]
RESULT: WRITTEN 1 test file(s)'
refused "it adds a test under a forbidden path" "mkdir -p lib/crypto/tests; printf 'assert False\n' > lib/crypto/tests/test_key.py" "forbidden path" 'TESTS_JSON: [{"file":"lib/crypto/tests/test_key.py","name":"n","accept":"a"}]
RESULT: WRITTEN 1 test file(s)'
fresh; st_reply default "$W"; hook 'mkdir -p tests; for i in 1 2 3; do printf "assert False\n" > tests/test_$i.py; done'
st_reply default 'TESTS_JSON: [{"file":"tests/test_1.py","name":"n","accept":"a"},{"file":"tests/test_2.py","name":"n","accept":"a"},{"file":"tests/test_3.py","name":"n","accept":"a"}]
RESULT: WRITTEN 3 test file(s)'
QUARTERDECK_MAX_ITEMS=2 st_duty assayer --issue 7 --pr 3 --apply
ck "QUARTERDECK_MAX_ITEMS caps the files in one run" '[ "$(last_verdict)" = REFUSED ] && grep -q "at most 2" <<<"$(last_detail)"'
fresh; st_reply default 'I wrote the tests.'; hook "$GOODTEST"; before=$(refs)
st_duty assayer --issue 7 --pr 3 --apply
ck "an unparseable reply is an ERROR run that commits and posts nothing" '[ "$(last_verdict)" = ERROR ] && [ "$(refs)" = "$before" ] && no_gh_writes'
# ---- #86: tests that only prove a thing exists are not tests of the behaviour ---------------------------------------------------------------
EXIST='mkdir -p tests; printf "src = open(\"calc.py\").read()\nassert \"def add\" in src\nassert \"return\" in src and \"mul\" in src\n" > tests/test_add.py'
refused "#86 a test that only greps the source for a string" "$EXIST" "only checks that something exists"
fresh; st_reply default "$W"; hook "$GOODTEST"; st_duty assayer --issue 7 --pr 3 --apply
ck "#86 a test that calls the code is still accepted" '! grep -q "only checks that something exists" <<<"$(last_detail)"'
ck "#86 the Assayer is told a check that only looks for an element or string is not enough" 'grep -q "exercises the behaviour" "$T/claude-calls" && grep -q "never only that" "$T/claude-calls"'

fresh; st_reply default 'RESULT: NO_TESTS the issue has no acceptance check that can be run'; st_duty assayer --issue 7 --pr 3 --apply
ck "NO_TESTS is a real answer: recorded, nothing written" '[ "$(last_verdict)" = NO_TESTS ] && no_gh_writes'

# ---- structure ----------------------------------------------------------------------------------------------------------------------------------
ck "the duty is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/duties/assayer.sh" && [ "$(tail -c 3 "$REAL/duties/assayer.sh" | tr -d "\n")" = "}" ]'
ck "the worktrees are gone after a run" '[ "$(git -C "$T/work" worktree list | wc -l | tr -d " ")" = 1 ]'
ck "no name uses a word the owner ruled out" '! grep -liE "(^|[^[:alnum:]])(tester|sentry|mender|critic|prover)([^[:alnum:]]|$)" "$REAL/duties/assayer.sh" | grep -q .'
st_done
