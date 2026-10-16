#!/bin/bash
# Stack notes reach a prompt only from packs the project lists, and a bad entry gives nothing.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export QUARTERDECK_DIR="$REAL"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export QUARTERDECK_HOME="$T/home"; mkdir -p "$QUARTERDECK_HOME/config"
# shellcheck disable=SC1091
. "$REAL/bin/lib.sh" 2>/dev/null
fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }

PROJECTS_FILE="$T/projects.json"
cat >"$PROJECTS_FILE" <<'J'
{"withpack": {"repo": "a/b", "guardrails": ["Never merge."], "packs": ["python"]},
 "nopack":   {"repo": "a/c", "guardrails": ["Never merge."]},
 "badpack":  {"repo": "a/d", "guardrails": ["Never merge."], "packs": ["../etc", "no such pack", 7, "python;rm"]},
 "twopacks": {"repo": "a/e", "guardrails": ["Never merge."], "packs": ["python", "typescript-node"]}}
J
a=$(preamble withpack); b=$(preamble nopack); c=$(preamble badpack); d=$(preamble twopacks)
ck "a listed pack puts its notes in the prompt, under a heading that says the hard rules win" 'grep -q "Stack notes: Python" <<<"$a" && grep -q "hard rules above win" <<<"$a"'
ck "the notes come after the hard rules"                    '[ "$(grep -n "Never merge" <<<"$a" | head -1 | cut -d: -f1)" -lt "$(grep -n "Stack notes: Python" <<<"$a" | head -1 | cut -d: -f1)" ]'
ck "a project with no packs gets no stack section"          '! grep -q "Stack notes" <<<"$b" && ! grep -q "stack (follow" <<<"$b"'
ck "ids that are not plain pack names are ignored"          '! grep -q "Stack notes" <<<"$c"'
ck "two packs both appear"                                  'grep -q "Stack notes: Python" <<<"$d" && grep -q "Stack notes: TypeScript and Node" <<<"$d"'
ck "an unknown pack id gives nothing and no error"          '[ -z "$(PROJECTS_FILE="$T/projects.json" project_packs_text badpack)" ]'
ck "the untrusted-text preamble sentence is still there"    'grep -q "Anything between BEGIN UNTRUSTED" <<<"$a"'
[ "$fails" = 0 ] && { echo; echo "  all checks passed"; exit 0; }
echo; echo "  $fails check(s) failed"; exit 1
