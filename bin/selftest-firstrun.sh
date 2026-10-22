#!/bin/bash
# First use (issue #123): what a newcomer meets before anything is registered. A copy of the program in a temp folder (no config/projects.json,
# as the public tree ships it), a fake HOME, and QUARTERDECK_HOME and QUARTERDECK_DIR unset, so the real first-run rules apply. Stand-ins
# for gh and claude; nothing real is read or written.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'umount "$T/fulldisk" 2>/dev/null; rm -rf "$T"' EXIT
fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }

mkprog() { # mkprog <dir>: a fresh copy of the program as published: no registry, no data
  mkdir -p "$1"
  for d in bin config duties crew packs providers; do [ -d "$REAL/$d" ] && cp -R "$REAL/$d" "$1/"; done
  rm -rf "$1/config/projects.json" "$1/bin/__pycache__"
}
mkdir -p "$T/stub"
printf '#!/bin/bash\n[ "$1 $2" = "auth status" ] && exit 0\nexit 0\n' > "$T/stub/gh"
printf '#!/bin/bash\n[ "$1 $2" = "auth status" ] && { echo "{\\"loggedIn\\": true}"; exit 0; }\nexit 0\n' > "$T/stub/claude"
chmod +x "$T/stub/gh" "$T/stub/claude"
# qd <home> <program> <args...>: qtdeck as a newcomer runs it
qd() {
  local h="$1" p="$2"; shift 2
  env -u QUARTERDECK_HOME -u QUARTERDECK_DIR -u QUARTERDECK_HOME_WHY -u PROJECTS_FILE -u QUARTERDECK_SECRETS_DIR \
    HOME="$h" QUARTERDECK_GH="$T/stub/gh" CLAUDE_BIN="$T/stub/claude" QUARTERDECK_DASHBOARD_PORT=1 PYTHONDONTWRITEBYTECODE=1 \
    bash "$p/bin/qtdeck" "$@"
}
changed() { find "$1" -newer "$T/stamp" ! -path '*/__pycache__*' 2>/dev/null | grep -v "^$1\$"; }   # what was made or changed under $1 since the stamp

P="$T/prog"; H="$T/home"; mkprog "$P"; mkdir -p "$H"
touch "$T/stamp"; sleep 1

# ---- help writes nothing, says how to use it, and a typo is an error ----
qd "$H" "$P" --help >"$T/h1" 2>"$T/h1e"; r1=$?
qd "$H" "$P" -h >"$T/h2" 2>/dev/null; r2=$?
qd "$H" "$P" help >"$T/h3" 2>/dev/null; r3=$?
ck "--help, -h and help print the usage on stdout and exit 0" '[ "$r1$r2$r3" = 000 ] && grep -q "^Usage: qtdeck" "$T/h1" && cmp -s "$T/h1" "$T/h2" && cmp -s "$T/h1" "$T/h3" && [ ! -s "$T/h1e" ]'
ck "help writes nothing: no data folder, nothing in the program folder" '[ ! -e "$H/.quarterdeck" ] && [ -z "$(changed "$P")" ] && [ -z "$(changed "$H")" ]'
ck "plain help is short and names the day-one commands, --no-open included" \
  '[ "$(grep -cE "^  [a-z]" "$T/h1")" -le 12 ] && for c in attach run dashboard doctor status plan cycle help setup; do grep -qE "^  $c( |$)" "$T/h1" || exit 1; done && grep -q -- "--no-open" "$T/h1"'
qd "$H" "$P" help more >"$T/hm" 2>/dev/null; rm=$?
ck "help more lists the rest" '[ "$rm" = 0 ] && grep -q "billing" "$T/hm" && grep -q "keys set anthropic" "$T/hm" && grep -q "home migrate" "$T/hm"'
qd "$H" "$P" bogus >"$T/b" 2>"$T/be"; rb=$?
ck "an unknown command: a short error and the usage on stderr, exit 2, nothing written" \
  '[ "$rb" = 2 ] && [ ! -s "$T/b" ] && grep -q "unknown command .bogus." "$T/be" && grep -q "^Usage: qtdeck" "$T/be" && [ ! -e "$H/.quarterdeck" ]'

