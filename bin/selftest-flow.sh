#!/bin/bash
# The whole flow for a newcomer, end to end, with no model and no network: attach a small React project, read what the scan says of its stack,
# draft tickets, build one on a local branch from the command line, then do the same through the dashboard's API and its Missions page.
# The project is fixtures/sample-react (a Vite + React todo app, committed as plain files; the test copies it to a temp folder and runs `git init`
# there). The model is the fake provider (providers/fake.sh); a hook plays the builder that edits the throwaway worktree; `gh` is the stand-in
# behind QUARTERDECK_GH, which records every call (the flow must make none). The data folder is a temp folder with the .quarterdeck-home marker and
# HOME is a temp folder, so nothing real is read or written. No GitHub account or repository is made, and GitHub is never called.
#
# The verify command is `node --test`, not the project's own `npm test`: `npm test` runs Vitest, and Vitest needs an install from the registry,
# which this suite never does. src/todos.test.mjs is written for Node's own test runner so the project's logic can be verified offline.
#
# Run it on its own: bash bin/selftest-flow.sh. QD_KEEP=1 keeps the throwaway folder. A later part can be added as one more function below.
#
#   part 1  attach          dry run (the stack sentence, verify/build/lint, the off list, nothing changed), then --apply, the registry entry, the record
#   part 2  tickets         qtdeck repo, ticket new (a draft files nothing), --apply saves two local tickets, no gh call at all, ticket list
#   part 3  cycle (CLI)     qtdeck cycle --ticket: purser, dev panel, shipwright; the branch, its one commit, the verify result, the record, --status, --resume
#   part 4  dashboard       the same through the API (draft, file, cycle start, the mission) and, where a browser starts, the Missions page
#   part 5  negative        a project with a repo is never filed locally unless asked; a credential in a request; no such ticket; --ticket with --issue
ST_PROVIDER=fake
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init planner purser panel shipwright
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
mkdir -p "$T/home" "$T/proj" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" QUARTERDECK_PROJECT_ROOTS="$T/proj"
export QUARTERDECK_HOME="$T" REAL PYTHONDONTWRITEBYTECODE=1; touch "$T/.quarterdeck-home"
export QUARTERDECK_DAILY_BUDGET=100 QUARTERDECK_CALL_BUDGET=0.01 QUARTERDECK_CYCLE_BUDGET=15
QD="bash $T/bin/qtdeck"
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT
echo '[]' > "$T/ghdata/issue-list.json"

mkproj() { # mkproj <name>: a copy of the fixture with its own git repository, one commit on main, and no remote
  cp -R "$REAL/fixtures/sample-react" "$T/proj/$1"
  git init -q -b main "$T/proj/$1" 2>/dev/null || { git init -q "$T/proj/$1"; git -C "$T/proj/$1" checkout -q -b main; }
  git -C "$T/proj/$1" add -A; git -C "$T/proj/$1" commit -q -m "initial todo app"
}
reg() { jq -r "$1" "$T/config/projects.json" 2>/dev/null; }
store() { jq -r "$2" "$T/state/tickets/$1.json" 2>/dev/null; }                      # store <project> <jq filter>
ghn() { local n; n=$(grep -cE "$1" "$T/gh-calls" 2>/dev/null); echo "${n:-0}"; }    # ghn <regex>: how many recorded gh calls match
nogh() { [ ! -s "$T/gh-calls" ]; }                                                   # the gh stand-in was never called, not even to read
files_in() { git -C "$1" diff --name-only "main...$2" | sort | tr '\n' ' '; }       # files_in <checkout> <branch>
mode() { python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$1"; }
datasnap() { (cd "$T" && find config state -type f 2>/dev/null | sort | while IFS= read -r f; do cksum "$f"; done); }
setreg() { # setreg <jq assignment>: edit the 0600 registry the way a person would, and keep it 0600
  jq "$1" "$T/config/projects.json" > "$T/c.t" && chmod 600 "$T/c.t" && mv "$T/c.t" "$T/config/projects.json"
}
pyck() { # pyck <file.py>: each "ok ..." / "FAIL ..." line of its output is one check; a block that crashes is one failed check
  local line n=0
  python3 "$1" > "$T/py.out" 2> "$T/py.err"; local prc=$?
  while IFS= read -r line; do
    case "$line" in
      ok\ *)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)); n=$((n + 1)) ;;
      FAIL\ *) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)); n=$((n + 1)) ;;
    esac
  done < "$T/py.out"
  if [ "$prc" != 0 ] || [ "$n" = 0 ]; then printf '  FAIL  a python block crashed (exit %s): %s\n' "$prc" "$(tail -3 "$T/py.err" | tr '\n' ' ')"; fails=$((fails + 1)); fi
}

