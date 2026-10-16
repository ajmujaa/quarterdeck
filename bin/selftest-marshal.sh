#!/bin/bash
# The marshal is read only and its three hard rules live in the harness: a forbidden path is BLOCK before any model
# runs; a clean verdict needs all three seats; nothing is posted or written without --apply. Run here against
# stand-ins for the model and gh and a real git repository of invented files.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init marshal
st_repo
st_pr 1 feat-ok src/ui/Button.tsx 'export const b = 1' README.md '# fixture changed'
st_pr 2 feat-keys lib/crypto/keys.ts 'export const rotate = 1' src/other.ts 'x'
st_pr 3 feat-mig db/migrations/001.sql 'select 1'
st_registry '["marshal"]' '{"forbidden_paths":["lib/crypto/","db/migrations/"]}'

CLEAN='FINDINGS_JSON: []
ADR: searched none
VERDICT: CLEAN'
F1='FINDINGS_JSON: [{"file":"src/ui/Button.tsx","line":1,"severity":"major","title":"Logs the whole request","body":"The error report carries the amount. Log the id only."}]
ADR: searched none
VERDICT: FINDINGS 1'

# ---- 1. forbidden paths: BLOCK before any model ---------------------------------------------------------------
st_noreplies; st_reply default "$CLEAN"
st_duty marshal --pr 2
ck "a diff touching a forbidden path is BLOCK in report-only mode" 'grep -q "BLOCK" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ] && grep -q "BLOCK" <<<"$(last_detail)"'
ck "  and no model was asked" '[ ! -s "$T/claude-calls" ]'
ck "  and nothing was written to GitHub or the findings folder" 'no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
st_duty marshal --pr 2 --apply
ck "--apply records BLOCK, naming the file and the rule, and still asks no model" '[ "$(last_verdict)" = BLOCK ] && grep -q "lib/crypto/keys.ts (lib/crypto/)" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
ck "  and comments once on the pull request" '[ "$(grep -c "^gh pr comment" "$T/gh-calls")" = 1 ]'
ck "  and the findings file says BLOCK for the Caulker and the pipeline" 'jq -e ".verdict == \"BLOCK\" and .duty == \"marshal\"" "$T/state/findings/tp-pr2-marshal.json" >/dev/null'
rm -f "$T/gh-calls"
st_duty marshal --pr 3 --apply
ck "a migration is BLOCK too" '[ "$(last_verdict)" = BLOCK ] && grep -q "db/migrations/001.sql" <<<"$(last_detail)"'
st_registry '["marshal"]' '{"forbidden_paths":["lib/crypto"]}'
st_pr 4 feat-lookalike lib/crypto-notes/readme.md 'x'
st_noreplies; st_reply default "$CLEAN"; rm -f "$T/gh-calls"
st_duty marshal --pr 4
ck "a forbidden path is a literal prefix, so lib/crypto also covers lib/crypto-notes" '[ "$(last_verdict)" = DRY-RUN ] && grep -q "BLOCK" <<<"$(last_detail)"'
st_registry '["marshal"]' '{"forbidden_paths":["lib/crypto/","db/migrations/"]}'

# ---- 2. the crew, read only ---------------------------------------------------------------------------------------
st_noreplies; st_reply default "$CLEAN"; rm -f "$T/gh-calls"; rm -rf "$T/state/findings"
st_duty marshal --pr 1
ck "all three security seats are asked, from the crew files" '[ "$(wc -l < "$T/claude-calls" | tr -d " ")" = 3 ] && grep -q "You are the gunner" "$T/claude-calls" && grep -q "You are the customs" "$T/claude-calls" && grep -q "You are the gatekeeper" "$T/claude-calls"'
first=$(head -1 "$T/claude-calls")
ck "every seat is read only: edit and publish tools are denied and not allowed" \
   'jq -e ".deny | contains(\"Write\") and contains(\"Edit\") and contains(\"Bash(git push\") and contains(\"Bash(gh pr comment\")" <<<"$first" >/dev/null && [ "$(jq -r ".allow" "$T/claude-calls" | grep -Ec "Edit|Write|git push|gh pr (comment|create|merge)")" = 0 ]'
ck "  the lead seat (gunner) names no model of its own, so it runs on the account default; the others run on Sonnet" \
   '[ "$(jq -r "select(.prompt | contains(\"You are the gunner\")) | .model" "$T/claude-calls")" = "" ] && [ "$(jq -r "select(.prompt | contains(\"You are the customs\")) | .model" "$T/claude-calls")" = claude-sonnet-5 ]'
