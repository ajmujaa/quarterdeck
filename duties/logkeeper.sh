#!/bin/bash
# logkeeper — keep the log of decisions.
#
# Turns a decision panel's ruling into a numbered record in the project's own repository, docs/decisions/NNNN-slug.md,
# opened as a pull request and never pushed to the trunk. The model reads the ruling and returns the parts of the
# record as data (RECORD_JSON); the HARNESS validates them, numbers the record, renders the file from a fixed template,
# checks that the file is the only thing in the commit, pushes a branch and opens the pull request. Without --apply it
# only prints the record it would propose.
#
# Each record has: what was chosen, the options rejected and what each costs, what is hard to reverse, and what would
# make it wrong. It also lists the Paths and Keywords the harness (bin/decisions.sh, bin/adr.py) matches a later review's
# diff and issue against, so the right records are put in front of every review duty.
#
#   qtdeck run <p> logkeeper --panel <decision-panel-id>            report only
#   qtdeck run <p> logkeeper --panel <decision-panel-id> --apply    branch decision/NNNN-slug and a pull request
#
# Contract:
#   RECORD_JSON: {"title","chosen","rejected":[{"option","cost"}],"hard_to_reverse":[],"wrong_if":[],"paths":[],"keywords":[]}
#   RESULT: RECORD <one line> | NEEDS_HUMAN <reason>
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text: once, a fix opened
# a pull request and then recorded itself as "taken". The group closes on the
# last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

PROJECT="${QUARTERDECK_PROJECT:?run me through: qtdeck run <project> logkeeper --panel <id>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/logkeeper-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
BASE=$(project_get "$PROJECT" default_branch main)
GH="${QUARTERDECK_GH:-gh}"
ADR_PY="${ADR_PY:-$QUARTERDECK_DIR/bin/adr.py}"
# Writing a record from a ruling is routine work, not a hard call.
export QUARTERDECK_MODEL_PERSONA="${QUARTERDECK_MODEL_LOGKEEPER:-claude-sonnet-5}"

APPLY=0 PANEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --panel) PANEL="${2:-}"; shift ;;
    *) die "logkeeper: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
[[ "$PANEL" =~ ^[A-Za-z0-9._-]+$ ]] || die "logkeeper needs a decision panel: --panel <id>"
TX="$QUARTERDECK_HOME/state/panels/$PANEL.json"
[ -f "$TX" ] || die "logkeeper: no panel called $PANEL"
[ "$(jq -r .project "$TX")" = "$PROJECT" ] || die "logkeeper: $PANEL belongs to another project"
[ "$(jq -r '.mode // .discipline // ""' "$TX")" = decision ] || die "logkeeper: $PANEL is not a decision panel"
[ "$(jq '.ruling | length' "$TX")" -gt 0 ] || die "logkeeper: $PANEL has not ruled yet"

