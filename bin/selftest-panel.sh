#!/bin/bash
# A panel builds three prompts by string interpolation, and one stray quote in
# any of them changes what bash parses without `bash -n` noticing. That once
# made every panel fail at the ruling, after the seats had been paid for. So a
# whole panel is run here against a stand-in `claude` that answers each prompt
# by its contract — in a throwaway Quarterdeck, never the real one.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T"/{bin,config,crew,duties,state/panels,workspace,logs/runs,work}
cp "$REAL"/bin/{lib.sh,markers.py,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re} "$T/bin/"; cp "$REAL"/duties/panel.sh "$T/duties/"
cp "$REAL"/config/quarterdeck.env "$T/config/"; cp "$REAL"/crew/*.md "$T/crew/"
jq -n --arg w "$T/work" '{tp:{repo:"x/tp",path:$w,summary:"s",default_branch:"main",duties:["panel"],guardrails:[],verify:""}}' \
  > "$T/config/projects.json"
cat > "$T/claude" <<'STUB'
#!/bin/bash
p=$(cat); while [ $# -gt 0 ]; do shift; done
case "$p" in
  *RULING_JSON*) r='HEADLINE: two things
RULING_JSON: [{"kind":"change","tier":"routine","area":"a","severity":"major","title":"t","claim":"c","where":"w","why":"y","action":"a","support":["shipwright"],"overruled":[],"note":""}]
RESULT: RULED 1' ;;
  *STANCES_JSON*) r='STANCES_JSON: [{"id":"shipwright-1","stance":"agree","note":"n"}]
RESULT: STANCES 1' ;;
  *) r='ITEMS_JSON: [{"area":"a","severity":"major","title":"t","claim":"c","where":"w","why":"y","action":"a"}]
RESULT: ITEMS 1' ;;
esac
echo "$p" >> "$QUARTERDECK_DIR/prompts"
jq -n --arg r "$r" '{result:$r, total_cost_usd:0, num_turns:1, usage:{}, modelUsage:{}}'
STUB
chmod +x "$T/claude"
export QUARTERDECK_DIR="$T" QUARTERDECK_SECRETS_DIR="$T/nosecrets" CLAUDE_BIN="$T/claude" QUARTERDECK_CLAUDE_ENV=inherit

fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }
last() { ls -t "$T"/state/panels/*.json | head -1; }

QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/panel.sh" --panel design --seats shipwright,inspector >/dev/null 2>&1
P="$(last)"
ck "a whole panel runs to a ruling"          '[ "$(jq -r .status "$P")" = done ] && [ "$(jq ".ruling | length" "$P")" = 1 ]'
ck "the chair was told to scale the ruling to the subject"  'grep -q "Scale the ruling to what was asked" "$T/prompts"'
ck "the chair was asked for kind and tier"   'grep -q "kind — what the item IS" "$T/prompts"'

# a panel that argued but was never ruled on is ruled from its transcript alone
jq '.ruling = [] | .status = "failed" | .verdict = "the ruling prompt did not build"' "$P" > "$P.t" && mv "$P.t" "$P"
: > "$T/prompts"
QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/panel.sh" --resume "$(basename "$P" .json)" >/dev/null 2>&1
ck "--resume rules a failed panel"           '[ "$(jq -r .status "$P")" = done ] && [ "$(jq ".ruling | length" "$P")" = 1 ]'
ck "  and pays only for the chair"           '[ "$(grep -c "^You are the " "$T/prompts")" = 1 ] && grep -q "You are the dockmaster" "$T/prompts"'
ck "  in the same transcript"                '[ "$(ls "$T"/state/panels/*.json | wc -l | tr -d " ")" = 1 ]'
out=$(QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/panel.sh" --resume "$(basename "$P" .json)" 2>&1)
ck "an already-ruled panel is not resumed"   'grep -q "nothing to resume" <<<"$out"'
out=$(QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/panel.sh" --resume "../x" 2>&1)
ck "--resume takes only a panel id"          'grep -q "takes a panel id" <<<"$out"'

echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
