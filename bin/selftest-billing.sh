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
    export ANTHROPIC_API_KEY="$STRAY" ANTHROPIC_AUTH_TOKEN="tok-$STRAY" QUARTERDECK_RUN_ID="${FIXED_RID:-r-$duty-$RANDOM}"QUARTERDECK_PROJECT=tp
    bash -c 'source "$QUARTERDECK_DIR/bin/lib.sh"; claude_run "$1" "the prompt" "$2" >/dev/null; rc=$?; echo "$rc" > "$QUARTERDECK_DIR/cr-rc"
             record_run tp "$(basename "$0" .sh)" ERROR "run failed"' "$duty" "$T/w" "$tools" 2>/dev/null )
  CRRC=$(cat "$T/cr-rc"); }

# ---- the key goes in on standard input only -------------------------------------------------------------------------
out=$(bash "$T/bin/qtdeck" keys set anthropic "$KEY" 2>&1 </dev/null); arc=$?
ck "qtdeck keys set anthropic refuses the key as an argument, stores nothing and does not echo it" \
   '[ "$arc" != 0 ] && ! grep -qF "$KEY" <<<"$out" && ! grep -rqF "$KEY" "$T/sec" 2>/dev/null'
out=$(printf '%s\n' "$KEY" | bash "$T/bin/qtdeck" keys set anthropic 2>&1); src=$?
ck "qtdeck keys set anthropic reads the key from standard input into the owner-only credential file, and says only that it is stored" \
   '[ "$src" = 0 ] && grep -q "stored" <<<"$out" && ! grep -qF "$KEY" <<<"$out" && grep -qxF "anthropic_api_key=\"$KEY\"" "$T/sec/integrations.env" && [ "$(stat -c %a "$T/sec/integrations.env" 2>/dev/null || stat -f %Lp "$T/sec/integrations.env")" = 600 ]'
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
# review r9 A1: a credential or endpoint that bills anything but the claude sign-in (a cloud switch and its credentials, Foundry, a gateway URL or
# header) reaches neither a plan call nor an api call; the model names do
FOREIGN="ANTHROPIC_FOUNDRY_API_KEY ANTHROPIC_BASE_URL ANTHROPIC_CUSTOM_HEADERS ANTHROPIC_BEDROCK_BASE_URL CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY CLAUDE_CODE_SKIP_BEDROCK_AUTH AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY GOOGLE_APPLICATION_CREDENTIALS CLOUD_ML_REGION AZURE_CLIENT_SECRET"
for em in clean inherit; do for du in surveyor shipwright; do
  ( for v in $FOREIGN; do export "$v=decoy-$v"; done; export ANTHROPIC_MODEL=decoy-model; cr "$du" "$em" )
  ck "[$em env] a $du call (billed to $([ $du = surveyor ] && echo the plan || echo the key)) gets no cloud switch, cloud credential, Foundry key, gateway URL or header; it keeps ANTHROPIC_MODEL" \
     '[ "$CRRC" = 0 ] && ! envof | grep -q "^decoy-\|=decoy-[A-Z]" && envof | grep -qx "ANTHROPIC_MODEL=decoy-model"'
done; done
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

# ---- review r9 A2, A3: a setting, cap or ledger that cannot be read stops a call billed to the key; it never becomes a plan call or an uncapped one --
BJ="$T/config/billing.json"; cp "$BJ" "$T/billing.bak"
stopped() { # stopped <words>: the last call did not start, returned 5, and its NEEDS_HUMAN row says <words>
  [ "$CRRC" = 5 ] && [ "$(calls)" = "$n0" ] && [ "$(jq -r ".[-1].verdict" "$T/state/runs.json")" = NEEDS_HUMAN ] && jq -r ".[-1].detail" "$T/state/runs.json" | grep -qi -- "$1"; }
bad_cfg() { # bad_cfg <label> <billing.json text> <words>
  printf '%s' "$2" > "$BJ"; n0=$(calls); cr shipwright; W=$3
  ck "a billing.json with $1 stops the api duty with NEEDS_HUMAN naming it; it is not billed to the plan" 'stopped "$W"'; }
