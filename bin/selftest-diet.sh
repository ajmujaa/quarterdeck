#!/bin/bash
# Using fewer tokens (issue 121): the turn cap and what a builder does when it is reached, reuse of an answer whose inputs did not change,
# the panel's second round only where seats overlap, fewer seats on a small subject, a model per seat and its cost, and the prompt
# switches (terse block, build focus, stable system prompt). Run against stand-ins for the model and gh and a real git repository.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init shipwright inspector panel
cp "$REAL/bin/spend.py" "$T/bin/"
# The stand-in model, plus: a reply of __MAX_TURNS__ comes back the way the CLI reports a call stopped at --max-turns.
mv "$T/claude" "$T/claude.base"
cat > "$T/claude" <<'W'
#!/bin/bash
o=$("$QUARTERDECK_DIR/claude.base" "$@")
if [ "$(jq -r .result <<<"$o")" = __MAX_TURNS__ ]; then jq -c '. + {subtype:"error_max_turns", is_error:true, result:null, num_turns:4}' <<<"$o"; else printf '%s' "$o"; fi
W
chmod +x "$T/claude"
st_repo
st_file src/cart.js $'function total(c) { return c.length; }\n'
st_commit "cart"
st_issue 7 "Cart total ignores quantity" "Two apples at 5 total 5."
PR_BODY="Fixes #7" st_pr 2 fix-qty src/cart.js $'function total(c) { return c.length * 2; }\n'
st_registry '["shipwright","inspector","panel"]'
calls() { [ -f "$T/claude-calls" ] && grep -c . "$T/claude-calls" || echo 0; }
argv_has() { jq -e --arg a "$1" 'select(.argv | index([$a]))' "$T/claude-calls" >/dev/null 2>&1; }
INSPECT_OK='TEST_JSON: {"exists":true,"name":"n","given":"g","when":"w","then":"t","where":"test/x.js"}
ADR: searched none
RESULT: UNPROVEN no test'

# ---- 1. the turn cap, and a builder that reaches it -------------------------------------------------------------------------
st_noreplies; st_reply default '__MAX_TURNS__'
cat > "$T/claude-hook" <<'HOOK'
#!/bin/bash
case "$1" in *"Fix this one issue"*) echo "// half done" >> src/cart.js ;; esac
HOOK
chmod +x "$T/claude-hook"
QUARTERDECK_MAX_TURNS_SHIPWRIGHT=40 st_duty shipwright --issue 7 --apply
WT="$T/workspace/wt-tp-7"
ck "the builder's call is capped: --max-turns 40 from QUARTERDECK_MAX_TURNS_SHIPWRIGHT" 'jq -e "select(.argv | index([\"--max-turns\"])) | .argv[(.argv | index([\"--max-turns\"])) + 1] == \"40\"" "$T/claude-calls" >/dev/null'
ck "a call that runs out of turns ends NEEDS_HUMAN: ran out of turns" '[ "$(last_verdict)" = NEEDS_HUMAN ] && grep -q "ran out of turns" <<<"$(last_detail)" && grep -q "NEEDS_HUMAN: ran out of turns" <<<"$OUT"'
ck "  the partial work is kept in the worktree" 'grep -q "half done" "$WT/src/cart.js"'
ck "  and nothing is committed, pushed or opened" '[ "$(git -C "$T/origin.git" branch --list "fix/7-*" | wc -l | tr -d " ")" = 0 ] && [ "$(git -C "$WT" rev-parse HEAD)" = "$(git -C "$T/work" rev-parse main)" ] && no_gh_writes'
ck "  and the spend ledger books the call as stopped at the turn cap" '[ "$(tail -1 "$T/state/spend.jsonl" | jq -r .stopped)" = turns ]'
rm -f "$T/claude-hook"; git -C "$T/work" worktree remove --force "$WT" 2>/dev/null
st_noreplies; st_reply default 'RESULT: NO_CHANGE nothing'
st_duty shipwright --issue 7
ck "no cap set: no --max-turns is passed" '! argv_has --max-turns'

