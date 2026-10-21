#!/bin/bash
# Show your own agents (round 4): `qtdeck fleet source add` and `fleet report` (level 1) and add-ons in the data folder (level 3). A copy of the program in a
# temp folder, a fake HOME and a data folder of its own; nothing real is read or written (no port 7878, no ~/.quarterdeck, no ~/.config, no keychain).
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT
fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }

P="$T/prog"; mkdir -p "$P" "$T/home"
for d in bin config duties crew packs providers dashboard; do [ -d "$REAL/$d" ] && cp -R "$REAL/$d" "$P/"; done
rm -rf "$P/config/projects.json" "$P"/bin/__pycache__
QH="$T/data"; mkdir -p "$QH"; chmod 700 "$QH"
qd() { env -u QUARTERDECK_DIR -u PROJECTS_FILE -u QUARTERDECK_ADDONS HOME="$T/home" QUARTERDECK_HOME="$QH" PYTHONDONTWRITEBYTECODE=1 QUARTERDECK_DASHBOARD_PORT=1 bash "$P/bin/qtdeck" "$@"; }
# py <args...>: python with the program's bin on the path and the same fake environment
py() { env -u QUARTERDECK_DIR -u PROJECTS_FILE HOME="$T/home" QUARTERDECK_HOME="$QH" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$P/bin" python3 "$@"; }

# ---- level 1: register a source, report, see it ---------------------------------------------------------------------------------------
ck "fleet report refuses an id nobody registered, and writes nothing" '! qd fleet report --source relay --kind session_start --session s1 2>"$T/e1" && grep -q "not a registered source" "$T/e1" && [ ! -e "$QH/state/fleet-events/relay.jsonl" ]'
ck "fleet source add registers it (config/fleet.local.json, mode 0600)" 'qd fleet source add relay "Relay jobs" >/dev/null && [ "$(jq -r ".sources[0].id + .sources[0].kind + .sources[0].title" "$QH/config/fleet.local.json")" = "relayreportedRelay jobs" ] && [ "$(stat -c %a "$QH/config/fleet.local.json" 2>/dev/null || stat -f %Lp "$QH/config/fleet.local.json")" = 600 ]'
ck "a source id cannot be registered twice, nor a bad id or a label with a control character" '! qd fleet source add relay "Again" 2>/dev/null && ! qd fleet source add "Bad Id" "x" 2>/dev/null && ! qd fleet source add other "$(printf "a\tb")" 2>/dev/null'
qd fleet report --source relay --kind session_start --session run-42 --worktree nightly --branch main || echo "report failed"
qd fleet report --source relay --kind prompt --session run-42
qd fleet report --source relay --kind agent_start --session run-42 --agent checker
EV="$QH/state/fleet-events/relay.jsonl"
ck "three reports are three lines in state/fleet-events/relay.jsonl (mode 0600), with exactly the six fields" '[ "$(wc -l < "$EV" | tr -d " ")" = 3 ] && [ "$(stat -c %a "$EV" 2>/dev/null || stat -f %Lp "$EV")" = 600 ] && jq -e "keys == [\"agent\",\"branch\",\"event\",\"session\",\"t\",\"worktree\"]" "$EV" >/dev/null'
bad=""
chk() { qd fleet report "$@" >/dev/null 2>&1 && bad="$bad [$*]"; }
chk --source relay --kind bogus --session s1
chk --source relay --kind stop --session "bad id"
chk --source relay --kind stop --session "$(printf 'a\nb')"
chk --source relay --kind stop --session "$(printf 'x%.0s' $(seq 1 81))"
chk --source relay --kind stop --session s1 --worktree "../etc"
chk --source relay --kind stop --session s1 --branch "a b"
chk --source relay --kind agent_start --session s1
chk --source relay --kind stop --session s1 --agent checker
chk --source relay --kind stop --session s1 --prompt "hello"
chk --source relay --kind stop --session s1 --transcript /etc/passwd
chk --source "../x" --kind stop --session s1
ck "bad fields, unknown kinds and options that would carry a prompt, a reply or a file are all refused${bad:+ (ACCEPTED:$bad)}" '[ -z "$bad" ] && [ "$(wc -l < "$EV" | tr -d " ")" = 3 ]'
py - <<'PY' > "$T/state.out" 2>"$T/state.err"
import json, dashboard as d, fleetview
st = d.build_state()
live = st["live"]
snap = fleetview.snapshot()
src = [s for s in snap["sources"] if s["id"] == "relay"][0]
print(json.dumps({"live_src": live["sources"], "items": [(i["source"], i["agent"], i["state"], i["worktree"], i["branch"]) for i in live["items"]],
                  "kind": src["kind"], "title": src["title"], "sessions": [(s["state"], s["running_agents"]) for s in src["sessions"]]}))
PY
ck "the report shows in /api/state (live work) and in the Fleet snapshot, under the source's label" '[ -s "$T/state.out" ] && jq -e ".live_src[0].id == \"relay\" and .live_src[0].title == \"Relay jobs\" and .items[0] == [\"relay\",\"checker\",\"working\",\"nightly\",\"main\"] and .kind == \"reported\" and .sessions == [[\"working\", [\"checker\"]]]" "$T/state.out" >/dev/null' || cat "$T/state.err" | tail -3

# ---- level 3: add-ons in the data folder --------------------------------------------------------------------------------------------------
ck "addon new writes ext_<name>.py and a test, mode 0600, in a 0700 addons folder, and prints the next step" \
  'qd addon new scout >"$T/new.out" && [ -f "$QH/addons/ext_scout.py" ] && [ -f "$QH/addons/test_scout.py" ] && [ "$(stat -c %a "$QH/addons" 2>/dev/null || stat -f %Lp "$QH/addons")" = 700 ] && grep -q "next:" "$T/new.out"'
ck "the scaffold's own test passes" 'python3 -I "$QH/addons/test_scout.py" | grep -q "^ok"'
ck "addon new never overwrites, and refuses a bad name" 'echo "# mine" > "$QH/addons/ext_scout.py"; ! qd addon new scout 2>/dev/null && [ "$(cat "$QH/addons/ext_scout.py")" = "# mine" ] && ! qd addon new "../x" 2>/dev/null && ! qd addon new Bad-Name 2>/dev/null'
qd addon new tail >/dev/null
# Relay: the sample in ADDONS.md, exactly as published (a private checkout keeps it in docs/public/, the published repo at the root)
ADDOC="$REAL/docs/public/ADDONS.md"; [ -f "$ADDOC" ] || ADDOC="$REAL/ADDONS.md"; AGDOC="$REAL/docs/public/AGENTS.md"; [ -f "$AGDOC" ] || AGDOC="$REAL/AGENTS.md"
python3 - "$ADDOC" "$QH/addons/ext_relay.py" <<'PY'
import re, sys
s = open(sys.argv[1]).read()
open(sys.argv[2], "w").write(re.findall(r"```python\n(# ext_relay\.py.*?)```", s, re.S)[0])
PY
printf 'def install(core):\n    raise RuntimeError("broken on purpose")\n' > "$QH/addons/ext_broken.py"
printf 'def install(core:\n' > "$QH/addons/ext_syntax.py"
printf 'def install(core):\n    pass\n' > "$QH/addons/ext_loose.py"
printf 'def install(core):\n    pass\n' > "$T/outside.py"; ln -s "$T/outside.py" "$QH/addons/ext_link.py"
printf 'def install(core):\n    pass\n' > "$QH/addons/ext_Bad-Name.py"
printf 'def install(core):\n    pass\n' > "$QH/addons/ext_dash.py"; printf 'x\n' > "$QH/addons/notes.txt"
chmod 600 "$QH"/addons/*.py 2>/dev/null; chmod 666 "$QH/addons/ext_loose.py"; chmod 666 "$T/outside.py"
mkdir -p "$QH/state/relay"
printf '[{"id":"1","name":"Example","status":"failed","at":"2099-01-01T00:00:00Z"},{"id":"2","name":"Fine","status":"ok","at":"2099-01-02T00:00:00Z"}]' > "$QH/state/relay/jobs.json"
cat > "$T/load.py" <<'PY'
import json, dashboard as d
mods = d.EXTENSIONS
print(json.dumps({"addons": d.addons_list(), "attention": [a for f in d.EXT["attention"] for a in f({})], "state": {k: f() for k, f in d.EXT["state"].items()},
                  "events": [e for f in d.EXT["events"] for e in f("2000-01-01T00:00:00Z")], "post": sorted(d.EXT["post"]),
                  "status": json.load(open(d.STATE / "addons-status.json"))}))
PY
py "$T/load.py" > "$T/load.out" 2>"$T/load.err"
ck "a local add-on loads, appears in the Add-ons list as a local add-on, and its alert, state, timeline and action are installed" \
  '[ -s "$T/load.out" ] && jq -e "([.addons[] | select(.id == \"relay\")][0] | .label == \"Relay\" and .where == \"local\") and (.attention | length == 1) and (.attention[0].text == \"Relay job Example failed\") and .state.relay == {jobs: 2, failed: 1} and (.events | length == 2) and (.post | index(\"/api/relay/clear\") != null)" "$T/load.out" >/dev/null' || tail -3 "$T/load.err"
ck "the scaffold add-on loads too" 'jq -e "[.addons[].id] | index(\"tail\") != null" "$T/load.out" >/dev/null'
ck "a broken add-on, a syntax error, a world-writable file, a link and a bad name are skipped or fail alone, each with its reason, and the rest still load" \
  'jq -e "([.status[] | select(.id == \"broken\")][0].status == \"failed\") and ([.status[] | select(.id == \"syntax\")][0].status == \"failed\") and ([.status[] | select(.id == \"ext_loose\")][0].reason | test(\"writable\")) and ([.status[] | select(.id == \"ext_link\")][0].reason | test(\"link\")) and ([.status[] | select(.id == \"ext_Bad-Name\")][0].status == \"skipped\") and ([.addons[].id] | index(\"broken\") == null and index(\"loose\") == null and index(\"link\") == null)" "$T/load.out" >/dev/null && grep -q "add-on ext_loose" "$QH/logs/dashboard-server.log" && grep -q "extension ext_broken" "$QH/logs/dashboard-server.log"'
ck "the built-in add-on is not shadowed: a local file with a built-in one's name is skipped" \
  'printf "def install(core):\n    pass\n" > "$P/bin/ext_dash.py" && chmod 600 "$P/bin/ext_dash.py" && py "$T/load.py" | jq -e "[.status[] | select(.id == \"dash\")][0].reason | test(\"built-in\")" >/dev/null; rm -f "$P/bin/ext_dash.py"'
ck "qtdeck addon list shows loaded and skipped with the reason" \
  'qd addon list > "$T/list.out" && grep -qE "^  relay +loaded" "$T/list.out" && grep -qE "^  broken +failed +RuntimeError" "$T/list.out" && grep -qE "^  ext_loose +skipped +it is writable" "$T/list.out" && grep -qE "^  ext_link +skipped +it is a link" "$T/list.out"'
ck "the add-on's action needs a confirmation and writes one log line in the logs folder" \
  'py - <<PY > "$T/act.out" 2>&1
import dashboard as d
f = d.EXT["post"]["/api/relay/clear"]
try:
    f({"id": "1"}); print("NO-REFUSAL")
except ValueError as e:
    print("refused")
f({"id": "1", "confirm": True}); print("done")
PY
  [ "$(cat "$T/act.out")" = "$(printf "refused\ndone")" ] && [ "$(grep -c "cleared job 1" "$QH/logs/addon-relay.log")" = 1 ] && ! grep -q Example "$QH/state/relay/jobs.json"'
cat > "$T/off.py" <<'PY'
import json, dashboard as d
print(json.dumps({"addons": d.addons_list(), "attention": len(d.EXT["attention"])}))
PY
QUARTERDECK_ADDONS=off py "$T/off.py" > "$T/off.out" 2>/dev/null
# built-in add-ons (a private checkout has some) add attention hooks of their own: the baseline is a data folder with no addons folder at all
mkdir -p "$T/empty-home"; : > "$T/empty-home/.quarterdeck-home"
env -u QUARTERDECK_DIR -u PROJECTS_FILE HOME="$T/home" QUARTERDECK_HOME="$T/empty-home" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$P/bin" python3 "$T/off.py" > "$T/base.out" 2>/dev/null
ck "QUARTERDECK_ADDONS=off loads none from the data folder" 'jq -e --slurpfile b "$T/base.out" "[.addons[] | select(.where == \"local\")] == [] and .attention == \$b[0].attention" "$T/off.out" >/dev/null'
ck "addon list says they are turned off when the switch is set" 'QUARTERDECK_ADDONS=off bash "$P/bin/qtdeck" addon list 2>&1 | grep -q "turned off"'
# the folder itself must be a real, private directory
chmod 755 "$QH/addons"; py "$T/off.py" > "$T/open.out" 2>/dev/null
ck "an addons folder open to others (mode 0755) loads nothing, and the reason names it" 'jq -e "[.addons[] | select(.where == \"local\")] == []" "$T/open.out" >/dev/null && qd addon list | grep -q "not mode 0700"'
chmod 700 "$QH/addons"; mv "$QH/addons" "$T/addons-real"; ln -s "$T/addons-real" "$QH/addons"; py "$T/off.py" > "$T/lnk.out" 2>/dev/null
ck "an addons folder that is a link loads nothing" 'jq -e "[.addons[] | select(.where == \"local\")] == []" "$T/lnk.out" >/dev/null && qd addon list | grep -q "is a link"'
rm "$QH/addons"; mv "$T/addons-real" "$QH/addons"

# ---- no model and no project command can write there ------------------------------------------------------------------------------------
rules=$( (export QUARTERDECK_HOME="$QH"; . "$P/bin/lib.sh"; private_read_rules) 2>&1 )
sbj=$( (export QUARTERDECK_HOME="$QH"; . "$P/bin/lib.sh"; claude_sandbox_json "$T/wt") 2>&1 )
ck "the folder is in the model's deny-write rules and in the sandbox's denyWrite" \
  'grep -qF "Edit(/$QH/addons)" <<<"$rules" && grep -qF "Edit(/$QH/addons/**)" <<<"$rules" && jq -e --arg p "$QH/addons" ".sandbox.filesystem.denyWrite | index(\$p) != null" <<<"$sbj" >/dev/null'
prof=$( (export QUARTERDECK_HOME="$QH"; . "$P/bin/lib.sh"; mkdir -p "$T/wt" "$T/scr"; _qd_sb_profile check "$T/wt" "$T/scr") 2>&1 )
ck "the project-command sandbox profile denies writes there" 'grep -qF "(deny file-write* (subpath \"$QH/addons\"))" <<<"$prof"'
case "$(uname -s)" in
  Darwin) if command -v sandbox-exec >/dev/null 2>&1; then
      printf '%s\n' "$prof" > "$T/p.sb"; mkdir -p "$T/wt"
      (cd "$T/wt" && env -i PATH=/usr/bin:/bin /usr/bin/sandbox-exec -f "$T/p.sb" /usr/bin/touch "$QH/addons/ext_x.py") >/dev/null 2>&1
      ck "under the real macOS sandbox, a command cannot create addons/ext_x.py" '[ ! -e "$QH/addons/ext_x.py" ]'
    else printf '  skip  %s\n' "no sandbox-exec"; fi ;;
  Linux) if bwrap --ro-bind / / true >/dev/null 2>&1; then
      mkdir -p "$T/wt" "$T/scr"
      args=(); while IFS= read -r w; do args+=("$w"); done < <( (export QUARTERDECK_HOME="$QH"; . "$P/bin/lib.sh"; _qd_bwrap_argv check "$T/wt" "$T/scr") )
      bwrap "${args[@]}" /bin/sh -c "touch '$QH/addons/ext_x.py'" >/dev/null 2>&1
      ck "under real bubblewrap, a command cannot create addons/ext_x.py" '[ ! -e "$QH/addons/ext_x.py" ]'
    else printf '  skip  %s\n' "bubblewrap cannot make namespaces here"; fi ;;
esac

# ---- the builder agent's file ---------------------------------------------------------------------------------------------------------------
A="$REAL/agents/addon-builder.md"
EM=$(printf "\342\200\224"); EN=$(printf "\342\200\223")
ck "the add-on builder is a crew-style file: frontmatter whose name matches the file, a seat and a bias, no project named, no dashes the style forbids" \
  '[ "$(sed -n 1p "$A")" = --- ] && [ "$(sed -n "s/^name: *//p" "$A" | sed -n 1p)" = addon-builder ] && grep -q "^seat: ." "$A" && grep -q "^bias: ." "$A" && [ "$(grep -c "^---[[:space:]]*$" "$A")" = 2 ] && ! LC_ALL=C grep -q -e "$EM" -e "$EN" "$A"'
ck "it is read-only toward the service by default, asks before a button, never sees keys, and its output is a diff" 'grep -qi "read-only toward the service" "$A" && grep -qi "ask before any action button" "$A" && grep -qi "never see a key" "$A" && grep -qi "diff" "$A" && grep -qi "only when the owner starts it" "$A"'
SECDOC="$REAL/SECURITY.md"; [ -f "$SECDOC" ] || SECDOC="$REAL/docs/public/SECURITY.md"; THRDOC="$REAL/THREAT-MODEL.md"; [ -f "$THRDOC" ] || THRDOC="$REAL/docs/public/THREAT-MODEL.md"
ck "the new docs and the security documents contain no long dashes" '! LC_ALL=C grep -q -e "$EM" -e "$EN" "$ADDOC" "$AGDOC" "$SECDOC" "$THRDOC"'
ck "SECURITY.md and THREAT-MODEL.md say what loading code from the data folder means and how to turn it off" 'grep -q "QUARTERDECK_ADDONS=off" "$SECDOC" && grep -q "QUARTERDECK_ADDONS=off" "$THRDOC"'

echo; [ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