# What the stand-in model says. The planner's reply is one TICKETS_JSON of two tickets; the crew's replies answer the purser, the dev panel and the
# shipwright. The ruling names no function, so the hook below picks its edit from the ticket text alone.
TICKETS_REPLY='TICKETS_JSON: {"tickets":[{"title":"Clear the completed todos","body":"Add a clearCompleted function to src/todos.js that removes every item that is done, with a test.","acceptance":["clearCompleted of a list with one done item returns the list without it"]},{"title":"Show a summary line","body":"Add a summary function to src/todos.js that says how many items are left, for example 2 left, with a test.","acceptance":["summary of two open items says 2 left"]}]}
RESULT: DRAFTED 2 tickets'
planner_replies() { st_noreplies; st_reply default "$TICKETS_REPLY"; }
crew_replies() { # crew_replies [<the shipwright's reply>]
  st_noreplies
  st_reply 'REQUIREMENTS_JSON' 'REQUIREMENTS_JSON: {"summary":"One small change to the todo logic","requirements":[{"what":"The new function works and has a test","accept":"node --test passes with the new test"}],"out_of_scope":["the page"]}
RESULT: READY 1 requirement(s)'
  st_reply 'RULING_JSON' 'HEADLINE: one change
RULING_JSON: [{"kind":"change","tier":"routine","area":"logic","severity":"major","title":"Add the function the ticket asks for","claim":"it is missing","where":"src/todos.js","why":"the ticket asks for it","action":"add it to src/todos.js and a test to src/todos.test.mjs","support":["shipwright"],"overruled":[],"note":""}]
RESULT: RULED 1'
  st_reply 'STANCES_JSON' 'STANCES_JSON: [{"id":"shipwright-1","stance":"agree","note":"n"}]
RESULT: STANCES 1'
  st_reply 'Build this one ticket' "${1:-RESULT: FIXED the todo logic has the new function and a test}"
  st_reply default 'ITEMS_JSON: [{"area":"logic","severity":"major","title":"Add the function the ticket asks for","claim":"it is missing","where":"src/todos.js","why":"the ticket asks for it","action":"add it"}]
RESULT: ITEMS 1'
}
# The builder: it runs in the throwaway worktree after the shipwright's model call and does what the ticket asks, by editing src/todos.js and its test.
cat > "$T/claude-hook" <<'HOOK'
#!/bin/bash
case "$1" in
  *"Build this one ticket"*)
    case "$1" in
      *clearCompleted*)
        cat >> src/todos.js <<'JS'

export function clearCompleted(todos) {
  return todos.filter((t) => !t.done);
}
JS
        cat >> src/todos.test.mjs <<'JS'

import { clearCompleted } from "./todos.js";

test("clearCompleted drops the done items and keeps the open ones", () => {
  const list = toggleTodo(addTodo(addTodo([], "a"), "b"), 1);
  assert.deepEqual(clearCompleted(list).map((t) => t.text), ["b"]);
});
JS
        ;;
      *"Add a summary function"*)
        cat >> src/todos.js <<'JS'

export function summary(todos) {
  return `${remaining(todos)} left`;
}
JS
        cat >> src/todos.test.mjs <<'JS'

import { summary } from "./todos.js";

test("summary says how many are left", () => {
  assert.equal(summary(addTodo(addTodo([], "a"), "b")), "2 left");
});
JS
        ;;
    esac ;;
esac
HOOK
chmod +x "$T/claude-hook"

cyc() { OUT=$($QD cycle "$@" 2>&1); RC=$?; ID=$(ls -t "$T/state/cycles"/cyc-*.json 2>/dev/null | head -1 | xargs -n1 basename 2>/dev/null | sed 's/\.json$//'); REC="$T/state/cycles/$ID.json"; }
stg() { jq -r --arg id "$1" ".stages[] | select(.id == \$id) | $2" "$REC"; }
calls_n() { local n; n=$(grep -c . "$T/claude-calls" 2>/dev/null); echo "${n:-0}"; }

P=$T/proj/sample-react

# ---- part 1. attach -------------------------------------------------------------------------------------------------------------------------------
part1_attach() {
  echo "part 1: attach the sample React project"
  mkproj sample-react
  ck "the fixture has no README and no architecture document on purpose (a later part drafts the missing docs)" '[ ! -e "$P/README.md" ] && [ -z "$(ls "$P" | grep -i -E "^(readme|architecture)")" ] && [ -f "$P/package-lock.json" ] && [ ! -d "$P/node_modules" ]'
  $QD projects >/dev/null 2>&1                         # the first command of a new install makes the data folder's files; the snapshot starts after it
  local before after; before=$(datasnap)
  OUT=$($QD attach "$P" 2>&1); RC=$?; after=$(datasnap)
  ck "dry run: the scan names the stack in one sentence" '[ "$RC" = 0 ] && grep -qF "React 18 with Vite, tests by Vitest, lint by ESLint, package manager npm" <<<"$OUT"'
  ck "  it shows the verify, build and lint commands it proposes, each with where it came from" 'grep -qE "verify +npm test +\(package.json scripts.test\)" <<<"$OUT" && grep -qE "build +npm run build" <<<"$OUT" && grep -qE "lint +npm run lint" <<<"$OUT"'
  ck "  it lists the duties that also fit this stack as OFF, joiner among them, and joiner is not among the duties that are on" 'grep -qE "also fit this stack \(off\):.*joiner" <<<"$OUT" && ! grep -E "^ +duties " <<<"$OUT" | grep -q joiner'
  ck "  it says nothing was changed, and the data folder is byte for byte the same: no registry entry, no profile" 'grep -q "nothing was changed" <<<"$OUT" && [ "$before" = "$after" ] && [ "$(reg "has(\"sample-react\")")" = false ] && [ ! -e "$T/state/profiles/sample-react.json" ]'
  ck "  and the next step is the same command with --apply" 'grep -qF "next: qtdeck attach $P --apply" <<<"$OUT"'
  # npm test is Vitest and Vitest needs an install from the registry; node --test runs src/todos.test.mjs with nothing installed, so it is the offline verify command
  OUT=$($QD attach "$P" --verify "node --test" --apply 2>&1); RC=$?
  ck "--apply with --verify \"node --test\" registers the project and says so" '[ "$RC" = 0 ] && grep -q "registered .sample-react. in your data folder" <<<"$OUT" && grep -qE "verify +node --test +\(set with --verify\)" <<<"$OUT"'
  ck "  the registry entry: verify, build and lint, and no repo" '[ "$(reg ".\"sample-react\".verify")" = "node --test" ] && [ "$(reg ".\"sample-react\".build")" = "npm run build" ] && [ "$(reg ".\"sample-react\".lint")" = "npm run lint" ] && [ "$(reg ".\"sample-react\".repo")" = "" ] && [ "$(reg ".\"sample-react\".default_branch")" = main ]'
  ck "  the duties are the read-only ones plus the shipwright (a verify command exists); nothing suggested is on" '[ "$(reg ".\"sample-react\".duties | join(\" \")")" = "surveyor foreman inspector shipwright" ]'
  ck "  the protected paths include package.json and the lockfile (the crew may not change them)" '[ "$(reg ".\"sample-react\".forbidden_paths | index(\"package.json\") != null and index(\"package-lock.json\") != null")" = true ]'
  ck "  the record of the scan is in the data folder (state/profiles), owner-only, and names the stack" '[ -s "$T/state/profiles/sample-react.json" ] && [ "$(mode "$T/state/profiles/sample-react.json")" = 0o600 ] && grep -q "Vitest" "$T/state/profiles/sample-react.json"'
  ck "  the registry file is 0600, and the project folder itself was not written to" '[ "$(mode "$T/config/projects.json")" = 0o600 ] && [ -z "$(git -C "$P" status --porcelain)" ]'
  ck "  the message says local tickets still work, points at the repo options, and also names the way to stay on this computer" 'grep -q "local tickets still work" <<<"$OUT" && grep -q "qtdeck repo sample-react" <<<"$OUT" && grep -qF "or keep it on this computer: qtdeck ticket new sample-react" <<<"$OUT"'
  # a cycle spends money, so it is never on by default: the owner opts in by editing the registry (there is no command and no page for this yet)
  setreg '.["sample-react"].cycle = true'
  ck "the owner opts the project in to cycles by editing the registry (cycle: true), and the file stays 0600" '[ "$(reg ".\"sample-react\".cycle")" = true ] && [ "$(mode "$T/config/projects.json")" = 0o600 ]'
}

