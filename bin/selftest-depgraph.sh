#!/bin/bash
# The dependency graph: which parts of a project call which, and what a review is told a change could break. Run against a real git
# repository of invented files and a stand-in model. The graph is worked out by bin/depgraph.py from the base branch, never by a model.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init surveyor inspector marshal shipwright
cp "$REAL/bin/adr.py" "$REAL/bin/depgraph.py" "$T/bin/"
st_repo
pkg() { # pkg <folder> <name> [dep]... — a package.json
  local d=$1 n=$2; shift 2; local deps="" x
  for x in "$@"; do deps="$deps\"$x\":\"1.0.0\","; done
  st_file "$d/package.json" "{\"name\":\"$n\",\"dependencies\":{${deps%,}}}"
}
st_file package.json '{"name":"shop-root","private":true}'
pkg services/users users
pkg services/billing billing users
pkg services/web web billing users lodash
pkg services/lonely lonely
st_file services/users/src/index.ts $'export const id = 1\n'
st_file node_modules/junk/package.json '{"name":"junk"}'
st_commit "units"
DG="python3 $REAL/bin/depgraph.py"
g=$($DG graph --repo "$T/work" --base main)
ck "every folder with a package.json is a unit, the root and node_modules are not" '[ "$(jq -c ".units | keys" <<<"$g")" = "[\"billing\",\"lonely\",\"users\",\"web\"]" ]'
ck "an edge is made only for a dependency that is another unit (lodash is not)" '[ "$(jq "[.edges[] | select(.source==\"scanned\")] | length" <<<"$g")" = 3 ]'
printf 'services/users/src/index.ts\nREADME.md\n' > "$T/f"
imp=$($DG impact --repo "$T/work" --base main --files "$T/f")
ck "a change in users: billing and web depend on it directly, in that order of the sorted names" '[ "$(jq -r "[.dependents[] | select(.depth==1) | .unit] | join(\",\")" <<<"$imp")" = "billing,web" ]'
ck "  a file outside every unit is counted, not dropped" '[ "$(jq .unmapped <<<"$imp")" = 1 ] && [ "$(jq -r ".touched[0].unit" <<<"$imp")" = users ]'
printf 'services/billing/x.ts\n' > "$T/f"
imp=$($DG impact --repo "$T/work" --base main --files "$T/f")
ck "a change in billing: only web depends on it; users is not a dependent" '[ "$(jq -r "[.dependents[].unit] | join(\",\")" <<<"$imp")" = web ]'
printf 'services/lonely/x.ts\n' > "$T/f"
ck "a unit nothing depends on gives no text, so a review gets no block" '[ -z "$($DG text --repo "$T/work" --base main --files "$T/f")" ]'
ck "a base branch that does not exist is an empty graph, not an error" '[ "$($DG graph --repo "$T/work" --base nope | jq ".units | length")" = 0 ]'

# declared edges: what a scan cannot see
st_file docs/architecture/dependencies.json '{"services":{"lonely":{"path":"services/lonely/","calls":{"users":"sqs user-events","ghost":"http /v1/ghost"}},"billing":{"path":"services/billing/","calls":{}}}}'
st_commit "declared"
g=$($DG graph --repo "$T/work" --base main)
ck "a declared call is an edge, marked declared, with how it is made" '[ "$(jq -r "[.edges[] | select(.source==\"declared\" and .from==\"lonely\" and .to==\"users\")][0].how" <<<"$g")" = "sqs user-events" ]'
printf 'services/users/src/index.ts\n' > "$T/f"
ck "  and a change in users now lists lonely as a dependent too" '$DG text --repo "$T/work" --base main --files "$T/f" | grep -q "lonely calls users: sqs user-events (declared)"'
chk=$($DG check --repo "$T/work" --base main); rc=$?
ck "check: a declared call to something that is not a unit is a problem, and the exit status says so" '[ $rc = 1 ] && jq -r ".problems[]" <<<"$chk" | grep -q "lonely is declared to call ghost"'
ck "check: a package.json dependency the declared graph leaves out is a problem (billing declares no calls but needs users)" 'jq -r ".problems[]" <<<"$chk" | grep -q "billing depends on users in its package.json"'
ck "check: a unit the declared graph does not mention is not flagged" '! jq -r ".problems[]" <<<"$chk" | grep -q "^web "'
st_file docs/architecture/dependencies.json 'not json'; st_commit "broken file"
ck "a declared file that is not JSON is ignored, not a crash" '$DG graph --repo "$T/work" --base main | jq -e ".declared == false and (.units | length) == 4" >/dev/null'
git -C "$T/work" rm -q docs/architecture/dependencies.json; st_commit "no declared"
ck "check with no declared graph has nothing to check" '$DG check --repo "$T/work" --base main | jq -e ".declared == false and .problems == []" >/dev/null'

