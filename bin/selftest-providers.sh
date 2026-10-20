#!/bin/bash
# The provider seam behind claude_run (docs/design-providers.md, ticket #100). Offline; no model, no network.
#
#   bin/selftest-providers.sh                    every check below
#   bin/selftest-providers.sh --record           rewrite fixtures/providers/claude-call.golden from the lib.sh in this checkout
#   bin/selftest-providers.sh --against <lib.sh> run the same claude calls through another lib.sh and through this one, and
#                                                compare what the claude process got byte for byte, with nothing normalised
#
# 1. The claude adapter. A recorder stands in for the claude binary and writes down exactly what it was started with: every
#    argument, the environment (in order, as the process received it), the folder it ran in, standard input, and the sandbox
#    settings file with its mode. A dozen calls (review, builder with a shell, overrides, the inherited and the cloud
#    environment, a secret screen hit, the cap, the usage limit, a failure, no output, output that is not JSON, a refused tool list, the sandbox off)
#    are compared with fixtures/providers/claude-call.golden, recorded from claude_run BEFORE the adapter seam existed. The
#    golden file has the throwaway folder, the random settings file name and the PATH given to the test replaced by
#    placeholders; nothing else is changed.
# 2. The provider setting: default claude, the order of precedence, an unknown name refused before any model runs.
# 3. The fake adapter: deterministic replies, a record of what it was given, and the failure, cost, cap and limit paths.
set -uo pipefail
export TMPDIR=/tmp
unset QUARTERDECK_HOME QUARTERDECK_HOME_WHY QUARTERDECK_PROJECT QUARTERDECK_WORKDIR GH_TOKEN GITHUB_TOKEN
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOLD="$REAL/fixtures/providers/claude-call.golden"
MODE=check; AGAINST=""
case "${1:-}" in --record) MODE=record ;; --against) MODE=against; AGAINST=$(cd "$(dirname "$2")" && pwd -P)/$(basename "$2") ;; esac
# A physical root: on a Mac /tmp is a link, and a path listed both ways would make the record depend on the machine.
R=$(cd "$(mktemp -d)" && pwd -P); trap 'rm -rf "$R"' EXIT
fails=0; passed=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; passed=$((passed+1)); else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
DECOY1=$(python3 "$REAL/injection/fixtures.py" decoy1)
# The PATH the test hands lib.sh: the folders of the tools the harness needs, so the record names no machine-specific folder.
PATHIN=""
for b in jq python3 perl git bash; do d=$(dirname "$(command -v "$b")"); case ":$PATHIN:" in *":$d:"*) ;; *) PATHIN="$PATHIN${PATHIN:+:}$d" ;; esac; done

mkqd() { # mkqd <dir> <lib.sh>: a throwaway Quarterdeck holding the harness files claude_run needs
  mkdir -p "$1"/{bin,config,state,logs/runs,workspace}
  cp "$REAL"/bin/{markers.py,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re,behaviour.py,routes.py} "$1/bin/"
  cp "$2" "$1/bin/lib.sh"; cp "$REAL/config/quarterdeck.env" "$1/config/"
  [ -d "$REAL/providers" ] && cp -R "$REAL/providers" "$1/providers"
  echo '{}' > "$1/config/projects.json"
}
mkdir -p "$R/home" "$R/systmp" "$R/nosecrets" "$R/wd" "$R/wd2"; chmod 700 "$R/nosecrets"
printf 'def f():\n    return 1\n' > "$R/wd/app.py"; printf 'def f():\n    return 1\n' > "$R/wd2/app.py"
printf 'staging token: %s\n' "$DECOY1" > "$R/wd2/notes.txt"

# The recorder: python, so the environment is read as the process received it (/proc/self/environ where there is one, in order).
cat > "$R/rec-claude" <<PY
#!/usr/bin/env python3
import json, os, sys
R = "$R"
try:
    env = [e.decode("utf-8", "surrogateescape") for e in open("/proc/self/environ", "rb").read().split(b"\0") if e]
except OSError:
    env = ["%s=%s" % kv for kv in os.environ.items()]
a = sys.argv[1:]; settings = ""; smode = ""
if "--settings" in a:
    p = a[a.index("--settings") + 1]
    try:
        settings = open(p).read(); smode = oct(os.stat(p).st_mode & 0o777)
    except OSError as e:
        settings = "unreadable: %s" % e
rec = {"argv": a, "env": env, "cwd": os.getcwd(), "stdin": sys.stdin.read(), "settings": settings, "smode": smode}
with open(R + "/calls.jsonl", "a") as f:
    f.write(json.dumps(rec) + "\n")
sys.stdout.write(open(R + "/reply.out").read())
sys.exit(int(open(R + "/reply.rc").read().strip() or 0))
PY
chmod +x "$R/rec-claude"

reply() { printf '%s' "$1" > "$R/reply.out"; printf '%s' "${2:-0}" > "$R/reply.rc"; }
OKR='{"type":"result","subtype":"success","is_error":false,"result":"VERDICT: CLEAN","total_cost_usd":0.0123,"num_turns":3,"usage":{"input_tokens":10,"cache_read_input_tokens":200,"cache_creation_input_tokens":5,"output_tokens":40},"modelUsage":{"claude-sonnet-5":{}}}'

