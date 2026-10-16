#!/bin/bash
# joiner — review the interface: accessibility, states, responsive and PWA behaviour.
#
# A ship's joiner does the interior fit-out — the surfaces people actually touch
# and live with. This duty reads UI source and reports what is wrong with the
# experience, judged against a fixed rubric rather than taste.
#
# The rubric it judges against lives in crew/joiner.md, so this duty and the
# joiner's seat on the design panel are the same brief rather than two copies
# that drift. It writes a findings document and nothing else: no GitHub access.
# Hand its output to the foreman to get issues:
#   quarterdeck run <p> joiner
#   quarterdeck run <p> foreman --from workspace/<p>-joiner-<date>.md --apply
#
# Contract:
#   FINDINGS_JSON: [{"area","severity","title","what","where","why","fix"}, ...]
#   RESULT: FINDINGS <count> | CLEAN
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> joiner}"
WORKDIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/joiner-$PROJECT.log"

SCOPE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --path) SCOPE="${2:-}"; shift ;;
    --apply) : ;;   # accepted and ignored: this duty only ever writes a local file
    *) die "joiner: unknown argument '$1'" ;;
  esac
  shift
done

acquire_lock "joiner-$PROJECT"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$(project_get "$PROJECT" repo)")-joiner-$(date +%s)"

OUT="$QUARTERDECK_HOME/workspace/${PROJECT}-joiner-$(date +%Y-%m-%d).md"

working_on "interface: ${SCOPE:-everything}"
say "quarterdeck: joiner reading ${SCOPE:-the interface} in $PROJECT"

prompt="$(preamble "$PROJECT")

$(crew_role joiner)

--- THIS RUN ---

Review this project's user interface as source, working the rubric above. You
cannot run the app, so judge what the code necessarily produces, and say so
plainly when something needs a device to confirm rather than asserting it.

${SCOPE:+Restrict yourself to: $SCOPE}

End your reply with exactly these two lines and nothing after them:
FINDINGS_JSON: <one-line JSON array. Each item: {\"area\":\"one of operability|touch|states|responsive|formatting|copy|promise\",\"severity\":\"critical|major|minor\",\"title\":\"one short claim\",\"what\":\"what the user experiences\",\"where\":\"file:line, or file\",\"why\":\"why it matters\",\"fix\":\"the concrete change\"}>
RESULT: FINDINGS <count>
  or
RESULT: CLEAN"

result=$(claude_run "$WORKDIR" "$prompt"); rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" joiner ERROR "run failed"; die "joiner run failed"; }

findings=$(grep -o 'FINDINGS_JSON: .*' <<<"$result" | tail -1 | sed 's/^FINDINGS_JSON: //')
verdict=$(grep -Eo '^RESULT: (FINDINGS [0-9]+|CLEAN)' <<<"$result" | tail -1)
jq -e 'type == "array"' <<<"$findings" >/dev/null 2>&1 || findings=""

if [ -z "$findings" ] || [ -z "$verdict" ]; then
  log "$PROJECT: contract did not parse — logs/runs/$QUARTERDECK_RUN_ID.json"
  record_run "$PROJECT" joiner ERROR "unparseable contract"
  die "contract did not parse — nothing written (see logs/runs/$QUARTERDECK_RUN_ID.json)"
fi

n=$(jq 'length' <<<"$findings")
if [ "$n" = 0 ]; then
  say "quarterdeck: joiner found nothing in $PROJECT"
  record_run "$PROJECT" joiner CLEAN "no interface findings"
  exit 0
fi

# The harness renders the document. The model returns structured data only, so a
# formatting change here never needs the prompt touched.
{
  echo "# ${PROJECT} — interface review, $(date +%Y-%m-%d)"
  echo
  echo "Produced by Quarterdeck's joiner from source, without running the app."
  [ -n "$SCOPE" ] && { echo; echo "Scope: \`$SCOPE\`"; }
  echo
  jq -r '
    group_by(.severity)
    | sort_by(if .[0].severity=="critical" then 0 elif .[0].severity=="major" then 1 else 2 end)
    | .[] | "## " + (.[0].severity | ascii_upcase) + "\n\n" + (
        map("### \(.title)\n\n**What happens.** \(.what)\n\n**Where.** `\(.where)`\n\n**Why it matters.** \(.why)\n\n**Fix.** \(.fix)\n\n_area: \(.area)_")
        | join("\n---\n\n")
      )' <<<"$findings"
} > "$OUT"

say ""
jq -r '.[] | "  [\(.severity)] \(.area) — \(.title)"' <<<"$findings" >&2
say ""
say "quarterdeck: $n finding(s) written to"
say "  $OUT"
say ""
say "  file them with:"
say "  quarterdeck run $PROJECT foreman --from \"$OUT\" --apply"

record_run "$PROJECT" joiner "FINDINGS" "$n written to $(basename "$OUT")"

exit
}
