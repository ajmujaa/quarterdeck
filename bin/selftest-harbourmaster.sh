#!/bin/bash
# The harbourmaster keeps what the model says off GitHub: its notes go to a
# local document, and the only thing it writes to the board is a column change
# computed from GitHub's own data. That rule exists because a real run proposed
# a note quoting a price from a project's memory. So it is asserted here: a note
# carrying a marker is run through the duty with --apply, against stand-ins for
# board.py and gh that record every call, and the marker must reach the local
# document and nothing that talks to GitHub.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T"/{bin,config,crew,duties,state,workspace,logs/runs,work,path}
cp "$REAL"/bin/{lib.sh,markers.py,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re} "$T/bin/"; cp "$REAL"/duties/harbourmaster.sh "$T/duties/"
cp "$REAL"/config/quarterdeck.env "$T/config/"; cp "$REAL"/crew/*.md "$T/crew/"
jq -n --arg w "$T/work" '{tp:{repo:"x/tp",path:$w,summary:"s",default_branch:"main",duties:["harbourmaster"],
  guardrails:[],verify:"",board:{number:1,owner:"x"}}}' > "$T/config/projects.json"
MARK="SECRET-PRICE-4711"

cat > "$T/bin/board.py" <<'PY'
import json, os, sys
open(os.environ["QUARTERDECK_DIR"] + "/github-calls", "a").write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1] == "snapshot":
    print(json.dumps({"fields": [{"name": "Status", "options": [{"name": "Todo"}, {"name": "In Progress"}, {"name": "Done"}]}],
                      "items": [{"number": 5, "item_id": "I5", "state": "CLOSED", "status": "Todo", "open_prs": []},
                                {"number": 6, "item_id": "I6", "state": "OPEN", "status": "Todo", "open_prs": []}],
                      "missing_from_board": []}))
elif sys.argv[1] == "text":
    print("#5 Todo closed\n#6 Todo open")
PY
printf '#!/bin/bash\necho "gh $*" >> "$QUARTERDECK_DIR/github-calls"\n' > "$T/path/gh"; chmod +x "$T/path/gh"
cat > "$T/claude" <<STUB
#!/bin/bash
r='MOVES_JSON: [{"item_id":"I6","number":6,"to":"In Progress","why":"$MARK is being worked on"}]
NOTES_JSON: [{"number":6,"note":"the budget of $MARK should be raised on the issue"}]
RESULT: BOARD 1 move(s), 1 note(s)'
jq -n --arg r "\$r" '{result:\$r, total_cost_usd:0, num_turns:1, usage:{}, modelUsage:{}}'
STUB
chmod +x "$T/claude"
export QUARTERDECK_DIR="$T" QUARTERDECK_SECRETS_DIR="$T/nosecrets" CLAUDE_BIN="$T/claude" QUARTERDECK_CLAUDE_ENV=inherit PATH="$T/path:$PATH"

fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/harbourmaster.sh" --apply >/dev/null 2>&1

ck "the duty ran and wrote to the board"       'grep -q "^move x 1 I5 Status Done" "$T/github-calls"'
ck "the model's move is applied by column"     'grep -q "^move x 1 I6 Status In Progress" "$T/github-calls"'
ck "the note is kept in a local document"      'grep -q "$MARK" "$T"/workspace/tp-board-*.md'
ck "nothing the model wrote reaches GitHub"    '! grep -q "$MARK" "$T/github-calls"'
ck "  and gh is never called with prose"       '! grep -q "^gh .*comment" "$T/github-calls"'

echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