call() { # call <qd> <duty> <env assignments...> -- <claude_run args...>: one claude_run in a clean, fixed environment; its return code in $R/rc
  local qd=$1 duty=$2; shift 2
  local -a ev=()
  while [ $# -gt 0 ] && [ "$1" != -- ]; do ev+=("$1"); shift; done; shift
  (cd "$R" && env -i HOME="$R/home" PATH="$PATHIN" USER=fixture LOGNAME=fixture SHELL=/bin/bash LANG=C.UTF-8 TERM=dumb TZ=UTC TMPDIR="$R/systmp" \
    GH_TOKEN=decoy-gh-token QUARTERDECK_DECOY=decoy-quarterdeck ANTHROPIC_API_KEY=decoy-anthropic-key AWS_SECRET_ACCESS_KEY=decoy-aws \
    QUARTERDECK_DIR="$qd" QUARTERDECK_SECRETS_DIR="$R/nosecrets" CLAUDE_BIN="$R/rec-claude" ${ev[@]+"${ev[@]}"} \
    bash -c '. "$QUARTERDECK_DIR/bin/lib.sh"; out=$(claude_run "$@" 2>>"'"$R"'/stderr"); rc=$?; printf "%s" "$out" > "'"$R"'/stdout"; echo "$rc" > "'"$R"'/rc"' "$duty" "$@" </dev/null)   # stdin not a socket: bash would read the system bashrc
}

# Every case: the claude process's arguments, environment, folder, input and settings file, then what claude_run made of the reply.
CASES="review builder overrides default-model inherit cloud screen cap limit failure empty garbage refused sandbox-off turns stable"
run_case() { # run_case <qd> <case>
  local qd=$1 c=$2
  rm -f "$R/calls.jsonl" "$R/stdout" "$R/rc" "$qd/state/spend.jsonl" "$qd/state/usage-limit" "$qd/logs/quarterdeck.log" "$qd"/logs/runs/*
  reply "$OKR" 0
  case "$c" in
    review)        call "$qd" surveyor -- "$R/wd" "Review this. BEGIN UNTRUSTED x"$'\n'"line two" ;;
    builder)       call "$qd" shipwright -- "$R/wd" "Fix it." "Read,Edit,Write,Grep,Glob,Bash(npm test),Bash(node *)" ;;
    overrides)     call "$qd" panel QUARTERDECK_MODEL_OVERRIDE=claude-haiku-4-5 QUARTERDECK_EFFORT_OVERRIDE=high QUARTERDECK_CALL_BUDGET=0.5 \
                     QUARTERDECK_SETTING_SOURCES=user QUARTERDECK_RUN_ID=r-42 QUARTERDECK_PROJECT=tp QUARTERDECK_FIX_KEY=fx -- "$R/wd" "Seat." "Read,Glob" "Write,Edit" ;;
    default-model) call "$qd" inspector QUARTERDECK_MODEL_OVERRIDE=default QUARTERDECK_EFFORT_OVERRIDE=medium QUARTERDECK_RUN_TIMEOUT=77 -- "$R/wd" "Check." ;;
    inherit)       call "$qd" surveyor QUARTERDECK_CLAUDE_ENV=inherit -- "$R/wd" "Review." ;;
    cloud)         call "$qd" surveyor CLAUDE_CODE_USE_BEDROCK=1 AWS_REGION=eu-north-1 -- "$R/wd" "Review." ;;
    screen)        call "$qd" surveyor -- "$R/wd2" "Review." ;;
    cap)           reply '{"type":"result","subtype":"error_max_budget_usd","is_error":true,"total_cost_usd":6.01,"num_turns":9,"usage":{"input_tokens":1},"modelUsage":{"claude-sonnet-5":{}}}' 1
                   call "$qd" surveyor -- "$R/wd" "Review." ;;
    limit)         reply '{"type":"result","subtype":"success","is_error":false,"result":"You have hit your usage limit. Resets 5pm.","total_cost_usd":0,"num_turns":1,"usage":{},"modelUsage":{}}' 0
                   call "$qd" surveyor -- "$R/wd" "Review." ;;
    failure)       reply '{"type":"result","subtype":"error_during_execution","is_error":true,"result":"","total_cost_usd":0.2,"num_turns":2,"usage":{},"modelUsage":{"claude-sonnet-5":{}}}' 1
                   call "$qd" surveyor -- "$R/wd" "Review." ;;
    empty)         reply '' 1; call "$qd" surveyor -- "$R/wd" "Review." ;;
    garbage)       reply 'not json {' 0; call "$qd" surveyor -- "$R/wd" "Review." ;;
    refused)       call "$qd" shipwright -- "$R/wd" "Fix it." "Read,Bash(git status)" ;;
    sandbox-off)   call "$qd" shipwright QUARTERDECK_SANDBOX=off -- "$R/wd" "Fix it." "Read,Edit,Bash(npm test)" ;;
    turns)         reply '{"type":"result","subtype":"error_max_turns","is_error":true,"result":null,"total_cost_usd":0.3,"num_turns":7,"usage":{"input_tokens":3,"cache_read_input_tokens":40,"cache_creation_input_tokens":2,"output_tokens":9},"modelUsage":{"claude-sonnet-5":{"costUSD":0.3}}}' 1
                   call "$qd" shipwright QUARTERDECK_MAX_TURNS_SHIPWRIGHT=7 -- "$R/wd" "Fix it." "Read,Edit" ;;
    stable)        call "$qd" surveyor QUARTERDECK_STABLE_PROMPT=on -- "$R/wd" "Review." ;;
  esac
  python3 - "$qd" "$c" "$R" <<'PY'
import json, os, re, sys
qd, case, R = sys.argv[1:4]
out = {"case": case, "calls": [json.loads(l) for l in open(R + "/calls.jsonl")] if os.path.exists(R + "/calls.jsonl") else []}
out["rc"] = open(R + "/rc").read().strip()
out["stdout"] = open(R + "/stdout").read()
sp = qd + "/state/spend.jsonl"
# the fields the ledger had before the seam; fields it gained since are checked on their own
OLD = ("project", "duty", "run", "fix", "effort", "model", "cost", "turns", "read", "out", "stopped", "in", "cache_write", "cache_read", "seat", "key", "reused")
out["spend"] = [{k: j.get(k) for k in OLD} for j in (json.loads(l) for l in open(sp))] if os.path.exists(sp) else []
out["runlog"] = {f: open(qd + "/logs/runs/" + f).read() for f in sorted(os.listdir(qd + "/logs/runs"))}
out["usage_limit"] = os.path.exists(qd + "/state/usage-limit")
lg = qd + "/logs/quarterdeck.log"
out["log"] = [re.sub(r"^\[[^]]*\] ", "", l) for l in open(lg).read().splitlines()] if os.path.exists(lg) else []
print(json.dumps(out))
PY
}

normalise() { # normalise <qd> <records>: the record as the golden file holds it: the throwaway folder, the settings file name and the given PATH as placeholders
  python3 - "$1" "$R" "$PATHIN" "$2" <<'PY'
import json, re, sys
qd, R, pathin, src = sys.argv[1:5]
for l in open(src):
    s = l.rstrip("\n")
    s = re.sub(r"quarterdeck-settings\.[A-Za-z0-9]{6}", "quarterdeck-settings.@RANDOM@", s)
    s = s.replace(qd, "@QD@").replace(R, "@R@").replace(pathin, "@PATH@")
    # lib.sh puts its own folders before PATH, and which ones depends on the system (Homebrew on a Mac): the record is the same on both
    s = re.sub(r'"PATH=(?:[^":]+:)*@PATH@"', '"PATH=@SYS@:@PATH@"', s)
    s = re.sub(r'"_=[^"]*"', '"_=@LAST@"', s)
    print(json.dumps(json.loads(s), indent=1, sort_keys=True))
PY
}

echo "providers: the claude adapter starts claude exactly as claude_run did before the seam"
mkqd "$R/qd" "$REAL/bin/lib.sh"
: > "$R/now.jsonl"
for c in $CASES; do run_case "$R/qd" "$c" >> "$R/now.jsonl"; done
case "$MODE" in
  record)
    mkdir -p "$(dirname "$GOLD")"; normalise "$R/qd" "$R/now.jsonl" > "$GOLD"; echo "  wrote $GOLD"; exit 0 ;;
  against)
    mkqd "$R/qd0" "$AGAINST"; mv "$R/qd" "$R/qd1"; mv "$R/qd0" "$R/qd"   # the same folder name for both, so nothing needs normalising
    : > "$R/then.jsonl"; for c in $CASES; do run_case "$R/qd" "$c" >> "$R/then.jsonl"; done
    sed 's/quarterdeck-settings\.[A-Za-z0-9]\{6\}/quarterdeck-settings.X/g' "$R/then.jsonl" > "$R/a"; sed 's/quarterdeck-settings\.[A-Za-z0-9]\{6\}/quarterdeck-settings.X/g' "$R/now.jsonl" > "$R/b"
    ck "every argument, the environment in order, the folder, standard input and the settings file are the same bytes under $AGAINST and this lib.sh (only the random settings file name differs)" 'cmp -s "$R/a" "$R/b" || { diff <(python3 -m json.tool --json-lines "$R/a") <(python3 -m json.tool --json-lines "$R/b") | head -40; false; }'
    echo; [ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }; exit 0 ;;
esac
normalise "$R/qd" "$R/now.jsonl" > "$R/now.golden"
# The record was made on a Mac: the order of the exported environment is the shell's (bash 3.2 there, another bash elsewhere) and macOS adds
# __CF_USER_TEXT_ENCODING to every process. Elsewhere both sides are compared with each environment sorted and that one variable left out;
# every name and value, and everything else in the record, must still be the same.
if [ "$(uname -s)" != Darwin ]; then
  canon() { python3 - "$1" <<'PY'
import json, sys
t, i, dec = open(sys.argv[1]).read(), 0, json.JSONDecoder()
while True:
    while i < len(t) and t[i].isspace(): i += 1
    if i >= len(t): break
    o, i = dec.raw_decode(t, i)
    for c in o.get("calls", []):
        if isinstance(c.get("env"), list): c["env"] = sorted(e for e in c["env"] if not e.startswith("__CF_USER_TEXT_ENCODING="))
    print(json.dumps(o, indent=1, sort_keys=True))
PY
  }
  canon "$GOLD" > "$R/gold.canon"; canon "$R/now.golden" > "$R/now.canon"; GOLD_CMP="$R/gold.canon"; NOW_CMP="$R/now.canon"
else GOLD_CMP="$GOLD"; NOW_CMP="$R/now.golden"; fi
ck "the golden record exists (fixtures/providers/claude-call.golden)" '[ -s "$GOLD" ]'
ck "argv, environment, folder, stdin, settings file, return code, output, spend, run log and log lines match the golden record for: $CASES" \
   'cmp -s "$GOLD_CMP" "$NOW_CMP" || { diff "$GOLD_CMP" "$NOW_CMP" | head -60; false; }'
ck "the record proves something: the review call got the prompt on stdin and no shell, and the builder's sandbox file was 0600" \
   'grep -q "\"stdin\": \"Review this. BEGIN UNTRUSTED x\\\\nline two\"" "$GOLD" && grep -q "\"smode\": \"0o600\"" "$GOLD"'
ck "the clean environment carries no decoy (GH_TOKEN, QUARTERDECK_*); no call, the inherited one included, gets the shell's ANTHROPIC_API_KEY or a cloud credential, the cloud case's switch included (review r9 A1: every call here is billed to the plan, bin/billing.py)" \
   'python3 -c "
import json,sys
cs=[json.loads(l) for l in open(\"$R/now.jsonl\")]
for c in cs:
    for call in c[\"calls\"]:
        env=\"\n\".join(call[\"env\"])
        assert \"decoy-anthropic-key\" not in env and \"decoy-aws\" not in env and \"CLAUDE_CODE_USE_BEDROCK\" not in env, c[\"case\"]
        if c[\"case\"]==\"inherit\": continue
        assert \"decoy-gh-token\" not in env and \"decoy-quarterdeck\" not in env, c[\"case\"]
"'

ck "the spend ledger names the provider of every call and whether its cost was reported" \
   'run_case "$R/qd" review >/dev/null; jq -e "select(.provider == \"claude\" and .cost_known == true and .cost == 0.0123)" "$R/qd/state/spend.jsonl" >/dev/null'
ck "record_spend still takes a claude envelope as it is (the cycle self-test and older callers hand it one)" \
   '(export QUARTERDECK_DIR="$R/qd"; . "$R/qd/bin/lib.sh"; rm -f "$QUARTERDECK_HOME/state/spend.jsonl"; record_spend "{\"total_cost_usd\":0.1,\"modelUsage\":{\"stub\":{}}}" cycle ""; jq -e "select(.duty == \"cycle\" and .cost == 0.1 and .model == \"stub\" and .provider == \"claude\")" "$QUARTERDECK_HOME/state/spend.jsonl") >/dev/null 2>&1'

# ---- 2. which provider -------------------------------------------------------------------------------------------
echo "providers: which one a call uses"
QD="$R/qd"
fresh() { rm -f "$R/calls.jsonl" "$R/fake-calls.jsonl" "$R/stdout" "$R/rc" "$QD/state/spend.jsonl" "$QD/state/usage-limit" "$QD/logs/quarterdeck.log" "$QD"/logs/runs/*; echo '{}' > "$QD/config/projects.json"; reply "$OKR" 0; }
FK=(QUARTERDECK_FAKE_SCRIPT="$R/fake.json" QUARTERDECK_FAKE_RECORD="$R/fake-calls.jsonl")
fake_script() { printf '%s' "$1" > "$R/fake.json"; }
fake_script '{"text":"VERDICT: FAKE","cost_usd":0.25,"input_tokens":11,"output_tokens":7,"turns":2,"model":"fake-1"}'
used() { # which adapter ran in the last call: claude, fake, none or both
  local c=""; [ -s "$R/calls.jsonl" ] && c=claude; [ -s "$R/fake-calls.jsonl" ] && c="${c:+both}${c:-fake}"; printf '%s' "${c:-none}"
}
lastlog() { cat "$QD/logs/quarterdeck.log" 2>/dev/null; }
fresh; call "$QD" surveyor -- "$R/wd" "Review."
ck "with nothing set the provider is claude" '[ "$(used)" = claude ] && [ "$(cat "$R/rc")" = 0 ]'
fresh; call "$QD" surveyor QUARTERDECK_PROVIDER=default -- "$R/wd" "Review."
ck "'default' means claude, as it means the account default for a model" '[ "$(used)" = claude ]'
fresh; call "$QD" surveyor QUARTERDECK_PROVIDER=gpt9 -- "$R/wd" "Review."
ck "an unknown provider is refused before any model runs, and the message names it, where it was set and what exists" \
   '[ "$(used)" = none ] && [ "$(cat "$R/rc")" = 1 ] && grep -q "unknown provider .gpt9." <<<"$(lastlog)" && grep -q "QUARTERDECK_PROVIDER" <<<"$(lastlog)" && grep -q "claude, fake" <<<"$(lastlog)"'
fresh; call "$QD" surveyor "QUARTERDECK_PROVIDER=fake;touch $R/pwned" -- "$R/wd" "Review."
ck "a provider name that is not a plain word is refused and runs nothing" '[ "$(used)" = none ] && [ "$(cat "$R/rc")" = 1 ] && [ ! -e "$R/pwned" ]'
fresh; call "$QD" surveyor QUARTERDECK_PROVIDER=fake "${FK[@]}" -- "$R/wd" "Review."
ck "QUARTERDECK_PROVIDER=fake runs the fake adapter and never the claude binary" '[ "$(used)" = fake ] && [ "$(cat "$R/stdout")" = "VERDICT: FAKE" ]'
fresh; call "$QD" surveyor QUARTERDECK_PROVIDER=nope QUARTERDECK_PROVIDER_SURVEYOR=fake "${FK[@]}" -- "$R/wd" "Review."
ck "the duty's own setting (QUARTERDECK_PROVIDER_<DUTY>) beats the fleet-wide one" '[ "$(used)" = fake ]'
printf '{"tp":{"repo":"x/tp","path":"%s","providers":{"surveyor":"fake"}}}' "$R/wd" > "$R/reg.json"
fresh; cp "$R/reg.json" "$QD/config/projects.json"; call "$QD" surveyor QUARTERDECK_PROJECT=tp QUARTERDECK_PROVIDER_SURVEYOR=claude "${FK[@]}" -- "$R/wd" "Review."
ck "the registry's per-duty setting (\"providers\": {\"surveyor\": \"fake\"}) beats the duty default" '[ "$(used)" = fake ]'
fresh; cp "$R/reg.json" "$QD/config/projects.json"; call "$QD" inspector QUARTERDECK_PROJECT=tp "${FK[@]}" -- "$R/wd" "Review."
ck "... and applies to that duty only" '[ "$(used)" = claude ]'
fresh; cp "$R/reg.json" "$QD/config/projects.json"; call "$QD" surveyor QUARTERDECK_PROJECT=tp QUARTERDECK_PROVIDER_PERSONA=claude "${FK[@]}" -- "$R/wd" "Review."
ck "a crew seat's provider: line (QUARTERDECK_PROVIDER_PERSONA) beats the registry" '[ "$(used)" = claude ]'
fresh; call "$QD" surveyor QUARTERDECK_PROVIDER_PERSONA=nope QUARTERDECK_PROVIDER_OVERRIDE=fake "${FK[@]}" -- "$R/wd" "Review."
ck "QUARTERDECK_PROVIDER_OVERRIDE beats everything (a decision panel can put every seat on one provider)" '[ "$(used)" = fake ]'
printf '{"tp":{"repo":"x/tp","path":"%s","providers":{"surveyor":"llama-cloud"}}}' "$R/wd" > "$QD/config/projects.json"
rm -f "$R/calls.jsonl" "$R/fake-calls.jsonl"; call "$QD" surveyor QUARTERDECK_PROJECT=tp -- "$R/wd" "Review."
ck "an unknown provider in the registry is refused too, and the message says it came from the registry" '[ "$(used)" = none ] && grep -q "unknown provider .llama-cloud." <<<"$(lastlog)" && grep -q "projects.json" <<<"$(lastlog)"'
# root reads a file through chmod 000, so a check that needs an unreadable file would pass or fail by who runs it; a directory cannot be read as a file by anyone
unreadable() { if [ "$(id -u)" = 0 ]; then rm -f "$1"; mkdir "$1"; else chmod 000 "$1"; fi; }
readable() { [ -d "$1" ] && rmdir "$1"; chmod 600 "$1" 2>/dev/null; return 0; }
# review r9 P1: a registry that cannot be read is not "no provider set": the call is refused, it never falls through to claude
for bad in 'invalid JSON:{"tp": {"providers": {"surveyor": "fake"}' 'a provider that is not a string:{"tp": {"providers": {"surveyor": ["fake"]}}}' \
           'providers that are not an object:{"tp": {"providers": "fake"}}' 'a project that is not an object:{"tp": "fake"}'; do
  printf '%s' "${bad#*:}" > "$QD/config/projects.json"; rm -f "$R/calls.jsonl" "$R/fake-calls.jsonl" "$QD/logs/quarterdeck.log"
  call "$QD" surveyor QUARTERDECK_PROJECT=tp "${FK[@]}" -- "$R/wd" "Review."
  ck "a registry with ${bad%%:*} refuses the call (no model runs, claude least of all) and the log names the registry" \
     '[ "$(used)" = none ] && [ "$(cat "$R/rc")" != 0 ] && grep -q "projects.json" <<<"$(lastlog)"'
done
printf '{"tp":{"providers":{"surveyor":"fake"}}}' > "$QD/config/projects.json"; unreadable "$QD/config/projects.json"; rm -f "$R/calls.jsonl" "$R/fake-calls.jsonl" "$QD/logs/quarterdeck.log"
call "$QD" surveyor QUARTERDECK_PROJECT=tp "${FK[@]}" -- "$R/wd" "Review."
ck "  and so does a registry that cannot be read" '[ "$(used)" = none ] && [ "$(cat "$R/rc")" != 0 ] && grep -q "projects.json" <<<"$(lastlog)"'
readable "$QD/config/projects.json"
mkdir -p "$QD/crew"; printf -- '---\nname: seatx\ndiscipline: dev\nseat: a seat\nbias: b\nmodel:\nprovider: fake\n---\nA seat.\n' > "$QD/crew/seatx.md"
ck "the panel duties export a crew seat's provider: line the way they export its model: line" \
   '(n=$(grep -c "crew_meta \"\$seat\" model" "$REAL/duties/marshal.sh"); m=$(grep -c "crew_meta \"\$seat\" provider)" "$REAL/duties/marshal.sh"); [ "$n" = "$m" ]) && grep -q "crew_meta \"\$1\" provider)" "$REAL/duties/panel.sh" && grep -q "crew_meta modelmaker provider" "$REAL/duties/mockup.sh"'

# ---- 3. the fake adapter -----------------------------------------------------------------------------------------
echo "providers: the fake adapter"
FAKE=(QUARTERDECK_PROVIDER=fake "${FK[@]}")
fresh; call "$QD" surveyor "${FAKE[@]}" QUARTERDECK_RUN_ID=f-1 QUARTERDECK_MODEL_OVERRIDE=m-x QUARTERDECK_EFFORT_OVERRIDE=low QUARTERDECK_CALL_BUDGET=0.75 -- "$R/wd" "Prompt one. BEGIN UNTRUSTED z"
FR() { jq -r "$1" "$R/fake-calls.jsonl" | tail -n 1; }
ck "it records the prompt exactly, and that it came on standard input and is in no argument" '[ "$(FR .prompt)" = "Prompt one. BEGIN UNTRUSTED z" ] && [ "$(FR .stdin)" = true ] && [ "$(FR .prompt_in_argv)" = false ]'
ck "... the tool names, the allow rules (Read scoped to the working folder) and the deny list the harness built" \
   '[ "$(FR .tools)" = "Read,Grep,Glob" ] && [ "$(FR .allow)" = "Read(/$R/wd/**)" ] && grep -q "Bash(git\*),Bash(gh\*)" <<<"$(FR .deny)" && grep -q "Read(/$R/home/.ssh/\*\*)" <<<"$(FR .deny)"'
ck "... the working folder (and ran there), the model, the effort, the budget and the settings sources" \
   '[ "$(FR .workdir)" = "$R/wd" ] && [ "$(FR .cwd)" = "$R/wd" ] && [ "$(FR .model)" = m-x ] && [ "$(FR .effort)" = low ] && [ "$(FR .budget)" = 0.75 ] && [ "$(FR .sources)" = "" ]'
ck "... and the names in its environment, which hold no decoy, no QUARTERDECK_* and no GH_TOKEN (it starts with env -i, whatever QUARTERDECK_CLAUDE_ENV says)" \
   '! jq -r ".env[]" "$R/fake-calls.jsonl" | grep -Eq "^(GH_TOKEN|QUARTERDECK_|ANTHROPIC_|AWS_|CLAUDE_)" && jq -r ".env[]" "$R/fake-calls.jsonl" | grep -qx PATH'
ck "its reply is the text it was scripted with, and the raw envelope is kept in the run log" '[ "$(cat "$R/stdout")" = "VERDICT: FAKE" ] && jq -e ".provider == \"fake\" and .text == \"VERDICT: FAKE\"" "$QD/logs/runs/f-1.json" >/dev/null'
ck "the spend ledger books its scripted cost, tokens, turns and model under provider fake" \
   'jq -e "select(.provider == \"fake\" and .cost == 0.25 and .read == 11 and .out == 7 and .turns == 2 and .model == \"fake-1\" and .stopped == null and .cost_known == true)" "$QD/state/spend.jsonl" >/dev/null'
fresh; call "$QD" shipwright "${FAKE[@]}" QUARTERDECK_MAX_TURNS_SHIPWRIGHT=7 -- "$R/wd" "Fix it." "Read,Edit"
ck "review r9 P2: ... the turn cap and who pays (none: only the claude adapter signs in to Anthropic), so the seam shows both reach every provider" \
   '[ "$(FR .turns)" = 7 ] && [ "$(FR .billing)" = none ]'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "Prompt one. BEGIN UNTRUSTED z"; A=$(cat "$R/stdout"); call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "Prompt one. BEGIN UNTRUSTED z"
ck "it is deterministic: the same prompt gives the same reply" '[ "$A" = "$(cat "$R/stdout")" ] && [ "$(wc -l < "$R/fake-calls.jsonl" | tr -d " ")" = 2 ]'
fake_script '[{"match":"second","text":"B"},{"match":"first|second","text":"A"},{"text":"C"}]'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "the second one"; A=$(cat "$R/stdout"); call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "the first one"; B=$(cat "$R/stdout"); call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "neither"
ck "a scripted list answers with the first entry whose match is found in the prompt, and an entry without one matches anything" '[ "$A" = B ] && [ "$B" = A ] && [ "$(cat "$R/stdout")" = C ]'
fake_script '{"text":"partial","cost_usd":6.2,"stop":"cap","exit":1}'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "x"
ck "cap: a call stopped at the per-call cap returns 3, writes nothing out, and its cost is still booked as stopped at the cap" \
   '[ "$(cat "$R/rc")" = 3 ] && [ -z "$(cat "$R/stdout")" ] && grep -q "stopped at the per-call cap" <<<"$(lastlog)" && jq -e "select(.cost == 6.2 and .stopped == \"cap\")" "$QD/state/spend.jsonl" >/dev/null'
fake_script '{"text":"","stop":"limit"}'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "x"
ck "limit: a usage limit returns 2 and leaves the mark the queue waits on" '[ "$(cat "$R/rc")" = 2 ] && [ -s "$QD/state/usage-limit" ] && grep -q "usage limit reached" <<<"$(lastlog)"'
fake_script '{"text":"","cost_usd":0.4,"stop":"error","exit":1}'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "x"
ck "failure: a failed call returns 1 and its cost is still booked, as an error" '[ "$(cat "$R/rc")" = 1 ] && grep -q "fake run failed (exit 1" <<<"$(lastlog)" && jq -e "select(.cost == 0.4 and .stopped == \"error\")" "$QD/state/spend.jsonl" >/dev/null'
fake_script '{"text":"t","cost_known":false}'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "x"
ck "a provider that does not report its cost is booked with cost_known false" 'jq -e "select(.cost_known == false)" "$QD/state/spend.jsonl" >/dev/null'
fake_script '{"output":"empty","exit":1}'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "x"
ck "no output at all returns 1 and books nothing" '[ "$(cat "$R/rc")" = 1 ] && grep -q "fake returned nothing (exit 1" <<<"$(lastlog)" && [ ! -s "$QD/state/spend.jsonl" ]'
fake_script '{"output":"malformed"}'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd" "x"
ck "output that is not the envelope returns 1: an adapter that cannot say what happened has failed" '[ "$(cat "$R/rc")" = 1 ] && [ -z "$(cat "$R/stdout")" ] && grep -q "not a reply envelope" <<<"$(lastlog)"'
fake_script '{"text":"late","sleep":5}'
fresh; t0=$(date +%s); call "$QD" surveyor "${FAKE[@]}" QUARTERDECK_RUN_TIMEOUT=1 -- "$R/wd" "x"; t1=$(date +%s)
ck "the harness's timeout applies to it (QUARTERDECK_RUN_TIMEOUT)" '[ "$(cat "$R/rc")" = 1 ] && [ $((t1 - t0)) -lt 4 ]'
fake_script '{"text":"t"}'
fresh; call "$QD" surveyor QUARTERDECK_PROVIDER=fake QUARTERDECK_FAKE_RECORD="$R/fake-calls.jsonl" -- "$R/wd" "x"
ck "with no script and no replies folder it refuses (it is for tests) and runs nothing" '[ "$(cat "$R/rc")" = 1 ] && [ "$(used)" = none ] && grep -q "for tests" <<<"$(lastlog)"'

echo "providers: reuse of an earlier answer (issue 121) through the seam"
mkdir -p "$R/wdg"; printf 'x = 1\n' > "$R/wdg/a.py"
(cd "$R/wdg" && git init -q && git -c user.name=f -c user.email=f@example.invalid add -A && git -c user.name=f -c user.email=f@example.invalid commit -qm base) >/dev/null 2>&1
fake_script '{"text":"RESULT: FAKE-ANSWER"}'
OKRR='{"type":"result","subtype":"success","is_error":false,"result":"RESULT: CLAUDE-ANSWER","total_cost_usd":0.01,"num_turns":1,"usage":{},"modelUsage":{"claude-sonnet-5":{}}}'
fresh; rm -rf "$QD/state/reuse"; reply "$OKRR" 0
call "$QD" surveyor "${FAKE[@]}" -- "$R/wdg" "Same prompt."; F1=$(cat "$R/stdout")
call "$QD" surveyor -- "$R/wdg" "Same prompt."; C1=$(cat "$R/stdout"); n1=$(wc -l < "$R/calls.jsonl" 2>/dev/null | tr -d ' ')
call "$QD" surveyor -- "$R/wdg" "Same prompt."; C2=$(cat "$R/stdout"); n2=$(wc -l < "$R/calls.jsonl" 2>/dev/null | tr -d ' ')
ck "an answer the fake gave is never handed back for a claude call with the same inputs (the provider is one of the reuse inputs)" \
   '[ "$F1" = "RESULT: FAKE-ANSWER" ] && [ "$C1" = "RESULT: CLAUDE-ANSWER" ] && [ "$n1" = 1 ]'
ck "a claude answer is reused for the same inputs: no second claude call, the same text, booked as reused at no cost" \
   '[ "$C2" = "RESULT: CLAUDE-ANSWER" ] && [ "$n2" = 1 ] && tail -1 "$QD/state/spend.jsonl" | jq -e ".reused == true and .cost == 0 and .provider == \"claude\"" >/dev/null'

echo "providers: the harness's rules hold at the seam, whichever adapter is behind it"
fake_script '{"text":"t"}'
fresh; call "$QD" shipwright "${FAKE[@]}" -- "$R/wd" "x" "Read,Bash(git status)"
ck "a tool list with git is refused before the fake runs" '[ "$(cat "$R/rc")" = 1 ] && [ "$(used)" = none ]'
fresh; call "$QD" shipwright "${FAKE[@]}" -- "$R/wd" "x" "Read,WebFetch"
ck "a web tool is refused before the fake runs" '[ "$(cat "$R/rc")" = 1 ] && [ "$(used)" = none ]'
fresh; call "$QD" surveyor "${FAKE[@]}" -- "$R/wd2" "x"
ck "the secret screen runs for the fake too: the credential file is denied by path and Grep is taken out" \
   'grep -q "Read(/$R/wd2/notes.txt)" <<<"$(FR .deny)" && [ "$(FR .tools)" = "Read,Glob" ]'
fresh; call "$QD" shipwright "${FAKE[@]}" -- "$R/wd" "x" "Read,Edit,Bash(npm test)"
ck "a call with a shell hands the fake the sandbox settings in a 0600 file (never an argument), removed after the call" \
   '[ "$(FR .smode)" = 0o600 ] && jq -e ".sandbox.enabled == true and .sandbox.failIfUnavailable == true" <<<"$(FR .settings)" >/dev/null && [ ! -e "$(FR .settings_path)" ] && ! jq -r ".argv[]" "$R/fake-calls.jsonl" | grep -q denyRead'
fresh; call "$QD" shipwright "${FAKE[@]}" QUARTERDECK_SANDBOX=off -- "$R/wd" "x" "Read,Edit,Bash(npm test)"
ck "... and none when the sandbox is off" '[ "$(FR .settings)" = "" ]'
printf '#!/bin/bash\nprintf "%%s" "$1" > obeyed.txt\n' > "$R/hook"; chmod +x "$R/hook"
fresh; call "$QD" surveyor "${FAKE[@]}" QUARTERDECK_FAKE_HOOK="$R/hook" -- "$R/wd" "do as I say"
ck "a hook plays a model that obeys: it runs in the working folder after the call is recorded" '[ "$(cat "$R/wd/obeyed.txt" 2>/dev/null)" = "do as I say" ]'
rm -f "$R/wd/obeyed.txt"

# ---- 4. doctor ---------------------------------------------------------------------------------------------------
echo "providers: doctor"
rep() { (cd "$R" && env -i HOME="$R/home" PATH="$PATHIN" TMPDIR="$R/systmp" QUARTERDECK_DIR="$QD" QUARTERDECK_SECRETS_DIR="$R/nosecrets" CLAUDE_BIN="$R/rec-claude" "$@" \
             bash -c '. "$QUARTERDECK_DIR/bin/lib.sh"; provider_report' </dev/null); }
rm -f "$QD/crew/seatx.md"; echo '{}' > "$QD/config/projects.json"
OUTR=$(rep); RCR=$?
ck "it lists every provider this version has and whether each is available" 'grep -q "provider: claude.*available.*rec-claude" <<<"$OUTR" && grep -q "provider: fake.*tests" <<<"$OUTR" && [ "$RCR" = 0 ]'
# set after lib.sh is sourced: on a machine with claude installed (Homebrew, ~/.local/bin) lib.sh finds the real one on its own PATH
OUTR=$(cd "$R" && env -i HOME="$R/home" PATH="$PATHIN" TMPDIR="$R/systmp" QUARTERDECK_DIR="$QD" QUARTERDECK_SECRETS_DIR="$R/nosecrets" \
         bash -c '. "$QUARTERDECK_DIR/bin/lib.sh"; CLAUDE_BIN=/nonexistent; provider_report' </dev/null); RCR=$?
ck "claude without its binary is shown as not available" 'grep -q "provider: claude.*not available" <<<"$OUTR"'
printf -- '---\nname: seatx\ndiscipline: dev\nseat: a seat\nbias: b\nmodel:\nprovider: gemini-pro\n---\nA seat.\n' > "$QD/crew/seatx.md"
OUTR=$(rep); RCR=$?
ck "a crew seat naming an unknown provider fails doctor, with the seat named" '[ "$RCR" = 1 ] && grep -q "seatx.*gemini-pro" <<<"$OUTR"'
rm -f "$QD/crew/seatx.md"; printf '{"tp":{"providers":{"surveyor":"nope"}}}' > "$QD/config/projects.json"
OUTR=$(rep); RCR=$?
ck "... and so does a registry duty naming one" '[ "$RCR" = 1 ] && grep -q "tp/surveyor.*nope" <<<"$OUTR"'
echo '{}' > "$QD/config/projects.json"
OUTR=$(rep QUARTERDECK_PROVIDER_SURVEYOR=fake); RCR=$?
ck "... and a provider that is used but cannot run (the fake without a script) fails it too" '[ "$RCR" = 1 ] && grep -q "QUARTERDECK_PROVIDER_SURVEYOR.*fake" <<<"$OUTR"'
ck "qtdeck doctor prints the provider report" 'grep -q "provider_report" "$REAL/bin/qtdeck"'

echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