# ---- 2. the prompt switches -----------------------------------------------------------------------------------------------------
printf '# plan\n\n## 1. Multiply\n\n**Where.** `src/cart.js:1`\n\n## 2. Receipt\n\n**Where.** `src/receipt.js`\n' > "$T/plan.md"
st_noreplies; st_reply default 'RESULT: NO_CHANGE nothing'
QUARTERDECK_BUILD_FOCUS=on QUARTERDECK_TERSE=on QUARTERDECK_STABLE_PROMPT=on st_duty shipwright --issue 7 --plan "$T/plan.md"
P=$(jq -r .prompt "$T/claude-calls")
ck "build focus: the files the plan names are given up front" 'grep -q "Start from the files the ruling names" <<<"$P" && grep -q "^    src/cart.js:1$" <<<"$P" && grep -q "^    src/receipt.js$" <<<"$P"'
ck "  with a stop rule" 'grep -q "Stop as soon as the change is made" <<<"$P"'
ck "the terse block is in the shared preamble, and keeps the safety words" 'grep -q "Say only what the contract needs" <<<"$P" && grep -q "never skip validation, security checks, or the required fields" <<<"$P"'
ck "  and the hard rules and the UNTRUSTED rule are still there" 'grep -q "Never touch money code" <<<"$P" && grep -q "BEGIN UNTRUSTED issue text" <<<"$P"'
ck "a stable system prompt: the CLI is asked to move per-machine sections out of it" 'argv_has --exclude-dynamic-system-prompt-sections'
st_noreplies; st_reply default 'RESULT: NO_CHANGE nothing'
QUARTERDECK_BUILD_FOCUS=off QUARTERDECK_TERSE=off QUARTERDECK_STABLE_PROMPT=off st_duty shipwright --issue 7 --plan "$T/plan.md"
P=$(jq -r .prompt "$T/claude-calls")
ck "all three off: none of it is sent" '! grep -q "Start from the files" <<<"$P" && ! grep -q "Say only what the contract needs" <<<"$P" && ! argv_has --exclude-dynamic-system-prompt-sections'

# ---- 3. skip when nothing changed ---------------------------------------------------------------------------------------------------
export QUARTERDECK_REUSE="inspector panel"
st_noreplies; st_reply default "$INSPECT_OK"
st_duty inspector --pr 2
ck "first inspection: one model call, its answer stored for reuse" '[ "$(calls)" = 1 ] && [ "$(ls "$T/state/reuse" | wc -l | tr -d " ")" = 1 ]'
st_duty inspector --pr 2
ck "the same inputs again: no model call, the same verdict" '[ "$(calls)" = 1 ] && grep -q "UNPROVEN" <<<"$(last_detail)"'
ck "  with a visible reused note, in the output and on the run's row" 'grep -q "reused: the same inputs were answered" <<<"$OUT" && grep -q -- "--fresh" <<<"$OUT" && grep -q "reused 1 earlier answer" <<<"$(last_detail)"'
ck "  the ledger books it as reused, at no cost, with the input hash" 'tail -1 "$T/state/spend.jsonl" | jq -e ".reused == true and .cost == 0 and (.key | length) == 32" >/dev/null'
st_registry '["shipwright","inspector","panel"]' '{"verify":"echo took $(od -An -N4 -tu4 /dev/urandom) ms"}'
st_duty inspector --pr 2; n=$(calls); st_duty inspector --pr 2
ck "numbers in the verify command's output (timings) do not make the inputs new" '[ "$n" = 2 ] && [ "$(calls)" = 2 ] && grep -q "reused" <<<"$(last_detail)"'
st_registry '["shipwright","inspector","panel"]'
QUARTERDECK_FRESH=1 st_duty inspector --pr 2
ck "--fresh (QUARTERDECK_FRESH=1) asks the model again" '[ "$(calls)" = 3 ] && ! grep -q "reused" <<<"$(last_detail)"'
out=$(grep -A3 'args=()' "$REAL/bin/qtdeck")
ck "  and qtdeck run turns --fresh into QUARTERDECK_FRESH=1 and does not pass it to the duty" 'grep -q "= --fresh ]; then export QUARTERDECK_FRESH=1; else args+=" <<<"$out"'
jq '.body = "Fixes #7 and more"' "$T/ghdata/pr-2.json" > "$T/x.json" && mv "$T/x.json" "$T/ghdata/pr-2.json"
st_duty inspector --pr 2
ck "a changed input (the pull request text) is a new key: the model is asked" '[ "$(calls)" = 4 ]'
QUARTERDECK_MODEL_INSPECTOR=claude-other st_duty inspector --pr 2
ck "  so is another model" '[ "$(calls)" = 5 ]'
st_noreplies; st_reply default 'nonsense with no contract'
QUARTERDECK_MODEL_INSPECTOR=claude-third st_duty inspector --pr 2
QUARTERDECK_MODEL_INSPECTOR=claude-third st_duty inspector --pr 2
ck "an answer without a contract is never stored: asked again next time" '[ "$(calls)" = 2 ]'
st_noreplies; st_reply default "$INSPECT_OK"
QUARTERDECK_REUSE="" st_duty inspector --pr 2; QUARTERDECK_REUSE="" st_duty inspector --pr 2
ck "a duty not listed in QUARTERDECK_REUSE is always asked" '[ "$(calls)" = 2 ]'
st_noreplies; st_reply default 'RESULT: NO_CHANGE nothing'
QUARTERDECK_REUSE="shipwright" st_duty shipwright --issue 7; QUARTERDECK_REUSE="shipwright" st_duty shipwright --issue 7
ck "a call that can edit (the builder) is never reused, even when listed" '[ "$(calls)" = 2 ]'
echo "x" >> "$T/work/README.md"
st_noreplies; st_reply default "$INSPECT_OK"
st_duty panel --panel design --seats shipwright,inspector 2>/dev/null; n1=$(calls)
st_duty panel --panel design --seats shipwright,inspector 2>/dev/null
ck "a working folder with a tracked change is never reused" '[ "$(calls)" -gt "$n1" ]'
git -C "$T/work" checkout -q README.md
export QUARTERDECK_REUSE=""   # empty, not unset: unset means the shipped default

