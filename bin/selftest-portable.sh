#!/bin/bash
# Quarterdeck's scripts must run on macOS as it ships: bash 3.2 and BSD userland. This greps every shell script for the forms that work
# on Linux and fail there, and fails if any appears (a comment is not code and is not checked). It is a reading check, not a run:
# each pattern below has already cost a failed test on a Mac.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fails=0
FILES=$(ls bin/*.sh bin/fix bin/cycle bin/qtdeck bin/lib.sh duties/*.sh providers/*.sh 2>/dev/null | grep -v '^bin/selftest-portable.sh$')
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
# python files: every one must compile on the oldest supported Python (README says 3.10). Before 3.12 an f-string expression may not hold a backslash
# or the quote that encloses it; a newer interpreter accepts both, so look for them in the source too (attach.py broke 3.10 and 3.11 this way).
pyhits=$(python3 - bin/*.py bin/integrations/*.py <<'PY'
import ast, sys
for f in sys.argv[1:]:
    src = open(f, encoding="utf-8").read()
    try:
        tree = ast.parse(src, f)
    except SyntaxError as e:
        print(f"{f}:{e.lineno}: {e.msg}"); continue
    for js in (n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)):
        whole = ast.get_source_segment(src, js) or ""
        body = whole.lstrip("rbfRBF")
        q = body[:1]
        for fv in (n for n in ast.walk(js) if isinstance(n, ast.FormattedValue)):
            seg = ast.get_source_segment(src, fv.value) or ""
            if "\\" in seg or (q and q in seg and not isinstance(fv.value, ast.Constant)):
                print(f"{f}:{js.lineno}: f-string expression holds a backslash or its own quote (Python before 3.12 rejects it)"); break
PY
)
if [ -z "$pyhits" ]; then printf '  ok    %s\n' "every bin/*.py compiles, and no f-string expression holds a backslash or its own quote (Python 3.10 and 3.11)"
else printf '  FAIL  %s\n' "a python file would not compile on Python before 3.12"; printf '%s\n' "$pyhits" | head -5 | sed 's/^/          /'; fails=$((fails+1)); fi
echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