# ---- part 2. tickets ------------------------------------------------------------------------------------------------------------------------------
part2_tickets() {
  echo "part 2: tickets from a plain request"
  OUT=$($QD repo sample-react 2>&1); RC=$?
  ck "qtdeck repo <project> prints the one sentence and then the four options in order" '[ "$RC" = 0 ] && grep -qF "sample-react has no GitHub repo, so the crew cannot open pull requests yet; local tickets still work." <<<"$OUT" && [ "$(grep -E "^  \([abcd]\) " <<<"$OUT" | sed -E "s/^  \((.)\).*/\1/" | tr -d "\n")" = abcd ]'
  ck "  the options are named in plain words, and (c) says a person has to do the sign-up" 'grep -q "(a) I already have a GitHub repo" <<<"$OUT" && grep -q "(b) I have a GitHub account" <<<"$OUT" && grep -q "(c) I have no GitHub account" <<<"$OUT" && grep -q "(d) Not now" <<<"$OUT" && grep -q "A person has to do this" <<<"$OUT"'
  ck "  asking for the options changes nothing and calls no gh" 'nogh && [ "$(reg ".\"sample-react\".repo")" = "" ]'
  planner_replies
  OUT=$($QD ticket new sample-react "Let me clear the finished todos and show how many are left" 2>&1); RC=$?
  ck "ticket new, report only: the draft shows two tickets with their acceptance checks, and says nothing was filed" '[ "$RC" = 0 ] && grep -q "1. Clear the completed todos" <<<"$OUT" && grep -q "2. Show a summary line" <<<"$OUT" && grep -q "Acceptance checks:" <<<"$OUT" && grep -q "draft d1 saved; nothing was filed" <<<"$OUT"'
  ck "  the draft is kept (d1), no ticket exists yet, and the stand-in gh was not called" '[ "$(store sample-react ".drafts | length")" = 1 ] && [ "$(store sample-react ".drafts[0].id")" = d1 ] && [ "$(store sample-react ".tickets | length")" = 0 ] && nogh'
  ck "  the fake provider answered (the claude binary never ran), reading the project with Read, Grep and Glob only" '[ ! -e "$T/claude-was-run" ] && [ "$(jq -r .tools "$T/claude-calls" | head -1)" = "Read,Grep,Glob" ]'
  OUT=$($QD ticket new sample-react "Let me clear the finished todos and show how many are left" --apply 2>&1); RC=$?
  ck "ticket new --apply on a project with no repo saves two LOCAL tickets on this computer, and says there is no repo" '[ "$RC" = 0 ] && grep -q "no GitHub repo: saved as local tickets on this computer" <<<"$OUT" && [ "$(store sample-react ".tickets | length")" = 2 ] && [ "$(store sample-react "[.tickets[].source] | unique | join(\",\")")" = local ] && [ "$(store sample-react "[.tickets[].issue] | map(tostring) | unique | join(\",\")")" = null ]'
  ck "  it ends by saying nothing went to GitHub and what to run next" 'grep -q "nothing went to GitHub" <<<"$OUT" && grep -q "next: qtdeck cycle sample-react --ticket 1" <<<"$OUT"'
  ck "  the gh stand-in log shows no call at all: no issue, no pr, no repo, not even a read or a sign-in check" 'nogh'
  OUT=$($QD ticket list sample-react 2>&1)
  ck "ticket list shows both tickets, open and local, and the draft that is still waiting" 'grep -qE "^ +1 +open +local +Clear the completed todos" <<<"$OUT" && grep -qE "^ +2 +open +local +Show a summary line" <<<"$OUT" && grep -q "d1" <<<"$OUT" && grep -q "nothing filed" <<<"$OUT"'
  OUT=$($QD ticket show sample-react 1 2>&1)
  ck "ticket show 1 prints the ticket, its acceptance check, and the command that builds it" 'grep -q "clearCompleted" <<<"$OUT" && grep -q "clearCompleted of a list with one done item" <<<"$OUT" && grep -q "next: qtdeck cycle sample-react --ticket 1" <<<"$OUT"'
  $QD ticket remove sample-react d1 >/dev/null 2>&1
  ck "the leftover draft is thrown away with ticket remove, and the two tickets stay" '[ "$(store sample-react ".drafts | length")" = 0 ] && [ "$(store sample-react ".tickets | length")" = 2 ]'
  OUT=$($QD ticket new sample-react "the same request again" --apply 2>&1); RC=$?
  ck "asking again for the same thing adds no duplicate, and each line says the ticket was already on the list" '[ "$RC" = 0 ] && [ "$(store sample-react ".tickets | length")" = 2 ] && [ "$(grep -c "already on the list, not added again" <<<"$OUT")" = 2 ]'
}