# the reviews
st_registry '["surveyor","inspector"]' '{}'
st_pr 5 feat-id services/users/src/index.ts $'export const id = 2\n'
st_pr 6 feat-lonely services/lonely/x.ts $'x\n'
echo '{}' > "$T/state/reviewed.json"
st_noreplies; st_reply default 'FINDINGS_JSON: []
ADR: searched none, no records on this trunk
VERDICT: CLEAN'
st_duty surveyor --pr 5 --apply
ck "surveyor: a change in a unit others depend on carries the block, naming them" 'grep -q "WHAT DEPENDS ON THIS CHANGE" "$T/claude-calls" && grep -q "billing calls users: package dependency (scanned)" "$T/claude-calls"'
ck "  and it says the list is a lead to check against the code, not a verdict" 'grep -q "The list is a lead, not a verdict" "$T/claude-calls"'
st_noreplies; st_reply default 'FINDINGS_JSON: []
ADR: searched none, no records on this trunk
VERDICT: CLEAN'; echo '{}' > "$T/state/reviewed.json"
st_duty surveyor --pr 6 --apply
ck "surveyor: a change nothing depends on has no block, and the review still runs" '[ "$(last_verdict)" = CLEAN ] && ! grep -q "WHAT DEPENDS ON THIS CHANGE" "$T/claude-calls"'
mv "$T/bin/depgraph.py" "$T/bin/depgraph.off"; st_noreplies; st_reply default 'FINDINGS_JSON: []
ADR: searched none, no records on this trunk
VERDICT: CLEAN'; echo '{}' > "$T/state/reviewed.json"
st_duty surveyor --pr 5 --apply
ck "without the graph program the surveyor works as it did" '[ "$(last_verdict)" = CLEAN ] && ! grep -q "WHAT DEPENDS ON THIS CHANGE" "$T/claude-calls"'
mv "$T/bin/depgraph.off" "$T/bin/depgraph.py"
ck "the graph reads git objects of the project only: no path outside the repository is opened" '! grep -nE "open\(|read_text|expanduser|HOME" "$REAL/bin/depgraph.py" | grep -vE "open\(a\.files\)"'
# suggest: the calls the declared graph is missing
st_file docs/architecture/dependencies.json '{"services":{"billing":{"path":"services/billing/","calls":{}},"users":{"path":"services/users/","calls":{}}}}'
st_commit "declared, billing leaves out users"
sug=$($DG suggest --repo "$T/work" --base main)
ck "suggest: a listed unit that needs another per its package.json gets the missing call as a line to add, naming how" '[ "$(jq -c "." <<<"$sug")" = "[{\"unit\":\"billing\",\"calls\":\"users\",\"how\":\"package dependency\"}]" ]'
ck "suggest: a unit the declared file does not list is left alone (web also depends on users)" '! jq -r ".[].unit" <<<"$sug" | grep -q "^web$"'
np=$($DG newproblems --repo "$T/work" --base main --head main); rc=$?
ck "newproblems: a head with the same problems as the base adds none, so exit 0" '[ $rc = 0 ] && [ "$(jq ".problems | length" <<<"$np")" = 0 ]'

# the shipwright: told to keep the file in step, and refused when its change makes the graph disagree with the code
st_issue 20 "Rename the users export" "users/src/index.ts exports id; keep it."
VERIFY_OK="true"
ship() { # ship <hook> — the real shipwright against the stand-in model; the hook is the model's edit
  st_noreplies; : > "$T/claude-calls"; rm -f "$T/gh-calls"; st_registry '["shipwright"]' "$(jq -nc --arg c "$VERIFY_OK" '{verify:$c}')"
  st_reply default 'RESULT: FIXED changed it'
  printf '#!/bin/bash\n%s\n' "$1" > "$T/claude-hook"; chmod +x "$T/claude-hook"
  st_duty shipwright --issue 20
}
ckn() { if st_can_nest_sandbox; then ck "$@"; else st_skip "$1 (needs a sandbox inside the sandbox)"; fi; }
EDIT_SRC="printf 'export const id = 3\n' > services/users/src/index.ts"
ship "$EDIT_SRC"
ckn "shipwright: a project that keeps a declared graph tells the builder to keep it in step, and an ordinary change is not refused" \
    'grep -q "keeps docs/architecture/dependencies.json" "$T/claude-calls" && [ "$(last_verdict)" = DRY-RUN ]'
ship "$EDIT_SRC; jq '.services.billing.calls.ghost = \"http /v1/ghost\"' docs/architecture/dependencies.json > d.t && mv d.t docs/architecture/dependencies.json"
ckn "shipwright: a change that declares a call to something that is not a part is REFUSED, and says which call" \
    '[ "$(last_verdict)" = REFUSED ] && grep -q "billing is declared to call ghost" <<<"$OUT" && grep -q "dependency graph" <<<"$(last_detail)" && no_gh_writes'
ship "$EDIT_SRC; jq '.services.billing.calls.users = \"package dependency\"' docs/architecture/dependencies.json > d.t && mv d.t docs/architecture/dependencies.json"
ckn "shipwright: a change that fixes a problem the base already had is not refused (billing now declares users)" '[ "$(last_verdict)" = DRY-RUN ]'
st_file docs/architecture/dependencies.json 'not json'; st_commit "unreadable"
ship "$EDIT_SRC"
ckn "shipwright: a project whose declared file is unreadable has no declared graph, so the builder is not told to keep it" '! grep -q "keeps docs/architecture/dependencies.json" "$T/claude-calls"'
ck "shipwright: the gate names the base as the project does (\$BASE, which depgraph resolves to origin/\$BASE or the local branch), so a checkout with no origin is still checked" \
   '! grep -q "depgraph.py\" newproblems.*origin/" "$REAL/duties/shipwright.sh"'
st_done
