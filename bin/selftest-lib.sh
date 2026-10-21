#!/bin/bash
# Shared by bin/selftest-<duty>.sh for the crew duties. Source it; do not run it.
#
# Every one of those checks runs a duty in a throwaway Quarterdeck against stand-ins: a `claude` that answers by
# contract and records what it was asked, a `gh` that serves fixture files and records every call, and a real git
# repository in a temp directory with a bare "origin" holding refs/pull/<n>/head. Nothing real is read or written:
# no GitHub, no model, no project checkout, only invented files.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
#   st_init pilot            # copies the harness and the named duties; the real crew files and quarterdeck.env
#   st_registry '["pilot"]' '{"qa":{"start":"..."}}'
#   st_repo; st_pr 1 feat-x index.html '<h1>hi</h1>'
#   st_reply '<match regex>' '<reply text>'      # first matching reply wins; "default" matches everything
#   st_duty pilot --pr 1                         # runs duties/pilot.sh as project tp; output in $OUT, status in $RC
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT
fails=0; passed=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; passed=$((passed+1)); else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
st_done() { echo; [ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }; }
_obj() { if [ -n "$1" ]; then printf '%s' "$1"; else printf '{}'; fi; }   # "${1:-{}}" is "{\}" in bash 3.2, so a default object goes through here
# A process group is killed asynchronously: wait up to four seconds for what matches $1 to disappear before calling it still alive.
st_gone() { local i; for i in $(seq 1 40); do pgrep -f "$1" >/dev/null 2>&1 || return 0; sleep 0.1; done; return 1; }