# ---- part 3. a cycle from a ticket on the command line --------------------------------------------------------------------------------------------
part3_cycle_cli() {
  echo "part 3: qtdeck cycle --ticket, on the command line"
  crew_replies
  : > "$T/claude-calls"; rm -f "$T/gh-calls"; echo '[]' > "$T/state/runs.json"
  # attach turned on the read-only duties and the shipwright only: a ticket also needs the purser and the dev panel, and the cycle says so up front
  cyc sample-react --ticket 1 --apply
  ck "a ticket cycle on a project whose duties lack the purser and the panel is refused up front, naming both and where to add them; nothing ran" '[ "$RC" != 0 ] && grep -q "these are not enabled for .sample-react.: purser panel" <<<"$OUT" && grep -qF "\"duties\"" <<<"$OUT" && [ -z "$ID" ] && [ "$(calls_n)" = 0 ]'
  setreg '.["sample-react"].duties += ["purser", "panel"]'
  cyc sample-react --ticket 1
  ck "without --apply it only reports: the purser and the dev panel are previewed, nothing is written, no branch exists, no gh call" '[ "$RC" = 0 ] && [ "$(jq -r .status "$REC")" = report-only ] && grep -q "Add --apply" <<<"$OUT" && [ -z "$(git -C "$P" branch --list "ticket/*")" ] && [ "$(store sample-react ".tickets[0].status")" = open ] && nogh'
  : > "$T/claude-calls"
  cyc sample-react --ticket 1 --apply
  BR=$(store sample-react ".tickets[0].branch")
  ck "cycle --ticket 1 --apply runs the purser, the dev panel and the shipwright in that order, then stops for a person: awaiting-review" '[ "$RC" = 0 ] && [ "$(jq -r .status "$REC")" = awaiting-review ] && [ "$(jq -r "[.stages[] | select(.state == \"done\") | .id] | join(\" \")" "$REC")" = "purser panel shipwright" ] && [ "$(stg human .state)" = waiting ]'
  ck "  the stand-in model answered every stage; the real claude binary never ran" '[ ! -e "$T/claude-was-run" ] && [ "$(calls_n)" -ge 4 ]'
  ck "  the local branch ticket/1-<slug> exists in the temp checkout with exactly one commit on top of main" '[ "$BR" = ticket/1-clear-the-completed-todos ] && [ "$(git -C "$P" rev-list --count main..$BR)" = 1 ] && [ "$(git -C "$P" log -1 --format=%s $BR)" = "build: Clear the completed todos" ]'
  ck "  the branch holds the change the stand-in builder made: clearCompleted in src/todos.js and a test for it" 'git -C "$P" show $BR:src/todos.js | grep -q "export function clearCompleted" && git -C "$P" show $BR:src/todos.test.mjs | grep -q "clearCompleted drops the done items"'
  ck "  git diff main...<branch> touches only src/todos.js and src/todos.test.mjs: not package.json, not the lockfile" '[ "$(files_in "$P" $BR)" = "src/todos.js src/todos.test.mjs " ] && ! git -C "$P" diff --name-only main...$BR | grep -qE "package(-lock)?\.json"'
  ck "  the project checkout is left alone: still on main, clean, with no worktree left behind" '[ "$(git -C "$P" rev-parse --abbrev-ref HEAD)" = main ] && [ -z "$(git -C "$P" status --porcelain)" ] && [ -z "$(find "$T/workspace" -maxdepth 1 -type d -name "wt-*")" ] && [ "$(git -C "$P" worktree list | wc -l | tr -d " ")" = 1 ]'
  ck "  no remote exists and nothing was pushed (no remote at all, no remote-tracking ref)" '[ -z "$(git -C "$P" remote)" ] && [ -z "$(git -C "$P" for-each-ref refs/remotes)" ]'
  ck "  the gh stand-in log has no issue, pr or repo call (it is empty)" '[ "$(ghn "^gh (issue|pr|repo)")" = 0 ] && nogh'
  ck "  the verify command ran before and after the build, and its result is in the shipwright detail: checks: verify exit 0" 'grep -q "baselining local checks" <<<"$OUT" && grep -q "re-running local checks" <<<"$OUT" && grep -qF "checks: verify exit 0" <<<"$(stg shipwright .detail)" && [ "$(stg shipwright .verdict)" = BRANCH ]'
  mkdir -p "$T/exported"; git -C "$P" archive "$BR" | tar -x -C "$T/exported"
  ck "  the built branch really passes the project's own offline check: node --test on its files passes all 6 tests, the new one among them" '[ "$(cd "$T/exported" && node --test 2>&1 | grep -cE "^# (pass 6|fail 0)$")" = 2 ]'
  ck "  the ticket is in review with its branch and the cycle id; the cycle lock is released" '[ "$(store sample-react ".tickets[0].status")" = review ] && [ "$(store sample-react ".tickets[0].cycle")" = "$ID" ] && [ ! -d "$T/state/cycle-sample-react-t1.lock" ]'
  ck "  the cycle record: ticket 1, no issue, no pull request, apply true, the branch and the review command" '[ "$(jq -r .ticket "$REC")" = 1 ] && [ "$(jq -r .issue "$REC")" = null ] && [ "$(jq -r .pr "$REC")" = null ] && [ "$(jq -r .apply "$REC")" = true ] && [ "$(jq -r .branch "$REC")" = "$BR" ] && jq -r .review "$REC" | grep -q "diff .*\.\.\.$BR"'
  ck "  the stages that need a pull request are skipped with the plain reason, never failed" 'R="needs a GitHub pull request: connect a repo with qtdeck repo sample-react and run them there"; for sid in assayer r1:surveyor r1:marshal r1:lookout r1:pilot r1:inspector caulker; do [ "$(stg $sid .state)" = skipped ] && [ "$(stg $sid .detail)" = "$R" ] && [ "$(stg $sid .verdict)" = SKIPPED ] || { echo "bad $sid"; false; break; }; done'
  ck "  the last message names the branch, the review command, and says nothing was pushed and no pull request exists" 'grep -q "local branch $BR" <<<"$OUT" && grep -q "diff .*\.\.\.$BR" <<<"$OUT" && grep -q "Nothing was pushed and no pull request exists" <<<"$OUT"'
  local cid=$ID
  cyc --status "$cid"
  ck "--status <id> prints the ticket, the status, the branch, the review command and every stage with its state" '[ "$RC" = 0 ] && grep -q "local ticket #1" <<<"$OUT" && grep -q "awaiting-review" <<<"$OUT" && grep -q "local branch: $BR" <<<"$OUT" && grep -q "review it: git" <<<"$OUT" && grep -qi "purser" <<<"$OUT" && grep -qi "shipwright" <<<"$OUT" && grep -qi "skipped" <<<"$OUT"'
  local n0; n0=$(calls_n)
  cyc --resume "$cid"
  ck "a --resume of a finished cycle says there is nothing to resume, and no stage ran again (no new model call)" '[ "$RC" != 0 ] && grep -q "nothing to resume" <<<"$OUT" && [ "$(calls_n)" = "$n0" ] && [ "$(git -C "$P" rev-list --count main..$BR)" = 1 ]'
  cyc sample-react --ticket 1 --apply
  ck "starting the same ticket again is refused: it is in review on its local branch, and the message names the branch" '[ "$RC" != 0 ] && grep -q "ticket 1 is review on the local branch $BR" <<<"$OUT"'

  # a stop in the middle: the shipwright leaves no contract, the cycle fails after the purser and the panel, and --resume goes on from the failed stage only
  crew_replies "I did something but I will not say what"
  : > "$T/claude-calls"
  cyc sample-react --ticket 2 --apply
  local fid=$ID
  ck "a shipwright that leaves no contract fails its stage: the cycle is failed, the earlier stages are kept, the ticket is still building, and it says how to resume" '[ "$RC" != 0 ] && [ "$(jq -r .status "$REC")" = failed ] && [ "$(stg purser .state)" = done ] && [ "$(stg panel .state)" = done ] && [ "$(stg shipwright .state)" = failed ] && [ "$(store sample-react ".tickets[1].status")" = building ] && grep -q "qtdeck cycle --resume $fid" <<<"$OUT"'
  local early; early=$(jq -r 'select(.prompt | contains("REQUIREMENTS_JSON") or contains("RULING_JSON")) | 1' "$T/claude-calls" | wc -l | tr -d ' ')
  crew_replies; : > "$T/claude-calls"
  setreg '.["sample-react"].build = "qd-no-such-tool"'      # a check whose tool is not installed exits 127; the shipwright says what that means
  cyc --resume "$fid"
  setreg '.["sample-react"].build = "npm run build"'
  local again builds; again=$(jq -r 'select(.prompt | contains("REQUIREMENTS_JSON") or contains("RULING_JSON")) | 1' "$T/claude-calls" | wc -l | tr -d ' '); builds=$(jq -r 'select(.prompt | contains("Build this one ticket")) | 1' "$T/claude-calls" | wc -l | tr -d ' ')
  ck "--resume goes on at the failed stage: the purser and the panel are not asked again (they were asked $early times), the shipwright builds once" '[ "$RC" = 0 ] && [ "$ID" = "$fid" ] && [ "$early" -ge 2 ] && [ "$again" = 0 ] && [ "$builds" = 1 ] && [ "$(jq -r .status "$REC")" = awaiting-review ] && [ "$(jq -r .resumed "$REC")" = 1 ]'
  ck "  a check that exits 127 is explained: the command was not found, the crew never installs, and what to change" 'grep -q "build exit 127" <<<"$OUT" && grep -q "exit 127 means that command was not found" <<<"$OUT" && grep -q "never installs" <<<"$OUT" && grep -qF "needs no install" <<<"$OUT"'
  ck "  ticket 2 now has its own branch with one commit that adds summary, and the checkout is still clean on main" '[ "$(git -C "$P" rev-list --count main..ticket/2-show-a-summary-line)" = 1 ] && git -C "$P" show ticket/2-show-a-summary-line:src/todos.js | grep -q "export function summary" && [ "$(git -C "$P" rev-parse --abbrev-ref HEAD)" = main ] && [ -z "$(git -C "$P" status --porcelain)" ]'
  ck "  all along, nothing was pushed and gh was never called" '[ -z "$(git -C "$P" remote)" ] && nogh'
}