bad_cfg "invalid JSON" '{"duties": {"shipwright": "api"' "billing.json"
bad_cfg "a mode in capitals" '{"duties": {"shipwright": "API"}}' "billing.json"
bad_cfg "a misspelt duty" '{"duties": {"shipwrigth": "api"}}' "shipwrigth"
bad_cfg "a cap written as a string" '{"duties": {"shipwright": "api"}, "caps": {"daily_usd": "5"}}' "daily_usd"
bad_cfg "a cap of NaN" '{"duties": {"shipwright": "api"}, "caps": {"daily_usd": NaN}}' "billing.json"
bad_cfg "a cap of null" '{"duties": {"shipwright": "api"}, "caps": {"duty_usd": {"shipwright": null}}}' "duty_usd"
bad_cfg "a cap of a million dollars" '{"duties": {"shipwright": "api"}, "caps": {"daily_usd": 1e6}}' "daily_usd"
bad_cfg "a cap for a duty that does not exist" '{"duties": {"shipwright": "api"}, "caps": {"duty_usd": {"no such": 2}}}' "duty_usd"
ck "  and doctor says the billing setting is broken and why, instead of showing every duty on the plan" \
   'python3 "$T/bin/billing.py" doctor | grep -q "^no	billing	config/billing.json: caps duty_usd" && ! python3 "$T/bin/billing.py" doctor | grep -q "your plan"'
cp "$T/billing.bak" "$BJ"
cp "$T/bin/billing.py" "$T/billing.py.bak"; printf 'import sys\nsys.exit(1)\n' > "$T/bin/billing.py"; n0=$(calls); cr shipwright
ck "a billing.py that fails stops the call (whatever the duty's setting, it cannot be known); nothing goes to the plan" 'stopped "billing"'
cp "$T/billing.py.bak" "$T/bin/billing.py"
python3 "$T/bin/billing.py" cap daily 5 >/dev/null; : > "$T/state/spend.jsonl"; chmod 000 "$T/state/spend.jsonl"; n0=$(calls); cr shipwright
ck "with a daily cap, a spend ledger that cannot be read stops the api duty (it is not read as no spend)" 'stopped "spend ledger"'
chmod 600 "$T/state/spend.jsonl"; printf '{"at":"2999-01-01T00:00:00Z","billing":"api","duty":"shipwright","cost":0.01}\nnot json\n' > "$T/state/spend.jsonl"; n0=$(calls); cr shipwright
ck "  and so does a ledger with a line that is not a row" 'stopped "spend ledger"'
printf '{"at":"2999-01-01T00:00:00Z","billing":"api","duty":"shipwright","cost":"lots"}\n' > "$T/state/spend.jsonl"; n0=$(calls); cr shipwright
ck "  and a row billed to the key whose cost is not a number" 'stopped "spend ledger"'
: > "$T/state/spend.jsonl"; cp "$T/billing.bak" "$BJ"; n0=$(calls); cr surveyor
ck "with the setting readable again, a plan duty runs and an api duty runs" '[ "$CRRC" = 0 ] && cr shipwright && [ "$CRRC" = 0 ] && [ "$(calls)" = $((n0 + 2)) ]'

# ---- review r9 A4, A5: every api call that may have reached the API counts against the caps, at its per-call budget at worst; calls running at once
# share what is left instead of each being handed all of it
# a stand-in whose behaviour comes from a file: sleep (killed by the timeout), nocost (no total_cost_usd), empty (prints nothing), slow (a second,
# then a reply costing $0.01). Each call leaves its --max-budget-usd in $T/budgets.
{ printf '#!/bin/bash\nT=%q\n' "$T"; cat <<'STUB'
b=""; while [ $# -gt 0 ]; do [ "$1" = --max-budget-usd ] && b=$2; shift; done
cat >/dev/null; mkdir -p "$T/slowcalls"; : > "$T/slowcalls/$$.$RANDOM"; printf '%s\n' "${b:-none}" >> "$T/budgets"
case "$(cat "$T/slowmode")" in
  sleep)  exec sleep 5 ;;
  nocost) echo '{"result":"RESULT: DONE ok","num_turns":1,"usage":{},"modelUsage":{"stub-model":{}}}' ;;
  empty)  exit 1 ;;
  slow)   sleep 1; echo '{"result":"RESULT: DONE ok","total_cost_usd":0.01,"num_turns":1,"usage":{},"modelUsage":{"stub-model":{}}}' ;;