# ---- 4. panels: round 2 only where seats disagree; fewer seats for a small subject; a model per seat -------------------------------
ITEM() { printf 'ITEMS_JSON: [{"area":"a","severity":"major","title":"t","claim":"c","where":"%s","why":"y","action":"a"}]\nRESULT: ITEMS 1' "$1"; }
RULE='HEADLINE: h
RULING_JSON: [{"kind":"change","tier":"routine","area":"a","severity":"major","title":"t","claim":"c","where":"w","why":"y","action":"a","support":["shipwright"],"overruled":[],"note":""}]
RESULT: RULED 1'
seats3() { st_reply 'RULING_JSON' "$RULE"; st_reply 'STANCES_JSON' $'STANCES_JSON: []\nRESULT: STANCES 0'
  st_reply 'You are the shipwright' "$(ITEM src/cart.js:1)"; st_reply 'You are the inspector' "$(ITEM test/cart.test.js)"; st_reply 'You are the naval-architect' "$(ITEM src/receipt.js:4)"; }
r2calls() { jq -r 'select(.prompt | contains("STANCES_JSON")) | 1' "$T/claude-calls" | wc -l | tr -d " "; }
st_noreplies; st_reply 'CONTESTED_JSON' $'CONTESTED_JSON: []\nRESULT: CONTESTED 0'; seats3
st_duty panel --panel dev --issue 7 --rounds auto
ck "--rounds auto, no seat contradicts another: no second round, straight to the ruling" '[ "$(r2calls)" = 0 ] && grep -q "round 2 skipped" <<<"$OUT" && [ "$(calls)" = 5 ]'
ck "  the agreement check is one call on the small model, Read only, the seat items as UNTRUSTED data" 'jq -e "select(.prompt | contains(\"CONTESTED_JSON\")) | .model == \"claude-haiku-4-5\" and .tools == \"Read\" and (.prompt | contains(\"BEGIN UNTRUSTED seat findings\"))" "$T/claude-calls" >/dev/null'
ck "  and the panel is ruled as usual" '[ "$(jq -r .status "$(ls -t "$T"/state/panels/*.json | head -1)")" = done ]'
st_noreplies; st_reply 'CONTESTED_JSON' $'CONTESTED_JSON: ["shipwright-1","naval-architect-1"]\nRESULT: CONTESTED 2'; seats3
st_duty panel --panel dev --issue 7 --rounds auto
R2=$(jq -r 'select(.prompt | contains("STANCES_JSON")) | .prompt' "$T/claude-calls")
ck "two seats contradict each other: a second round, on those items only" '[ "$(r2calls)" = 3 ] && grep -q "\[shipwright-1\]" <<<"$R2" && grep -q "\[naval-architect-1\]" <<<"$R2" && ! grep -q "\[inspector-1\]" <<<"$R2"'
st_noreplies; st_reply 'CONTESTED_JSON' 'I am not sure'; seats3
st_duty panel --panel dev --issue 7 --rounds auto
R2=$(jq -r 'select(.prompt | contains("STANCES_JSON")) | .prompt' "$T/claude-calls")
ck "  an agreement check that does not parse sends every item back, as before" '[ "$(r2calls)" = 3 ] && grep -q "\[inspector-1\]" <<<"$R2" && grep -q "every item goes back" <<<"$OUT"'
st_noreplies; st_reply 'RULING_JSON' "$RULE"; st_reply 'STANCES_JSON' $'STANCES_JSON: []\nRESULT: STANCES 0'; st_reply default "$(ITEM src/cart.js)"
st_duty panel --panel dev --issue 7
ck "the default is still two rounds for every item" '[ "$(jq -r "select(.prompt | contains(\"STANCES_JSON\")) | 1" "$T/claude-calls" | wc -l | tr -d " ")" = 3 ]'
st_duty panel --panel dev --issue 7 --rounds 3
ck "--rounds takes 1, 2 or auto" '[ "$RC" != 0 ] && grep -q "takes 1, 2 or auto" <<<"$OUT"'

