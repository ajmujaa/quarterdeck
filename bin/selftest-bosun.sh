#!/bin/bash
# The bosun reports drift and writes to no repository. The HARNESS finds everything with plain checks (bin/deck.py) and a model only
# ranks it. Run against stand-ins for the model and gh and a real git repository of invented files, with the planted cases asserted:
# a stale merged branch, a dead environment variable, a README naming a file that is gone, an unused script, an open issue whose
# pull request merged, an old TODO. A real .env is planted too, and must never be read.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init bosun
cp "$REAL/bin/deck.py" "$T/bin/"
ago() { python3 -c 'import datetime as d,sys; print((d.datetime.now(d.timezone.utc) - d.timedelta(days=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%S+0000"))' "$1"; }
commit_at() { # commit_at <days ago> <message>
  (cd "$T/work" && git add -A && GIT_AUTHOR_DATE="$(ago "$1")" GIT_COMMITTER_DATE="$(ago "$1")" git commit -q -m "$2")
}
st_repo
W="$T/work"
st_file README.md $'# Project\n\nStart it with `npm start`. Lint everything with `npm run lint:all`.\nSee `src/app.js` and `src/gone.js`. Deploy with `scripts/deploy.sh --frobnicate`.\nSet `API_URL`, and `LEGACY_TOKEN` for the old login.\n'
st_file package.json '{"name":"app","scripts":{"start":"node src/app.js","test":"echo test","orphan":"echo nobody calls me","seed":"node scripts/seed.js"}}'
st_file src/app.js $'const url = process.env.API_URL;\nconst x = process.env.UNSET_VAR;\nconst t = require("./config").theme;\n// TODO: remove this old workaround\n'
st_file .env.example $'API_URL=http://localhost\nUNUSED_KEY=1\n'
st_file .env $'REAL_SECRET=SECRET-VALUE-DO-NOT-READ\n'
st_file scripts/deploy.sh $'#!/bin/sh\necho deploy\n'
st_file scripts/old-helper.sh $'#!/bin/sh\necho old\n'
st_file config/app.json '{"theme":"dark","legacyFlag":true}'
st_file .github/workflows/ci.yml $'steps:\n  - run: npm run seed\n'
commit_at 200 "old base"
st_file src/app.js $'const url = process.env.API_URL;\nconst x = process.env.UNSET_VAR;\nconst t = require("./config").theme;\n// TODO: remove this old workaround\n// TODO: fresh note from today\n'
commit_at 0 "recent change"
(cd "$W" && git push -q origin HEAD:main)
branch() { # branch <name> <days ago> [merge]
  (cd "$W" && git checkout -q -b "$1" main && echo "$1" > "b-$1.txt" && git add -A && GIT_AUTHOR_DATE="$(ago "$2")" GIT_COMMITTER_DATE="$(ago "$2")" git commit -q -m "$1" && git push -q origin "$1" \
   && git checkout -q main)
}
branch old-merged 100; (cd "$W" && git merge -q --no-ff -m "merge old-merged" old-merged && git push -q origin main)
branch abandoned 120
branch closed-branch 5
branch active 1
branch fresh-no-pr 2
printf '%s' '[{"number":3,"state":"CLOSED","headRefName":"closed-branch","mergedAt":null,"closingIssuesReferences":[]},{"number":4,"state":"OPEN","headRefName":"active","mergedAt":null,"closingIssuesReferences":[]},{"number":5,"state":"MERGED","headRefName":"old-merged","mergedAt":"2026-01-01T00:00:00Z","closingIssuesReferences":[{"number":12}]}]' > "$T/ghdata/pr-list.json"
printf '%s' '[{"number":12,"title":"Fix the thing"},{"number":13,"title":"Another open issue"}]' > "$T/ghdata/issue-list.json"
st_registry '["bosun"]' '{}'
REFS_BEFORE=$(git -C "$T/origin.git" for-each-ref --format='%(refname) %(objectname)' | sort)
HEAD_BEFORE=$(git -C "$W" rev-parse HEAD)