# ---- part 4. the same through the dashboard -------------------------------------------------------------------------------------------------------
part4_dashboard() {
  echo "part 4: the same through the dashboard API, and its Missions page"
  mkproj sample-web
  $QD attach "$T/proj/sample-web" --name sample-web --verify "node --test" --apply >/dev/null 2>&1
  setreg '.["sample-web"].cycle = true | .["sample-web"].duties += ["purser", "panel"]'
  local W=$T/proj/sample-web PORT
  planner_replies; : > "$T/claude-calls"; rm -f "$T/gh-calls"
  PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  export QD_PORT="$PORT" T
  # the dashboard holds the fake provider's settings and nothing that names a real model account, a key or a token: it starts from an empty environment
  local k; local -a denv=()
  for k in $(compgen -e); do
    case "$k" in
      *KEY*|*TOKEN*) ;;
      QUARTERDECK_*|HOME|PATH|XDG_CONFIG_HOME|LANG|LC_*|TMPDIR|TZ|TERM|USER|PYTHONDONTWRITEBYTECODE|CLAUDE_BIN|GIT_AUTHOR_*|GIT_COMMITTER_*|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM) denv+=("$k=${!k}") ;;
    esac
  done
  env -i "${denv[@]}" QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
  DASH=$!
  if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then ck "the dashboard started on a free port" 'false'; return; fi
  ck "a real dashboard is up on a free port with the temp data folder" 'true'
  if [ -r "/proc/$DASH/environ" ]; then
    ck "  its environment holds the fake provider and no key, token or login of a real model or of GitHub" 'tr "\0" "\n" < /proc/$DASH/environ > "$T/dash.env"; grep -q "^QUARTERDECK_PROVIDER=fake$" "$T/dash.env" && grep -q "^QUARTERDECK_FAKE_REPLIES=" "$T/dash.env" && ! grep -qiE "KEY|TOKEN|PASSWORD|OAUTH|ANTHROPIC|OPENAI|AWS_|GOOGLE|CLOUDSDK" "$T/dash.env"'
  else st_skip "its environment cannot be read on this machine (no /proc): the check that it holds no key is not run"; fi
  # a small client: pairs like a browser (the one-time link, a cookie and this tab's token) and speaks as it
  cat > "$T/qc.py" <<'PY'
