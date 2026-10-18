#!/bin/bash
# First use (issue #123): what a newcomer meets before anything is registered. A copy of the program in a temp folder (no config/projects.json,
# as the public tree ships it), a fake HOME, and QUARTERDECK_HOME and QUARTERDECK_DIR unset, so the real first-run rules apply. Stand-ins
# for gh and claude; nothing real is read or written.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
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
  '[ "$rs" = 0 ] && [ -f "$H/.quarterdeck/.quarterdeck-home" ] && [ "$(stat -f %Lp "$H/.quarterdeck" 2>/dev/null || stat -c %a "$H/.quarterdeck")" = 700 ] && [ "$(cat "$H/.quarterdeck/config/projects.json")" = "{}" ] && grep -q "made your data folder" "$T/s1e" && grep -q "next: qtdeck" "$T/s1e"'
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
ck "attach: short (languages, duties, verify), the protected list only with --verbose, and the exact next command" \
  '[ "$(wc -l < "$T/a1")" -le 16 ] && grep -q "languages" "$T/a1" && grep -q "duties" "$T/a1" && ! grep -q "package-lock.json" "$T/a1" && grep -qF "next: qtdeck attach $A --apply" "$T/a1"'
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
ck "attach --apply registers it and names the next step: the repo, since there is no GitHub remote" 'grep -q "registered .tiny." "$T/a3" && grep -qF "next: qtdeck repo tiny <owner/name>" "$T/a3"'
qd "$H" "$P" projects >"$T/pj" 2>&1
ck "projects lists it without the column tool" 'grep -q "^  tiny" "$T/pj" && ! grep -q "command not found" "$T/pj" && ! grep -vE "^[[:space:]]*#" "$P/bin/qtdeck" | grep -qE "\| *column( |$)"'

# ---- run: no GitHub repo is said plainly, and exits non-zero ----
qd "$H" "$P" run tiny surveyor >"$T/r1" 2>&1; rr=$?
ck "run without a GitHub repo: says so, names the command, exits non-zero" '[ "$rr" != 0 ] && grep -q "has no GitHub repo set" "$T/r1" && grep -qF "qtdeck repo tiny <owner/name>" "$T/r1" && ! grep -q "no open pull requests on" "$T/r1"'
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

echo; [ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