RANK='RANKED_JSON: [{"id":"f2","action":"Fix the README line."},{"id":"f999","action":"An id the harness never gave."}]
SUMMARY: The README misleads; the rest is tidying.'
st_noreplies; st_reply default "$RANK"; rm -f "$T/state/bosun/"*
st_duty bosun
REPORT=$(ls "$T"/state/bosun/tp-*.md 2>/dev/null | head -1)
ck "report only: DECK <n> is recorded as a DRY-RUN, and the dated report exists" '[ "$(last_verdict)" = DRY-RUN ] && grep -q "DECK [0-9]" <<<"$(last_detail)" && [ -f "$REPORT" ]'
ck "  the report is mode 0600 in a folder of its own, under the duty's own state" '[ "$(stat -c %a "$REPORT" 2>/dev/null || stat -f %Lp "$REPORT")" = 600 ] && [[ "$REPORT" == "$T/state/bosun/"* ]]'
ck "  nothing is written to GitHub: it only listed pull requests and issues" '[ "$(gh_writes)" = 0 ] && grep -q "^gh pr list" "$T/gh-calls" && grep -q "^gh issue list" "$T/gh-calls"'
ck "  no branch was touched, nothing pushed, and the project checkout is exactly where it was" '[ "$(git -C "$T/origin.git" for-each-ref --format="%(refname) %(objectname)" | sort)" = "$REFS_BEFORE" ] && [ "$(git -C "$W" rev-parse HEAD)" = "$HEAD_BEFORE" ] && [ -z "$(git -C "$W" status --porcelain)" ] && [ "$(git -C "$W" worktree list | wc -l | tr -d " ")" = 1 ]'

# ---- the planted cases, found by the harness ----------------------------------------------------------------------------------
ck "a stale branch that is already merged is found, with the evidence" 'grep -q "origin/old-merged" "$REPORT" && grep -q "already merged into main" "$REPORT"'
ck "a branch with no commit for 120 days and no pull request is found; a closed pull request is found" 'grep -q "origin/abandoned" "$REPORT" && grep -q "no commit for 120 days" "$REPORT" && grep -q "origin/closed-branch" "$REPORT" && grep -q "pull request #3 was closed without merging" "$REPORT"'
ck "  and a branch with an open pull request, and a recent branch, are left alone" '! grep -q "origin/active" "$REPORT" && ! grep -q "origin/fresh-no-pr" "$REPORT"'
ck "a variable the code reads that nothing defines is found; one the example file defines and nothing reads is found; a defined one is not" 'grep -q "UNSET_VAR" "$REPORT" && grep -q "UNUSED_KEY" "$REPORT" && ! grep -q "| .API_URL. |" "$REPORT"'
ck "a README naming a file that is gone, a script that is not there, a flag and a variable nothing knows are all found" 'grep -q "src/gone.js" "$REPORT" && grep -q "no script called lint:all" "$REPORT" && grep -q -- "--frobnicate" "$REPORT" && grep -q "LEGACY_TOKEN" "$REPORT"'
ck "  and what the README names correctly is not" '! grep -q "names the file .src/app.js." "$REPORT" && ! grep -q "npm start" "$REPORT" && ! grep -q "scripts/deploy.sh. which is not" "$REPORT"'
ck "an unused script and an unused script file and an unused config key are found; used ones are not" 'grep -q "scripts.orphan" "$REPORT" && grep -q "scripts/old-helper.sh" "$REPORT" && grep -q "legacyFlag" "$REPORT" && ! grep -q "scripts.seed" "$REPORT" && ! grep -q "| .scripts/deploy.sh. |" "$REPORT" && ! grep -q "key theme" "$REPORT"'
ck "an open issue whose pull request has merged is found; an issue with no such pull request is not" 'grep -q "issue #12" "$REPORT" && grep -q "pull request #5" "$REPORT" && ! grep -q "issue #13" "$REPORT"'
ck "a TODO written 200 days ago is found; one written today is not" 'grep -q "src/app.js:4" "$REPORT" && grep -q "written 20[0-9] days ago" "$REPORT" && ! grep -q "fresh note from today" "$REPORT"'
ck "a real .env is never opened: its secret is in no report, no prompt, no log" '! grep -rq "SECRET-VALUE-DO-NOT-READ" "$T/state" "$T/claude-calls" "$T/logs" 2>/dev/null && ! grep -q "REAL_SECRET" "$REPORT"'

