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
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fails=0; passed=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; passed=$((passed+1)); else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
st_done() { echo; [ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }; }
_obj() { if [ -n "$1" ]; then printf '%s' "$1"; else printf '{}'; fi; }   # "${1:-{}}" is "{\}" in bash 3.2, so a default object goes through here
# A process group is killed asynchronously: wait up to four seconds for what matches $1 to disappear before calling it still alive.
st_gone() { local i; for i in $(seq 1 40); do pgrep -f "$1" >/dev/null 2>&1 || return 0; sleep 0.1; done; return 1; }

st_init() { # st_init <duty>... — a throwaway Quarterdeck holding the harness, those duties and the real crew
  mkdir -p "$T"/{bin,config,crew,duties,state,workspace,logs/runs,path,ghdata,replies}
  cp "$REAL"/bin/{lib.sh,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re,behaviour.py,routes.py} "$T/bin/"
  for f in browse.mjs decisions.sh; do [ -f "$REAL/bin/$f" ] && cp "$REAL/bin/$f" "$T/bin/"; done
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
[ -f "${settings:-/nonexistent}" ] && { spath="$settings"; smode="$(stat -f %Lp "$settings" 2>/dev/null || stat -c %a "$settings")"; settings="$(cat "$settings")"; }
jq -nc --arg p "$p" --arg deny "${deny:-}" --arg allow "${allow:-}" --arg model "${model:-}" --arg tools "${tools:-}" --arg settings "${settings:-}" --arg sources "${sources-unset}" --argjson argv "$argv" --arg spath "$spath" --arg smode "$smode" '{spath:$spath, smode:$smode, argv:$argv, prompt:$p, deny:$deny, allow:$allow, model:$model, tools:$tools, settings:$settings, sources:$sources}' >> "$QUARTERDECK_DIR/claude-calls"
rmdir "$lk"
[ -x "$QUARTERDECK_DIR/claude-hook" ] && "$QUARTERDECK_DIR/claude-hook" "$p" >/dev/null 2>&1
jq -n --arg r "$reply" --argjson c "${STUB_COST:-0.05}" '{result:$r, total_cost_usd:$c, num_turns:1, usage:{}, modelUsage:{"stub-model":{}}}'
STUB
  chmod +x "$T/claude"
  # QUARTERDECK_GH, not PATH: lib.sh puts the real gh first, and a stand-in that is bypassed would touch a real repository.
  export QUARTERDECK_DIR="$T" QUARTERDECK_SECRETS_DIR="$T/nosecrets" CLAUDE_BIN="$T/claude" QUARTERDECK_CLAUDE_ENV=inherit QUARTERDECK_GH="$T/path/gh"
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

# Browser checks need playwright and a browser; say plainly when this machine has neither, and run nothing then.
st_have_browser() {
  [ -z "${NODE_PATH:-}" ] && [ -d /opt/node-tools/node_modules ] && export NODE_PATH=/opt/node-tools/node_modules
  command -v node >/dev/null 2>&1 && node -e 'require("playwright")' 2>/dev/null \
    && node -e 'require("playwright").chromium.launch({executablePath:process.env.QUARTERDECK_CHROMIUM||undefined}).then(b=>b.close()).then(()=>process.exit(0),()=>process.exit(1))' 2>/dev/null
}
st_skip() { printf '  skip  %s\n' "$1"; }