ck "  the project guardrails and the files changed reach every seat" '[ "$(grep -c "Never touch money code" "$T/claude-calls")" = 3 ] && [ "$(grep -c "src/ui/Button.tsx" "$T/claude-calls")" = 3 ]'
ck "  and each is told it never needs a real secret" '[ "$(grep -c "never need a real secret" "$T/claude-calls")" = 3 ]'
ck "report only: three clean seats say CLEAN, record DRY-RUN, write and post nothing" 'grep -q "CLEAN" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ] && no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
st_duty marshal --pr 1 --apply
ck "--apply, clean: records CLEAN, comments once, writes an empty findings file" '[ "$(last_verdict)" = CLEAN ] && [ "$(grep -c "^gh pr comment" "$T/gh-calls")" = 1 ] && jq -e ".verdict == \"CLEAN\" and (.findings | length) == 0" "$T/state/findings/tp-pr1-marshal.json" >/dev/null'

# ---- findings ---------------------------------------------------------------------------------------------------------
st_noreplies; st_reply 'You are the customs' "$F1"; st_reply default "$CLEAN"; rm -f "$T/gh-calls"
st_duty marshal --pr 1 --apply
ck "a finding from one seat is FINDINGS 1, and the comment carries it" '[ "$(last_verdict)" = FINDINGS ] && grep -q "^1" <<<"$(last_detail)" || grep -q "1 finding" <<<"$(last_detail)"; grep -rq "Logs the whole request" "$T"/body-*'
ck "  the findings file names the path the Caulker may touch" 'jq -e ".findings[0].paths == [\"src/ui/Button.tsx\"] and .findings[0].id == \"marshal-1\"" "$T/state/findings/tp-pr1-marshal.json" >/dev/null'
st_noreplies; st_reply default "$F1"
st_duty marshal --pr 1
ck "the same finding from all three seats is one finding" 'grep -q "1 finding" <<<"$OUT"'
many=$(jq -nc '[range(0;20) | {file:"f\(.).ts",line:1,severity:"minor",title:"t\(.)",body:"b"}]')
st_noreplies; st_reply default "FINDINGS_JSON: $many
ADR: searched none
VERDICT: FINDINGS 20"
QUARTERDECK_MAX_ITEMS=2 st_duty marshal --pr 1
ck "QUARTERDECK_MAX_ITEMS caps what each seat may bring (2 each; identical findings across seats merge)" 'grep -q "2 finding" <<<"$OUT"'

# ---- unparseable and incomplete ------------------------------------------------------------------------------------
st_noreplies; st_reply default 'Looks fine to me.'; rm -f "$T/gh-calls"; rm -rf "$T/state/findings"
st_duty marshal --pr 1 --apply
ck "an unparseable reply from every seat is an ERROR run that writes nothing" '[ "$(last_verdict)" = ERROR ] && no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
st_noreplies; st_reply 'You are the gatekeeper' 'No contract at all.'; st_reply default "$CLEAN"; rm -f "$T/gh-calls"
st_duty marshal --pr 1 --apply
ck "one silent seat means the crew cannot call it clean: ERROR, nothing written" '[ "$(last_verdict)" = ERROR ] && grep -q "gatekeeper" <<<"$(last_detail)" && no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
st_noreplies; st_reply 'You are the gatekeeper' 'No contract at all.'; st_reply 'You are the customs' "$F1"; st_reply default "$CLEAN"
st_duty marshal --pr 1
ck "a finding from the seats that did answer still stands, and the report says a seat did not report" 'grep -q "gatekeeper did not report" <<<"$OUT"'

# ---- structure ---------------------------------------------------------------------------------------------------------
ck "the duty is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/duties/marshal.sh" && [ "$(tail -c 3 "$REAL/duties/marshal.sh" | tr -d "\n")" = "}" ]'
ck "the three security seats exist on the security panel, each with a bias and something it is willing to be wrong about" \
   '[ "$(for c in gunner customs gatekeeper; do grep -q "^discipline: security$" "$REAL/crew/$c.md" && grep -q "^bias: ." "$REAL/crew/$c.md" && grep -c "willing to be wrong about" "$REAL/crew/$c.md"; done | grep -c 1)" = 3 ]'
ck "no new crew member is named with a word the owner ruled out" '! grep -rliE "(^|[^[:alnum:]])(tester|sentry|mender|critic|prover)([^[:alnum:]]|$)" "$REAL"/crew/gunner.md "$REAL"/crew/customs.md "$REAL"/crew/gatekeeper.md "$REAL"/duties/marshal.sh'
ck "the duty never calls gh with a write verb but comment, and only through post()" '[ "$(grep -cE "gh\"? (pr|issue) (create|edit|merge|review|close)" "$REAL/duties/marshal.sh")" = 0 ]'
st_done
