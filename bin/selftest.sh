#!/bin/bash
# The bash-side checks qtdeck check runs. These cover the commit gate: the thing that
# decides whether work a model did is allowed to reach a branch. It is the most
# safety-critical logic here and it is pure shell, so it gets asserted rather
# than assumed.
#
# Fast on purpose — no worktrees, no builds. The real gate was proven end to end
# against a genuine type error in harvest-pipeline; this pins the comparison it depends on.
set -uo pipefail
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/state" "$T/config"; echo "[]" > "$T/state/runs.json"; touch "$T/config/quarterdeck.env"
export QUARTERDECK_DIR="$T"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

fails=0
ck() { # ck <label> <expected> <actual>
  if [ "$2" = "$3" ]; then printf '  ok    %s\n' "$1"
  else printf '  FAIL  %s: expected %s, got %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
j() { printf '{"name":"%s","cmd":"%s","rc":%s,"errors":%s,"tail":""}' "$1" "$1" "$2" "$3"; }
n_reg() { check_regressions "$1" "$2" | jq length; }

pass="$(j verify 0 0)"
fail="$(j verify 1 2)"

ck "a clean run regresses nothing"                 0 "$(n_reg "$pass" "$pass")"
ck "a check that passed and now fails is caught"   1 "$(n_reg "$pass" "$(j verify 1 4)")"
ck "a crash with no error lines is still caught"   1 "$(n_reg "$pass" "$(j verify 1 0)")"
ck "more error lines is caught"                    1 "$(n_reg "$pass" "$(j verify 0 3)")"
ck "a pre-existing failure may keep failing"       0 "$(n_reg "$fail" "$fail")"
ck "a pre-existing failure getting worse is caught" 1 "$(n_reg "$fail" "$(j verify 1 5)")"
ck "a pre-existing failure improving is allowed"   0 "$(n_reg "$fail" "$(j verify 0 0)")"
ck "each check is compared on its own name"        1 \
   "$(n_reg "$(j verify 0 0)
$(j build 0 0)" "$(j verify 0 0)
$(j build 1 1)")"
ck "a check appearing for the first time must pass" 1 "$(n_reg "$(j verify 0 0)" "$(j test 1 1)")"
ck "no checks at all is not a regression"          0 "$(n_reg "" "")"

reason="$(check_regressions "$pass" "$(j verify 1 0)" | jq -r '.[0].why')"
ck "a crash is reported as a pass-to-fail, not a count" "passed before, fails now" "$reason"

# Every long-running script must be read whole before it runs, or editing it
# mid-run resumes the run inside the new text. Checked structurally, for every
# duty that exists now and every one copied from the template later.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for f in "$root"/duties/*.sh "$root"/bin/fix; do
  n="${f#$root/}"
  if grep -q '^# quarterdeck: read-whole-file$' "$f" && [ "$(tail -c 3 "$f" | tr -d '\n')" = "}" ]; then
    ck "$n is read whole before it runs" ok ok
  else
    ck "$n is read whole before it runs" wrapped "not wrapped"
  fi
done

# A review or a verify names the exact commit it read, so a later push cannot
# go on wearing an earlier verdict (F09). Only those two duties, and only when
# there is a PR to ask about.
cat > "$T/gh-stub" <<'GH'
#!/bin/bash
[ "$1 $2" = "pr view" ] && echo "sha-of-the-moment"
GH
chmod +x "$T/gh-stub"
QUARTERDECK_GH="$T/gh-stub" record_run harvest-pipeline surveyor CLEAN "#901" "https://github.com/x/harvest-pipeline/pull/901"
QUARTERDECK_GH="$T/gh-stub" record_run harvest-pipeline inspector PROVEN "#901 — traced it" "https://github.com/x/harvest-pipeline/pull/901"
QUARTERDECK_GH="$T/gh-stub" record_run harvest-pipeline surveyor CLEAN "no PR here"
QUARTERDECK_GH="$T/gh-stub" record_run harvest-pipeline shipwright PR "#900 → pull/901" "https://github.com/x/harvest-pipeline/pull/901"
ck "a review of a real PR is stamped with the revision it read" \
   "sha-of-the-moment sha-of-the-moment" \
   "$(jq -r '[.[0].sha, .[1].sha] | join(" ")' "$T/state/runs.json")"
ck "the same duty with no PR to ask about is not stamped with anything" \
   null "$(jq -r '.[2].sha // null' "$T/state/runs.json")"
ck "only the two judging duties are stamped, not every duty that touches a PR" \
   null "$(jq -r '.[3].sha // null' "$T/state/runs.json")"

# A run a mission started carries that mission's id the same way a fix run
# carries QUARTERDECK_FIX_RUN — the duty itself never has to know either exists.
QUARTERDECK_MISSION_RUN="m-abc123" record_run harvest-pipeline panel RULED "spec: worth doing"
ck "a run started for a mission is tagged with it" \
   "m-abc123" "$(jq -r '.[-1].mission' "$T/state/runs.json")"
record_run harvest-pipeline panel RULED "spec: an unrelated run"
ck "a run started outside any mission carries no tag" \
   null "$(jq -r '.[-1].mission // null' "$T/state/runs.json")"

# Several fixes can now run on one project at once, each on its own issue, so
# two of them finishing in the same instant and both calling record_run must
# not let one's row overwrite the other's — this is the race with_file_lock
# exists to close. Fired for real, from real background processes, not
# simulated: twenty of them racing on the exact same ledger file.
echo "[]" > "$T/state/runs.json"
for i in $(seq 1 20); do
  ( record_run harvest-pipeline shipwright PR "concurrent $i" ) &
done
wait
ck "twenty concurrent writers to one ledger lose nothing" 20 "$(jq length "$T/state/runs.json")"

# A duty running inside a fix pipeline carries that pipeline's tag on its own
# lock, the same way it carries it on every ledger row (QUARTERDECK_FIX_RUN) — so
# the dashboard can tell a fix's own card and its current step's agent card
# are one operation, whichever duty that step is. Run in a subshell: acquire_lock
# sets an EXIT trap of its own, which would otherwise clobber this script's.
fr=$( ( QUARTERDECK_FIX_RUN="p#3@999" acquire_lock "fixruntest1"
        cat "$QUARTERDECK_DIR/state/fixruntest1.lock/fixrun" ) 2>/dev/null )
ck "a lock taken inside a fix carries that fix's tag" "p#3@999" "$fr"
nofr=$( ( unset QUARTERDECK_FIX_RUN
          acquire_lock "fixruntest2"
          [ -f "$QUARTERDECK_DIR/state/fixruntest2.lock/fixrun" ] && echo yes || echo no ) 2>/dev/null )
ck "a lock taken outside any fix carries no such tag" "no" "$nofr"

echo
[ "$fails" = 0 ] && { echo "  all checks passed"; exit 0; }
echo "  $fails check(s) failed"; exit 1