esac
STUB
} > "$T/slowclaude"; chmod +x "$T/slowclaude"
slowcalls() { ls "$T/slowcalls" 2>/dev/null | wc -l | tr -d ' '; }
apicost() { jq -s 'map(select(.billing == "api") | .cost) | add // 0' "$T/state/spend.jsonl"; }
python3 "$T/bin/billing.py" cap daily 0.10 >/dev/null
for m in "sleep:is killed at the timeout" "nocost:reports no cost" "empty:crashes with no reply"; do
  : > "$T/state/spend.jsonl"; rm -rf "$T/slowcalls"; echo "${m%%:*}" > "$T/slowmode"
  ( export CLAUDE_BIN="$T/slowclaude" QUARTERDECK_RUN_TIMEOUT=1 QUARTERDECK_CALL_BUDGET=0.06; cr shipwright; cr shipwright; cr shipwright )
  ck "an api call that ${m#*:} is booked at its budget (0.06, then the 0.04 left), so the third does not start" \
     '[ "$(slowcalls)" = 2 ] && [ "$(apicost)" = 0.1 ] && [ "$(jq -sr "map(.cost_known) | unique | join(\",\")" "$T/state/spend.jsonl")" = false ] && [ "$(cat "$T/cr-rc")" = 5 ]'
done
: > "$T/state/spend.jsonl"; rm -rf "$T/slowcalls"; : > "$T/budgets"; echo slow > "$T/slowmode"
( export CLAUDE_BIN="$T/slowclaude" QUARTERDECK_CALL_BUDGET=0.06
  for i in 1 2 3; do ( export QUARTERDECK_RUN_ID="par-$i"; bash -c 'source "$QUARTERDECK_DIR/bin/lib.sh"; claude_run "$1" "the prompt" >/dev/null' shipwright "$T/w" 2>/dev/null ) & done; wait )
ck "three api calls started at once with \$0.10 left share it: the budgets handed out add up to at most \$0.10, and so does what was booked" \
   '[ "$(awk "{ s += \$1 } END { print (s <= 0.1 + 1e-9) ? 1 : 0 }" "$T/budgets")" = 1 ] && [ "$(slowcalls)" -ge 1 ] && [ "$(apicost | awk "{ print (\$1 <= 0.1 + 1e-9) ? 1 : 0 }")" = 1 ]'
ck "  and once they end nothing is left held: the next call is offered the cap less what was booked (\$0.01 a call)" \
   'left=$(python3 "$T/bin/billing.py" gate shipwright) && awk -v l="$left" -v c="$(apicost)" "BEGIN { exit !(c > 0 && l + c > 0.0999 && l + c < 0.1001) }"'
python3 "$T/bin/billing.py" cap daily off >/dev/null; : > "$T/state/spend.jsonl"

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

# review r9 A6: only the run that stopped for billing loses its ERROR row; a later run with the same id (inspect-<PR>) keeps its own
cp "$T/sec/integrations.env" "$T/keyfile.bak"; printf '' | python3 "$T/bin/billing.py" remove-key >/dev/null
FIXED_RID=inspect-7 cr shipwright; a6a=$(jq -r ".[-1].verdict" "$T/state/runs.json")
cp "$T/keyfile.bak" "$T/sec/integrations.env"; chmod 600 "$T/sec/integrations.env"
FIXED_RID=inspect-7 cr shipwright
ck "a run stopped for billing has one NEEDS_HUMAN row; the next run with the same id that fails gets its ERROR row" \
   '[ "$a6a" = NEEDS_HUMAN ] && [ "$(jq -r ".[-1].verdict" "$T/state/runs.json")" = ERROR ]'

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
