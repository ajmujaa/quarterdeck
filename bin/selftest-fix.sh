#!/bin/bash
# The fix pipeline is the one path that files issues, pushes branches and opens
# pull requests from a single click, so its control flow is asserted rather than
# assumed — against stand-in duties in a throwaway Quarterdeck, never the real repo.
# Each scenario checks where the pipeline stopped and what it recorded.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T"/{bin,config,crew,duties,state/panels,workspace,logs}
cp "$REAL"/bin/{lib.sh,fix} "$T/bin/"; cp "$REAL"/config/quarterdeck.env "$T/config/"; cp "$REAL"/crew/*.md "$T/crew/"
# the registry is the test's own, never anyone's real one: a fresh clone has none
cat > "$T/config/projects.json" <<'JSON'
{"harvest-pipeline": {"repo": "x/harvest-pipeline", "path": "~/Projects/harvest-pipeline", "default_branch": "main",
  "duties": ["surveyor", "foreman", "joiner", "shipwright", "panel", "inspector", "harbourmaster", "purser"],
  "board": {"number": "2", "owner": "x"}, "verify": "npx tsc --noEmit", "build": "npm run build",
  "forbidden_paths": ["db/migrations/", "src/crypto/"], "guardrails": ["Never merge a pull request."]}}
JSON
export QUARTERDECK_DIR="$T" QUARTERDECK_SECRETS_DIR="$T/nosecrets"

stub() { printf '#!/bin/bash\nsource "$QUARTERDECK_DIR/bin/lib.sh"\necho "args=$* model=${QUARTERDECK_MODEL_OVERRIDE:-} effort=${QUARTERDECK_EFFORT_OVERRIDE:-}" >> "$QUARTERDECK_DIR/state/called-%s"\n%s\n' "$1" "$2" > "$T/duties/$1.sh"; }
stub foreman '
if [ "${S_FILE:-yes}" = yes ]; then
  f=$QUARTERDECK_DIR/state/filed.json; [ -f $f ] || echo "[]" > $f
  jq --arg d "$(basename "$2")" ". + [{project:\"harvest-pipeline\",document:\$d,issues:[{number:900,url:\"u\",title:\"t\"}]}]" $f > $f.t && mv $f.t $f
  record_run harvest-pipeline foreman FILED "1 issue(s)"
else record_run harvest-pipeline foreman DRY-RUN "0 to file"; fi'
stub panel '
case "${S_PLAN:-ruled}" in
  ruled) echo "# plan" > "$QUARTERDECK_DIR/workspace/harvest-pipeline-plan-900.md"; record_run harvest-pipeline panel RULED "dev: 2 of 3 on issue #900" ;;
  zero)  echo "# plan" > "$QUARTERDECK_DIR/workspace/harvest-pipeline-plan-900.md"; record_run harvest-pipeline panel RULED "dev: 0 of 3 on issue #900" ;;
  clean) record_run harvest-pipeline panel CLEAN "dev: nothing found" ;;
  none)  : ;;
esac'
stub shipwright '
case "${S_BUILD:-pr}" in
  pr)      record_run harvest-pipeline shipwright PR "#900 → pull/901" "https://github.com/x/harvest-pipeline/pull/901" ;;
  refused) record_run harvest-pipeline shipwright REFUSED "#900 — build got worse"; exit 1 ;;
  taken)   record_run harvest-pipeline shipwright TAKEN "#900 already has #950 (someone-else)" ;;
esac'
stub surveyor 'record_run harvest-pipeline surveyor CLEAN "#901"'
stub inspector 'record_run harvest-pipeline inspector PROVEN "#901 — traced it"'
cat > "$T/gh" <<'GH'
#!/bin/bash
open='{"title":"A card","state":"OPEN"}'
if [ "$1 $2" = "issue view" ]; then echo "${GH_ISSUE:-$open}"; else printf "%s" "${GH_TAKEN:-}"; fi
GH
chmod +x "$T/gh"; export QUARTERDECK_GH="$T/gh"
# The board stand-in records every move. Asked to take a card it says the card was in Ready.
cat > "$T/bin/board.py" <<'PY'
import os, sys
open(os.environ["QUARTERDECK_DIR"] + "/state/board-calls", "a").write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1] == "to" and sys.argv[5] == "doing": print("Ready")
PY

jq -n '{id:"tp", project:"harvest-pipeline", discipline:"design", status:"done",
        ruling:[{title:"A button with no name",severity:"major",area:"a11y",kind:"change",tier:"intricate",
                 claim:"c",where:"w",why:"y",action:"a"}]}' > "$T/state/panels/tp.json"
retier() { # retier <kind> <tier>
  jq --arg k "$1" --arg t "$2" '.ruling[0].kind = $k | .ruling[0].tier = $t' "$T/state/panels/tp.json" > "$T/tp.t" \
    && mv "$T/tp.t" "$T/state/panels/tp.json"; }
got() { cat "$T/state/called-$1" 2>/dev/null; }

fails=0
run() { # run <label> <expect-status> [env...]  — fresh state each time
  local label=$1 want=$2; shift 2
  rm -f "$T"/state/{runs,filed}.json "$T"/state/called-* "$T"/workspace/*.md; rm -rf "$T/state/fixes"
  local a; for a in "$@"; do case "$a" in SEED_OWN_PR=*)   # a PR an earlier click opened
    jq -n --arg n "${a#*=}" '[{project:"harvest-pipeline",duty:"shipwright",verdict:"PR",detail:"#900",
          url:("https://github.com/x/harvest-pipeline/pull/" + $n),at:"2026-09-01T00:00:00Z"}]' \
      > "$T/state/runs.json" ;;
    SEED_FULL=1)   # a ledger already at its 200-row cap
    jq -n '[range(200) | {project:"other",duty:"x",verdict:"OK",detail:"",url:"",at:"2026-09-01T00:00:00Z"}]' \
      > "$T/state/runs.json" ;;
    BUSY_INSPECTOR=1) mkdir -p "$T/state/inspector-harvest-pipeline-901.lock"; echo $$ > "$T/state/inspector-harvest-pipeline-901.lock/pid" ;;
    esac; done
  env "$@" bash "$T/bin/fix" harvest-pipeline --panel tp --item 1 --apply >/dev/null 2>&1
  got=$(jq -r .status "$T/state/fixes/tp-1.json" 2>/dev/null || echo "(no record)")
  if [ "$got" = "$want" ]; then printf '  ok    %s\n' "$label"
  else printf '  FAIL  %s: expected %s, got %s\n' "$label" "$want" "$got"; fails=$((fails+1)); fi
}
called() { [ -f "$T/state/called-$1" ]; }
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }

run "the whole crew: file, plan, build, review, verify" pr
ck  "  it planned before it built"        'called panel && called shipwright'
ck  "  the surveyor reviewed the PR"       'called surveyor'
ck  "  the inspector's verdict is kept"    '[ "$(jq -r .verdict $T/state/fixes/tp-1.json)" = PROVEN ]'
ck  "  the builder was handed the plan"    '[ "$(jq -r .plan $T/state/fixes/tp-1.json)" = harvest-pipeline-plan-900.md ]'

run "a full ledger: the fix still finds its own rows" pr SEED_FULL=1
ck  "  and keeps the inspector's verdict"  '[ "$(jq -r .verdict $T/state/fixes/tp-1.json)" = PROVEN ]'
run "a busy inspector is recorded, not skipped silently" pr BUSY_INSPECTOR=1
ck  "  the item says it was not verified"   '[ "$(jq -r .verdict $T/state/fixes/tp-1.json)" = "skipped: inspector busy" ]'
rm -rf "$T/state/inspector-harvest-pipeline-901.lock"

run "someone already has a PR: stops before planning" taken GH_TAKEN="#950 (other-bot/fix-900)"
ck  "  no planning calls were spent"       '! called panel && ! called shipwright'

run "the foreman declines: nothing to build" nothing S_FILE=no
ck  "  nothing after the foreman ran"      '! called panel'

run "the dev panel finds nothing to change" nothing S_PLAN=clean
ck  "  the shipwright was never called"    '! called shipwright'
run "the dev panel rules zero steps"        nothing S_PLAN=zero
run "planning stops (usage limit, no row)"  blocked S_PLAN=none
ck  "  it did not build around the plan"   '! called shipwright'

run "a local check regresses: refused"     blocked S_BUILD=refused
ck  "  nobody reviewed a PR that isn't there" '! called surveyor && ! called inspector'
run "someone got there while it planned"   taken S_BUILD=taken

run "Quarterdeck's own earlier PR: adopt it, then review it" pr GH_TAKEN="#950 (fix/900-x)" SEED_OWN_PR=950
ck  "  reviewed and verified the existing PR" 'called surveyor && called inspector'
ck  "  did not plan or build a second one"   '! called panel && ! called shipwright'
ck  "  recorded that PR as this item's"      '[ "$(jq -r .pr $T/state/fixes/tp-1.json)" = https://github.com/x/harvest-pipeline/pull/950 ]'
run "someone else's PR is still hands-off"   taken GH_TAKEN="#951 (other-bot/fix-900)" SEED_OWN_PR=950
ck  "  and the crew stays out of it"         '! called surveyor && ! called panel' 

# ---- routing by tier: what each fix is allowed to cost -------------------------
export QUARTERDECK_TIER_MECHANICAL=claude-haiku-4-5 QUARTERDECK_TIER_ROUTINE=claude-sonnet-5 QUARTERDECK_TIER_INTRICATE= QUARTERDECK_TIER_HARD=

retier change mechanical
run "mechanical: no developer panel at all"   pr
ck  "  the panel was never convened"           '! called panel'
ck  "  built on Haiku"                          'grep -q "model=claude-haiku-4-5" <<<"$(got shipwright)"'
ck  "  built from the ruling item itself"       'grep -q -- "--plan .*harvest-pipeline-fix-tp-1.md" <<<"$(got shipwright)"'

retier change routine
run "routine: a light panel"                   pr
ck  "  one round, on Sonnet"                    'grep -q -- "--rounds 1" <<<"$(got panel)" && grep -q "model=claude-sonnet-5" <<<"$(got panel)"'
ck  "  built on Sonnet"                         'grep -q "model=claude-sonnet-5" <<<"$(got shipwright)"'

retier change intricate
run "intricate: the full panel"                pr
ck  "  both rounds, each seat on its own model" '! grep -q -- "--rounds" <<<"$(got panel)" && grep -q "model= " <<<"$(got panel)"'

retier change hard
run "hard: the full panel on Opus at xhigh"    pr
ck  "  planned at xhigh on the account default" 'grep -q "model=default effort=xhigh" <<<"$(got panel)"'
ck  "  built at xhigh"                          'grep -q "effort=xhigh" <<<"$(got shipwright)"'
ck  "  reviewed and verified at xhigh too"      'grep -q "effort=xhigh" <<<"$(got surveyor)" && grep -q "effort=xhigh" <<<"$(got inspector)"'

retier decision routine
rm -f "$T"/state/called-*; rm -rf "$T/state/fixes" "$T"/state/{runs,filed}.json
bash "$T/bin/fix" harvest-pipeline --panel tp --item 1 --apply >/dev/null 2>&1
ck "a decision is never built: nothing is even filed" '! called foreman && ! called panel && ! called shipwright'

retier change mechanical
run "planning=full puts even a mechanical item through the panel" pr QUARTERDECK_FIX_PLANNING=full
ck  "  the panel was convened"                  'called panel'
ck  "  but it still builds on its own tier"     'grep -q "model=claude-haiku-4-5" <<<"$(got shipwright)"'
retier change intricate

# ---- a batch: several related items, one branch, one pull request -------------
jq '.ruling += [{title:"Another nameless button",severity:"minor",area:"a11y",kind:"change",tier:"mechanical",claim:"c",where:"w2",why:"y",action:"a"},
                {title:"Pick a dialog library",severity:"major",area:"a11y",kind:"decision",tier:"routine",claim:"c",where:"w3",why:"y",action:"a"},
                {title:"Touches the key",severity:"major",area:"a11y",kind:"change",tier:"hard",claim:"c",where:"w4",why:"y",action:"a"}]' \
  "$T/state/panels/tp.json" > "$T/tp.t" && mv "$T/tp.t" "$T/state/panels/tp.json"
batch() { rm -f "$T"/state/{runs,filed}.json "$T"/state/called-* "$T"/workspace/*.md; rm -rf "$T/state/fixes"
          bash "$T/bin/fix" harvest-pipeline --panel tp --item "$1" --apply >/dev/null 2>&1; }
batch 1,2,3
ck "a batch is filed once, as one issue"         '[ "$(grep -c . $T/state/called-foreman)" = 1 ] && grep -q -- "--one" <<<"$(got foreman)"'
ck "  and built once, as one pull request"       '[ "$(grep -c . $T/state/called-shipwright)" = 1 ]'
ck "  every member it built is marked with it"   '[ "$(jq -r .status $T/state/fixes/tp-1.json)" = pr ] && [ "$(jq -r .pr $T/state/fixes/tp-2.json)" = https://github.com/x/harvest-pipeline/pull/901 ]'
ck "  the decision in it is left out"            '[ ! -f $T/state/fixes/tp-3.json ] && ! grep -q "Pick a dialog library" $T/workspace/harvest-pipeline-fix-tp-1-2.md'
ck "  it plans at its hardest item's tier"       '! grep -q -- "--rounds" <<<"$(got panel)"'
batch 2,4
ck "a batch with a hard item is hard throughout" 'grep -q "effort=xhigh" <<<"$(got shipwright)" && grep -q "effort=xhigh" <<<"$(got inspector)"'
jq '.ruling |= .[:1]' "$T/state/panels/tp.json" > "$T/tp.t" && mv "$T/tp.t" "$T/state/panels/tp.json"
ck "--item refuses anything but numbers"         '! bash "$T/bin/fix" harvest-pipeline --panel tp --item "1;x" >/dev/null 2>&1'

# ---- an issue that already exists: a card on the board ------------------------
runi() { # runi <label> <expect-status> [env...]  — fresh state each time
  local label=$1 want=$2; shift 2
  rm -f "$T"/state/{runs,filed,board-calls}* "$T"/state/called-* "$T"/workspace/*.md; rm -rf "$T/state/fixes"
  env "$@" bash "$T/bin/fix" harvest-pipeline --issue 900 --apply >/dev/null 2>&1
  got=$(jq -r .status "$T/state/fixes/issue-900.json" 2>/dev/null || echo "(no record)")
  if [ "$got" = "$want" ]; then printf '  ok    %s\n' "$label"
  else printf '  FAIL  %s: expected %s, got %s\n' "$label" "$want" "$got"; fails=$((fails+1)); fi
}
moved() { grep -q "^to x 2 900 $1" "$T/state/board-calls" 2>/dev/null; }

runi "a card on the board goes through the crew" pr
ck  "  nothing was filed: it already is an issue"  '! called foreman'
ck  "  it planned, built, reviewed and verified"   'called panel && called shipwright && called surveyor && called inspector'
ck  "  the card was taken into In progress"        'moved doing'
ck  "  and moved to In review when the PR opened"  'moved review'
ck  "  and never put back"                         '! moved Ready'
ck  "  the record names the issue and its PR"      '[ "$(jq -r .issue $T/state/fixes/issue-900.json)" = 900 ] && [ "$(jq -r .pr $T/state/fixes/issue-900.json)" = https://github.com/x/harvest-pipeline/pull/901 ]'
ck  "  the ledger says where it came from"         'jq -e "map(select(.duty == \"fix\" and .verdict == \"PR\" and (.detail | startswith(\"started from the board\")))) | length == 1" $T/state/runs.json >/dev/null'

runi "the build is refused: no PR"          blocked S_BUILD=refused
ck  "  the card goes back to where it was"   'moved doing && moved Ready && ! moved review'
runi "someone else already has it"           taken GH_TAKEN="#950 (other-bot/fix-900)"
ck  "  no planning was spent"                '! called panel && ! called shipwright'
ck  "  the card goes back"                   'moved Ready'
runi "the dev panel finds nothing to change" nothing S_PLAN=clean
ck  "  the card goes back"                   'moved Ready'

rm -f "$T"/state/board-calls; rm -rf "$T/state/fixes"
out=$(GH_ISSUE='{"title":"Old","state":"CLOSED"}' bash "$T/bin/fix" harvest-pipeline --issue 900 --apply 2>&1); rc=$?
ck "a closed issue is refused before anything moves" '[ $rc != 0 ] && grep -q "not open" <<<"$out" && [ ! -f $T/state/board-calls ] && [ ! -f $T/state/fixes/issue-900.json ]'
ck "--issue takes a number and stands alone"   '! bash "$T/bin/fix" harvest-pipeline --issue "9;x" --apply >/dev/null 2>&1 && ! bash "$T/bin/fix" harvest-pipeline --issue 900 --panel tp >/dev/null 2>&1'
rm -f "$T"/state/board-calls "$T"/state/called-*; rm -rf "$T/state/fixes"
bash "$T/bin/fix" harvest-pipeline --issue 900 >/dev/null 2>&1
ck "without --apply it changes nothing"        '[ ! -f $T/state/board-calls ] && [ ! -d $T/state/fixes ] && ! called panel && ! called shipwright'

# a project with no board still works; there is just no card to move
cp "$T/config/projects.json" "$T/projects.bak"
jq 'del(.["harvest-pipeline"].board)' "$T/projects.bak" > "$T/config/projects.json"
runi "a project with no board still builds"   pr
ck  "  and touches no board"                   '[ ! -f $T/state/board-calls ]'
cp "$T/projects.bak" "$T/config/projects.json"

# a second pipeline on the SAME item is refused while the first runs — but a
# fix on a DIFFERENT item of the same project is not held up by it: each locks
# by its own target now, not the whole project (several fixes, several
# worktrees, side by side).
rm -rf "$T/state/fixes"; sleep 30 & holder=$!; disown $holder
mkdir -p "$T/state/fix-harvest-pipeline-tp-1.lock"; echo $holder > "$T/state/fix-harvest-pipeline-tp-1.lock/pid"
out=$(bash "$T/bin/fix" harvest-pipeline --panel tp --item 1 --apply 2>&1); rc=$?
ck "a second fix on the same item is refused" '[ $rc != 0 ] && grep -q "already running" <<<"$out" && [ ! -f $T/state/fixes/tp-1.json ]'

out=$(bash "$T/bin/fix" harvest-pipeline --issue 900 --apply 2>&1); rc=$?
kill $holder 2>/dev/null
ck "a fix on a different item of the same project is not held up by it" \
   '[ $rc = 0 ] && [ -f $T/state/fixes/issue-900.json ] && ! grep -q "already running" <<<"$out"'

echo
[ "$fails" = 0 ] && { echo "  all checks passed"; exit 0; }
echo "  $fails check(s) failed"; exit 1