import http.client, json, os, re, subprocess, sys, time
PORT, T = int(os.environ["QD_PORT"]), os.environ["T"]
ORIGIN = "http://127.0.0.1:%d" % PORT
def chk(label, cond, extra=None): print(("ok " if cond else "FAIL ") + label + ("" if cond or extra is None else "  | " + str(extra)[:300]))
def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None: h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
    c.request(method, path, body=data, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    try: j = json.loads(raw)
    except ValueError: j = {"raw": raw.decode("replace")}
    return r.status, j, r.getheader("Set-Cookie") or ""
def pair():
    link = subprocess.run([sys.executable, T + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
    st, j, ck = req("POST", "/api/pair", {"nonce": link.split("#pair=")[1]})
    return {"cookie": ck.split(";")[0], "token": j["token"]}
S = pair()
def get(path): return req("GET", path, headers={"Cookie": S["cookie"]})[:2]
def post(path, body):
    return req("POST", path, body, {"Cookie": S["cookie"], "X-Quarterdeck-Token": S["token"], "Origin": ORIGIN})[:2]
def tickets(p): return get("/api/tickets?project=" + p)[1]
def wait_idle(p, limit=90):
    end = time.time() + limit
    while time.time() < end:
        j = tickets(p)
        if not j.get("running"): return j
        time.sleep(0.3)
    return tickets(p)
def ghcalls(): return open(T + "/gh-calls").read().splitlines() if os.path.exists(T + "/gh-calls") else []
def cycles_of(p): return [f for f in (os.listdir(T + "/state/cycles") if os.path.isdir(T + "/state/cycles") else []) if "-" + p + "-" in f]
PY
  cat > "$T/p4a.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
st, j = get("/api/tickets?project=sample-web")
chk("GET /api/tickets for the project with no repo: no repo, the one sentence, the four options, nothing yet", st == 200 and j["has_repo"] is False and j["sentence"].startswith("sample-web has no GitHub repo")
    and [o["key"] for o in j["options"]] == list("abcd") and j["tickets"] == [] and j["drafts"] == [], j)
st, j = post("/api/ticket/draft", {"project": "sample-web", "request": "Let me clear the finished todos and show how many are left", "confirm": True})
chk("POST /api/ticket/draft starts the planner (the stand-in provider) and answers started", st == 200 and j == {"started": True}, j)
done = wait_idle("sample-web")
chk("  the draft arrives: two tickets with their acceptance checks, nothing filed, no error", len(done["drafts"]) == 1 and len(done["drafts"][0]["tickets"]) == 2 and done["tickets"] == []
    and done["last_draft_error"] == "" and done["drafts"][0]["tickets"][1]["title"] == "Show a summary line" and done["drafts"][0]["tickets"][0]["acceptance"], done)
st, j = post("/api/ticket/file", {"project": "sample-web", "draft": done["drafts"][0]["id"], "local": True, "confirm": True})
r = tickets("sample-web")
chk("POST /api/ticket/file with local true saves two local tickets, uses the draft up, and the stand-in gh was never called", st == 200 and len(r["tickets"]) == 2 and r["drafts"] == []
    and [t["source"] for t in r["tickets"]] == ["local", "local"] and [t["status"] for t in r["tickets"]] == ["open", "open"] and ghcalls() == [], (st, j))
PY
  pyck "$T/p4a.py"
  crew_replies; : > "$T/claude-calls"
  cat > "$T/p4b.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
st, j = post("/api/cycle/start", {"project": "sample-web", "ticket": 2})
chk("POST /api/cycle/start without confirm is a 400 that says confirm, and starts nothing", st == 400 and "confirm" in j["error"] and cycles_of("sample-web") == [], (st, j))
st, j = post("/api/cycle/start", {"project": "sample-web", "ticket": 2, "confirm": True})
chk("POST /api/cycle/start {project, ticket, confirm} for ticket 2 starts it detached: cycle sample-web --ticket 2", st == 200 and j["started"] == "cycle sample-web --ticket 2" and j["id"].startswith("cyc-sample-web-t2-"), (st, j))
cid = j["id"]
mine, end = None, time.time() + 240
while time.time() < end:
    cs = [c for c in get("/api/state")[1]["cycles"] if c["id"] == cid]
    if cs:
        mine = cs[0]
        if mine["status"] != "running": break
    time.sleep(0.4)
chk("the mission appears in the dashboard's mission list (the state's cycles) and ends awaiting-review, for ticket 2, with its branch", mine is not None and mine["status"] == "awaiting-review" and mine["ticket"] == 2
    and mine["issue"] is None and (mine.get("branch") or "").startswith("ticket/2-"), mine)
st, m = get("/api/mission?id=cycle:" + cid)
nodes = {n["id"]: n for n in m["pipeline"]}
chk("/api/mission shows ticket #2, the crew's steps (brief, build) done, review and seal skipped and never blocked, and a person awaited", st == 200 and "ticket #2" in m["title"] and m["state"] == "awaiting"
    and nodes["brief"]["state"] == "done" and nodes["build"]["state"] == "done" and nodes["review"]["state"] == "skipped" and nodes["seal"]["state"] == "skipped" and nodes["human"]["state"] == "awaiting"
    and not any(n["state"] in ("blocked", "failed") for n in m["pipeline"]), m.get("pipeline"))
skipped = [h for h in m["history"] if h["verdict"] == "SKIPPED"]
chk("  the history has the purser, the dev panel and the shipwright, the verify result, and the pull-request stages as SKIPPED with the reason", len(skipped) >= 4
    and all("needs a GitHub pull request" in h["detail"] for h in skipped) and any("verify exit 0" in h["detail"] for h in m["history"])
    and {"purser", "panel", "shipwright"} <= {h["duty"].lower() for h in m["history"]} | {w for h in m["history"] for w in h["duty"].lower().split()}, m["history"])
chk("  the ticket block has the branch and the review command as plain text, and one line of what is next", m["ticket"]["n"] == 2 and m["ticket"]["branch"] == mine["branch"] and "diff" in m["ticket"]["review"] and "merge it yourself" in m["ticket"]["next"], m.get("ticket"))
r = tickets("sample-web")
t2 = [x for x in r["tickets"] if x["id"] == 2][0]
chk("the ticket list shows ticket 2 in review with the branch, the review command and the cycle id; ticket 1 is still open", t2["status"] == "review" and t2["branch"] == mine["branch"] and t2["cycle"] == cid and "diff" in t2["review"]
    and [x for x in r["tickets"] if x["id"] == 1][0]["status"] == "open", t2)
chk("  starting ticket 2 again is refused", post("/api/cycle/start", {"project": "sample-web", "ticket": 2, "confirm": True})[0] in (400, 409))
chk("  the gh stand-in log has no call at all", ghcalls() == [])
open(T + "/flow-cid", "w").write(cid)
PY
  pyck "$T/p4b.py"
  local cid BR2; cid=$(cat "$T/flow-cid" 2>/dev/null); BR2=$(store sample-web ".tickets[1].branch")
  REC="$T/state/cycles/$cid.json"
  ck "on disk: the branch ticket/2-<slug> has exactly one commit on top of main, with summary and its test, in src/todos.js and src/todos.test.mjs only" '[ "$BR2" = ticket/2-show-a-summary-line ] && [ "$(git -C "$W" rev-list --count main..$BR2)" = 1 ] && [ "$(files_in "$W" $BR2)" = "src/todos.js src/todos.test.mjs " ] && git -C "$W" show $BR2:src/todos.js | grep -q "export function summary" && git -C "$W" show $BR2:src/todos.test.mjs | grep -q "summary says how many are left"'
  ck "  not package.json, not the lockfile; no remote, nothing pushed; the checkout is clean on main" '! git -C "$W" diff --name-only main...$BR2 | grep -qE "package(-lock)?\.json" && [ -z "$(git -C "$W" remote)" ] && [ "$(git -C "$W" rev-parse --abbrev-ref HEAD)" = main ] && [ -z "$(git -C "$W" status --porcelain)" ]'
  ck "  the cycle record on disk carries the verify result: checks: verify exit 0" 'grep -qF "checks: verify exit 0" <<<"$(stg shipwright .detail)"'
  ck "  the model never reached the claude binary, and gh was never called" '[ ! -e "$T/claude-was-run" ] && nogh'
  if st_have_browser || node "$REAL/bin/tickets-ui-page.mjs" probe >/dev/null 2>&1; then
    mkdir -p "$T/shots"
    local LINK; LINK=$(QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link)
    OUT=$(QD_LINK="$LINK" QD_SHOTS="$T/shots" QD_T="$T" QD_PROJECT=sample-web QD_CYCLE="$cid" node "$REAL/bin/flow-ui-page.mjs" 2>&1); RC=$?
    local line nf=0
    while IFS= read -r line; do
      case "$line" in
        "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
        "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)); nf=$((nf + 1)) ;;
        "skip "*) printf '  skip  %s\n' "${line#skip }" ;;
      esac
    done <<<"$OUT"
    if [ "$RC" != 0 ] && [ "$nf" = 0 ]; then printf '  FAIL  the page test crashed (exit %s): %s\n' "$RC" "$(printf '%s\n' "$OUT" | tail -3 | tr '\n' ' ')"; fails=$((fails + 1)); fi
    [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
  else
    st_skip_browser "the Missions page checks (the ticket list, the mission) are not run"
  fi
  kill "$DASH" 2>/dev/null; wait "$DASH" 2>/dev/null; DASH=""
  ck "the dashboard stops cleanly when asked: the process is gone and the port no longer answers" 'st_gone "$T/bin/dashboard.py" && [ "$(curl -s -m 2 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/health")" != 200 ]'
}

# ---- part 5. the refusals ------------------------------------------------------------------------------------------------------------------------
part5_negative() {
  echo "part 5: what is refused, and what is never done by default"
  mkproj sample-gh
  $QD attach "$T/proj/sample-gh" --name sample-gh --verify "node --test" --apply >/dev/null 2>&1
  OUT=$($QD repo sample-gh acme/sample-gh 2>&1); RC=$?
  ck "a project given a repo (checked through the gh stand-in) has one in the registry" '[ "$RC" = 0 ] && [ "$(reg ".\"sample-gh\".repo")" = acme/sample-gh ]'
  planner_replies; rm -f "$T/gh-calls"
  OUT=$($QD ticket new sample-gh "clear the finished todos" 2>&1); RC=$?
  ck "a project WITH a repo: ticket new, report only, keeps a draft and files nothing, not even locally" '[ "$RC" = 0 ] && [ "$(store sample-gh ".drafts | length")" = 1 ] && [ "$(store sample-gh ".tickets | length")" = 0 ] && [ "$(ghn "^gh (issue (create|edit|comment)|pr |api)")" = 0 ]'
  OUT=$($QD ticket new sample-gh "clear the finished todos" --apply 2>&1); RC=$?
  ck "  --apply files GitHub issues (two gh issue create calls) and saves no local ticket unless asked" '[ "$RC" = 0 ] && [ "$(ghn "^gh issue create")" = 2 ] && [ "$(store sample-gh "[.tickets[] | select(.source == \"local\")] | length")" = 0 ] && [ "$(store sample-gh "[.tickets[] | select(.source == \"github\")] | length")" = 2 ]'
  rm -f "$T/gh-calls"
  OUT=$($QD ticket new sample-gh "clear the finished todos again" --apply --local 2>&1); RC=$?
  ck "  --local is the way to ask for local tickets on such a project: they are saved here and gh creates nothing" '[ "$RC" = 0 ] && [ "$(ghn "^gh issue create")" = 0 ] && [ "$(store sample-gh "[.tickets[] | select(.source == \"local\")] | length")" = 2 ]'
  local DEC="ghp_$(printf 'a%.0s' $(seq 1 36))"                  # a decoy credential shape, built here so no file of the program holds one
  rm -f "$T/gh-calls"; local n0; n0=$(store sample-react ".tickets | length"); : > "$T/claude-calls"
  OUT=$($QD ticket new sample-react "log in with the token $DEC and show the todos" --apply 2>&1); RC=$?
  ck "a credential shape in the request stops ticket new --apply: non-zero, no model call, nothing saved, the decoy is never printed" '[ "$RC" != 0 ] && [ "$(calls_n)" = 0 ] && [ "$(store sample-react ".tickets | length")" = "$n0" ] && ! grep -qF "$DEC" <<<"$OUT" && nogh'
  cyc sample-react --ticket 99 --apply
  ck "cycle --ticket 99 says there is no such ticket" '[ "$RC" != 0 ] && grep -q "there is no local ticket 99" <<<"$OUT"'
  cyc sample-react --ticket 1 --issue 3 --apply
  ck "--ticket and --issue together are refused: they are two different jobs" '[ "$RC" != 0 ] && grep -q "two different jobs" <<<"$OUT"'
  cyc sample-react --issue 3 --apply
  ck "a cycle on an issue number needs a repo, and the message names the local way instead" '[ "$RC" != 0 ] && grep -qF "sample-react has no GitHub repo" <<<"$OUT" && grep -q "qtdeck cycle sample-react --ticket" <<<"$OUT"'
  setreg 'del(.["sample-react"].cycle)'
  local t3; t3=$(store sample-react ".tickets | length")
  cyc sample-react --ticket 1 --apply
  ck "a project that has not opted in (no cycle: true) is refused, and the message says where to put it, without talking of pull requests a ticket never opens" '[ "$RC" != 0 ] && grep -q "has not opted in" <<<"$OUT" && grep -qF "\"cycle\": true" <<<"$OUT" && ! grep -q "pull requests" <<<"$OUT"'
  setreg '.["sample-react"].cycle = true'
}

part1_attach
part2_tickets
part3_cycle_cli
part4_dashboard
part5_negative
st_done
