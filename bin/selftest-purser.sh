#!/bin/bash
# The purser is the one duty that puts model-written prose into an existing
# issue, and the harbourmaster's history says why that deserves a check: a real
# run once proposed a note quoting a value the project's own rules forbid
# putting in an issue. So the paths are asserted, against stand-ins for gh,
# board.py and the model that record every call:
#   - the requirements reach GitHub only as an edit of the issue BODY, never as
#     a comment (the builder reads the body and nothing else);
#   - the person's own text survives, and a second analysis replaces the block
#     instead of stacking a second one;
#   - a NEEDS_HUMAN answer, an unparseable reply and a report-only run write
#     nothing to GitHub at all;
#   - the card moves only out of Backlog.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T"/{bin,config,crew,duties,state,workspace,logs/runs,work,path}
cp "$REAL"/bin/{lib.sh,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re,behaviour.py} "$T/bin/"; cp "$REAL"/duties/purser.sh "$T/duties/"
cp "$REAL"/config/quarterdeck.env "$T/config/"; cp "$REAL"/crew/*.md "$T/crew/"
jq -n --arg w "$T/work" '{tp:{repo:"x/tp",path:$w,summary:"s",default_branch:"main",duties:["purser"],
  guardrails:[],verify:"",board:{number:1,owner:"x"}}}' > "$T/config/projects.json"

# The board: says the card was in Backlog, and records what it was asked.
cat > "$T/bin/board.py" <<'PY'
import os, sys
open(os.environ["QUARTERDECK_DIR"] + "/board-calls", "a").write(" ".join(sys.argv[1:]) + "\n")
if os.environ.get("CARD_IN", "Backlog") == "Backlog" and sys.argv[1] == "to": print("Backlog")
PY
# gh: `issue view` returns $BODY; `issue edit --body-file` keeps what it was given.
cat > "$T/path/gh" <<'GH'
#!/bin/bash
echo "gh $*" >> "$QUARTERDECK_DIR/gh-calls"
case "$1 $2" in
  "issue view") if [[ "$*" == *"--jq"* ]]; then printf '%s' "$BODY"
                else jq -n --arg b "$BODY" '{number:7,title:"Notify me on settlement",state:"OPEN",body:$b}'; fi ;;
  "issue edit") while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$QUARTERDECK_DIR/edited-body"; shift; done ;;
esac
GH
chmod +x "$T/path/gh"
cat > "$T/claude" <<'STUB'
#!/bin/bash
cat >> "$QUARTERDECK_DIR/prompts"; echo >> "$QUARTERDECK_DIR/prompts"
jq -n --arg r "$REPLY" '{result:$r, total_cost_usd:0, num_turns:1, usage:{}, modelUsage:{}}'
STUB
chmod +x "$T/claude"
# QUARTERDECK_GH, not PATH: lib.sh puts the real gh first, and a stand-in that is
# bypassed would edit a real issue.
export QUARTERDECK_DIR="$T" QUARTERDECK_SECRETS_DIR="$T/nosecrets" CLAUDE_BIN="$T/claude" QUARTERDECK_CLAUDE_ENV=inherit QUARTERDECK_GH="$T/path/gh"

READY='REQUIREMENTS_JSON: {"summary":"Tell people when a bill is settled.","requirements":[{"what":"When a member marks a bill settled, every other member gets a notification.","accept":"Settle a bill as A; B sees a notification within a minute."},{"what":"A notification names the bill.","accept":"The text contains the bill title."}],"out_of_scope":["Email notifications"]}
RESULT: READY 2 requirement(s)'

fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
go() { # go <body> <reply> [flags...] — a fresh run, everything recorded
  rm -f "$T"/{gh-calls,board-calls,edited-body,prompts,state/runs.json} "$T"/workspace/*.md
  export BODY="$1" REPLY="$2"; shift 2
  QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/purser.sh" --issue 7 "$@" >/dev/null 2>&1
}
verdict() { jq -r '.[-1].verdict // "none"' "$T/state/runs.json" 2>/dev/null || echo none; }

ORIG=$'When someone settles a bill, the others should hear about it.\n\nSee also the settlement screen.'

go "$ORIG" "$READY" --apply
ck "the Purser is told a control needs keyboard reach and a visible focus indicator"  'grep -q "visible focus indicator while focused" "$T/prompts"'
ck "READY: the issue is edited, once"               '[ "$(grep -c "^gh issue edit" $T/gh-calls)" = 1 ]'
ck "  through its body, never a comment"            '! grep -q "issue comment" $T/gh-calls'
ck "  the person's own text is untouched"           'grep -q "the others should hear about it" $T/edited-body && grep -q "See also the settlement screen" $T/edited-body'
ck "  the requirements are in it, with acceptance"  'grep -q "^1. When a member marks a bill settled" $T/edited-body && grep -q "Accept when:\*\* Settle a bill as A" $T/edited-body'
ck "  what is out of scope is stated"               'grep -q "Email notifications" $T/edited-body'
ck "  the block is marked so it can be replaced"    'grep -q "<!-- quarterdeck:requirements -->" $T/edited-body && grep -q "<!-- /quarterdeck:requirements -->" $T/edited-body'
ck "  the card moves to Ready, from Backlog only"   'grep -q "^to x 1 7 ready .* todo" $T/board-calls'
ck "  the verdict is READY"                         '[ "$(verdict)" = READY ]'
ck "  a local copy is kept"                         'grep -q "Accept when" $T/workspace/tp-requirements-7.md'

# a second analysis: the block is replaced, not stacked, and the text is still there
FIRST="$(cat "$T/edited-body")"
go "$FIRST" "$READY" --apply
ck "again: still exactly one block"                 '[ "$(grep -c "<!-- quarterdeck:requirements -->" $T/edited-body)" = 1 ]'
ck "  and the person's text is still there"         'grep -q "See also the settlement screen" $T/edited-body'

# a block someone damaged (opening marker only) is not guessed at
go $'Keep me.\n\n<!-- quarterdeck:requirements -->\nhalf a block, edited by hand\n\nAnd me.' "$READY" --apply
ck "a damaged block deletes nothing"                'grep -q "And me." $T/edited-body && grep -q "Keep me." $T/edited-body'

# an issue already being worked on is not pulled back to Ready by being analysed
CARD_IN="In progress" go "$ORIG" "$READY" --apply
ck "a card that is not in Backlog stays where it is" '! grep -q "moved from" $T/state/runs.json && [ "$(verdict)" = READY ]'

go "$ORIG" "RESULT: NEEDS_HUMAN This is three features; split pricing from notifications first." --apply
ck "NEEDS_HUMAN: nothing is written to GitHub"      '! grep -q "issue edit" $T/gh-calls && [ ! -f $T/edited-body ]'
ck "  the card does not move"                        '[ ! -f $T/board-calls ]'
ck "  the reason is kept locally and in the ledger"  'grep -q "split pricing" $T/workspace/tp-requirements-7.md && [ "$(verdict)" = NEEDS_HUMAN ]'

go "$ORIG" "I think this looks fine." --apply
ck "an unparseable reply writes nothing"            '! grep -q "issue edit" $T/gh-calls && [ ! -f $T/board-calls ] && [ "$(verdict)" = ERROR ]'
go "$ORIG" $'REQUIREMENTS_JSON: {"requirements":[{"what":"x"}]}\nRESULT: READY 1 requirement(s)' --apply
ck "a requirement with no acceptance check is refused" '! grep -q "issue edit" $T/gh-calls && [ "$(verdict)" = ERROR ]'

# #86: an acceptance check that only proves a thing exists is not enough; at least one must make the thing do something
EXISTONLY='REQUIREMENTS_JSON: {"summary":"Add a Reset button.","requirements":[{"what":"There is a Reset button.","accept":"grep index.html for id=\"reset\"; the element exists."},{"what":"It is labelled.","accept":"The page contains the string Reset."}],"out_of_scope":[]}
RESULT: READY 2 requirement(s)'
go "$ORIG" "$EXISTONLY" --apply
ck "#86 checks that only grep for an element or string are refused: nothing written, the card does not move" '! grep -q "issue edit" $T/gh-calls && [ ! -f $T/board-calls ] && [ "$(verdict)" = ERROR ]'
ck "  and the local copy is not written as if it were requirements" '! grep -q "Accept when" $T/workspace/tp-requirements-7.md 2>/dev/null'
MIXED='REQUIREMENTS_JSON: {"summary":"Add a Reset button.","requirements":[{"what":"There is a Reset button.","accept":"The page contains the string Reset."},{"what":"Reset clears the form.","accept":"Type a name, click Reset: the field is empty again."}],"out_of_scope":[]}
RESULT: READY 2 requirement(s)'
go "$ORIG" "$MIXED" --apply
ck "#86 an existence check beside one that exercises the behaviour is accepted" 'grep -q "^gh issue edit" $T/gh-calls && [ "$(verdict)" = READY ]'
ck "#86 the Purser is told to write one check that makes the thing do something and to say what happens" 'grep -q "exercises the behaviour" $T/prompts && grep -q "never only that" $T/prompts'

go "$ORIG" "$READY"
ck "report only: nothing is written or moved"       '! grep -q "issue edit" $T/gh-calls && [ ! -f $T/board-calls ] && [ "$(verdict)" = DRY-RUN ]'

echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