st_noreplies; st_reply 'RULING_JSON' "$RULE"; st_reply default "$(ITEM src/cart.js)"
n_design=$(cd "$T" && QUARTERDECK_DIR="$T" bash -c 'source bin/lib.sh; crew_by_discipline design | wc -l' | tr -d ' ')
QUARTERDECK_PANEL_SMALL_LINES=50 st_duty panel --panel design --target src --rounds 1
ck "a small subject (a --target of at most QUARTERDECK_PANEL_SMALL_LINES lines) sits two seats" '[ "$n_design" -gt 2 ] && [ "$(jq -r "select(.prompt | contains(\"ITEMS_JSON\")) | 1" "$T/claude-calls" | wc -l | tr -d " ")" = 2 ] && grep -q "is small" <<<"$OUT"'
st_noreplies; st_reply 'RULING_JSON' "$RULE"; st_reply default "$(ITEM src/cart.js)"
st_duty panel --panel design --target src --rounds 1
ck "  the threshold is off by default: every seat sits" '[ "$(jq -r "select(.prompt | contains(\"ITEMS_JSON\")) | 1" "$T/claude-calls" | wc -l | tr -d " ")" = "$n_design" ]'

st_noreplies; : > "$T/state/spend.jsonl"; st_reply 'RULING_JSON' "$RULE"; st_reply default "$(ITEM src/cart.js)"
QUARTERDECK_MODEL_SEAT_NAVAL_ARCHITECT=claude-seat-test st_duty panel --panel dev --issue 7 --rounds 1
ck "a model per seat: QUARTERDECK_MODEL_SEAT_NAVAL_ARCHITECT reaches that seat's call only" '[ "$(jq -r "select(.prompt | contains(\"You are the naval-architect\")) | .model" "$T/claude-calls")" = claude-seat-test ] && [ "$(jq -r "select(.prompt | contains(\"You are the shipwright\")) | .model" "$T/claude-calls")" != claude-seat-test ]'
ck "  every panel call is booked under its seat, the chair included" '[ "$(jq -sr "map(.seat) | sort | join(\",\")" "$T/state/spend.jsonl")" = "dockmaster,inspector,naval-architect,shipwright" ]'
ck "  and qtdeck spend shows the cost per seat and the top sinks" 'o=$(python3 "$T/bin/spend.py" "$T"); grep -q "by panel seat" <<<"$o" && grep -q "naval-architect" <<<"$o" && grep -q "top sinks" <<<"$o" && grep -q "tp/panel" <<<"$o"'

st_done