# ---- the first real command makes the data folder, never writes into the program ----
qd "$H" "$P" status >"$T/s1" 2>"$T/s1e"; rs=$?
ck "the first run makes ~/.quarterdeck (0700, the marker, an empty registry) and says what to do next" \
  '[ "$rs" = 0 ] && [ -f "$H/.quarterdeck/.quarterdeck-home" ] && [ "$(stat -c %a "$H/.quarterdeck" 2>/dev/null || stat -f %Lp "$H/.quarterdeck")" = 700 ] && [ "$(cat "$H/.quarterdeck/config/projects.json")" = "{}" ] && grep -q "made your data folder" "$T/s1e" && grep -q "next: qtdeck" "$T/s1e"'
ck "nothing is written into the program folder (no registry, state, logs or workspace)" '[ -z "$(changed "$P")" ] && [ ! -e "$P/config/projects.json" ] && [ ! -e "$P/state" ]'
qd "$H" "$P" status >/dev/null 2>"$T/s2e"
ck "the second run says nothing about it" '! grep -q "made your data folder" "$T/s2e"'

# ---- an install whose data is still in the program folder keeps it there; a ~/.quarterdeck without the marker is left alone ----
P2="$T/prog2"; H2="$T/home2"; mkprog "$P2"; mkdir -p "$H2"; echo '{"old": {"repo": "a/b", "path": "/nowhere"}}' > "$P2/config/projects.json"
qd "$H2" "$P2" home >"$T/o2" 2>&1
ck "data already in the program folder: it stays the data folder, no ~/.quarterdeck is made, and it says how to move" '[ ! -e "$H2/.quarterdeck" ] && grep -q "home migrate" "$T/o2"'
P3="$T/prog3"; H3="$T/home3"; mkprog "$P3"; mkdir -p "$H3/.quarterdeck"; touch "$H3/.quarterdeck/.quarterdeck-home.off"
qd "$H3" "$P3" status >/dev/null 2>&1
ck "a ~/.quarterdeck that was switched off (no marker) is not switched on again" '[ ! -e "$H3/.quarterdeck/.quarterdeck-home" ]'
qd "$H" "$P" home init "$T/elsewhere" >"$T/hi" 2>&1
ck "home init prints the folder and the next step" 'grep -q "$T/elsewhere" "$T/hi" && grep -q "next: qtdeck attach" "$T/hi" && [ -f "$T/elsewhere/.quarterdeck-home" ]'

# ---- attach: a short summary, pytest found, the exact next command ----
A="$T/home/Projects/tiny"; mkdir -p "$A"
printf 'def add(a, b):\n    return a + b\n' > "$A/app.py"; printf 'from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n' > "$A/test_app.py"
( cd "$A" && git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm one ) >/dev/null 2>&1
touch "$T/stamp"; sleep 1
qd "$H" "$P" attach "$A" >"$T/a1" 2>&1; ra=$?
ck "attach: a test file is enough to find pytest as the verify command" '[ "$ra" = 0 ] && grep -qE "verify +python -m pytest" "$T/a1"'
# round 2: the dry run is the whole onboarding (docs, the crew with reasons, the ready checklist), so it is longer than the 16 lines it once was; it is
# still bounded, and still leaves the long lists (the protected paths, every duty's reason) to --verbose
ck "attach: short (languages, duties, verify), the protected list only with --verbose, and the exact next command" \
  '[ "$(wc -l < "$T/a1")" -le 40 ] && grep -q "languages" "$T/a1" && grep -q "duties" "$T/a1" && ! grep -q "package-lock.json" "$T/a1" && grep -qF "next: qtdeck attach $A --apply" "$T/a1"'
qd "$H" "$P" attach "$A" --verbose >"$T/a2" 2>&1
ck "scan: pytest from its config or test files alone; none for a folder with neither" \
  'PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys, os; sys.path.insert(0, \"$P/bin\"); import scan