st_init() { # st_init <duty>... — a throwaway Quarterdeck holding the harness, those duties and the real crew
  mkdir -p "$T"/{bin,config,crew,duties,state,workspace,logs/runs,path,ghdata,replies}
  cp "$REAL"/bin/{lib.sh,markers.py,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re,behaviour.py,routes.py} "$T/bin/"
  for f in browse.mjs decisions.sh billing.py; do [ -f "$REAL/bin/$f" ] && cp "$REAL/bin/$f" "$T/bin/"; done
  mkdir -p "$T/bin/integrations"; cp -R "$REAL"/bin/integrations/. "$T/bin/integrations/"; rm -rf "$T/bin/integrations/__pycache__"   # billing.py keeps the API key in the same store
  for d in "$@"; do cp "$REAL/duties/$d.sh" "$T/duties/"; done
  cp "$REAL"/config/quarterdeck.env "$T/config/"; cp "$REAL"/crew/*.md "$T/crew/"
  cat > "$T/path/gh" <<'GH'
#!/bin/bash
# Serves $QUARTERDECK_DIR/ghdata and records every call. Unknown calls succeed and print nothing.
echo "gh $*" >> "$QUARTERDECK_DIR/gh-calls"
D="$QUARTERDECK_DIR/ghdata"
num() { for a in "$@"; do case "$a" in [0-9]*) echo "$a"; return ;; esac; done; }
expr() { local prev=""; for a in "$@"; do { [ "$prev" = --jq ] || [ "$prev" = -q ]; } && { echo "$a"; return; }; prev="$a"; done; }
case "$1 $2" in
  "pr view")    n=$(num "${@:3}"); [ -f "$D/pr-$n.json" ] || exit 1
                e=$(expr "$@"); if [ -n "$e" ]; then jq -r "$e" "$D/pr-$n.json"; else cat "$D/pr-$n.json"; fi ;;
  "pr diff")    n=$(num "${@:3}"); if [[ "$*" == *"--name-only"* ]]; then cat "$D/diff-$n.names" 2>/dev/null; else cat "$D/diff-$n.patch" 2>/dev/null; fi ;;
  "pr list")    e=$(expr "$@"); f="$D/pr-list.json"; [ -f "$f" ] || echo '[]' > "$f"; if [ -n "$e" ]; then jq -r "$e" "$f"; else cat "$f"; fi ;;
  "issue view") n=$(num "${@:3}"); [ -f "$D/issue-$n.json" ] || exit 1
                if [[ "$*" == *"--template"* ]]; then jq -r '.title + "\n\n" + .body' "$D/issue-$n.json"; else cat "$D/issue-$n.json"; fi ;;
  "pr create")  echo "https://github.com/x/tp/pull/${PR_CREATED:-900}" ;;
  "issue list") e=$(expr "$@"); f="$D/issue-list.json"; [ -f "$f" ] || echo '[]' > "$f"; if [ -n "$e" ]; then jq -r "$e" "$f"; else cat "$f"; fi ;;
  "issue create") while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$QUARTERDECK_DIR/issue-created-body"; shift; done; echo "https://github.com/x/tp/issues/${ISSUE_CREATED:-901}" ;;
  "issue edit") while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$QUARTERDECK_DIR/issue-edited-body"; shift; done ;;
  "pr edit"|"pr comment"|"issue comment") while [ $# -gt 0 ]; do { [ "$1" = --body-file ] || [ "$1" = --body ]; } && { if [ "$1" = --body ]; then printf '%s' "$2" > "$QUARTERDECK_DIR/body-$(python3 -c 'import time; print(time.time_ns())')"; else cp "$2" "$QUARTERDECK_DIR/body-$(python3 -c 'import time; print(time.time_ns())')"; fi; }; shift; done ;;
esac
exit 0
GH
  chmod +x "$T/path/gh"
  cat > "$T/claude" <<'STUB'
#!/bin/bash
# Answers by contract: the first replies/*.match regex found in the prompt picks replies/<same name>.reply.
# Records argv and prompt in claude-calls (one JSON object per call), and costs a fixed figure so spend can be checked.
argv=$(printf '%s\0' "$@" | jq -Rsc 'split("\u0000")[:-1]')
p=$(cat)   # the prompt arrives on stdin, never in the process arguments
while [ $# -gt 0 ]; do case "$1" in -p) ;; --disallowedTools) deny="$2"; shift ;; --allowedTools) allow="$2"; shift ;; --model) model="$2"; shift ;; --tools) tools="$2"; shift ;; --settings) settings="$2"; shift ;; --setting-sources) sources="$2"; shift ;; esac; shift; done
R="$QUARTERDECK_DIR/replies"; reply=""
for m in $(ls "$R"/*.match 2>/dev/null | sort); do
  if grep -Eq "$(cat "$m")" <<<"$p"; then reply="$(cat "${m%.match}.reply")"; break; fi
done
[ -n "$reply" ] || reply="$(cat "$R/default.reply" 2>/dev/null)"
# one writer at a time: seats run in parallel, and on macOS a long line is written in 4 KB pieces that interleave
lk="$QUARTERDECK_DIR/.calls.lock"; until mkdir "$lk" 2>/dev/null; do sleep 0.02; done
spath=""; smode=""
[ -f "${settings:-/nonexistent}" ] && { spath="$settings"; smode="$(stat -c %a "$settings" 2>/dev/null || stat -f %Lp "$settings")"; settings="$(cat "$settings")"; }
jq -nc --arg p "$p" --arg deny "${deny:-}" --arg allow "${allow:-}" --arg model "${model:-}" --arg tools "${tools:-}" --arg settings "${settings:-}" --arg sources "${sources-unset}" --argjson argv "$argv" --arg spath "$spath" --arg smode "$smode" '{spath:$spath, smode:$smode, argv:$argv, prompt:$p, deny:$deny, allow:$allow, model:$model, tools:$tools, settings:$settings, sources:$sources}' >> "$QUARTERDECK_DIR/claude-calls"
rmdir "$lk"
[ -x "$QUARTERDECK_DIR/claude-hook" ] && "$QUARTERDECK_DIR/claude-hook" "$p" >/dev/null 2>&1
jq -n --arg r "$reply" --argjson c "${STUB_COST:-0.05}" '{result:$r, total_cost_usd:$c, num_turns:1, usage:{}, modelUsage:{"stub-model":{}}}'
STUB
  chmod +x "$T/claude"
  # QUARTERDECK_GH, not PATH: lib.sh puts the real gh first, and a stand-in that is bypassed would touch a real repository.
  export QUARTERDECK_DIR="$T" QUARTERDECK_SECRETS_DIR="$T/nosecrets" CLAUDE_BIN="$T/claude" QUARTERDECK_CLAUDE_ENV=inherit QUARTERDECK_GH="$T/path/gh"
  # The checks change what the stand-in answers between runs with the same inputs, so reuse of an earlier answer stays off here
  # (bin/selftest-diet.sh turns it on to test it).
  export QUARTERDECK_REUSE=""
  # ST_PROVIDER=fake: the same duty through the fake adapter (providers/fake.sh) instead of this stand-in. It answers from the same replies
  # folder, runs the same hook and records in the same file; the claude stand-in becomes a tripwire, so a call that went around the
  # adapter seam leaves claude-was-run behind.
  if [ "${ST_PROVIDER:-claude}" = fake ]; then
    cp -R "$REAL/providers" "$T/providers"
    printf '#!/bin/bash
echo "$*" >> "$QUARTERDECK_DIR/claude-was-run"
exit 1
' > "$T/claude"; chmod +x "$T/claude"
    export QUARTERDECK_PROVIDER=fake QUARTERDECK_FAKE_REPLIES="$T/replies" QUARTERDECK_FAKE_HOOK="$T/claude-hook" QUARTERDECK_FAKE_RECORD="$T/claude-calls" QUARTERDECK_FAKE_COST="${STUB_COST:-0.05}"
  else
    unset QUARTERDECK_PROVIDER QUARTERDECK_FAKE_REPLIES QUARTERDECK_FAKE_HOOK QUARTERDECK_FAKE_RECORD QUARTERDECK_FAKE_COST   # left by an earlier st_init in this shell
  fi
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@example.invalid GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
  echo '[]' > "$T/state/runs.json"
}

st_registry() { # st_registry <duties-json-array> [extra-object-json]
  jq -n --arg w "$T/work" --argjson d "$1" --argjson x "$(_obj "${2:-}")" \
    '{tp: ({repo:"x/tp", path:$w, summary:"a fixture", default_branch:"main", duties:$d, guardrails:["Never touch money code."], verify:""} + $x)}' \
    > "$T/config/projects.json"
}

st_repo() { # st_repo — a fixture project: a bare origin and a clone, one commit on main
  git init -q --bare -b main "$T/origin.git" 2>/dev/null || git init -q --bare "$T/origin.git"
  git clone -q "$T/origin.git" "$T/work" 2>/dev/null
  git -C "$T/work" config user.name fixture; git -C "$T/work" config user.email fixture@example.invalid
  (cd "$T/work" && git checkout -q -b main 2>/dev/null; echo "# fixture" > README.md; git add README.md; git commit -q -m init; git push -q origin main)
}

st_file() { # st_file <path> <content> — write into the clone's working tree (committed by st_commit)
  mkdir -p "$(dirname "$T/work/$1")"; printf '%s' "$2" > "$T/work/$1"
}
st_commit() { (cd "$T/work" && git add -A && git commit -q -m "${1:-fixture}" && git push -q origin HEAD:main); }

st_pr() { # st_pr <n> <branch> <path> <content> [<path> <content>]... — a pull request: refs/pull/<n>/head on origin
  local n=$1 br=$2; shift 2
  (cd "$T/work" && git checkout -q -B "$br" main)
  while [ $# -gt 0 ]; do st_file "$1" "$2"; shift 2; done
  (cd "$T/work" && git add -A && git commit -q -m "pr $n" && git push -q origin "HEAD:refs/heads/$br" "HEAD:refs/pull/$n/head" && git checkout -q main)
  local sha; sha=$(git -C "$T/origin.git" rev-parse "refs/pull/$n/head")
  jq -n --argjson n "$n" --arg b "$br" --arg s "$sha" --arg t "${PR_TITLE:-A change}" --arg body "${PR_BODY:-Fixes #7}" \
    '{number:$n, title:$t, body:$body, state:"OPEN", headRefOid:$s, headRefName:$b, baseRefName:"main", isCrossRepository:false}' > "$T/ghdata/pr-$n.json"
  (cd "$T/work" && git diff --name-only main "$br") > "$T/ghdata/diff-$n.names"
  (cd "$T/work" && git diff main "$br") > "$T/ghdata/diff-$n.patch"
}

st_issue() { # st_issue <n> <title> <body>
  jq -n --argjson n "$1" --arg t "$2" --arg b "$3" '{number:$n, title:$t, body:$b, state:"OPEN"}' > "$T/ghdata/issue-$1.json"
}

st_reply() { # st_reply <match-regex> <reply> — checked in the order given; "default" for a catch-all
  local k; k=$(printf '%03d' "$(ls "$T/replies"/*.match 2>/dev/null | wc -l | tr -d " ")")
  if [ "$1" = default ]; then printf '%s' "$2" > "$T/replies/default.reply"
  else printf '%s' "$1" > "$T/replies/$k.match"; printf '%s' "$2" > "$T/replies/$k.reply"; fi
}
st_noreplies() { rm -f "$T"/replies/*; : > "$T/claude-calls"; }

st_duty() { # st_duty <duty> <args...> — run it as project tp. Output in $OUT, exit status in $RC, ledger rows in state/runs.json
  local d=$1; shift
  rm -f "$T/state/${d}"*.lock 2>/dev/null; rm -rf "$T"/state/*.lock
  OUT=$(QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="${ST_WORKDIR:-$T/work}" bash "$T/duties/$d.sh" "$@" 2>&1); RC=$?
}
last_verdict() { jq -r '.[-1].verdict // "none"' "$T/state/runs.json" 2>/dev/null || echo none; }
last_detail()  { jq -r '.[-1].detail // ""' "$T/state/runs.json" 2>/dev/null || echo ""; }
gh_writes()    { grep -cE '^gh (pr (create|edit|comment|merge|review)|issue (create|edit|comment)|api)' "$T/gh-calls" 2>/dev/null || true; }
no_gh_writes() { [ ! -f "$T/gh-calls" ] || [ "$(gh_writes)" = 0 ]; }

# Browser checks need playwright and a browser; say plainly when this machine has neither, and run nothing then. The probe launches the way
# bin/browse.mjs does (its executable, the renderer sandbox on: round 8, L18), so a machine where that cannot start is a skip, not 50 failures.
# Whether a browser can start here, asked of bin/browse.mjs itself (`probe`: the same launch, renderer sandbox on, same flags, as a run), so a
# machine where it cannot start (root in a container, no Chromium) skips the browser checks instead of failing them. Asked once per suite.
st_have_browser() {
  [ -z "${NODE_PATH:-}" ] && [ -d /opt/node-tools/node_modules ] && export NODE_PATH=/opt/node-tools/node_modules
  if [ -z "${_ST_BROWSER:-}" ]; then
    command -v node >/dev/null 2>&1 && node "$REAL/bin/browse.mjs" probe >/dev/null 2>&1 && _ST_BROWSER=yes || _ST_BROWSER=no
  fi
  [ "$_ST_BROWSER" = yes ]
}
st_skip() { printf '  skip  %s\n' "$1"; }
# st_can_nest_sandbox: 0 when a sandboxed project command can start from here. Outside the sandbox (marker unset) it is always 0, so nothing is
# ever skipped there. Inside it (QUARTERDECK_IN_SANDBOX=1) the answer is whether a new bubblewrap (Linux) or sandbox-exec (macOS) can really start.
# ST_NEST_PROBE, a command, replaces the probe (the test of this helper uses it).
st_can_nest_sandbox() {
  [ "${QUARTERDECK_IN_SANDBOX:-}" = 1 ] || return 0
  if [ -n "${ST_NEST_PROBE:-}" ]; then sh -c "$ST_NEST_PROBE" >/dev/null 2>&1; return; fi
  if [ "$(uname -s)" = Darwin ]; then /usr/bin/sandbox-exec -p '(version 1)(allow default)' /usr/bin/true >/dev/null 2>&1; return; fi
  ( source "$REAL/bin/lib.sh" >/dev/null 2>&1; _qd_bwrap_usable )
}
# st_skip_if_nested_sandbox <suite> [<what>]: at the top of a suite that starts its own sandboxed project command: inside the sandbox, where that
# cannot nest, print one skip line and exit 0. Anywhere else it does nothing.
st_skip_if_nested_sandbox() {
  st_can_nest_sandbox && return 0
  st_skip "$1: ${2:-needs to start a sandboxed project command, and a sandbox cannot start inside the sandbox it is already in}"
  exit 0
}
# st_http_up <url>... — 0 once every url answers 200 OUTSIDE any sandbox (a test server just started may take a while on a slow machine), 1 when
# one still does not after ten seconds: then this machine cannot do it at all, and a check that needs it is skipped, saying so.
st_http_up() { local i u ok; for i in $(seq 1 50); do ok=1; for u in "$@"; do [ "$(curl -s -m 2 -o /dev/null -w '%{http_code}' "$u")" = 200 ] || ok=""; done; [ -n "$ok" ] && return 0; sleep 0.2; done; return 1; }
# st_doc <name> — the path of a document written for strangers: docs/public/<name> here, <name> at the top of the public tree (bin/publish.py moves it)
st_doc() { if [ -f "$REAL/docs/public/$1" ]; then printf '%s' "$REAL/docs/public/$1"; else printf '%s' "$REAL/$1"; fi; }
st_skip_browser() { st_skip "skipped: no usable browser (playwright or Chromium cannot start here): $1"; }
