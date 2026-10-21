#!/bin/bash
# A suite that starts its own sandboxed project command cannot run inside the sandbox (a sandbox does not nest), so it skips there with one line.
# What is asserted: marker set and no way to nest gives one skip line and exit 0; marker set and nesting possible runs; marker unset runs, even when
# nesting would fail. The probe is replaced by ST_NEST_PROBE, so nothing real is sandboxed here.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"

probe() { # probe <marker or ""> <nest probe command> -> output in $PO, status in $PR; the sub-shell prints "RAN" when the suite body is reached
  PO=$(env -u QUARTERDECK_IN_SANDBOX ${1:+QUARTERDECK_IN_SANDBOX=$1} ST_NEST_PROBE="$2" bash -c 'source "$1/bin/selftest-lib.sh"; st_skip_if_nested_sandbox demo; echo RAN' _ "$REAL" 2>&1); PR=$?
}
probe 1 false
ck "marker set and no nested sandbox: one skip line naming the suite, exit 0, the body not reached" '[ "$PR" = 0 ] && [ "$(printf "%s\n" "$PO" | wc -l | tr -d " ")" = 1 ] && [[ "$PO" == "  skip  demo: "* ]] && [[ "$PO" != *RAN* ]]'
probe 1 true
ck "marker set and a sandbox can start: the body runs, no skip" '[ "$PR" = 0 ] && [ "$PO" = RAN ]'
probe "" false
ck "marker unset: the body runs even where nesting would fail (a skip never hides a failure outside the sandbox)" '[ "$PR" = 0 ] && [ "$PO" = RAN ]'
probe 0 false
ck "marker not 1: the body runs" '[ "$PR" = 0 ] && [ "$PO" = RAN ]'
ck "no real probe is used outside the sandbox: st_can_nest_sandbox is true with the marker unset" '(unset QUARTERDECK_IN_SANDBOX ST_NEST_PROBE; st_can_nest_sandbox)'
ck "the suites that nest a sandbox call the helper" 'for f in assayer caulker cycle diet pilot quartermaster tickets; do grep -q "^st_skip_if_nested_sandbox " "$REAL/bin/selftest-$f.sh" || exit 1; done; grep -q st_can_nest_sandbox "$REAL/bin/selftest-terraform.sh" "$REAL/bin/selftest-checks.sh" "$REAL/bin/selftest-prove-live.sh"'
st_done
