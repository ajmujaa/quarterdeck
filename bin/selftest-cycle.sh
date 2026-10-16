#!/bin/bash
# `quarterdeck cycle` runs the crew in order, on one issue, and stops for a person. What is asserted here is the orchestration:
# the order of the stages, that the reviewers run side by side and every result is collected, that the caulker is bounded at
# three cycles with the reviewers reading each new head, that the daily cap and the cycle ceiling stop a stage BEFORE it starts,
# that a stopped or crashed cycle resumes at the failed stage and never repeats a finished one, that nothing starts without the
# project's opt-in, and that a report-only cycle writes nothing. Part 1 runs the real orchestrator over stand-in duties (each
# records what it was asked and answers from a script); part 2 runs the REAL shipwright and assayer against a stand-in model
# and a real git repository to show the assayer never sees the shipwright's diff; part 3 shows the surveyor leaves the findings
# file the caulker reads. No GitHub, no model, no project checkout: only invented files.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init surveyor shipwright assayer
cp "$REAL/bin/cycle" "$T/bin/cycle"
st_repo
st_file app.py $'def counter_reset(n):\n    return n\n'
st_commit "base"
st_pr 1 feat-reset app.py $'def counter_reset(n):\n    return 0  # SHIPWRIGHT-MARKER-7\n'
HEAD0=$(jq -r .headRefOid "$T/ghdata/pr-1.json")
st_issue 7 "Add a Reset button" $'Add a Reset button that sets the counter back to zero.\n\n<!-- quarterdeck:requirements -->\n## Requirements\n\n1. Reset sets the counter to zero\n   - **Accept when:** counter_reset(5) equals 0\n<!-- /quarterdeck:requirements -->\n'
ALL='["purser","panel","shipwright","assayer","surveyor","marshal","lookout","pilot","inspector","caulker"]'
REG_EXTRA='{"cycle":true,"qa":{"start":"true"},"test_file":"PYTHONPATH=. python3 {file}"}'
export QUARTERDECK_DAILY_BUDGET=100 QUARTERDECK_CALL_BUDGET=0.01 QUARTERDECK_CYCLE_BUDGET=15 STUB_COST=0.10 PR_CREATED=1

