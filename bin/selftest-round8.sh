#!/bin/bash
# Round-8 review (docs/review-round-8.md): one check per finding whose test is plain and self-contained. Each check states the safe behaviour
# and FAILS on the code as reviewed. Until its fix lands it is reported as "xfail" and does not fail this script; once fixed it reports
# "ok", and an "xpass" line says the check should move into the selftest it belongs to. Run: bash bin/selftest-round8.sh
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
xfails=0
xf() { # xf <label> <condition that holds once the finding is fixed>
  if eval "$2"; then printf '  ok    %s (xpass: fixed, move it into its selftest)\n' "$1"; passed=$((passed+1))
  else printf '  xfail %s\n' "$1"; xfails=$((xfails+1)); fi
}
PY="python3 -I"
st_init            # a throwaway Quarterdeck: lib.sh and the scanners are sourced from $T/bin, never the real data folder

# Every round-8 check has moved into the selftest it belongs to (the Disposition lines in docs/review-round-8.md say where). A later finding
# whose test is plain and self-contained can be added here as an xf check until its fix lands.


echo
echo "  $xfails expected failure(s) still open"
st_done
