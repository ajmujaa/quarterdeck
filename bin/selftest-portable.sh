#!/bin/bash
# Quarterdeck's scripts must run on macOS as it ships: bash 3.2 and BSD userland. This greps every shell script for the forms that work
# on Linux and fail there, and fails if any appears (a comment is not code and is not checked). It is a reading check, not a run:
# each pattern below has already cost a failed test on a Mac.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fails=0
FILES=$(ls bin/*.sh bin/fix bin/cycle bin/quarterdeck bin/lib.sh duties/*.sh 2>/dev/null | grep -v '^bin/selftest-portable.sh$')
hits() { # hits <ERE> [<line must ALSO match ERE, or empty>] -> "file:line: text" for every code line that matches
  local f
  for f in $FILES; do
    grep -nE -e "$1" "$f" 2>/dev/null | grep -vE '^[0-9]+:[[:space:]]*#' | sed "s#^#$f:#" | { if [ -n "${2:-}" ]; then grep -vE -e "$2"; else cat; fi; }
  done
}
ck() { # ck <label> <ERE> [<ERE of lines that are fine>]
  local h; h=$(hits "$2" "${3:-}")
  if [ -z "$h" ]; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; printf '%s\n' "$h" | head -5 | sed 's/^/          /'; fails=$((fails+1)); fi
}
ck 'no "${x:-{\}}": bash 3.2 expands it to the string {\} (use a helper)'      ':-\{\\\}\}'
ck 'no $BASHPID: it is bash 4 only (use BASH_SUBSHELL)'                         'BASHPID'
ck 'no sed -i: BSD sed wants a suffix argument (write through a temp file)'     'sed( +-[A-Za-z]+)* +-[A-Za-z]*i'
ck 'no sed I flag: GNU only (use python, or a character class)'                 's(/|#)[^/#]*(/|#)[^/#]*(/|#)[gp]*I[gp]*([;'"'"'" ]|$)'
ck 'no date -d or --date: BSD date has neither (compute the date in python)'    'date( +-u)? +(-d|--date)'
ck 'no date +%N: BSD date prints %N literally'                                  '%N|%%N'
ck 'no grep -P: BSD grep has no PCRE'                                           'grep +-[A-Za-z]*P'
ck 'no stat -c without a stat -f fallback'                                      'stat +-c'  'stat +-f'
ck 'no readlink -f'                                                             'readlink +-f'
ck 'no xargs -r'                                                                'xargs +-[A-Za-z]*r'
ck 'no timeout command (use guard)'                                             '(^|[;&|(`]|[$][(])[[:space:]]*timeout +[0-9]'
ck 'no setsid, flock, or mktemp --tmpdir'                                       '(^|[[:space:];|&(])(setsid|flock)( |$)|mktemp +--'
ck 'no ${var,,} or ${var^^}: bash 4 only'                                       '[$][{][A-Za-z_0-9]+(,,|[\^][\^])'
ck 'no declare -A, mapfile, readarray, local -n, [[ -v ]], &>>, |&: bash 4 only' 'declare +-A|(^|[[:space:];])(mapfile|readarray)( |$)|local +-n |\[\[ +-v |&>>|[|]&'
ck 'no head -0 or head -n -N: BSD head rejects them'                            'head +-0|head +-n +-[0-9]'
ck 'no \b, \s or \d in a regex handed to git grep, grep or sed (not portable)'  '(git( +-C +[^ ]+)? +grep|grep +-[A-Za-z]*E|sed +-E)[^|]*\\[bsd]'
ck 'no immediate process check after a run: wait with st_gone'                  'pgrep +-f' 'st_gone\(\)|pgrep -f "[$]1" >/dev/null 2>&1 [|][|] return 0'
echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