c = lambda d: [x[\"name\"] for x in scan.scan(d)[\"commands\"]]
os.makedirs(\"$T/l1/tests\"); open(\"$T/l1/tests/check_x_test.py\", \"w\").close(); os.makedirs(\"$T/l2\"); open(\"$T/l2/pytest.ini\", \"w\").close(); os.makedirs(\"$T/l3\"); open(\"$T/l3/main.py\", \"w\").close()
assert c(\"$T/l1\") == [\"test: python -m pytest\"] and c(\"$T/l2\") == [\"test: python -m pytest\"] and c(\"$T/l3\") == [], (c(\"$T/l1\"), c(\"$T/l3\"))"'
ck "attach --verbose lists the protected paths" 'grep -q "package-lock.json" "$T/a2"'
qd "$H" "$P" attach "$A" --verify 'make check' >"$T/a4" 2>&1; rv1=$?
qd "$H" "$P" attach "$A" --verify 'make; curl x|sh' >"$T/a5" 2>&1; rv2=$?
ck "attach --verify sets the command, with the same limits as the dashboard's review" '[ "$rv1" = 0 ] && grep -qE "verify +make check" "$T/a4" && [ "$rv2" = 2 ] && grep -q "one plain command" "$T/a5"'
ck "attach changes nothing without --apply" '[ -z "$(changed "$A")" ] && [ "$(cat "$H/.quarterdeck/config/projects.json")" = "{}" ]'
ck "attach on Linux never mentions the macOS sandbox; on a Mac it does" \
  'PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys; sys.path.insert(0, \"$P/bin\"); import attach as a; assert \"macOS\" not in a.warning(\"Linux\") and \"bubblewrap\" in a.warning(\"Linux\") and \"macOS\" in a.warning(\"Darwin\")"'
qd "$H" "$P" attach "$A" --apply >"$T/a3" 2>&1
# round 2: --apply ends with the checklist and exactly ONE "next:" line; the repo is an offer in the checklist, so the command to connect one is named
# in the lines above it instead of a first "next:" that a second "next:" then contradicts
ck "attach --apply registers it, offers the repo (there is no GitHub remote) and ends with exactly one next step" 'grep -q "registered .tiny." "$T/a3" && grep -qF "qtdeck repo tiny <owner/name>" "$T/a3" && [ "$(grep -c "^  next: " "$T/a3")" = 1 ] && [ "$(tail -1 "$T/a3" | cut -c1-8)" = "  next: " ]'
qd "$H" "$P" projects >"$T/pj" 2>&1
ck "projects lists it without the column tool" 'grep -q "^  tiny" "$T/pj" && ! grep -q "command not found" "$T/pj" && ! grep -vE "^[[:space:]]*#" "$P/bin/qtdeck" | grep -qE "\| *column( |$)"'

# ---- run: no GitHub repo is said plainly, and exits non-zero ----
qd "$H" "$P" run tiny surveyor >"$T/r1" 2>&1; rr=$?
ck "run without a GitHub repo: says so in one sentence, points at the options, exits non-zero" '[ "$rr" != 0 ] && grep -qF "tiny has no GitHub repo, so the crew cannot open pull requests yet; local tickets still work." "$T/r1" && grep -qF "qtdeck repo tiny" "$T/r1" && ! grep -q "no open pull requests on" "$T/r1"'
qd "$H" "$P" repo tiny 'x; rm -rf /' >"$T/r2" 2>&1; rq=$?
qd "$H" "$P" repo tiny me/tiny >"$T/r3" 2>&1; rq2=$?
ck "repo: refuses what is not owner/name, sets a good one" '[ "$rq" != 0 ] && [ "$rq2" = 0 ] && [ "$(jq -r .tiny.repo "$H/.quarterdeck/config/projects.json")" = me/tiny ]'

# ---- doctor: wiring only, quick, one closing line; billing in one line when nothing is on the API key ----
s0=$(date +%s); qd "$H" "$P" doctor >"$T/d1" 2>&1; rd=$?; s1=$(date +%s)
ck "doctor finishes in under 10 seconds and runs no selftest" '[ $((s1 - s0)) -lt 10 ] && ! grep -q "self-check" "$T/d1"'
ck "doctor ends with one line: all good, or N problems" 'tail -1 "$T/d1" | grep -qE "^  (all good|[0-9]+ problems?: .+)$"'
ck "doctor: billing is one line while every duty is on the plan" '[ "$(grep -c "billing" "$T/d1")" = 1 ] && grep -q "dashboard" "$T/d1" && grep -q "data folder" "$T/d1"'
ck "doctor names the tools and the sign-ins" 'grep -q "claude sign-in" "$T/d1" && grep -q "gh sign-in" "$T/d1"'

# ---- setup: checks, prints install commands for the platform, installs nothing ----
ck "setup: the install command for each platform (apt-get update first on Debian and Ubuntu)" \
  'PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys; sys.path.insert(0, \"$P/bin\"); import setup as s
assert s.install_cmd([\"jq\", \"gh\"], \"Darwin\", {\"brew\"}) == \"brew install jq gh\"
assert s.install_cmd([\"jq\", \"bwrap\"], \"Linux\", {\"apt-get\"}) == \"sudo apt-get update && sudo apt-get install -y jq bubblewrap\"
assert \"dnf install -y jq\" in s.install_cmd([\"jq\"], \"Linux\", {\"dnf\"})
assert \"claude.com\" in s.install_cmd([\"claude\"], \"Darwin\", {\"brew\"})"'
mkdir -p "$T/all"; for t in git jq gh claude bwrap node; do cp "$T/stub/gh" "$T/all/$t"; done     # every tool "there": the result must not depend on this machine
PATH="$T/all:$PATH" qd "$H" "$P" setup </dev/null >"$T/su" 2>&1; rsu=$?
ck "setup: checks the tools, keeps the data folder, and ends with the attach step" '[ "$rsu" = 0 ] && grep -q "jq" "$T/su" && grep -q "data folder" "$T/su" && grep -q "next: qtdeck attach" "$T/su"'

# ---- dashboard: the Demo hint ----
ck "dashboard ends with the Demo hint" 'grep -qF "Switch Demo on to look around before you connect anything." "$REAL/bin/qtdeck"'

# ---- add: the default duty exists, and a duty or repo that does not is refused before anything is written ----
AD="$T/home/Projects/addme"; mkdir -p "$AD"
( cd "$AD" && git init -q && git remote add origin https://github.com/o/addme.git && echo x > f && git add -A && git -c user.email=t@t -c user.name=t commit -qm one ) >/dev/null 2>&1
( cd "$AD" && qd "$H" "$P" add --duties bogus,surveyor ) >"$T/ad1" 2>&1; rad1=$?
( cd "$AD" && qd "$H" "$P" add --repo bad ) >"$T/ad2" 2>&1; rad2=$?
ck "add refuses a duty that does not exist and a repo that is not owner/name, and registers nothing" \
  '[ "$rad1" != 0 ] && [ "$rad2" != 0 ] && grep -q "unknown duty .bogus." "$T/ad1" && grep -q "owner/name" "$T/ad2" && ! grep -q addme "$H/.quarterdeck/config/projects.json"'
( cd "$AD" && qd "$H" "$P" add ) >"$T/ad3" 2>&1; rad3=$?
adduty=$(sed -n 's/^Then: qtdeck run addme //p' "$T/ad3")
ck "add registers with a default duty that exists, and the next command it prints names a real duty" \
  '[ "$rad3" = 0 ] && [ -n "$adduty" ] && [ -f "$P/duties/$adduty.sh" ] && grep -q "duties: $adduty" "$T/ad3"'
# ---- small command line gaps: logs -f, a bad number, one usage line, an empty list that says so ----
qd "$H" "$P" logs -f >"$T/lg" 2>&1 & lgp=$!; sleep 2; pkill -P $lgp 2>/dev/null; kill $lgp 2>/dev/null; wait $lgp 2>/dev/null
ck "logs -f follows the default log, it is not read as a log called -f" '! grep -q -- "-f.log" "$T/lg"'
qd "$H" "$P" runs abc >"$T/rn" 2>&1; rrn=$?
qd "$H" "$P" spend --days abc >"$T/sp" 2>&1; rsp=$?
ck "runs and spend --days with something that is not a number say usage, with no jq error" \
  '[ "$rrn" != 0 ] && [ "$rsp" != 0 ] && grep -q "usage: qtdeck runs" "$T/rn" && grep -q "usage: qtdeck spend" "$T/sp" && ! grep -qi "jq" "$T/rn" "$T/sp"'
ck "run, plan, remove and mockup with a missing argument print one usage line, not the whole help" \
  'good=1; for c in run plan remove mockup; do qd "$H" "$P" $c >"$T/u" 2>&1; rc=$?; [ "$rc" != 0 ] && [ "$(wc -l < "$T/u" | tr -d " ")" -le 2 ] && grep -q "usage: qtdeck $c" "$T/u" || good=0; done; [ "$good" = 1 ]'
ck "plan list and brief list say so when there is nothing to list" \
  'qd "$H" "$P" plan list addme >"$T/pl" 2>&1; qd "$H" "$P" brief list >"$T/bl" 2>&1; grep -q "no plans" "$T/pl" && grep -q "no briefs" "$T/bl"'
# one unknown word is one usage line and exit 2, for the commands that used to ignore or accept it; the documented flags still work
for c in "dashboard --bogus" "doctor --nonsense" "status extra" "setup --bogus"; do
  qd "$H" "$P" $c >"$T/uw" 2>&1; rc=$?
  ck "qtdeck $c prints one usage line and exits 2" '[ "$rc" = 2 ] && [ "$(wc -l < "$T/uw" | tr -d " ")" = 1 ] && grep -q "^usage: qtdeck ${c%% *}" "$T/uw"'
done
qd "$H" "$P" status >"$T/uw" 2>&1; ruw=$?
ck "qtdeck status with no argument still works" '[ "$ruw" = 0 ] && grep -q "Quarterdeck" "$T/uw"'
qd "$H" "$P" ready addme >"$T/rdy" 2>&1
ck "qtdeck ready wraps a long sentence under its own text; no line is cut off with dots" \
  '! grep -q "\.\.\.$" "$T/rdy" && grep -A1 "Cycles" "$T/rdy" | grep -q "are off\|not both on\|switched on" && awk "length > 120 { bad = 1 } END { exit bad }" "$T/rdy"'
ck "the cycle refusal names the command that switches it on" 'grep -q "qtdeck enable \$PROJECT cycle" "$REAL/bin/cycle"'
# ---- a data folder that cannot be written: one plain line and a non-zero exit, never a traceback; remove does not say removed ----
RO="$T/ro"; RUNRO=""; ROOK=1; mkdir -p "$RO/home"; chmod 755 "$T" "$RO"; chmod -R a+rX "$P" "$T/stub"
if [ "$(id -u)" = 0 ]; then
  if command -v setpriv >/dev/null 2>&1; then RUNRO="setpriv --reuid=65534 --regid=65534 --clear-groups"; chown 65534 "$RO/home"; else ROOK=0; fi
else
  ROOK=0       # the owner of a folder can chmod it back (qtdeck does at start), so read-only needs another user to own it
fi
qdro() { $RUNRO env -u QUARTERDECK_HOME -u QUARTERDECK_DIR -u QUARTERDECK_HOME_WHY -u PROJECTS_FILE -u QUARTERDECK_SECRETS_DIR \
  HOME="$RO/home" QUARTERDECK_GH="$T/stub/gh" CLAUDE_BIN="$T/stub/claude" QUARTERDECK_DASHBOARD_PORT=1 PYTHONDONTWRITEBYTECODE=1 bash "$P/bin/qtdeck" "$@"; }
if [ "$ROOK" = 1 ]; then
  qdro home init >/dev/null 2>&1
  printf '{"demo":{"repo":"o/demo","path":"~/x","duties":["surveyor"],"default_branch":"main","guardrails":[]}}\n' > "$RO/home/.quarterdeck/config/projects.json"
  mkdir -p "$RO/home/x" && ( cd "$RO/home/x" && git init -q && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m one ) >/dev/null 2>&1; chown -R 65534 "$RO/home/x"
  rm -f "$RO/home/.quarterdeck/state/runs.json"      # the ledger is made on the first command; a folder that cannot be written must not show echo's own error for it
  [ "$(id -u)" = 0 ] && chown -R root "$RO/home/.quarterdeck"; chmod -R a-w,a+rX "$RO/home/.quarterdeck"
  for c in "enable demo planner" "repo demo a/b" "billing cap daily 5" "dashboard link" "fleet source add src1 Demo" "addon new foo" "add xx --path $RO/home/x --repo o/xx" "attach $RO/home/x --apply" "dashboard sessions revoke" "dashboard --no-open" "fix demo --issue 1" "home init" "remove demo"; do
    qdro $c >"$T/ro.out" 2>&1; rc=$?
    ck "read-only data folder, qtdeck $c: one plain line, non-zero exit, no traceback" \
      '[ "$rc" != 0 ] && grep -qi "read-only\|could not save" "$T/ro.out" && ! grep -q "Traceback\|Error:" "$T/ro.out" && [ "$(wc -l < "$T/ro.out" | tr -d " ")" -le 2 ]'
  done
  for c in "guardrail demo add Never_touch_x" "ticket new demo add_a_button"; do
    qdro $c >"$T/ro.out" 2>&1; rc=$?
    ck "read-only data folder, qtdeck $c: one plain reason, non-zero exit, no echo or Python error" \
      '[ "$rc" != 0 ] && grep -qi "read-only" "$T/ro.out" && ! grep -qi "write error\|Traceback\|OSError\|cannot be used" "$T/ro.out" && [ "$(wc -l < "$T/ro.out" | tr -d " ")" -le 2 ]'
  done
  ck "read-only data folder: remove did not say removed and the project is still registered" \
    '! grep -q "^removed" "$T/ro.out" && jq -e ".demo" "$RO/home/.quarterdeck/config/projects.json" >/dev/null'
  chmod -R u+w "$RO/home/.quarterdeck"
else
  echo "  skip  read-only data folder: needs to run as root with setpriv, so the folder belongs to someone else"
fi

# ---- a disk that is really full (a small tmpfs, root only): each command says "the disk is full" once, never echo's write error or a wrong reason ----
FD="$T/fulldisk"; mkdir -p "$FD"
if [ "$(id -u)" = 0 ] && mount -t tmpfs -o size=64k tmpfs "$FD" 2>/dev/null; then
  mkdir -p "$FD/h/config" "$FD/h/state" "$FD/h/logs" "$FD/h/workspace" "$T/fdgit"; touch "$FD/h/.quarterdeck-home"
  ( cd "$T/fdgit" && git init -q && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m one && git remote add origin https://github.com/o/demo.git ) >/dev/null 2>&1
  printf '{"demo":{"repo":"o/demo","path":"%s","duties":["planner"],"default_branch":"main","guardrails":[]}}\n' "$T/fdgit" > "$FD/h/config/projects.json"
  dd if=/dev/zero of="$FD/fill" bs=1k count=200 >/dev/null 2>&1
  qdfull() { env -u QUARTERDECK_DIR QUARTERDECK_HOME="$FD/h" HOME="$T/home" QUARTERDECK_GH="$T/stub/gh" CLAUDE_BIN="$T/stub/claude" QUARTERDECK_DASHBOARD_PORT=1 PYTHONDONTWRITEBYTECODE=1 bash "$P/bin/qtdeck" "$@"; }
  for c in "guardrail demo add Never_touch_x" "ticket new demo add_a_button"; do
    qdfull $c >"$T/fd.out" 2>&1; rc=$?
    ck "full disk, qtdeck $c: says the disk is full, exits non-zero, no echo error and no wrong reason" \
      '[ "$rc" != 0 ] && grep -q "disk is full" "$T/fd.out" && ! grep -qi "write error\|Traceback\|OSError\|cannot be used" "$T/fd.out" && [ "$(wc -l < "$T/fd.out" | tr -d " ")" -le 2 ]'
  done
  umount "$FD" 2>/dev/null
else
  echo "  skip  full disk: needs root and a tmpfs mount"
fi

echo; [ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
