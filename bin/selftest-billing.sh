#!/bin/bash
# Billing (ticket #38): a duty is billed to your plan (the claude sign-in, the default) or to an Anthropic API key, never silently to the wrong one.
#   - an api duty's process gets the key in its ENVIRONMENT only: never in argv, the sandbox settings file, the prompt, a run record or a log
#   - a plan duty gets no ANTHROPIC_API_KEY (nor ANTHROPIC_AUTH_TOKEN) even when the owner's shell has one, in the clean and the inherited environment
#   - an api duty with no key stored, or at a spend cap, does not run: NEEDS_HUMAN and why, and no second ERROR row for the same run
#   - `qtdeck keys set anthropic` reads standard input only; doctor and the outgoing-text scan know the key without ever showing it
# The stand-in claude records its argv, environment, prompt and sandbox settings. No real model and no real key: the key is invented.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init surveyor shipwright
cp "$REAL/bin/qtdeck" "$T/bin/"
export QUARTERDECK_SECRETS_DIR="$T/sec" QUARTERDECK_HOME="$T"
KEY="sk-ant-api03-Zq7$(printf 'k%.0s' $(seq 1 40))9xVb2"
STRAY="sk-ant-api03-STRAY$(printf 's%.0s' $(seq 1 40))41"

# a stand-in claude: one folder per call with argv (NUL separated), the environment (NUL separated), the prompt and the settings file
{ printf '#!/bin/bash\nQD_CALLS=%q\n' "$T/calls"; cat <<'STUB'
n=0; until mkdir "$QD_CALLS/$(printf %05d "$n")" 2>/dev/null; do n=$((n + 1)); done; d="$QD_CALLS/$(printf %05d "$n")"   # numbered, so the last call sorts last
printf '%s\0' "$@" > "$d/argv"
env -0 > "$d/env"
cat > "$d/prompt"
while [ $# -gt 0 ]; do [ "$1" = --settings ] && cp "$2" "$d/settings"; shift; done
printf 'claude: some error text on stderr\n' >&2
jq -n --argjson c "$(cat "$QD_CALLS.cost" 2>/dev/null || echo 0.05)" '{result:"RESULT: DONE ok", total_cost_usd:$c, num_turns:1, usage:{}, modelUsage:{"stub-model":{}}}'
STUB
} > "$T/envclaude"
chmod +x "$T/envclaude"
export CLAUDE_BIN="$T/envclaude"
mkdir -p "$T/calls" "$T/w"
calls() { ls "$T/calls" | wc -l | tr -d ' '; }
lastcall() { echo "$T/calls/$(ls "$T/calls" | sort | tail -1)"; }
envof() { tr '\0' '\n' < "$(lastcall)/env"; }
# run claude_run as duty $1 (the duty name is the script name, $0), clean environment unless $2 says inherit, with a stray key in the shell
cr() { local duty=$1 envmode=${2:-clean} tools=${3:-Read,Grep,Glob}
  ( unset QUARTERDECK_CLAUDE_ENV; [ "$envmode" = inherit ] && export QUARTERDECK_CLAUDE_ENV=inherit
    export ANTHROPIC_API_KEY="$STRAY" ANTHROPIC_AUTH_TOKEN="tok-$STRAY" QUARTERDECK_RUN_ID="r-$duty-$RANDOM" QUARTERDECK_PROJECT=tp
    bash -c 'source "$QUARTERDECK_DIR/bin/lib.sh"; claude_run "$1" "the prompt" "$2" >/dev/null; rc=$?; echo "$rc" > "$QUARTERDECK_DIR/cr-rc"
             record_run tp "$(basename "$0" .sh)" ERROR "run failed"' "$duty" "$T/w" "$tools" 2>/dev/null )
  CRRC=$(cat "$T/cr-rc"); }

# ---- the key goes in on standard input only -------------------------------------------------------------------------
out=$(bash "$T/bin/qtdeck" keys set anthropic "$KEY" 2>&1 </dev/null); arc=$?
ck "qtdeck keys set anthropic refuses the key as an argument, stores nothing and does not echo it" \
   '[ "$arc" != 0 ] && ! grep -qF "$KEY" <<<"$out" && ! grep -rqF "$KEY" "$T/sec" 2>/dev/null'
out=$(printf '%s\n' "$KEY" | bash "$T/bin/qtdeck" keys set anthropic 2>&1); src=$?
ck "qtdeck keys set anthropic reads the key from standard input into the owner-only credential file, and says only that it is stored" \
   '[ "$src" = 0 ] && grep -q "stored" <<<"$out" && ! grep -qF "$KEY" <<<"$out" && grep -qxF "anthropic_api_key=$KEY" "$T/sec/integrations.env" && [ "$(stat -c %a "$T/sec/integrations.env" 2>/dev/null || stat -f %Lp "$T/sec/integrations.env")" = 600 ]'
out=$(python3 "$T/bin/billing.py" key 2>&1 < /dev/null | cat)
ck "billing.py key hands the value to a pipe (the harness) and nothing else" '[ "$out" = "$KEY" ]'

# ---- plan is the default; api is chosen per duty ---------------------------------------------------------------------
ck "with no billing setting every duty is billed to the plan" '[ "$(python3 "$T/bin/billing.py" mode shipwright)" = plan ]'
out=$(bash "$T/bin/qtdeck" billing shipwright api 2>&1)
ck "qtdeck billing <duty> api sets one duty, the rest stay on the plan" \
   '[ "$(python3 "$T/bin/billing.py" mode shipwright)" = api ] && [ "$(python3 "$T/bin/billing.py" mode surveyor)" = plan ]'
python3 "$T/bin/billing.py" set-seat modelmaker api >/dev/null
ck "a crew seat's own setting wins over its duty's" '[ "$(python3 "$T/bin/billing.py" mode panel modelmaker)" = api ] && [ "$(python3 "$T/bin/billing.py" mode panel gunner)" = plan ]'

for em in clean inherit; do
  cr shipwright "$em"; d=$(lastcall)
  ck "[$em env] an api duty's claude gets ANTHROPIC_API_KEY = the stored key in its environment, not the shell's stray one, and no ANTHROPIC_AUTH_TOKEN" \
     '[ "$CRRC" = 0 ] && envof | grep -qxF "ANTHROPIC_API_KEY=$KEY" && ! envof | grep -qF "$STRAY" && ! envof | grep -q "^ANTHROPIC_AUTH_TOKEN="'
  ck "[$em env] and the key is not in its argv or its prompt" '[ -s "$d/argv" ] && ! grep -qaF "$KEY" "$d/argv" && ! grep -qaF "$KEY" "$d/prompt"'
  cr surveyor "$em"; d=$(lastcall)
  ck "[$em env] a plan duty's claude gets no ANTHROPIC_API_KEY and no ANTHROPIC_AUTH_TOKEN even though the owner's shell has both" \
     '[ "$CRRC" = 0 ] && ! envof | grep -q "^ANTHROPIC_API_KEY=" && ! envof | grep -q "^ANTHROPIC_AUTH_TOKEN=" && ! grep -qaF "$KEY" "$d/env" "$d/argv"'
done
( export QUARTERDECK_SEAT=modelmaker; cr panel ); seat_api=$(envof | grep -c "^ANTHROPIC_API_KEY=")
( export QUARTERDECK_SEAT=gunner; cr panel ); seat_plan=$(envof | grep -c "^ANTHROPIC_API_KEY=")
ck "a panel seat set to the API key gets it, a seat on the plan in the same duty does not; panel, marshal and pilot name the seat for each call" \
   '[ "$seat_api" = 1 ] && [ "$seat_plan" = 0 ] && grep -q "export QUARTERDECK_SEAT=\"\$1\"" "$REAL/duties/panel.sh" && grep -q "export QUARTERDECK_SEAT=\"\$seat\"" "$REAL/duties/marshal.sh" "$REAL/duties/pilot.sh"'
cr shipwright clean "Read,Edit,Grep,Glob,Bash(npm run*)"; d=$(lastcall)
ck "a call with a shell (so a sandbox settings file) carries the key in its environment only, not in the settings file" \
   '[ -s "$d/settings" ] && ! grep -qF "$KEY" "$d/settings" && ! grep -qaF "$KEY" "$d/argv" && envof | grep -qxF "ANTHROPIC_API_KEY=$KEY"'
ck "the spend ledger says which account each call was billed to" \
   'jq -se "map(select(.duty == \"shipwright\")) | all(.billing == \"api\")" "$T/state/spend.jsonl" >/dev/null && jq -se "map(select(.duty == \"surveyor\")) | all(.billing == \"plan\")" "$T/state/spend.jsonl" >/dev/null'

# ---- an api duty with no key, or at a cap, does not run ---------------------------------------------------------------
cp "$T/sec/integrations.env" "$T/keyfile.bak"; printf '' | python3 "$T/bin/billing.py" remove-key >/dev/null
n0=$(calls); cr shipwright
ck "an api duty with no key stored does not start claude, and is NOT quietly billed to the plan" '[ "$CRRC" != 0 ] && [ "$(calls)" = "$n0" ]'
ck "it stops with NEEDS_HUMAN and says why, and the duty's own ERROR row for the same run is not added" \
   '[ "$(jq -r ".[-1].verdict" "$T/state/runs.json")" = NEEDS_HUMAN ] && jq -r ".[-1].detail" "$T/state/runs.json" | grep -qi "no API key"'
cp "$T/keyfile.bak" "$T/sec/integrations.env"; chmod 600 "$T/sec/integrations.env"

: > "$T/state/spend.jsonl"
python3 "$T/bin/billing.py" cap daily 0.10 >/dev/null
echo 0.06 > "$T/calls.cost"     # the stand-in runs in a clean environment: its cost comes from a file
n0=$(calls); cr shipwright; r1=$CRRC; cr shipwright; r2=$CRRC; d2=$(lastcall); cr shipwright; r3=$CRRC
ck "the daily API cap: two calls of \$0.06 run (the second capped at what is left, \$0.04), the third does not start" \
   '[ "$r1" = 0 ] && [ "$r2" = 0 ] && [ "$r3" != 0 ] && [ "$(calls)" = $((n0 + 2)) ] && tr "\0" "\n" < "$d2/argv" | grep -A1 -x -- --max-budget-usd | tail -1 | grep -qx "0.0400"'
ck "at the cap the duty stops with NEEDS_HUMAN and says which cap" \
   '[ "$(jq -r ".[-1].verdict" "$T/state/runs.json")" = NEEDS_HUMAN ] && jq -r ".[-1].detail" "$T/state/runs.json" | grep -q "daily API spend cap"'
n0=$(calls); cr surveyor
ck "a plan duty is not stopped by the API caps (they count only calls billed to the key)" '[ "$CRRC" = 0 ] && [ "$(calls)" = $((n0 + 1)) ]'
: > "$T/state/spend.jsonl"; python3 "$T/bin/billing.py" cap daily off >/dev/null; python3 "$T/bin/billing.py" cap duty shipwright 0.05 >/dev/null
cr shipwright; r1=$CRRC; n0=$(calls); cr shipwright
ck "the per-duty API cap stops that duty with NEEDS_HUMAN once its own spend reaches it" \
   '[ "$r1" = 0 ] && [ "$CRRC" != 0 ] && [ "$(calls)" = "$n0" ] && jq -r ".[-1].detail" "$T/state/runs.json" | grep -q "cap of the shipwright duty"'
python3 "$T/bin/billing.py" cap duty shipwright off >/dev/null; rm -f "$T/calls.cost"

# ---- with the provider seam and the token diet (bin/selftest-providers.sh, bin/selftest-diet.sh) ------------------------------------
# A billing stop is its own return code: 4 is the turn cap, and a builder reports 4 as "ran out of turns" (a second, wrong NEEDS_HUMAN).
cp "$T/sec/integrations.env" "$T/keyfile.bak"; printf '' | python3 "$T/bin/billing.py" remove-key >/dev/null
cr shipwright
ck "a billing stop returns 5, not the turn cap's 4 (the builder would report it as 'ran out of turns')" '[ "$CRRC" = 5 ]'
cp "$T/keyfile.bak" "$T/sec/integrations.env"; chmod 600 "$T/sec/integrations.env"
# The ledger keeps the reuse key and the billing apart: both were the fourth argument of record_spend on their own branches.
: > "$T/state/spend.jsonl"; cr shipwright
ck "an api call's ledger row says billing api and carries no reuse key it did not have" \
   'tail -1 "$T/state/spend.jsonl" | jq -e ".billing == \"api\" and (has(\"key\") | not) and .provider == \"claude\"" >/dev/null'
# The key belongs to the claude adapter alone: the fake adapter is never handed it, whatever the duty's billing says.
cp -R "$REAL/providers" "$T/providers"; printf '{"text":"RESULT: DONE fake"}' > "$T/fake.json"; : > "$T/fake-calls.jsonl"; n0=$(calls)
( export QUARTERDECK_PROVIDER=fake QUARTERDECK_FAKE_SCRIPT="$T/fake.json" QUARTERDECK_FAKE_RECORD="$T/fake-calls.jsonl"; cr shipwright; cr shipwright inherit )
ck "an api duty on the fake provider: the fake ran, the claude stand-in did not, and the fake got no ANTHROPIC_* name and never the key" \
   '[ "$CRRC" = 0 ] && [ "$(calls)" = "$n0" ] && [ "$(wc -l < "$T/fake-calls.jsonl" | tr -d " ")" = 2 ] && ! jq -r ".env[]" "$T/fake-calls.jsonl" | grep -q "^ANTHROPIC_" && ! grep -qF "$KEY" "$T/fake-calls.jsonl"'
ck "  and its ledger rows are billed to neither account, so the API caps do not count them" \
   'tail -2 "$T/state/spend.jsonl" | jq -se "all(.provider == \"fake\" and .billing == \"none\")" >/dev/null'

# ---- the key is nowhere it should not be ---------------------------------------------------------------------------------
cat > "$T/leakclaude" <<STUB
#!/bin/bash
cat >/dev/null
printf 'Invalid API key: %s\n' "\$ANTHROPIC_API_KEY" >&2
jq -n --arg k "\$ANTHROPIC_API_KEY" '{result:("RESULT: DONE " + \$k), is_error:false, total_cost_usd:0.01, num_turns:1, usage:{}, modelUsage:{}, note:\$k}'
STUB
chmod +x "$T/leakclaude"
( export CLAUDE_BIN="$T/leakclaude"; cr shipwright )
ck "a claude that echoes its key on stderr and in its envelope: the log and the run envelope get it redacted" \
   '! grep -rqF "$KEY" "$T/logs" && grep -rq "API key removed" "$T/logs"'
dout=$(python3 "$T/bin/billing.py" doctor 2>&1)
ck "doctor shows each duty's billing and that the key is present, never the value" \
   'grep -q "billing: shipwright.*API key" <<<"$dout" && grep -q "billing: surveyor.*plan" <<<"$dout" && grep -q "API key.*present" <<<"$dout" && ! grep -qF "$KEY" <<<"$dout"'
ck "qtdeck doctor runs that billing report" 'grep -q "billing.py\" doctor" "$REAL/bin/qtdeck"'
ck "the key is in no run record, spend row, log, run envelope or state file" '! grep -rqaF "$KEY" "$T/state" "$T/logs" "$T/workspace"'
printf 'see %s here\n' "$KEY" > "$T/post.txt"
ck "the outgoing-text scan refuses a text that holds the stored key" '! python3 "$T/bin/outscan.py" "$T/post.txt" >/dev/null 2>&1'
printf 'the reversed form %s\n' "$(rev <<<"$KEY")" > "$T/post2.txt"
ck "and its reversed form, and says so without the value" '! out=$(python3 "$T/bin/outscan.py" "$T/post2.txt" 2>&1) && ! grep -qF "$KEY" <<<"$out"'
st_done