acquire_lock "logkeeper-$PROJECT-$PANEL"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-logkeeper-$PANEL"
WT="$QUARTERDECK_HOME/workspace/wt-logkeeper-${PROJECT}-${PANEL}"
cleanup() { [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0; safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap 'cleanup; rm -rf "${QUARTERDECK_LOCK:-}"' EXIT

guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || log "fetch failed; using local $BASE"
# Already recorded? A record names the panel it came from, so asking twice does not write twice.
ref="origin/$BASE"; safe_git -C "$SOURCE_REPO_DIR" rev-parse -q --verify "$ref" >/dev/null || ref="$BASE"
if safe_git -C "$SOURCE_REPO_DIR" grep -qE "^Panel: $PANEL\$" "$ref" -- docs/decisions 2>/dev/null; then
  say "quarterdeck: $PANEL is already on record in docs/decisions — nothing to do"
  record_run "$PROJECT" logkeeper NOTHING "$PANEL is already recorded"
  exit 0
fi

subject=$(jq -r '.subject' "$TX"); headline=$(jq -r '.headline // ""' "$TX")
working_on "decision: $subject"
say "quarterdeck: logkeeper on $PANEL — $subject"

prompt="$(preamble "$PROJECT")

You are keeping the project's log of decisions. A decision panel has ruled on the question below. Write the record of
that decision from the ruling and nothing else: do not add options the panel did not weigh, and do not soften what it
said was expensive to reverse.

$({ printf 'THE QUESTION\n%s\n' "$subject"
  [ -n "$headline" ] && printf '\nTHE ANSWER OF THE PANEL, IN ONE LINE\n%s\n' "$headline"
  printf '\nTHE RULING (items the panel kept; each has an area such as decision, option rejected, consequence, risk, reversibility)\n'
  jq -r '.ruling[] | "- [\(.area // "?")] \(.title): \(.claim) Where: \(.where). Why it matters: \(.why). \(if (.note // "") != "" then "Ruling note: " + .note else "" end)"' "$TX"
} | untrusted "decision panel ruling")

Return the parts of the record as data. The harness renders the file, so do not write markdown headings.
- title: what was chosen, as a short phrase (at most 100 characters).
- chosen: what was chosen and why, in one to four sentences.
- rejected: every option that was weighed and turned down, each with what choosing it would have cost.
- hard_to_reverse: what is expensive or impossible to undo. Spend the care here. If the panel named nothing, say that plainly.
- wrong_if: what would have to become true for this decision to be wrong. If you cannot name that, say the panel did not.
- paths: the repository paths this decision governs (folders end with a slash). Used to show the record to later reviews.
- keywords: single words or short phrases a later issue or pull request would use when this decision bears on it.

End your reply with exactly these two lines and nothing after them:
RECORD_JSON: <one-line JSON {\"title\":\"\",\"chosen\":\"\",\"rejected\":[{\"option\":\"\",\"cost\":\"\"}],\"hard_to_reverse\":[\"\"],\"wrong_if\":[\"\"],\"paths\":[\"\"],\"keywords\":[\"\"]}>
RESULT: RECORD <one line>
  or, instead of both lines, the single line
RESULT: NEEDS_HUMAN <what is missing from the ruling>"

result=$(claude_run "$SOURCE_REPO_DIR" "$prompt" "Read,Grep,Glob"); rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" logkeeper ERROR "$PANEL run failed"; die "logkeeper run failed"; }
if grep -q '^RESULT: NEEDS_HUMAN' <<<"$result"; then
  why=$(grep -o '^RESULT: NEEDS_HUMAN.*' <<<"$result" | tail -1 | sed 's/^RESULT: NEEDS_HUMAN *//')
  say "  needs a person: $why"
  record_run "$PROJECT" logkeeper NEEDS_HUMAN "$PANEL — $why"
  exit 0
fi
raw=$(grep -o '^RECORD_JSON: .*' <<<"$result" | tail -1 | sed 's/^RECORD_JSON: //')
grep -q '^RESULT: RECORD' <<<"$result" || raw=""
[ -n "$raw" ] || { record_run "$PROJECT" logkeeper ERROR "$PANEL unparseable contract"; die "contract did not parse — nothing written"; }

# ---- the harness validates what came back; it does not trust the shape ----------------------------------------------------
# Every field is a plain string on one line; paths are relative and cannot climb; nothing in a field can forge a header line.
rec=$(jq -c '
  def one: if type == "string" then gsub("[\r\n\t]+"; " ") | gsub("  +"; " ") | sub("^ "; "") | sub(" $"; "") else empty end;
  if (type == "object") then
    {title: (.title | one), chosen: (.chosen | one),
     rejected: [(.rejected // [])[] | select(type == "object") | {option: (.option | one), cost: (.cost | one)}],
     hard_to_reverse: [(.hard_to_reverse // [])[] | one], wrong_if: [(.wrong_if // [])[] | one],
     paths: [(.paths // [])[] | one], keywords: [(.keywords // [])[] | one]}
  else empty end' <<<"$raw" 2>/dev/null) || rec=""
bad=""
if [ -z "$rec" ]; then bad="the record is not an object"
else
  jq -e '(.title | length) >= 1 and (.title | length) <= 100 and (.chosen | length) >= 1 and (.chosen | length) <= 1200
         and (.rejected | length) >= 1 and (.rejected | length) <= 8 and all(.rejected[]; (.option | length) >= 1 and (.option | length) <= 300 and (.cost | length) >= 1 and (.cost | length) <= 300)
         and (.hard_to_reverse | length) >= 1 and (.hard_to_reverse | length) <= 8 and all(.hard_to_reverse[]; length >= 1 and length <= 300)
         and (.wrong_if | length) >= 1 and (.wrong_if | length) <= 8 and all(.wrong_if[]; length >= 1 and length <= 300)
         and (.paths | length) <= 8 and all(.paths[]; test("^[A-Za-z0-9._/-]+$") and (contains("..") | not) and (startswith("/") | not))
         and (.keywords | length) <= 10 and all(.keywords[]; length >= 1 and length <= 40 and (contains(",") | not))' <<<"$rec" >/dev/null 2>&1 \
    || bad="a required part is missing or malformed (title, chosen, rejected, hard_to_reverse, wrong_if, paths, keywords)"
  [ -n "$bad" ] || [ "$(jq '(.paths | length) + (.keywords | length)' <<<"$rec")" -gt 0 ] \
    || bad="the record lists no paths and no keywords, so no later review could ever be shown it"
fi
if [ -n "$bad" ]; then
  say "  refused: $bad"
  record_run "$PROJECT" logkeeper ERROR "$PANEL — $bad"
  die "logkeeper: $bad — nothing written"
fi

# Already proposed? The same panel must not open a second pull request while the first waits.
guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin '+refs/heads/decision/*:refs/remotes/origin/decision/*' 2>>"$LOG_FILE" || true
for b in $(safe_git -C "$SOURCE_REPO_DIR" for-each-ref --format='%(refname)' refs/remotes/origin/decision 2>/dev/null); do
  if safe_git -C "$SOURCE_REPO_DIR" log -1 --format=%B "$b" 2>/dev/null | grep -qF "Quarterdeck panel $PANEL."; then
    say "quarterdeck: $PANEL is already proposed as ${b#refs/remotes/origin/} — merge or close that pull request first"
    record_run "$PROJECT" logkeeper ERROR "$PANEL — already proposed as ${b#refs/remotes/origin/}"
    exit 0
  fi
done

# ---- number it: after every record on the trunk and every record already proposed on a branch --------------------------
n_base=$(python3 "$ADR_PY" next --repo "$SOURCE_REPO_DIR" --base "$BASE") || die "logkeeper: could not number the record"
n_branch=$(safe_git -C "$SOURCE_REPO_DIR" ls-remote --heads origin 'decision/*' 2>/dev/null | sed -nE 's#.*refs/heads/decision/([0-9]{4})-.*#\1#p' | sort -n | tail -1)
num=$(printf '%04d' $(( 10#${n_base} > 10#${n_branch:-0} + 1 ? 10#${n_base} : 10#${n_branch:-0} + 1 )))
slug=$(jq -r '.title' <<<"$rec" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-40 | sed -E 's/-+$//')
[ -n "$slug" ] || slug=decision
FILE="docs/decisions/${num}-${slug}.md"
BR="decision/${num}-${slug}"

render() {
  jq -r --arg n "$num" --arg d "$(date +%Y-%m-%d)" --arg panel "$PANEL" '
    "# \($n). \(.title)\n\nStatus: accepted\nDate: \($d)\nPanel: \($panel)\nPaths: \(.paths | join(", "))\nKeywords: \(.keywords | join(", "))\n\n"
    + "## What was chosen\n\n\(.chosen)\n\n"
    + "## Options rejected, and what each costs\n\n\(.rejected | map("- **\(.option):** \(.cost)") | join("\n"))\n\n"
    + "## What is hard to reverse\n\n\(.hard_to_reverse | map("- " + .) | join("\n"))\n\n"
    + "## What would make this wrong\n\n\(.wrong_if | map("- " + .) | join("\n"))"' <<<"$rec"
}
say ""; say "── proposed: $FILE ──"; render >&2; say ""

if [ "$APPLY" != 1 ]; then
  say "quarterdeck: report only — pass --apply to open a pull request that adds this record"
  record_run "$PROJECT" logkeeper "DRY-RUN" "$PANEL — would propose $FILE"
  exit 0
fi

# ---- a branch from the trunk holding that one file, and a pull request; never a push to the trunk ---------------------------
safe_git -C "$SOURCE_REPO_DIR" ls-remote --exit-code --heads origin "$BR" >/dev/null 2>&1 \
  && { record_run "$PROJECT" logkeeper ERROR "$PANEL — $BR is already proposed"; die "logkeeper: $BR already exists; merge or close that pull request first"; }
worktree_at "$SOURCE_REPO_DIR" "$WT" "$ref" || die "could not create a worktree at $WT"
safe_git -C "$WT" checkout -q -B "$BR" 2>>"$LOG_FILE" || die "could not create branch $BR"
mkdir -p "$WT/docs/decisions"
render > "$WT/$FILE"
[ "$(safe_git -C "$WT" status --porcelain | wc -l | tr -d ' ')" = 1 ] && safe_git -C "$WT" status --porcelain | grep -qF "$FILE" \
  || { record_run "$PROJECT" logkeeper ERROR "$PANEL — the commit would hold more than $FILE"; die "logkeeper: the working tree holds more than the record; nothing committed"; }
safe_git -C "$WT" add -- "$FILE"
commit_identity "$PROJECT" "$WT" || die "no commit identity for $PROJECT: GitHub could not be asked for the account's no-reply address and the checkout has no user.email (set \"git\": {\"name\", \"email\"} in the registry)"
safe_git -C "$WT" ${COMMIT_ID[@]+"${COMMIT_ID[@]}"} commit -q -m "$(printf 'decision %s: %s\n\nRecord of the ruling of Quarterdeck panel %s.\n\nOpened by the Quarterdeck logkeeper.\n' "$num" "$(jq -r .title <<<"$rec")" "$PANEL")" || die "commit failed"
safe_git_guard 180 -C "$WT" push -q origin "HEAD:refs/heads/$BR" 2>>"$LOG_FILE" || { record_run "$PROJECT" logkeeper ERROR "$PANEL push failed"; die "push failed"; }
pr_body="Record of a decision, written from the ruling of Quarterdeck panel \`$PANEL\`.

**$(jq -r .title <<<"$rec")**

Merging this adds \`$FILE\` and nothing else. Once merged, the harness shows it to every review whose diff touches its paths or whose issue uses its keywords.

<sub>Quarterdeck logkeeper. The model wrote the parts of the record; the harness validated, numbered and rendered it. Nothing was merged.</sub>"
if url=$(gh_post 90 pr create -R "$REPO" --base "$BASE" --head "$BR" --title "decision $num: $(jq -r .title <<<"$rec")" --body "$pr_body" 2>>"$LOG_FILE"); then
  say "  ✓ $url"
  record_run "$PROJECT" logkeeper RECORD "$num → $url" "$url"
else
  record_run "$PROJECT" logkeeper ERROR "$PANEL pushed $BR but the pull request failed"
  die "pushed $BR but could not open the pull request"
fi

exit
}