# ---- the model only ranks ----------------------------------------------------------------------------------------------------------------------
ck "the model is read only and told it cannot add findings, and not to open an env file" 'jq -e ".deny | contains(\"Write\") and contains(\"Bash(git push\") and contains(\"Bash(curl\")" "$T/claude-calls" >/dev/null && grep -q "anything else you write is thrown away" "$T/claude-calls" && grep -q "Do not open any environment file other than an example" "$T/claude-calls"'
ck "  the harness's findings, not the model's, are what the report holds: its order is used, its invented id is dropped, the rest follow" 'sed -n "/^| 1 |/p" "$REPORT" | grep -qE "doc drift|stale|dead|unused|open issue|old TODO"; ! grep -q "never gave" "$REPORT" && grep -q "Fix the README line." "$REPORT" && grep -q "The README misleads" "$REPORT"'
ck "  the first row is the finding the model ranked first (f2), and every finding is still there" '[ "$(grep -c "^| [0-9]* |" "$REPORT")" -ge 12 ] && sed -n "/^| 1 |/p" "$REPORT" | grep -q "Fix the README line."'

# ---- once a day, and the cap ------------------------------------------------------------------------------------------------------------------------
: > "$T/claude-calls"; st_duty bosun
ck "it runs at most once a day: a second walk is NOTHING, and asks no model" '[ "$(last_verdict)" = NOTHING ] && [ ! -s "$T/claude-calls" ]'
rm -f "$T"/state/bosun/*.md; st_noreplies; st_reply default "$RANK"
QUARTERDECK_BOSUN_MAX_ITEMS=3 st_duty bosun --again
REPORT=$(ls "$T"/state/bosun/tp-*.md | head -1)
ck "--again walks again, and QUARTERDECK_BOSUN_MAX_ITEMS caps the report, saying how many were cut" '[ "$(grep -c "^| [0-9]* |" "$REPORT")" = 3 ] && grep -q "more finding(s) were cut by the cap of 3" "$REPORT"'

# ---- one summary issue, never one per finding -----------------------------------------------------------------------------------------------------
rm -f "$T/gh-calls" "$T/issue-created-body" "$T/issue-edited-body"; st_noreplies; st_reply default "$RANK"
st_duty bosun --again --apply
ck "--apply creates ONE summary issue with a fixed title, holding the findings; no other write" '[ "$(grep -c "^gh issue create" "$T/gh-calls")" = 1 ] && grep -q -- "--title Quarterdeck bosun: deck report" "$T/gh-calls" && grep -q "origin/old-merged" "$T/issue-created-body" && [ "$(gh_writes)" = 1 ] && [ "$(last_verdict)" = DECK ]'
ck "  nothing in the issue repeats the secret, and no repository was changed" '! grep -q "SECRET-VALUE" "$T/issue-created-body" && [ "$(git -C "$T/origin.git" for-each-ref --format="%(refname) %(objectname)" | sort)" = "$REFS_BEFORE" ]'
printf '%s' '[{"number":77,"title":"Quarterdeck bosun: deck report"}]' > "$T/ghdata/issue-list.json"
rm -f "$T/gh-calls"; st_duty bosun --again --apply
ck "the next walk UPDATES that issue instead of opening another" '! grep -q "^gh issue create" "$T/gh-calls" && grep -q "^gh issue edit 77" "$T/gh-calls" && [ -s "$T/issue-edited-body" ]'
printf '%s' '[{"number":12,"title":"Fix the thing"},{"number":13,"title":"Another open issue"}]' > "$T/ghdata/issue-list.json"

# ---- an unparseable reply writes nothing ------------------------------------------------------------------------------------------------------------------
rm -rf "$T/state/bosun" "$T/gh-calls" "$T/issue-created-body"; st_noreplies; st_reply default 'The deck looks fine to me.'
st_duty bosun --again --apply
ck "an unparseable reply is an ERROR run: no report, no issue, and it does not count as a walk" '[ "$(last_verdict)" = ERROR ] && [ -z "$(ls "$T"/state/bosun 2>/dev/null)" ] && [ "$(gh_writes)" = 0 ]'
st_noreplies; st_reply default 'RANKED_JSON: not json
SUMMARY: x'
st_duty bosun --again --apply
ck "so is a ranking that is not an array" '[ "$(last_verdict)" = ERROR ] && [ -z "$(ls "$T"/state/bosun 2>/dev/null)" ]'

# ---- a clean deck, and gh down ------------------------------------------------------------------------------------------------------------------------------
mkdir -p "$T/clean"; git init -q --bare -b main "$T/clean.git" 2>/dev/null || git init -q --bare "$T/clean.git"; git clone -q "$T/clean.git" "$T/cleanw" 2>/dev/null
(cd "$T/cleanw" && git config user.name f && git config user.email f@example.invalid && git checkout -q -b main 2>/dev/null; echo "# tidy" > README.md; git add -A; git commit -q -m init; git push -q origin main)
jq --arg w "$T/cleanw" '.tp.path = $w' "$T/config/projects.json" > "$T/x" && mv "$T/x" "$T/config/projects.json"
printf '[]' > "$T/ghdata/pr-list.json"; printf '[]' > "$T/ghdata/issue-list.json"; rm -rf "$T/state/bosun"; : > "$T/claude-calls"
ST_WORKDIR="$T/cleanw" st_duty bosun --again
CR=$(ls "$T"/state/bosun/tp-*.md | head -1)
ck "a clean deck is DECK CLEAR, asks no model, and still leaves its report" 'grep -q "DECK CLEAR" "$CR" && grep -q "CLEAR" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
rm -f "$T/gh-calls" "$T/issue-created-body"; ST_WORKDIR="$T/cleanw" st_duty bosun --again --apply
ck "  and with no summary issue open and nothing to say, it opens none" '[ "$(gh_writes)" = 0 ]'
jq --arg w "$T/work" '.tp.path = $w' "$T/config/projects.json" > "$T/x" && mv "$T/x" "$T/config/projects.json"
printf '#!/bin/bash\nexit 1\n' > "$T/ghfail"; chmod +x "$T/ghfail"
rm -rf "$T/state/bosun"; st_noreplies; st_reply default "$RANK"
QUARTERDECK_GH="$T/ghfail" st_duty bosun --again
GR=$(ls "$T"/state/bosun/tp-*.md | head -1)
ck "with gh unavailable the checks that need it are said to be limited, and the rest still ran" 'grep -q "could not be listed" "$GR" && grep -q "UNSET_VAR" "$GR"'

# ---- structure ----------------------------------------------------------------------------------------------------------------------------------------------
ck "the duty is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/duties/bosun.sh" && [ "$(tail -c 3 "$REAL/duties/bosun.sh" | tr -d "\n")" = "}" ]'
ck "the bosun never deletes, edits or pushes: no such command is in the duty or the checks" '! grep -nE "git [^|]*(push|branch -[dD]|--delete|checkout|reset|rm |commit|merge)|gh (pr (create|edit|merge|close)|issue close|api)|rm -rf \"\\\$SOURCE" "$REAL/duties/bosun.sh" | grep -v "^[0-9]*:#" | grep -q . && ! grep -nE "(open|Path)\([^)]*, *.[wa]|os\.(remove|unlink|rename)|shutil|subprocess.*(push|delete)" "$REAL/bin/deck.py" | grep -q .'
ck "the only GitHub writes in the duty are the one summary issue's create and edit" '[ "$(grep -cE "gh_post [0-9]+ issue (create|edit)" "$REAL/duties/bosun.sh")" = 2 ]'
ck "the checks open only the project, never a home folder or an environment file with real values" '! grep -nE "expanduser|environ.*HOME|\.ssh|\.aws" "$REAL/bin/deck.py" | grep -q . && grep -q "REAL_ENV.match" "$REAL/bin/deck.py"'
ck "it ships with no schedule: nothing in the repository's config schedules it" '! grep -rqi "bosun" "$REAL/config" 2>/dev/null'
ck "the deckhand has a bias and something it is willing to be wrong about, and no ruled-out word is used" 'grep -q "^bias: ." "$REAL/crew/deckhand.md" && grep -q "willing to be wrong about" "$REAL/crew/deckhand.md" && ! grep -liE "(^|[^[:alnum:]])(tester|sentry|mender|critic|prover)([^[:alnum:]]|$)" "$REAL/crew/deckhand.md" "$REAL/duties/bosun.sh" | grep -q .'
st_done