# ---- the stand-in duties: record the call, answer from stubcfg/<duty> (one line per call: VERDICT|detail|url|findings) ----
mkstub() {
  cat > "$T/duties/$1.sh" <<'STUB'
#!/bin/bash
source "$QUARTERDECK_DIR/bin/lib.sh"
duty=$(basename "$0" .sh); C="$QUARTERDECK_DIR/stubcfg"; mkdir -p "$C"
n=$(( $(cat "$C/$duty.n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$C/$duty.n"
echo "start $duty $* dry=${QUARTERDECK_DRY_RUN:-} model=${QUARTERDECK_MODEL_OVERRIDE:-}" >> "$QUARTERDECK_DIR/stub-calls"
[ -f "$C/$duty.sleep" ] && sleep "$(cat "$C/$duty.sleep")"
line=$(sed -n "${n}p" "$C/$duty" 2>/dev/null); [ -n "$line" ] || line=$(tail -n 1 "$C/$duty" 2>/dev/null); [ -n "$line" ] || line="OK|fine|"
IFS='|' read -r verdict detail url nfind <<<"$line"
export QUARTERDECK_RUN_ID="stub-$duty-$n"
case "$verdict" in CRASH) kill -9 $PPID; exit 1 ;; SILENT) echo "end $duty" >> "$QUARTERDECK_DIR/stub-calls"; exit 0 ;; esac
record_spend "{\"total_cost_usd\":${STUB_COST:-0.10},\"modelUsage\":{\"stub\":{}}}" "$duty" ""
pr=""; a=("$@"); for ((i = 0; i < ${#a[@]}; i++)); do [ "${a[$i]}" = --pr ] && pr="${a[$((i + 1))]}"; done
issue=7
[ "$duty" = panel ] && echo "# plan" > "$QUARTERDECK_HOME/workspace/${QUARTERDECK_PROJECT}-plan-$issue.md"
if [ -n "$pr" ] && [ "${nfind:-0}" -gt 0 ]; then
  head=$(jq -r .headRefOid "$QUARTERDECK_DIR/ghdata/pr-$pr.json"); mkdir -p "$QUARTERDECK_HOME/state/findings"
  jq -n --arg d "$duty" --argjson pr "$pr" --arg h "$head" --arg v "$verdict $nfind" --argjson n "$nfind" \
    '{duty:$d, project:"tp", pr:$pr, head:$h, verdict:$v, findings:[range($n) | {id:($d + "-" + (. + 1 | tostring)), severity:"major", title:"a finding", body:"b", file:"app.py", line:1, paths:["app.py"], kind:"code"}]}' \
    > "$QUARTERDECK_HOME/state/findings/${QUARTERDECK_PROJECT}-pr${pr}-$duty.json"
fi
if [ "$duty" = caulker ] && [ "$verdict" = SEALED ]; then   # a push: the head moves, so the findings written about the old head are no longer open
  jq --arg s "sealed$n$(printf '%036d' 0)" '.headRefOid = $s' "$QUARTERDECK_DIR/ghdata/pr-1.json" > "$QUARTERDECK_DIR/x.json" && mv "$QUARTERDECK_DIR/x.json" "$QUARTERDECK_DIR/ghdata/pr-1.json"
fi
record_run "$QUARTERDECK_PROJECT" "$duty" "$verdict" "$detail" "$url"
echo "end $duty" >> "$QUARTERDECK_DIR/stub-calls"
STUB
  chmod +x "$T/duties/$1.sh"
}
use_stubs() { local d; for d in purser panel shipwright assayer surveyor marshal lookout pilot inspector caulker; do mkstub "$d"; done; }
cfg() { local d=$1; shift; mkdir -p "$T/stubcfg"; : > "$T/stubcfg/$d"; local l; for l in "$@"; do printf '%s\n' "$l" >> "$T/stubcfg/$d"; done; }
happy() {   # every duty answers well
  cfg purser "READY|2 requirement(s)|"; cfg panel "RULED|dev: 2 of 3 on issue #7|"; cfg shipwright "PR|#7 → pull/1|https://github.com/x/tp/pull/1"
  cfg assayer "VERIFIED|1 test file(s)|https://github.com/x/tp/pull/2"; cfg surveyor "CLEAN|#1|"; cfg marshal "CLEAN|#1|"; cfg lookout "CLEAN|#1|"
  cfg pilot "PASSED|#1|"; cfg inspector "PROVEN|#1 — traced it|"; cfg caulker "SEALED|sealed|"
}
fresh() {
  rm -rf "$T/state/cycles" "$T/state/findings" "$T/stubcfg" "$T/stub-calls" "$T/gh-calls" "$T/state/spend.jsonl" "$T/workspace"/* "$T"/state/*.lock "$T"/logs/cycle-*
  echo '[]' > "$T/state/runs.json"; : > "$T/stub-calls"
  git -C "$T/origin.git" update-ref refs/pull/1/head "$HEAD0" 2>/dev/null
  jq --arg h "$HEAD0" '.headRefOid = $h' "$T/ghdata/pr-1.json" > "$T/x.json" && mv "$T/x.json" "$T/ghdata/pr-1.json"
  happy
}
cyc() { OUT=$(bash "$T/bin/cycle" "$@" 2>&1); RC=$?; ID=$(ls -t "$T/state/cycles"/cyc-*.json 2>/dev/null | head -1 | xargs -n1 basename 2>/dev/null | sed 's/\.json$//'); REC="$T/state/cycles/$ID.json"; }
calls() { grep -c "^start $1 " "$T/stub-calls" 2>/dev/null || true; }
order() { grep '^start ' "$T/stub-calls" | awk '{print $2}' | tr '\n' ' '; }
ran_all() { local d; for d in surveyor marshal lookout pilot inspector; do [ "$(calls $d)" -ge 1 ] || return 1; done; }
stg() { jq -r --arg id "$1" ".stages[] | select(.id == \$id) | $2" "$REC"; }
refs() { git -C "$T/origin.git" for-each-ref --format='%(refname) %(objectname)' | sort; }
use_stubs

# ---- it refuses what it was not asked to do --------------------------------------------------------------------------------
st_registry "$ALL" '{}'; fresh
cyc tp --issue 7 --apply
ck "a project that has not opted in (no cycle: true) is refused, says how to opt in, and starts and records nothing" '[ "$RC" != 0 ] && grep -q "has not opted in" <<<"$OUT" && grep -q "\"cycle\": true" <<<"$OUT" && [ ! -s "$T/stub-calls" ] && [ -z "$(ls "$T/state/cycles" 2>/dev/null)" ]'
st_registry "$ALL" '{"cycle":false}'; cyc tp --issue 7 --apply
ck "  cycle: false is refused the same way" '[ "$RC" != 0 ] && grep -q "has not opted in" <<<"$OUT" && [ ! -s "$T/stub-calls" ]'
st_registry "$ALL" "$REG_EXTRA"
cyc tp
ck "no issue: refused with the usage" '[ "$RC" != 0 ] && grep -q "which issue" <<<"$OUT"'
cyc nope --issue 7
ck "an unknown project is refused" '[ "$RC" != 0 ] && grep -q "unknown project" <<<"$OUT"'
ck "a cycle is not a duty, so neither a schedule nor a dashboard button can name it" '[ ! -f "$REAL/duties/cycle.sh" ] && ! duty=cycle bash -c "source $REAL/bin/lib.sh; duty_exists cycle"'

# ---- report only: the stages that need no writes, and what each later stage would do ---------------------------------------
st_registry "$ALL" "$REG_EXTRA"; fresh
refs_before=$(refs)
QUARTERDECK_DRY_RUN=0 cyc tp --issue 7
ck "report only: only the purser and the dev panel ran, and nothing later" '[ "$RC" = 0 ] && [ "$(order)" = "purser panel " ]'
ck "  neither was given --apply, and a machine default of DRY_RUN=0 did not turn writes on" '! grep -q -- "--apply" "$T/stub-calls" && grep -q "^start purser .* dry=1 " "$T/stub-calls" && grep -q "^start panel .* dry=1 " "$T/stub-calls"'
ck "  it writes nothing to GitHub, moves no ref, and merges nothing" 'no_gh_writes && [ "$(refs)" = "$refs_before" ]'
ck "  the record says report-only and lists every later stage with what it would do" '[ "$(jq -r .status "$REC")" = report-only ] && [ "$(jq -r "[.stages[] | select(.state == \"would\")] | length" "$REC")" = 9 ] && [ "$(stg shipwright .detail)" = "would build the plan on a branch and open a pull request" ]'
ck "  the output says each later stage would run" 'grep -q "Shipwright" <<<"$OUT" && grep -q "WOULD" <<<"$OUT" && grep -q "Add --apply" <<<"$OUT"'
ck "  and the dev panel was asked on the routine model with one round" 'grep -q "^start panel --panel dev --issue 7 --rounds 1 " "$T/stub-calls" && grep -q "^start panel .* model=claude-sonnet-5" "$T/stub-calls"'
OLD=$ID; cyc --resume "$OLD"
ck "a report-only record cannot be resumed: nothing was started" '[ "$RC" != 0 ] && grep -q "report-only" <<<"$OUT" && grep -q "Run it again with --apply" <<<"$OUT"'

# ---- the whole cycle, in order, with every result collected --------------------------------------------------------------
fresh; echo 1 > "$T/stubcfg/surveyor.sleep"; for d in marshal lookout pilot inspector; do echo 1 > "$T/stubcfg/$d.sleep"; done
cfg surveyor "FINDINGS|1 on #1||1" "CLEAN|#1|"; cfg marshal "CLEAN|#1|"
cyc tp --issue 7 --apply
ck "stage order: purser, dev panel, shipwright, assayer, then the five reviewers" '[ "$RC" = 0 ] && [ "$(order | awk "{print \$1\" \"\$2\" \"\$3\" \"\$4}")" = "purser panel shipwright assayer" ]'
ck "  the reviewers all ran on the pull request, the inspector against the issue" 'ran_all && grep -q "^start inspector --pr 1 --issue 7 --apply" "$T/stub-calls" && grep -q "^start shipwright --issue 7 --plan .*tp-plan-7.md --apply" "$T/stub-calls" && grep -q "^start assayer --issue 7 --pr 1 --apply" "$T/stub-calls"'
ck "  the five reviewers ran side by side: all started before the first finished" '[ "$(grep -nE "^(start|end) (surveyor|marshal|lookout|pilot|inspector)" "$T/stub-calls" | head -5 | grep -c "^[0-9]*:start")" = 5 ]'
ck "  and every result was collected, a finding included, under its own stage" '[ "$(stg "r1:surveyor" .verdict)" = FINDINGS ] && [ "$(stg "r1:marshal" .verdict)" = CLEAN ] && [ "$(stg "r1:lookout" .verdict)" = CLEAN ] && [ "$(stg "r1:pilot" .verdict)" = PASSED ] && [ "$(stg "r1:inspector" .verdict)" = PROVEN ]'
ck "  the surveyor's finding is open, so the caulker ran (one sealed cycle) and the reviewers read the new head again" '[ "$(calls caulker)" = 1 ] && [ "$(calls surveyor)" = 2 ] && [ "$(calls inspector)" = 2 ]'
ck "  it stops for a person: awaiting-review, the pull request on the record, a human-review stage, nothing merged or approved" '[ "$(jq -r .status "$REC")" = awaiting-review ] && [ "$(jq -r .pr "$REC")" = https://github.com/x/tp/pull/1 ] && [ "$(stg human .state)" = waiting ] && ! grep -qE "^gh pr (merge|review)" "$T/gh-calls" 2>/dev/null'
ck "  every stage has a verdict, a duty run id, a start and an end, and a cost read back from the spend ledger" 'jq -e "[.stages[] | select(.state == \"done\")] | all(.verdict != null and (.runs | length) > 0 and .started != null and .finished != null and .cost > 0.099 and .cost < 0.101)" "$REC" >/dev/null'
ck "  the stage costs add up to the cycle total, which is what the ledger booked under this cycle's tag" 'jq -e "(.cost - ([.stages[].cost] | add)) | fabs < 0.0001" "$REC" >/dev/null && [ "$(jq -s "map(select(.fix == \"cycle:$ID\") | .cost) | add" "$T/state/spend.jsonl")" = "$(jq -r .cost "$REC")" ]'
ck "  the run ledger got one cycle row, with the pull request" '[ "$(jq -r "map(select(.duty == \"cycle\")) | last | .verdict" "$T/state/runs.json")" = AWAITING-REVIEW ] && [ "$(jq -r "map(select(.duty == \"cycle\")) | last | .url" "$T/state/runs.json")" = https://github.com/x/tp/pull/1 ]'
ck "  the output shows cost per stage and the total" 'grep -q "Shipwright" <<<"$OUT" && grep -q "total" <<<"$OUT" && grep -q "wall time" <<<"$OUT"'
cyc --status "$ID"
ck "--status <id> shows the stages, their verdicts and the cost" '[ "$RC" = 0 ] && grep -q "Round 1\|(round 1)" <<<"$OUT" && grep -q "awaiting-review" <<<"$OUT" && grep -q "total" <<<"$OUT"'
OLD=$ID; cyc --resume "$OLD"
ck "a finished cycle has nothing to resume" '[ "$RC" != 0 ] && grep -q "nothing to resume" <<<"$OUT"'

# ---- a clean first round: no caulker; some reviewers do not apply ------------------------------------------------------------
st_registry "$ALL" '{"cycle":true}'; fresh
cyc tp --issue 7 --apply
ck "no qa config and no test_file: lookout, pilot and the assayer are skipped, each with its reason on the record" '[ "$RC" = 0 ] && [ "$(stg "r1:lookout" .state)" = skipped ] && grep -q "qa.start" <<<"$(stg "r1:pilot" .detail)" && [ "$(stg assayer .state)" = skipped ] && grep -q "test_file" <<<"$(stg assayer .detail)" && [ "$(calls lookout)" = 0 ] && [ "$(calls pilot)" = 0 ] && [ "$(calls assayer)" = 0 ]'
ck "  clean reviewers: the caulker is never asked, and the cycle waits for a person" '[ "$(calls caulker)" = 0 ] && [ "$(jq -r .status "$REC")" = awaiting-review ]'
st_registry '["purser","panel","shipwright","surveyor","caulker"]' '{"cycle":true}'; fresh
cyc tp --issue 7 --apply
ck "a duty that is not enabled for the project is skipped with that reason, not run" '[ "$(stg "r1:marshal" .state)" = skipped ] && grep -q "not enabled" <<<"$(stg "r1:marshal" .detail)" && [ "$(calls marshal)" = 0 ]'
st_registry "$ALL" "$REG_EXTRA"

# ---- the caulker is bounded, and the reviewers read each new head --------------------------------------------------------------
fresh; cfg surveyor "FINDINGS|1||1" "FINDINGS|1||1" "CLEAN|ok|"
cyc tp --issue 7 --apply
ck "two sealed cycles and a clean third round: the reviewers ran three times, the caulker twice" '[ "$(calls caulker)" = 2 ] && [ "$(calls surveyor)" = 3 ] && [ "$(calls marshal)" = 3 ] && [ "$(jq -r .status "$REC")" = awaiting-review ]'
ck "  the caulker's stages and the review rounds interleave in that order" '[ "$(jq -r "[.stages[].id] | map(select(startswith(\"caulk\") or endswith(\":surveyor\"))) | join(\" \")" "$REC")" = "r1:surveyor caulk1 r2:surveyor caulk2 r3:surveyor" ]'
fresh; cfg surveyor "FINDINGS|1||1"; cfg caulker "SEALED|sealed|" "SEALED|sealed|" "SEALED|sealed|" "NEEDS_HUMAN|3 cycles used|"
cyc tp --issue 7 --apply
ck "a finding that never goes away: three caulker cycles, then ONE hand-over run (no more), and the reviewers read after each of the three" '[ "$(calls caulker)" = 4 ] && [ "$(calls surveyor)" = 4 ] && [ "$(jq -r "[.stages[] | select(.id | test(\"^caulk[0-9]+\$\"))] | length" "$REC")" = 3 ] && [ "$(stg caulk-handoff .verdict)" = NEEDS_HUMAN ]'
ck "  the cycle ends needs-human with the finding count, and there is no fifth round and no fourth cycle" '[ "$(jq -r .status "$REC")" = needs-human ] && grep -q "still open after 3 caulker cycle" <<<"$(jq -r .final "$REC")" && [ -z "$(stg "r5:surveyor" .id)" ] && [ -z "$(stg caulk4 .id)" ]'
fresh; cfg surveyor "FINDINGS|1||1"; cfg caulker "REJECTED|a test was edited|" "ERROR|run failed|" "REJECTED|too large|" "NEEDS_HUMAN|3 cycles used|"
cyc tp --issue 7 --apply
ck "rejected and failed caulker attempts use up the cycles too (the head did not move, so the reviewers are not asked again), and the loop still ends" '[ "$(calls caulker)" = 4 ] && [ "$(calls surveyor)" = 1 ] && [ "$(jq -r .status "$REC")" = needs-human ]'
fresh; cfg surveyor "FINDINGS|1||1"; cfg caulker "NEEDS_HUMAN|the fix needs a decision|"
cyc tp --issue 7 --apply
ck "a caulker that says it needs a person ends the cycle at once with that reason" '[ "$(calls caulker)" = 1 ] && [ "$(jq -r .status "$REC")" = needs-human ] && grep -q "needs a decision" <<<"$(jq -r .final "$REC")"'
NID=$ID; cfg surveyor "FINDINGS|1||1" "CLEAN|ok|"; cfg caulker "SEALED|sealed|"
cyc --resume "$NID"
ck "  once what stopped it is fixed, --resume tries that caulker stage again (and nothing before it): sealed, reviewed again, awaiting review" '[ "$RC" = 0 ] && [ "$ID" = "$NID" ] && [ "$(calls caulker)" = 2 ] && [ "$(calls purser)" = 1 ] && [ "$(jq -r .status "$REC")" = awaiting-review ]'
fresh; cfg marshal "BLOCK|touches a forbidden path||1"
cfg caulker "NEEDS_HUMAN|no finding names a file|"
cyc tp --issue 7 --apply
ck "a marshal BLOCK is an open finding the caulker cannot fix: the cycle hands it to a person" '[ "$(jq -r .status "$REC")" = needs-human ]'

# ---- stages that stop the cycle ---------------------------------------------------------------------------------------------------
fresh; cfg purser "NEEDS_HUMAN|decide the pricing first|"
cyc tp --issue 7 --apply
ck "the purser needs a person: nothing after it ran, the cycle says why" '[ "$(order)" = "purser " ] && [ "$(jq -r .status "$REC")" = needs-human ] && grep -q "pricing" <<<"$(jq -r .final "$REC")"'
fresh; cfg panel "RULED|dev: 0 of 3 on issue #7|"
cyc tp --issue 7 --apply
ck "a dev panel that ruled nothing to change stops the cycle as nothing-to-build" '[ "$(order)" = "purser panel " ] && [ "$(jq -r .status "$REC")" = nothing ]'
fresh; cfg shipwright "TAKEN|#7 already has #5 (someone-else)|"
cyc tp --issue 7 --apply
ck "a pull request someone else already has stops the cycle before any review" '[ "$(calls assayer)" = 0 ] && [ "$(calls surveyor)" = 0 ] && [ "$(jq -r .status "$REC")" = needs-human ] && grep -q "TAKEN" <<<"$(jq -r .final "$REC")"'

# ---- the daily cap and the cycle ceiling: a stage is not started if it would cross ---------------------------------------------
seed_spend() { jq -nc --arg at "$(date -u +%FT%TZ)" --argjson c "$1" '{at:$at, project:"tp", duty:"other", run:"seed", fix:"", cost:$c}' >> "$T/state/spend.jsonl"; }
fresh; seed_spend 99.995
cyc tp --issue 7 --apply
ck "the day's spend is already at the daily budget: no stage starts, and the record says stopped at the cap" '[ "$RC" = 2 ] && [ "$(order)" = "" ] && [ "$(jq -r .status "$REC")" = stopped-cap ] && grep -q "stopped at the cap" <<<"$OUT" && grep -q "stopped at the cap" <<<"$(jq -r .final "$REC")"'
ck "  nothing was written to GitHub or the ledger of duties" 'no_gh_writes && [ "$(jq "map(select(.duty != \"cycle\")) | length" "$T/state/runs.json")" = 0 ]'
fresh; export QUARTERDECK_DAILY_BUDGET=0.25
cyc tp --issue 7 --apply
ck "the cap is reached part-way: the next stage is not started (purser, panel and shipwright ran; the assayer did not)" '[ "$RC" = 2 ] && [ "$(order)" = "purser panel shipwright " ] && [ "$(jq -r .status "$REC")" = stopped-cap ] && grep -q "assayer" <<<"$(jq -r .final "$REC")"'
CAPID=$ID; export QUARTERDECK_DAILY_BUDGET=100
cyc --resume "$CAPID"
ck "  resumed after the cap is raised: it goes on at the assayer and never repeats the stages that finished" '[ "$RC" = 0 ] && [ "$ID" = "$CAPID" ] && [ "$(calls purser)" = 1 ] && [ "$(calls panel)" = 1 ] && [ "$(calls shipwright)" = 1 ] && [ "$(calls assayer)" = 1 ] && [ "$(jq -r .status "$REC")" = awaiting-review ] && [ "$(jq -r .resumed "$REC")" = 1 ]'
fresh; export QUARTERDECK_CYCLE_BUDGET=0.25
cyc tp --issue 7 --apply
ck "the per-cycle ceiling stops a stage that would cross it: the record says stopped-ceiling, with the cost so far" '[ "$RC" = 2 ] && [ "$(jq -r .status "$REC")" = stopped-ceiling ] && [ "$(order)" = "purser panel shipwright " ] && grep -q "cycle ceiling" <<<"$OUT" && grep -q "QUARTERDECK_CYCLE_BUDGET" <<<"$OUT"'
CEILID=$ID; export QUARTERDECK_CYCLE_BUDGET=15
cyc --resume "$CEILID"
ck "  raised, the same cycle resumes and finishes without repeating a stage" '[ "$RC" = 0 ] && [ "$(calls panel)" = 1 ] && [ "$(jq -r .status "$REC")" = awaiting-review ]'
unset QUARTERDECK_CYCLE_BUDGET; cyc --status; ck "the default ceiling is 15 dollars" 'grep -q "ceiling .15" <<<"$(bash "$T/bin/cycle" tp --issue 7 2>&1)" || jq -e ".budget.ceiling == 15" "$REC" >/dev/null'
export QUARTERDECK_CYCLE_BUDGET=15

# ---- resume: a failed stage, and a real crash --------------------------------------------------------------------------------------
fresh; cfg shipwright "ERROR|run failed|" "PR|#7 → pull/1|https://github.com/x/tp/pull/1"
cyc tp --issue 7 --apply
ck "a stage that fails stops the cycle as failed, resumable, with everything before it on the record" '[ "$RC" = 1 ] && [ "$(jq -r .status "$REC")" = failed ] && [ "$(stg shipwright .state)" = failed ] && [ "$(stg panel .state)" = done ] && grep -q "quarterdeck cycle --resume" <<<"$OUT"'
FID=$ID; cyc --resume "$FID"
ck "  --resume continues at the failed stage: the shipwright runs again, the purser and the panel do not" '[ "$RC" = 0 ] && [ "$(calls shipwright)" = 2 ] && [ "$(calls purser)" = 1 ] && [ "$(calls panel)" = 1 ] && [ "$(jq -r .status "$REC")" = awaiting-review ]'
fresh; cfg panel "CRASH|x|"
cyc tp --issue 7 --apply
CID=$ID
ck "a crashed cycle (the process is killed) leaves a record that still says running, with the purser finished" '[ "$(jq -r .status "$REC")" = running ] && [ "$(stg purser .state)" = done ] && [ "$(stg panel .state)" = running ]'
cfg panel "RULED|dev: 2 of 3 on issue #7|"
cyc --resume "$CID"
ck "  and --resume takes it over (the dead lock is broken), re-runs the panel, never the purser, and finishes" '[ "$RC" = 0 ] && [ "$ID" = "$CID" ] && [ "$(calls purser)" = 1 ] && [ "$(calls panel)" = 2 ] && [ "$(jq -r .status "$REC")" = awaiting-review ]'
fresh; cfg inspector "ERROR|unparseable|"
cyc tp --issue 7 --apply
ck "when one reviewer fails the others' results are still all collected before the cycle stops" '[ "$(jq -r .status "$REC")" = failed ] && [ "$(stg "r1:surveyor" .state)" = done ] && [ "$(stg "r1:pilot" .state)" = done ] && [ "$(stg "r1:inspector" .state)" = failed ] && [ "$(calls caulker)" = 0 ]'
cfg inspector "PROVEN|ok|"; FID=$ID; cyc --resume "$FID"
ck "  and the resume re-runs only the reviewer that failed" '[ "$RC" = 0 ] && [ "$(calls inspector)" = 2 ] && [ "$(calls surveyor)" = 1 ] && [ "$(calls marshal)" = 1 ]'
fresh; cfg purser "SILENT|x|"
cyc tp --issue 7 --apply
ck "a duty that leaves no verdict (a usage limit, a held lock) is a failed stage, never a pass" '[ "$(jq -r .status "$REC")" = failed ] && [ "$(stg purser .state)" = failed ] && [ "$(stg purser .verdict)" = NONE ]'
fresh; touch "$T/.x"; mkdir -p "$T/state/cycle-tp-7.lock"; sleep 30 & SLP=$!; echo "$SLP" > "$T/state/cycle-tp-7.lock/pid"
cyc tp --issue 7 --apply; kill "$SLP" 2>/dev/null; wait "$SLP" 2>/dev/null
ck "two cycles on the same issue cannot run at once" '[ "$RC" != 0 ] && grep -q "already running" <<<"$OUT" && [ ! -s "$T/stub-calls" ]'
rm -rf "$T/state/cycle-tp-7.lock"

# ---- part 2: the REAL shipwright and assayer, a stand-in model, a real git repository ---------------------------------------------
# The assayer works from the acceptance checks in a worktree of the BASE branch. Whatever the shipwright wrote must not reach it.
fresh
for d in purser panel surveyor marshal lookout pilot inspector caulker; do mkstub "$d"; done
cp "$REAL/duties/shipwright.sh" "$REAL/duties/assayer.sh" "$T/duties/"
st_registry "$ALL" "$REG_EXTRA"
cfg purser "READY|2|"; cfg panel "RULED|dev: 1 of 1 on issue #7|"
st_reply 'Fix this one issue' 'RESULT: FIXED reset sets the counter to zero'
st_reply 'writing tests for one issue' 'TESTS_JSON: [{"file":"tests/test_reset.py","name":"reset sets zero","accept":"counter_reset(5) equals 0"}]
RESULT: WRITTEN 1 test file(s)'
: > "$T/claude-calls"
cat > "$T/claude-hook" <<'HOOK'
#!/bin/bash
# runs in the model's working directory
case "$1" in
  *"Fix this one issue"*) sed 's/return n/return 0  # SHIPWRIGHT-MARKER-7/' app.py > app.py.t && mv app.py.t app.py ;;
  *"writing tests for one issue"*)
    grep -q SHIPWRIGHT-MARKER-7 app.py && echo "SAW-THE-DIFF" > "$QUARTERDECK_DIR/assayer-saw"
    [ -d "$QUARTERDECK_DIR/assayer-saw" ] || echo "$PWD" > "$QUARTERDECK_DIR/assayer-cwd"
    mkdir -p tests; printf 'from app import counter_reset\nassert counter_reset(5) == 0\n' > tests/test_reset.py ;;
esac
HOOK
chmod +x "$T/claude-hook"; rm -f "$T/assayer-saw" "$T/assayer-cwd"
cyc tp --issue 7 --apply
ck "the real shipwright built the change and the cycle took its pull request" '[ "$(stg shipwright .verdict)" = PR ] && [ "$(jq -r .pr "$REC")" = https://github.com/x/tp/pull/1 ] && git -C "$T/origin.git" show fix/7-add-a-reset-button:app.py | grep -q SHIPWRIGHT-MARKER-7'
ck "the assayer ran as a separate agent after it, and its tests were verified (fail on base, pass on head)" '[ "$(stg assayer .verdict)" = VERIFIED ] && [ "$(grep -c "writing tests for one issue" "$T/claude-calls")" = 1 ] && [ "$(grep -c "Fix this one issue" "$T/claude-calls")" = 1 ]'
ck "the assayer was never shown the shipwright's diff: not in its prompt, and not in the worktree it worked in" '! jq -r "select(.prompt | contains(\"writing tests for one issue\")) | .prompt" "$T/claude-calls" | grep -q "SHIPWRIGHT-MARKER-7" && [ ! -e "$T/assayer-saw" ] && [ -s "$T/assayer-cwd" ] && [[ "$(cat "$T/assayer-cwd")" == *wt-assay-base-* ]]'
ck "  and the assayer's prompt carries the acceptance checks from the issue" 'jq -r "select(.prompt | contains(\"writing tests for one issue\")) | .prompt" "$T/claude-calls" | grep -q "counter_reset(5) equals 0"'
ck "  the shipwright and the assayer are two separate model calls, each with its own run id and its own cost line" '[ -n "$(stg shipwright ".runs[0]")" ] && [ "$(stg shipwright ".runs[0]")" != "$(stg assayer ".runs[0]")" ] && jq -e "[.stages[] | select(.id == \"shipwright\" or .id == \"assayer\") | .cost] == [0.1, 0.1]" "$REC" >/dev/null'
ck "  the assayer proposed its tests as their own pull request, noted for the reviewer, never merged" 'jq -e ".notes | any(contains(\"the assayer proposed tests\"))" "$REC" >/dev/null && ! grep -qE "^gh pr (merge|review)" "$T/gh-calls"'
ck "  the cycle drove it to a stop for a person" '[ "$(jq -r .status "$REC")" = awaiting-review ]'

# ---- part 3: the surveyor leaves the findings file the caulker reads ----------------------------------------------------------------
cp "$REAL/duties/surveyor.sh" "$T/duties/"
st_noreplies; rm -f "$T/claude-hook" "$T/gh-calls"; rm -rf "$T/state/findings"
st_reply default 'FINDINGS_JSON: [{"file":"app.py","line":2,"severity":"major","title":"reset ignores the argument","body":"returns 0 for every input"}]
ADR: searched none
VERDICT: FINDINGS 1'
st_duty surveyor --pr 1
ck "report only: the surveyor writes no findings file" '[ ! -e "$T/state/findings/tp-pr1-surveyor.json" ]'
st_duty surveyor --pr 1 --apply
ck "--apply: the surveyor writes the findings file for this exact head, with the file the caulker may change" 'jq -e --arg h "$(jq -r .headRefOid "$T/ghdata/pr-1.json")" ".duty == \"surveyor\" and .head == \$h and .verdict == \"FINDINGS 1\" and .findings[0].id == \"surveyor-1\" and .findings[0].paths == [\"app.py\"] and .findings[0].kind == \"code\"" "$T/state/findings/tp-pr1-surveyor.json" >/dev/null'
st_noreplies; st_reply default $'FINDINGS_JSON: []\nADR: searched none\nVERDICT: CLEAN'
st_duty surveyor --pr 1 --apply
ck "  a clean review overwrites it with an empty list, so an old finding is not left open" 'jq -e ".verdict == \"CLEAN\" and (.findings | length) == 0" "$T/state/findings/tp-pr1-surveyor.json" >/dev/null'

# ---- structure ---------------------------------------------------------------------------------------------------------------------------
ck "the orchestrator is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/bin/cycle" && [ "$(tail -c 3 "$REAL/bin/cycle" | tr -d "\n")" = "}" ]'
ck "it never merges, approves, pushes or writes to GitHub itself (the duties do, with --apply)" '! grep -vE "^[[:space:]]*#" "$REAL/bin/cycle" | grep -qE "pr merge|pr review|git .*push|\"\\\$GH\" (pr|issue) (create|edit|comment|merge)"'
st_done
