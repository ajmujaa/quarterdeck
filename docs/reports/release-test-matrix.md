# Release test matrix (round 7)

Tried against `main` at 59566e3 (the visible Add a project button). Every row was tried in a throwaway data folder with a fake HOME and the fake provider and fake `gh`. Result is `pass`, `BUG-n` (a bug entry in the same part) or `not tested: reason`.

| Part | Rows | pass | bug rows | not tested |
| --- | --- | --- | --- | --- |
| A: API routes, commands, documents, fresh install | 207 | 138 | 40 | 29 |
| B: dashboard controls, journeys, hostile text, typing, accessibility | 366 | 299 | 35 | 32 |
| Total | 573 | 437 | 75 | 61 |

The bug rows point at 22 bugs in part A and 19 in part B. Bug numbers are per part: A-n and B-n below.

## Where each bug went

GitHub issues are the record. A pull request that says "Fixes" closes its issue; "Refs" leaves it open for what is not done.

| Bug | Issue | Fix PR |
| --- | --- | --- |
| A-1, A-21, A-22 (docs paths and claims) | #145 | #156 (Refs; the narrow-patterns and outside-home parts need a decision) |
| A-2 (billing cap duty) | #139 | #149 |
| A-3 (`add` default duty) | #138 | #155 |
| A-4 (`connect` with nothing) | #144 | #151 |
| A-5, A-6, A-19 (command-line usage) | #146 | #157 (Refs; some items left) |
| A-7, A-8, A-9 (bad JSON, wrong types) | #143 | #152 |
| A-10 (temp file collision) | #140 | #150 |
| A-11, A-13, A-15, A-17 (small input checks) | #147 | #154 (Refs; the xoxp- prefix check left) |
| A-12, A-20 (read-only, full disk) | #141 | #158 (Refs; ticket, guardrail, schedule, showcase left) |
| A-14, A-18 (HTTP methods, voice message) | #148 | #153 |
| A-16 (`--apply` inside args) | #142 | none: needs a decision |
| B-1 (second tab, "forbidden") | #160 | none yet |
| B-2 (folder of projects) | #161 | none: needs a decision |
| B-3, B-4, B-6, B-7 (double clicks) | #162 | none yet (the temp file part is helped by #150) |
| B-5 (tickets already exist) | #163 | none yet |
| B-8 (spec panel "bad value") | #164 | none: needs a decision |
| B-9, B-10 (notes) | #165 | none yet |
| B-11 (Brain More menu) | #166 | none yet |
| B-12 (no Turn off) | #167 | none: needs a decision |
| B-13 (lock folders) | #168 | none yet |
| B-14, B-19 (cap with cents, stale credential text) | #169 | none yet |
| B-15, B-16, B-17, B-18 (layout, targets, All missions) | #170 | none yet |

---

# Part A: API routes, commands, documents, fresh install


Tested on main as of the first run (c224e66), later fast-forwarded to 59566e3 (the Add a project button). Fake provider, fake gh, throwaway data folder and fake HOME, loopback port 7931. Part 1 of the table: API routes and actions (brief section 1 item 2, 2B, 2D).

| Item | How it was tried | Result |
|---|---|---|
| POST /api/pair, fresh link | paired with the link `qtdeck dashboard link` printed | pass |
| POST /api/pair, same link again | reused the used nonce | pass (401, plain message) |
| POST /api/pair, wrong or malformed nonce, no body, number, `<script>` | 5 variants | pass |
| POST /api/pair, cross-site Origin or Sec-Fetch-Site | 2 variants | pass (403) |
| Reads without cookie, bad Host header, localhost Host | GET /api/state, /api/health | pass |
| Writes without token, without Origin, wrong Origin, wrong token | POST /api/capture | pass (403) |
| POST /api/logout then reuse | logout, then GET /api/state | pass |
| Unknown GET/POST route, path traversal under /assets/ | 5 requests | pass |
| HEAD / | 405 with Allow | pass |
| PUT, DELETE, OPTIONS, PATCH on /api/state | one request each | BUG-14 |
| Body: bad JSON, JSON list, bad Content-Length, 5 MB, non-UTF-8 | POST /api/capture | pass |
| Body: JSON nested 5000 deep | POST /api/capture | BUG-7 |
| Content-Security-Policy and security headers on / | read headers | pass (CSP with nonce, X-Frame-Options DENY, no-store) |
| GET /, /api/health, /api/session, /api/firstrun, /api/state | plain reads | pass |
| GET /api/showcase/public, /api/intent, /api/rhythm, /api/connections, /api/settings | plain reads | pass |
| GET /api/fleet, /api/fleet/projects, /api/attention, /api/timeline, /api/prs, /api/progress, /api/board | plain reads, with and without project | pass |
| GET /api/cycle/estimate | known, unknown and `<script>` project | BUG-15 |
| GET /api/log | name traversal, NUL, spaces; n=-1, 0, huge | pass |
| GET /api/log?n=abc | non-numeric n | BUG-8 |
| GET /api/project-agents, /api/tickets, /api/guardrails, /api/ready | known, unknown, empty, `<script>`, 5000 chars | pass |
| GET /api/live | key=attach, mem:x, bad keys, since=abc and -5 | pass |
| GET /api/card | kind issue, pr, bogus; number -1, `<script>`, huge | pass |
| GET /api/doc, /api/panel, /api/brief, /api/plan, /api/mockup, /api/mission, /api/showcase/case | valid shape, traversal, `<script>` | pass |
| POST /api/capture action add (also no action) | text 1, 999, 1000 chars; whitespace; bad project | pass |
| POST /api/capture, 1001 and 5000 characters | over the 1000 limit | BUG-13 |
| POST /api/capture, control characters in text | NUL and BEL in text | BUG-13 |
| POST /api/capture action edit, done, reopen | valid, empty, bad id, twice | pass |
| POST /api/capture action promote (mission, plan, bad target, no project, no confirm) | 5 variants | pass |
| POST /api/missions action create | valid, 2000, 2001, empty, no project, duplicate objective | pass |
| POST /api/missions create with a non-string field | objective, constraints, success_criteria as number, bool, list | BUG-9 |
| POST /api/missions action update, link, propose_plan, approve_plan, start_panel | valid and out-of-order | pass |
| POST /api/missions two at once | two simultaneous creates | BUG-10 |
| POST /api/mission/action dismiss, undo, close_issue, retry, mark_merged | on a draft id, on an unknown id, bogus action | pass (plain 400); real finished missions not tested, see Not tested |
| POST /api/inbox action acknowledge | valid shape and bad id | not tested: needs an inbox item from a real run, only the 400 path was reached |
| POST /api/showcase actions create, update, publish, unpublish | full cycle, twice, edit while published, empty title | pass |
| POST /api/showcase with a non-string field | title, summary, before, after, role as number | BUG-9 |
| POST /api/ticket/draft | valid, double, no confirm, 2000, 2001, empty, key in request | pass |
| POST /api/ticket/file, /api/ticket/discard | local, to repo, bad draft, not bool, twice | pass |
| POST /api/repo actions set, create | valid, bad slug, injection text, already set | pass |
| POST /api/repo set, two at once | two simultaneous | BUG-10 |
| POST /api/ready/prove, /api/ready/prove-stop | start, second start (409), stop | pass |
| POST /api/docs/draft, /api/docs/apply | draft, double, no confirm, apply | pass |
| POST /api/project/duties | add, remove, bogus duty, cycle on, cycle bad | pass |
| POST /api/project/guardrails | locked rule removal, too many, long rule, wrong type | pass |
| POST /api/project/verify | already set, other command | pass |
| POST /api/newproject | valid, exists, no confirm, empty, 1 char, spaces, quote, `<script>`, 300, `../`, RTL, outside home, hidden, about 5000, about `<script>` | pass |
| POST /api/newproject, folder is a file | folder = path of an existing file | BUG-11 |
| POST /api/attach preview | empty, nonexistent, file, symlink, outside home, hidden, root, home, tilde, space, quote, NUL, relative | pass |
| POST /api/attach apply, name, edits | no confirm, apply, twice, name taken, name `<script>`, 300, verify with `$(...)`, edits wrong type | pass |
| POST /api/intent, /api/project-status | set, no confirm, unknown, 7 projects, next week, bad week | pass |
| POST /api/fixqueue actions pause, resume, clear, remove | valid, bad action | pass |
| POST /api/fixqueue with project as a list | `"project": []` | BUG-9 |
| POST /api/stop | not running, bad lock | pass |
| POST /api/stop with lock as a number | `"lock": 123` | BUG-9 |
| POST /api/schedule create, toggle, delete | every, at, bad at, bad every, none, bad duty | pass |
| POST /api/schedule with `every` or `at` as a number | `"every": 123` | BUG-9 |
| POST /api/schedule delete unknown id | `{"id":"zzzz","delete":true}` | BUG-15 |
| POST /api/schedule or /api/run with `--apply` inside args | args `["--pr","3","--apply"]` | BUG-16 |
| POST /api/run | valid, bad duty, unknown project, args not a list, 13 args, `$(id)` | pass |
| POST /api/run with a flag the duty does not take | args `["--evil"]` | BUG-16 |
| POST /api/work | bad action, bad issue | pass (plain 400); a valid start not reached, see Not tested |
| POST /api/cycle/start | no confirm, ticket, both, bad ticket, unknown project | pass |
| POST /api/merge | bad number, bad sha, shaped ok (fake gh) | pass |
| POST /api/fix | bad panel, bad item, 101 items | pass; a real panel not available, see Not tested |
| POST /api/brief/new, /api/brief/action (8 actions), /api/plan/action (4 actions) | valid, short, no confirm, unknown id | pass |
| POST /api/fleet/action | no confirm, unknown source | pass |
| POST /api/settings actions api_key, billing, seat, cap | valid, bad mode, bad duty, negative, string, 1e308, NaN, null, junk key | pass |
| POST /api/agent-sources actions add, remove | valid, duplicate, non-loopback http, file://, credentials in URL, `<script>` name, 60 and 61 chars, path traversal in map, non-string token | pass |
| POST /api/agent-sources, name with control characters | name `"‮\x00ab"` | BUG-17 |
| POST /api/connections actions credential, enable, store, signin, signin_status, signin_cancel | valid, bad label, 24 and 25 char label, test, remove, bogus action | pass |
| POST /api/connections credential values | wrong shape, NUL, number, 5000 chars, newline, `<script>` | BUG-17 |
| POST /api/firstrun actions demo, dismiss | no confirm, valid, bogus | pass |
| POST /api/demo on, off, restart; reads and writes while on | 8 writes in demo | pass (nothing real changed); BUG-19 for the wording |
| POST /api/chat, /api/understand, /api/speak, /api/transcribe | empty, tiny, junk WAV | not tested: Helm needs a local model and voice, none on this box; only the refusal paths ran and gave plain messages (see BUG-18) |
| Hostile text on every text field of every route above | 24 values (empty, 1 char, 200, 1000, 1001, 2000, 2001, 5000 chars, control characters, RTL, `<script>`, img onerror, quoted paths, `../`, `$(...)`, `;`, backtick, `--apply`, existing name, newline, emoji) x about 85 fields, about 4000 requests | pass: no 5xx for strings, nothing executed (no marker file appeared), nothing written outside the data folder and the fake HOME |
| Double submit, 15 actions sent twice at the same moment | missions, capture, schedule, cycle/start, prove, ticket draft, docs draft, run, repo, duties, newproject, attach, connections, merge, demo | pass for the duty effects (one model call, one cycle, one draft each); BUG-10 for the file collisions; merge sent two gh calls (gh refuses the second on a real PR) |
| Dashboard stopped mid-run and started again | SIGTERM during a planner run, restart | pass: old cookie gives 401, the run's lock is honoured (second draft gets 409 "already working"), a new link pairs |
| **Part 2: CLI commands** (brief section 1 item 3, 2E) | | |
| qtdeck (no arguments) | ran it with an empty data folder | pass (status page and a next step) |
| qtdeck help, --help, -h, help more | ran each; compared the command list with the dispatcher in bin/qtdeck | pass |
| qtdeck bogus | unknown command | pass (message, usage, exit 2) |
| qtdeck setup | fake HOME; compared with the text "installs nothing" | pass (installs nothing, lists sign-in steps; exit 1 while gh is not signed in) |
| qtdeck doctor | normal, with a missing gh, with an extra word | pass for output; extra flag ignored, see BUG-19 |
| qtdeck doctor --full | runs every test | not tested: the brief forbids running the whole check locally |
| qtdeck check | runs every test | not tested: same reason |
| qtdeck status | empty and with projects | pass |
| qtdeck projects | empty and with projects | pass |
| qtdeck duties, crew | listed | pass |
| qtdeck home, home init [path], home migrate, home rollback, home bogus | with QUARTERDECK_HOME set and a fake HOME | pass (home bogus shows the status page) |
| qtdeck attach <dir> (dry run) | React fixture; no argument; nonexistent folder | pass (no argument prints the attach usage, exit 2) |
| qtdeck attach <dir> --apply | registered, then again | pass |
| qtdeck attach flags --name --verify --build --lint --verbose | each given once; verify with `$(..)` rejected by the dashboard route | pass |
| qtdeck ready <p>, --details | fresh project, unknown project, no argument | pass |
| qtdeck ready <p> --prove | npm test in the bubblewrap sandbox with no node_modules | pass (exit 127 explained, tells you to install first) |
| qtdeck guardrail <p> list, add, remove, move, --effective | add, list, remove by number, bad number, move with no direction, no project | pass |
| qtdeck enable / disable <p> <duty>... | one duty, bogus duty, unknown project, no duty | pass |
| qtdeck enable / disable <p> cycle | turn on and off | pass |
| qtdeck repo <p> | project without repo shows the four ways | pass |
| qtdeck repo <p> <owner/name> | valid, 'notaslug', unknown project | pass |
| qtdeck repo create <p> | project that already has a repo | pass (refuses); the real create needs a signed-in gh: not tested |
| qtdeck ticket new <p> "..." | fake planner; no text; unknown project; text `-` on stdin | pass |
| qtdeck ticket new <p> "..." --apply, --local | to fake gh issue; local tickets | pass |
| qtdeck ticket list, show, file, remove | draft d1, ticket 1, filed, removed, missing ids | pass |
| qtdeck docs <p>, readme, architecture, --apply | fake scribe: refused one-line README, then a proper draft, applied to a new local branch; second apply | pass (never over an existing file, main untouched) |
| qtdeck cycle <p> --ticket n | fake model answers that do not parse | pass for the failure path (cycle record written, resume hint given); a full successful cycle not tested, see Not tested |
| qtdeck cycle <p> --issue n, --resume, --status | not opted in; bad number; no cycle on record | pass |
| qtdeck run <p> <duty> [flags] | surveyor --pr, unknown duty, not-enabled duty, bad flag, unknown project, planner --request | pass |
| qtdeck run <p> review | the example in the help ("Onboarding any project is two commands") | BUG-3 |
| qtdeck add [name] (inside a checkout), --repo, --path, --duties | in a git checkout with a remote; not in a checkout; existing name | BUG-3 (defaults and unvalidated flags) |
| qtdeck remove <name> | registered, unknown, no name | pass on a writable folder; BUG-12 on a read-only folder |
| qtdeck plan list / approve / apply | no plans | pass; BUG-19 (silent list) |
| qtdeck brief --idea, brief approve/changes/list, --revise | fake draughtsman reply refused; bad id | pass for the refusal paths; an accepted brief not tested |
| qtdeck mockup <brief-id>, approve, changes | bad id | pass for refusal; accepted mock-ups not tested |
| qtdeck fleet source add | valid, duplicate, bad id | pass |
| qtdeck fleet report --source --kind --session --worktree --branch --agent | valid, bad kind, unregistered source, --agent on a wrong kind | pass |
| qtdeck addon new <name>, addon list | scaffold, again, bad names, no name | BUG-1 (printed guide path); otherwise pass |
| qtdeck keys, keys set anthropic, keys remove anthropic | list, empty stdin, remove, bad name | pass |
| qtdeck billing (list) | default and broken config | pass |
| qtdeck billing <duty> plan/api, billing seat <name> plan/api | valid and invalid mode | pass |
| qtdeck billing cap daily <usd/off> | 5, off, abc | pass |
| qtdeck billing cap duty <duty/*> <usd/off> | known duty, unknown duty | BUG-2 |
| qtdeck connect list | printed | pass |
| qtdeck connect <service> [--account label] | unknown service, bad label, empty stdin | BUG-4 |
| qtdeck connect remove <service> [--account] [--yes] | default and labelled | pass |
| qtdeck spend [--days N] | 3, abc, 0 | BUG-6 for abc |
| qtdeck logs [name] [-f] | missing log, `-f` first | BUG-5 |
| qtdeck runs [n] | 3, none, abc, -5 | BUG-6 for abc |
| qtdeck fix <p> --panel --item | no panel, unknown panel | pass for refusals; a real panel ruling not available, see Not tested |
| qtdeck new <name> [--in DIR] [--about] | valid, existing folder, `../evil`, name with a space, no name | pass |
| qtdeck dashboard [--no-open] | started, started again ("already running", new link), pair worked once | pass |
| qtdeck dashboard link, dashboard sessions revoke, dashboard stop | link printed and paired once; stop killed the pid | pass for link and stop; revoke not separately exercised (server start also revokes) |
| qtdeck dashboard on a read-only data folder | run as another user | BUG-12 |
| Any command with a full data folder | 1 MB tmpfs filled to the brim | see the full-disk row below |
| **Part 3: documentation claims, fresh install, packaging** (section 1 item 4, 2E, 2F) | | |
| README: clone and `bin/qtdeck dashboard` shows a first-run screen with the doctor checks | extracted a tarball of the tracked files to an empty folder, fake HOME, no QUARTERDECK_HOME; started the dashboard; paired; GET /api/firstrun | pass (server answered in under 4 s; `first: true`, 8 checks: model CLI, gh, git, node, python3, model sign-in, gh sign-in, API key). The `git clone` of github.com itself: not tested, no network |
| README: "one button, Look around in Demo" | POST /api/firstrun demo, then GET /api/state and /api/demo off | pass for the API; the button itself is the other tester's |
| README: the dashboard "opens"; `--no-open` prints the link | ran with and without; this box has no browser opener | pass (prints the one-time link and no error) |
| README: "`bin/qtdeck setup` is still there if you prefer the terminal" | ran in the fresh folder | pass (5.5 s, installs nothing, changed only the data folder) |
| README: `brew install ajmujaa/quarterdeck/qtdeck` and `npm install -g qtdeck` "neither is published yet" | read packaging/ and ran bin/release.py | pass (nothing published; see the packaging rows) |
| README: `qtdeck attach ~/Projects/my-app` names the stack, proposes build and lint next to verify, lists "also fit this stack" duties that stay off | React fixture | pass |
| README: "The dry run writes nothing" | listed the data folder before and after, and `git status` in the project | pass (only the empty data-folder skeleton is created on the first command; the project is untouched) |
| README/GUIDE: attach "says why each duty is on or off" | default and `--verbose` | pass |
| README: missing docs are offered; `qtdeck docs my-app`; "only your yes puts it on a new branch" | fake scribe, with and without an origin remote | pass (new branch; a pull request through fake gh when the project has a repo and a remote; never over a file) |
| README: "ends with one checklist (`qtdeck ready my-app`) and one next action" | ran after attach | pass |
| README: "hands the survey to the agents as their stable context" | read the prompt the fake provider recorded for a planner call | pass (the stack sentence is in the prompt inside an untrusted-data block) |
| README: "`bin/qtdeck check` runs every test" | - | not tested: the brief forbids the whole check locally |
| README: "701 real runs against planted prompt injections: none obeyed. 400 control runs without the guard: 2 obeyed." | compared with docs/injection-report-2026-10-17.md (400 + 301 = 701, 0 obeyed; unwrapped control 2 of 400) | pass (numbers agree with the report; the runs themselves were not repeated: they need a real model) |
| README: "No keystrokes, screen, apps, clipboard or location, ever. A test scans the code for the APIs" | ran bin/forbidden_signals.py | pass |
| README: "Your plan, or an API key with spending caps" | `keys`, `billing`, caps on the CLI and in /api/settings | pass for the settings; that a capped duty stops with NEEDS_HUMAN needs the real model provider: not tested |
| README: `qtdeck ticket new my-app "..."` drafts one to five tickets and keeps the draft; `--apply` files them | fake planner, fake gh | pass |
| README: a project with no repo keeps local tickets | `ticket new dry "a counter" --apply` on a project with no repo | pass (saved on this computer, "nothing went to GitHub") |
| README: `qtdeck cycle my-app --ticket 1` builds one on a local branch with nothing pushed | fake model | not tested end to end: the fake model's answers are refused at the first stage; only the failure path ran (selftest-flow.sh covers the success path in CI) |
| README: `qtdeck repo my-app` lists the ways to get a repo; `repo create` only after you type yes | no repo; fake signed-in gh; no terminal; empty stdin | pass (shows the plan, says "There is no terminal to type yes in", creates nothing; gh was not called) |
| README: Missions page, New ticket box, Start a mission button, "four options as short rows" | - | not tested: browser journeys are the other tester's |
| README: "Running now" strip, "Live work" card, hook `bin/fleet-hook.sh install` | ran install and uninstall in the fake HOME | pass for the hook (backup written, only Quarterdeck's entries removed); the strip: other tester |
| README: "Available (N)" list with an Enable button on the Crew page | - | not tested: browser |
| README: guardrails editable on the project page and with `qtdeck guardrail <project> list|add|remove|move`; three locked | CLI and /api/project/guardrails | pass |
| README: Calm mode, Home/Projects layout, address keeps its place | - | not tested: browser |
| README: Status "Linux sandbox is run in CI only" | bubblewrap ran `npm test` in `ready --prove` on this Linux box | pass (consistent; the sandbox did work here) |
| README links: GUIDE.md, SECURITY.md, THREAT-MODEL.md, LICENSE, LICENSING.md, images/logo.png, logo-dark.png, home.png | checked each path exists | pass |
| GUIDE quick start, install and first-run commands (`setup`, `doctor`, `dashboard`, `dashboard --no-open`, `dashboard link`, `home init`) | ran each | pass |
| GUIDE: doctor "ends with all good or N problems" | ran with one problem | pass for "N problems"; the "all good" ending: not tested, `gh sign-in` always fails on this box |
| GUIDE: "nothing is placed outside the program folder, your data folder and the private credentials file" | listed the fake HOME after setup, doctor, dashboard, attach, fleet-hook | pass for Quarterdeck itself (the model CLI that doctor calls creates its own `~/.model CLI` and `~/.model CLI.json`) |
| GUIDE: dashboard link "good for five minutes and works once" | reused a link; the minting code has a 300 second life | pass for once; five minutes: not tested (would need a wait) |
| GUIDE: "Quarterdeck never scans your home folder" | attach with HOME as the path | pass (refused: "a whole folder of projects, not one project") |
| GUIDE: "Adding a project accepts folders under your home directory only" | dashboard routes and CLI | pass for the dashboard; BUG-22 for the CLI |
| GUIDE: `attach --verbose` "shows ... every path the crew may not change" | compared the two outputs | BUG-22 |
| GUIDE: `bin/qtdeck run my-app surveyor --pr 12` and `--apply` | fake gh with no PR | pass (reports only; "contract did not parse, nothing posted") |
| GUIDE: ticket commands (`ticket new`, `ticket list`, `ticket file d1 --apply`) | ran literally | pass |
| GUIDE: local tickets stored in `state/tickets/<project>.json` | looked in the data folder | pass |
| GUIDE: `repo create my-app --private` "if not signed in tells you to run gh auth login and creates nothing" | gh stub that says not signed in | pass (exit 3, creates nothing) |
| GUIDE: `bin/qtdeck cycle my-app --ticket 1 --apply` needs `"cycle": true` | ran without | pass (refused with a reason; wording in BUG-19) |
| GUIDE: crew table lists 22 names | compared with `qtdeck duties` | pass (every duty named in the table exists) |
| GUIDE: `bin/qtdeck crew` lists the crew | ran | pass |
| GUIDE: `bin/qtdeck brief --idea "..."`, `mockup <id>`, `plan approve` | refusal paths | pass for refusals; accepted brief and mock-ups not tested |
| GUIDE: billing steps (`keys set anthropic`, `billing shipwright api`, `billing seat modelmaker api`, `billing cap daily 20`, `billing cap duty shipwright 5`, `off`) | ran each literally | pass |
| GUIDE: `qtdeck packs list` | ran it | BUG-21 |
| GUIDE: `bin/qtdeck spend` | ran | pass |
| GUIDE: `bin/qtdeck connect gmail --account work`, `connect list`, `connect remove gmail --account work` | ran literally | pass (with BUG-4 for empty input) |
| GUIDE: `bash bin/selftest-flow.sh` and `crew/_README.md` exist | checked the paths | pass for existence; the script itself not run (full suite rule) |
| GUIDE links: README.md, images (home, fleet, connections), SECURITY.md, THREAT-MODEL.md, CONTRIBUTING.md, LICENSE, NOTICE | checked each path | pass |
| GUIDE: external links (jq, GitHub CLI, the model CLI, legal page) | - | not tested: no network |
| GUIDE: Helm, the Brain, Calm mode, Back and Forward, mission buttons | - | not tested: browser, microphone or real model (other tester or owner on a Mac) |
| SECURITY: dashboard binds 127.0.0.1 only | requested /api/health on the machine's other address | pass (no answer); loopback answers |
| SECURITY: Origin and Host checks, token in sessionStorage, token given once, a reload keeps working | all auth rows above | pass |
| SECURITY: data folder mode 0700 and files 0600 | `stat` on the data folder, state, config, token, runs, log; `find -perm /077` | pass |
| SECURITY: `/api/health` answers without pairing and carries no path or content | read the keys | pass (commit, disk_free_bytes, helpers, loops, ok, uptime_seconds, writable) |
| SECURITY: add-ons folder must be a real 0700 directory owned by you; others are skipped with a reason | `addon new`, `addon list` | pass for the loaded case; the refusal cases (link, wrong mode) not exercised |
| SECURITY: guardrails: three locked, owner rules at most 300 characters and 20, no control characters | CLI and API with 5000 chars, 200 rules, locked removal | pass |
| SECURITY: `POST /api/mission/action` guarded, plain 400 in Demo, `logs/missions.log` | auth rows; Demo POST | pass for the guard; the log line and Close the issue/Try again confirm text need a real finished mission: not tested |
| SECURITY: `qtdeck keys set anthropic` reads stdin only, refuses an argument | `keys set anthropic` with empty stdin; with a value as an argument | pass |
| SECURITY: credentials in a 0600 file in a 0700 folder; Keychain option | stat of `~/.config/quarterdeck/integrations.env` | pass for the file (0600); Keychain: not tested (macOS) |
| SECURITY: a ticket is plain text, no control characters, no `@mention`, no secret | draft with a key in the request, 2001 chars, empty | pass (refused with a reason) |
| SECURITY: outgoing text scanned for credentials | ticket request holding `sk-ant-...` | pass (refused before the model) |
| SECURITY: project commands run in a sandbox; macOS sandbox-exec; Linux bubblewrap | `ready --prove` ran under bubblewrap | pass for Linux; sandbox-exec and the claims about its profile: not tested (macOS) |
| SECURITY: a model gets minimal environment, prompt on stdin | read the fake provider record (`prompt_in_argv` false) | pass |
| SECURITY: injection tests ("50 hostile texts ...") | - | not tested: that is `qtdeck check`; not run |
| SECURITY: `docs/public/AGENTS.md` link | checked the path | BUG-22 |
| SECURITY: `qtdeck dashboard sessions revoke` signs every browser out | ran; an old cookie then got 401 after a server restart | pass |
| SECURITY: "Reporting: GitHub private vulnerability reporting" | - | not tested: needs the live repository settings |
| THREAT-MODEL.md exists and its facts (default port 7878, loopback, data folder `~/.quarterdeck` 0700) | compared with the code and the fresh install | pass; the line on launchd restarts: not tested (macOS) |
| LICENSE | present, Apache License 2.0 text | pass |
| NOTICE | present (3 lines, copyright 2026 The Quarterdeck contributors) | pass |
| LICENSING.md | present; says Apache-2.0, nothing paid today, intent to keep one-person use open; mentions issues #40 and #41 and `Signed-off-by` | pass for the text; the issue numbers: not tested (no network). CONTRIBUTING.md exists |
| Fresh install timing, as a stranger (extract to an empty folder, fake HOME) | `help` 0.01 s; `setup` 5.5 s; `doctor` 0.9 s; dashboard answering in under 4 s; demo on and off by API | pass: about 15 s of commands from an empty folder to a paired dashboard, plus the 4 s server start |
| Program folder read-only (as a package manager installs it) | ran help, doctor, setup, dashboard link and status as another user on a read-only copy | pass (no write attempted into the program folder) |
| Packaging: `bin/release.py --make-tarball 0.1.0`, then `release.py 0.1.0 --tarball ... --npm` | offline; checked that git status of the repo stayed clean | pass (formula filled with the tarball's sha256; nothing published; refuses a missing tarball and 'abc' as a version) |
| Packaging: Homebrew formula | `ruby -c` on the template and the filled copy; read it for network calls | pass for syntax and content (no download, no install script in `install`); `brew install` itself: not tested, no Homebrew here |
| Packaging: npm shim | ran `node npm/bin/qtdeck.js help` and `bogus`; with an empty PATH; with a wrong QUARTERDECK_APP; `npm pack --dry-run` | pass (finds Python, runs the program, exits 127 with a plain message when Python or the app is missing; the package is `private: true`; 611 files, 4.9 MB); `npm install -g` itself: not tested |

## Bugs

### BUG-1: `qtdeck addon new` points to a guide that does not exist
- Severity: cosmetic
- Steps: `QUARTERDECK_HOME=$(mktemp -d) bin/qtdeck addon new relay`
- Expected: the printed guide path exists in the public tree.
- Actual: last line reads `Add-ons from this folder can be turned off with QUARTERDECK_ADDONS=off. Guide: docs/public/ADDONS.md`. There is no `docs/public/`; the guide is `ADDONS.md` at the top of the repo. The same stale path is in the docstring of the generated `ext_relay.py` ("the contract is in docs/public/ADDONS.md").
- Where: bin/addons.py lines 4, 149, 249 (also bin/qtdeck lines 383, 386 comments, bin/lib.sh line 654).
- Fix size: small (change the string to ADDONS.md).

### BUG-2: a mistyped duty in `billing cap duty` breaks billing and every model call, and the CLI cannot repair it
- Severity: blocks a stranger (after one typo they cannot use the product until they hand-edit JSON)
- Steps: `bin/qtdeck billing cap duty nope 3` then `bin/qtdeck billing cap duty nope off`, then `bin/qtdeck billing surveyor plan`, then `bin/qtdeck billing`.
- Expected: the unknown duty name is refused when typed (the dashboard route /api/settings does refuse it with "scope is daily, or duty with a duty that exists (or *)").
- Actual: the first command prints `cap set to $3.00 a day` and writes `{"caps":{"duty_usd":{"nope":3.0}}}` to config/billing.json. Every later billing command, including the one that would remove it, prints `billing: config/billing.json: caps duty_usd names 'nope', which is not a duty of this version` (exit 2), and `qtdeck billing` says `every call of the model CLI provider stops with NEEDS_HUMAN until it is fixed`. Only editing the file by hand repairs it. Also the message says "a day" for a per-duty cap.
- Where: bin/billing.py (the `cap duty` branch of the CLI sets without calling `duty_names()`; the dashboard route in bin/dashboard.py settings_api, line about 3862+25, does).
- Fix size: small (validate the name; and let `cap duty <name> off` bypass the load check).

### BUG-3: `qtdeck add` registers a duty called "review" that does not exist, so the help's own onboarding example fails
- Severity: blocks a stranger
- Steps: in a git checkout with a remote: `bin/qtdeck add` then `bin/qtdeck run <name> review` (help text: "Onboarding any project is two commands: cd ~/Projects/Whatever && qtdeck add / qtdeck run whatever review"). Also `bin/qtdeck add --duties bogus,review` and `bin/qtdeck add --repo bad`.
- Expected: the default duties exist and the printed next step runs.
- Actual: `add` prints `duties: review` and `Then: qtdeck run plain review`; that command prints `quarterdeck: unknown duty 'review' (see: qtdeck duties)` (exit 1). `triage` (also in the help's example `qtdeck add --duties review,triage`) fails the same way. `--duties bogus` and `--repo bad` are accepted and written to projects.json without checking.
- Where: bin/qtdeck `add` command (default duties "review"), help text lines about "Flags for add" and "Examples".
- Fix size: small for the default and the help text (use surveyor; validate names); the old two-command flow may need a design decision, since `attach` is the documented path.

### BUG-4: `qtdeck connect <service>` with nothing on stdin says it saved and switched the service on
- Severity: annoying
- Steps: `bin/qtdeck connect slack </dev/null`
- Expected: a refusal ("nothing was given") and the service stays off.
- Actual: `Saved 0 credentials for Slack, and switched it on. Values are not shown again.` The card is then switched on with no credentials.
- Where: bin/connect.py (the save path counts zero and still enables).
- Fix size: small.

### BUG-5: `qtdeck logs -f` treats `-f` as the log name
- Severity: cosmetic
- Steps: `bin/qtdeck logs -f` (help: `logs [name] [-f]`).
- Expected: follow the default log.
- Actual: `no log yet: <data>/logs/-f.log`. Only `logs <name> -f` is understood.
- Where: the logs case in bin/qtdeck.
- Fix size: small.

### BUG-6: bad numbers to `runs` and `spend --days` give a jq error or are silently ignored
- Severity: cosmetic
- Steps: `bin/qtdeck runs abc`; `bin/qtdeck spend --days abc`.
- Actual: `jq: invalid JSON text passed to --argjson` plus jq's usage lines (exit 2); `spend --days abc` quietly shows 7 days.
- Expected: `usage: qtdeck runs [n]` and an error for a non-number.
- Where: runs case in bin/qtdeck; bin/spend.py argument parse.
- Fix size: small.

### BUG-7: JSON nested very deeply makes the dashboard drop the connection (no answer, traceback in the server log)
- Severity: cosmetic (needs a paired session)
- Steps: paired POST to /api/capture with body `{"text":` + `[`*5000 + `]`*5000 + `}`.
- Expected: `400 {"error": "the request body is not JSON"}`.
- Actual: `RemoteDisconnected: Remote end closed connection without response`; logs/dashboard-server.log has a RecursionError traceback. The server stays up.
- Where: bin/dashboard.py `_body`, line about 6000: `except ValueError` does not catch RecursionError (json.loads).
- Fix size: small (catch `(ValueError, RecursionError)`).

### BUG-8: `/api/log?n=abc` drops the connection
- Severity: cosmetic
- Steps: paired GET `/api/log?n=abc`.
- Expected: 400 with a plain message, or ignore n.
- Actual: no response; traceback in logs/dashboard-server.log (`int("abc")`).
- Where: bin/dashboard.py do_GET, the /api/log branch (`n = min(int((q.get("n") or ["200"])[0] or 200), 2000)`), line about 6143-6150.
- Fix size: small (try/except; also a negative n returns all but the first lines).

### BUG-9: a number, boolean or list where a route expects text gives a 500 with a Python message, or no answer at all
- Severity: cosmetic (needs a paired session; the page never sends these)
- Steps: paired POSTs:
  - `/api/missions {"action":"create","project":"my-app","objective":"x","constraints":123}` (also true, [..], -1, 1e308; same for success_criteria and a non-string objective).
  - `/api/showcase {"action":"create","title":123}` (same for summary, before, after, role).
  - `/api/schedule {"project":"my-app","duty":"surveyor","every":123}` and `"at":123`.
  - `/api/stop {"lock":123}`; `/api/fixqueue {"project":[],"action":"pause"}`.
- Expected: `400` with a plain message.
- Actual: missions: `500 {"error": "'int' object has no attribute 'strip'"}`; the others: the connection is closed with no reply.
- Where: bin/dashboard.py mission_act (about line 2649), showcase_act (1698), the /api/schedule branch (`(b.get("every") or "").strip()`), the /api/stop branch (`SAFE_LOCK.match(lock)`), the /api/fixqueue branch (`project not in read_json(...)` with a list).
- Fix size: small each; one helper that coerces or rejects non-strings would cover all.

### BUG-10: two writes at the same moment collide on a fixed temp file and one fails with a raw error
- Severity: annoying (a double click on Save or Create can show an error even though the first one worked)
- Steps: two simultaneous paired POSTs of `/api/missions {"action":"create","project":"my-app","objective":"double create"}`; likewise `/api/repo {"project":"my-app","action":"set","repo":"o/r","confirm":true}` and `/api/schedule {"project":"my-app","duty":"surveyor","every":"9h"}`.
- Expected: both succeed or the second gets a plain "already done" message.
- Actual: one request returns `500 {"error": "[Errno 2] No such file or directory: '<data>/state/missions.json.tmp'"}`; repo: `500 {"error": "could not write: FileNotFoundError"}`; schedule: connection closed with no reply. Reproduced on the first try.
- Where: bin/dashboard.py `write_json`, lines 470-474: `tmp = Path(str(path) + ".tmp")` is the same name for every writer, so the second `replace` finds the file gone.
- Fix size: small (unique temp name, for example with the pid and a counter).

### BUG-11: creating a project in a folder path that is a file gives a 500 with a Python error name
- Severity: cosmetic
- Steps: paired POST `/api/newproject {"name":"f1","folder":"<home>/Projects/fresh1/README.md","confirm":true}`
- Expected: `400` "that is a file, not a folder" (the attach route says this for the same input).
- Actual: `500 {"error": "could not create it: NotADirectoryError"}`
- Where: bin/dashboard.py newproject_api (about line 4127): `check_project_folder(..., whole=False)` does not test is_dir for the parent.
- Fix size: small.

### BUG-12: a read-only data folder gives Python tracebacks on the command line, and `remove` says "removed" when nothing was removed
- Severity: annoying
- Steps: copy a data folder, make it read-only for the user (run as another user, or a read-only mount), set `QUARTERDECK_HOME` to it, then:
  - `bin/qtdeck enable my-app joiner`
  - `bin/qtdeck repo my-app x/y`
  - `bin/qtdeck billing cap daily 5`
  - `bin/qtdeck dashboard --no-open` and `bin/qtdeck dashboard link`
  - `bin/qtdeck remove my-app`
- Expected: one plain line such as "your data folder is read-only: <path>" and a non-zero exit, as `guardrail add` already does (`qtdeck: could not write the registry: PermissionError`).
- Actual: a full Python traceback ending `PermissionError: [Errno 13] Permission denied: '<data>/config/projects.tmp'` for enable and repo; `PermissionError: ... '<data>/config/.billing.json.1jcfbz5v'` for billing; for the dashboard `PermissionError: [Errno 1] Operation not permitted: '<data>/state/pair'` then `could not make a link; is the data folder writable?`; for remove: `mv: cannot move '/tmp/tmp.S8nJPt28' to '<data>/config/projects.json': Permission denied` and then `removed 'dbl1'` with exit 0 (the project is still registered). `python3 bin/dashboard.py` directly: traceback at `(STATE / "dashboard.pid").write_text(...)` (line 6756).
- Where: bin/attach.py enable/disable and set-repo write path; bin/billing.py; bin/dashboard.py pair_mint (line 132) and main (line 6756); the remove case in bin/qtdeck.
- Fix size: small each (catch OSError, print one line); a common helper would be tidier.

### BUG-13: notes longer than 1000 characters are cut silently, and control characters are kept
- Severity: cosmetic
- Steps: paired POST `/api/capture {"text":"b"*1001}`; and `{"text":"a\u0000b\u0007c"}`.
- Expected: a 400 "a note is at most 1000 characters" (the missions route says "objective must be 1-2000 characters"), and control characters removed.
- Actual: 200 with the text cut to 1000; the NUL and BEL bytes are stored in state/capture.jsonl and returned.
- Where: bin/dashboard.py `_note_text` (line 3240): `" ".join(str(text or "").split())[:NOTE_CHARS]`.
- Fix size: small for the message; deciding to refuse or cut is a one-line product choice.

### BUG-14: PUT, DELETE, OPTIONS and PATCH answer with the standard library's HTML error page
- Severity: cosmetic
- Steps: `curl -X PUT http://127.0.0.1:<port>/api/state -H 'Host: 127.0.0.1:<port>'`
- Expected: a JSON 405 like HEAD gets (which sends Allow: GET, POST).
- Actual: `501` with `<!DOCTYPE HTML> ... <title>Error response</title>` (no security headers either).
- Where: bin/dashboard.py Handler (only do_HEAD, do_GET, do_POST exist).
- Fix size: small (add do_PUT etc. returning 405).

### BUG-15: some routes answer 200 for an id that does not exist
- Severity: cosmetic
- Steps: GET `/api/cycle/estimate?project=nope`; POST `/api/schedule {"id":"zzzz","delete":true}`; POST `/api/agent-sources {"action":"remove","id":"zork","confirm":true}`.
- Expected: 400/404 "unknown project", "no such schedule".
- Actual: `200 {"project": "nope", "opted_in": false, ...}`; `200 {"deleted": "zzzz"}`; `200 {"removed": false}`.
- Where: bin/dashboard.py /api/cycle/estimate branch (about line 6100) and the /api/schedule delete branch.
- Fix size: small.

### BUG-16: `--apply` smuggled in `args` of /api/run and /api/schedule; flags the duty rejects are reported as "started"
- Severity: annoying (design decision)
- Steps: paired POST `/api/run {"project":"my-app","duty":"surveyor","args":["--pr","3","--apply"]}`; POST `/api/schedule {"project":"my-app","duty":"surveyor","every":"1h","args":["--apply"]}`; POST `/api/run {... "args":["--evil"]}`.
- Expected: writing is only requested through the explicit `apply` field (the schedule record says `"apply": false`); an unknown flag is refused up front like the command line does (`surveyor: unknown argument '--evil'`).
- Actual: `{"started": "my-app surveyor --pr 3 --apply"}`; the schedule is stored with `"apply": false` and `"args": ["--apply"]` and would run with --apply every hour; `--evil` returns `{"started": "my-app surveyor --evil"}` and fails later in the background.
- Where: bin/dashboard.py validate_run (about line 2815): SAFE_FLAG allows any `--word`.
- Fix size: needs a decision (allow-list of flags per duty; refuse --apply in args).

### BUG-17: a credential or source name with odd content is accepted or mis-explained
- Severity: cosmetic
- Steps: POST `/api/connections {"action":"credential","id":"slack","key":"SLACK_USER_TOKEN","value":"xoxp-\u0000-1","confirm":true}` (also value 123, value "abc" for a field that "Starts with xoxp-"); POST `/api/agent-sources` with name `"‮\u0000ab"`.
- Expected: NUL and non-text refused; the name error says control characters are not allowed.
- Actual: stored, `{"present": true}`; the name is refused with `The name is a short label of up to 60 characters.` (wrong reason).
- Where: bin/integrations credential save path; bin/agentsources.py clean_source name check.
- Fix size: small.

### BUG-18: `/api/speak` error points to a README section that does not exist
- Severity: cosmetic
- Steps: POST `/api/speak {"text":"hello"}` with no voice set up.
- Actual: `500 {"error": "the natural voice is not set up: see the README"}`; README.md has only the words "Helm (optional voice)". /api/understand and /api/chat say `brew install llama.cpp and put a GGUF model at <path>`, also as a 500, on Linux.
- Expected: a pointer to real text, and a 4xx/503 for "not set up".
- Where: bin/dashboard.py speak() message; the 500 in the /api/speak and /api/understand branches.
- Fix size: small.

### BUG-19: small command-line wording and usage gaps
- Severity: cosmetic
- Items, each reproducible with the command shown:
  - `bin/qtdeck cycle my-app --ticket 2` on a project without cycles: `cycle: 'my-app' has not opted in. Add "cycle": true to its entry in <data>/config/projects.json first` while `qtdeck enable my-app cycle` exists. The dashboard's /api/cycle/start says the same (bin/dashboard.py line 957).
  - `bin/qtdeck plan list my-app` and `bin/qtdeck brief list` print nothing (exit 0) when empty.
  - `bin/qtdeck run my-app`, `plan`, `remove`, `mockup` with a missing argument print the whole help page (exit 1) instead of one usage line.
  - `bin/qtdeck dashboard --bogus` starts a dashboard; `bin/qtdeck doctor --nonsense`, `status extra`, `setup --bogus` ignore the extra word.
  - `bin/qtdeck ready my-app` prints `[ ] Cycles  Optional: a whole ticket in one go needs cycles (it is not switched on and the purser and ...` cut off mid-sentence.
  - `bin/qtdeck docs my-app --apply` for a project with `repo` set but no `origin` remote prints `to open a pull request for it later: connect a repo with  qtdeck repo my-app` (duties/scribe.sh line 136, duties/shipwright.sh line 380) although a repo is connected.
  - In Demo mode POST /api/attach, /api/newproject, /api/settings answer `404 {"error": "not found"}` instead of the "Demo mode: nothing is changed" wording other routes use.
- Fix size: small each.

### BUG-20: a full disk gives Python tracebacks on the command line and 500s with no cause from the dashboard
- Severity: annoying
- Steps: mount a 1 MB tmpfs, copy a data folder with projects into it, fill it (`dd if=/dev/zero of=<mnt>/fill bs=1k count=4000`), set `QUARTERDECK_HOME` to it, then run:
  - `bin/qtdeck enable app2 joiner`, `bin/qtdeck repo app2 a/b`, `bin/qtdeck billing cap daily 5`, `bin/qtdeck dashboard link`
  - `bin/qtdeck ticket new app2 hello`, `bin/qtdeck remove app2`, `bin/qtdeck guardrail app2 add x`
  - with a paired dashboard already running: POST /api/repo, /api/project/duties, /api/settings (cap), /api/ticket/draft, /api/schedule, /api/showcase.
- Expected: one plain line such as "the disk is full: nothing was saved".
- Actual: enable, repo, billing and dashboard link print a traceback ending `OSError: [Errno 28] No space left on device`. `ticket new` prints `quarterdeck: planner: that request cannot be used (plain text, at most 2000 characters)` (wrong reason). `remove` prints `jq: error: writing output failed: No space left on device` then `removed 'app2'` with exit 0. `guardrail add` prints `qtdeck: could not write the registry: OSError` and `echo: write error` lines from lib.sh lines 106 and 521. Dashboard: capture and missions give the errno text; repo, duties, settings return `500 {"error": "could not write: OSError"}`, ticket draft `500 {"error": "could not start the planner: OSError"}`; schedule and showcase close the connection with no reply.
- Where: bin/attach.py main (lines about 585 and 603), bin/integrations/common.py write_private (line 85), bin/dashboard.py pair_mint, the `except OSError` branches in bin/dashboard.py that print only `type(e).__name__`, the `remove` case in bin/qtdeck, bin/lib.sh lines 106-108 and 521.
- Fix size: small each; a shared "could not save: <reason>" wrapper would cover most.

### BUG-21: GUIDE tells the reader to run a command that does not exist
- Severity: annoying
- Steps: `bin/qtdeck packs list` (GUIDE.md line 249: "`qtdeck packs list` shows the packs found").
- Expected: a list of packs.
- Actual: `qtdeck: unknown command 'packs'` followed by the usage page, exit 2. `bin/qtdeck help more` does not list it either.
- Where: GUIDE.md line 249 (text) or bin/qtdeck (no `packs` case; bin/packs.py exists).
- Fix size: small either way (add the one-line case, or fix the sentence).

### BUG-22: documentation sentences that the program does not match
- Severity: cosmetic
- Items:
  - SECURITY.md (Agent sources bullet) links `docs/public/AGENTS.md`; there is no `docs/public/`. The file is `AGENTS.md` at the repository root. (Same stale prefix as BUG-1.)
  - GUIDE.md "Attach a project": "`--verbose` shows the whole scan and every path the crew may not change." The `--verbose` output (61 lines against 30) adds per-duty reasons but no list of protected paths.
  - GUIDE.md "Adding a project accepts folders under your home directory only, never a hidden folder." True for the dashboard (`POST /api/attach`, `/api/newproject`), but `bin/qtdeck attach /some/folder/outside/home` previews and `--apply` registers it without `QUARTERDECK_PROJECT_ROOTS`. Either the sentence should say "in the dashboard" or the command line should apply the same rule (design decision).
  - GUIDE.md header says "Built and used daily on macOS; Linux is next" while README.md says "Linux tested in CI" and the guide itself describes the Linux sandbox.
  - SECURITY.md and THREAT-MODEL.md say run arguments are "narrow patterns" (numbers digits only); `POST /api/run` accepts any `--word` flag and `--apply` inside args (see BUG-16).
- Where: the files named above.
- Fix size: small (text), except the outside-home rule which needs a decision.

## Not tested

- Everything that needs a browser (buttons, Copy, Demo switch, Calm mode, Brain, keyboard and screen reader): the other tester's part.
- A real model: model provider behaviour, caps stopping a duty with NEEDS_HUMAN, billing to an API key, the injection measurements, Helm chat, voice (`/api/speak`, `/api/transcribe`, `/api/understand`: they need llama.cpp and a voice model; the not-set-up answers were seen, see BUG-18).
- A successful cycle, brief, mock-up, panel ruling, `qtdeck fix` and `/api/fix` with a real panel, a real Close the issue or Try again on a finished mission, and `/api/inbox acknowledge` on a real item: the fake provider's canned answers do not satisfy the stage contracts, so only the refusal and failure paths ran. `bin/selftest-flow.sh` and the duty selftests cover the success paths in CI.
- Real GitHub: `gh` was a stand-in. `repo create` against a real account, issue and pull request filing, `/api/board`, `/api/prs`, `/api/card` with real data.
- `qtdeck check`, `qtdeck doctor --full`, `bin/selftest-*.sh`: not run (the brief forbids the full check locally).
- macOS only: `sandbox-exec` profile, Keychain, launchd restart, Homebrew install, `open` launching a browser.
- External links in the documents, the `git clone` URL, issue numbers in LICENSING.md, GitHub private vulnerability reporting, trademark and name availability.
- The dashboard link's five minute expiry (a wait was not worth it); the add-on refusal cases (link, wrong mode).
- Concurrency beyond two simultaneous requests, and killing a running verify command in the middle.

Not run by me but noted: the container restarted once during the work. The first run was against main c224e66; the Add a project change (59566e3) was re-checked on the attach routes and the CLI attach only.

## Five worst things

1. BUG-3: the onboarding path in `qtdeck help` (`qtdeck add` then `qtdeck run <name> review`) fails with "unknown duty 'review'"; a stranger who types what the help says gets stuck at step two.
2. BUG-2: one mistyped duty name in `qtdeck billing cap duty` stops every billing command and every model call, and the CLI cannot repair it.
3. BUG-10: two writes at the same moment (a double click on Create, Save repo or Schedule) collide on one fixed temp file name and show a raw `[Errno 2] No such file or directory` or a dropped connection.
4. BUG-12 and BUG-20: a read-only or full data folder gives Python tracebacks on the command line, and `qtdeck remove` says "removed" when it removed nothing.
5. BUG-16 (and BUG-9): the run and schedule routes accept `--apply` inside `args`, so a stored schedule can write every hour although its record says `apply: false`; non-text values in several routes give 500s or dropped connections.


---

# Part B: dashboard

Tester notes: headless Chromium via Playwright, fake provider, fake gh, throwaway data folder and fake HOME, loopback port other than 7878. Nothing was fixed.

| Item | How it was tried | Result |
|---|---|---|
| pair: fresh link | opened a new one-time link in a clean browser context. Saw: title Home | pass |
| pair: used link | opened the same link a second time in another context. Saw: Q Open Quarterdeck from its link That link has already been used or has expired. Quarterdeck shows your work only to a tab opened from a one | pass |
| pair: nonce removed from address bar | read location after pairing | pass |
| pair: wrong token | opened #pair=AAAA... (32 chars). Saw: Q Open Quarterdeck from its link That link has already been used or has expired. Quarterdeck shows y | pass |
| pair: malformed fragment | opened #pair=short. Saw: Q Open Quarterdeck from its link This is a new tab, and each tab needs its own link. Quarterdeck sho | pass |
| pair: expired link | rewrote the nonce file's expiry to 10s ago (cannot wait 5 min), opened link. Saw: Q Open Quarterdeck from its link That link has already been used or has expired. Quarterdeck shows y | pass |
| pair: reload keeps the pairing | reload paired tab | pass |
| pair: second tab same browser, no link | opened / in a second tab of the paired context. Saw: Q Open Quarterdeck from its link This is a new tab, and each tab needs its own link. Quarterdeck shows your work only to | pass |
| pair: second tab with own link | pasted a new link into the second tab | pass |
| pair: two tabs both live | first tab still polling after second paired | pass |
| pair: paste link into unpaired tab | set location.hash on the unpaired tab | pass |
| journey 1: first run, checks list | empty data folder, opened the paired link | pass |
| journey 1: Copy buttons (first command, keys set) | clicked each Copy with clipboard permission granted; read the clipboard | pass |
| journey 1: Skip, I will set it up myself | clicked Skip; reloaded | pass |
| pair: two tabs in one browser | paired tab A then tab B in the same context; added a note in A | BUG-1 |
| journey 3: scan with empty path | Add a project (drawer) typed a path into the Project folder field and pressed Scan: empty. Saw: field says "Paste a folder path first." | pass |
| journey 3: scan a nonexistent path | Add a project (drawer) typed a path into the Project folder field and pressed Scan: <home>/Projects/nonexistent. Saw: says it is not a folder | pass |
| journey 3: scan a file | Add a project (drawer) typed a path into the Project folder field and pressed Scan: a .txt file. Saw: "is a file, not a folder" | pass |
| journey 3: scan outside the home folder | Add a project (drawer) typed a path into the Project folder field and pressed Scan: /etc, "1", the data folder, the program folder. Saw: refused, names QUARTERDECK_PROJECT_ROOTS | pass |
| journey 3: scan a hidden folder | Add a project (drawer) typed a path into the Project folder field and pressed Scan: <home>/Projects/.hidden. Saw: refused plainly | pass |
| journey 3: scan the home folder itself | Add a project (drawer) typed a path into the Project folder field and pressed Scan: fake HOME. Saw: refused as a whole folder of projects | pass |
| journey 3: scan a symlink to a project | Add a project (drawer) typed a path into the Project folder field and pressed Scan: symlink pointing at a project folder. Saw: resolved and scanned as the target | pass |
| journey 3: scan a folder that holds several projects | Add a project (drawer) typed a path into the Project folder field and pressed Scan: <home>/Projects (holds sample-react, sample-web) | BUG-2 |
| journey 3: scan a name with spaces and quotes | Add a project (drawer) typed a path into the Project folder field and pressed Scan: folder named sp ace's "q" | pass |
| 2B: hostile and RTL and 5000-char path in Project folder | Add a project (drawer) typed a path into the Project folder field and pressed Scan: "><img src=x onerror=alert(1)>, U+202E text, 5000 "a". Saw: rendered as text, no dialog, no console error | pass |
| journey 3: Scan result, Missing docs, Copy buttons | scanned sample-react (no README); clicked both Copy buttons. Saw: clipboard denied in this run for the toast path: shows "Press Cmd+C or Ctrl+C to copy it." | pass |
| journey 3: crew switches in the attach drawer | toggled the joiner switch on and off | pass |
| journey 3: ready checklist rows (rdToggle x6) | opened every summary row | pass |
| journey 3: Attach this project | clicked Attach once-by-double-click on sample-react | BUG-3 |
| action attachAdd (double-click) | double-clicked Attach this project | BUG-3 |
| journey 3: new project, empty name | New-project form (Create it): empty name. Saw: toast: the name may hold letters, digits, dot, dash and underscore... | pass |
| journey 3: new project, taken name | New-project form (Create it): sample-react. Saw: toast: already exists and is not empty | pass |
| journey 3: new project, bad names | New-project form (Create it): slash, dotdot, space, 80 chars, <script> name. Saw: all refused with the same plain rule | pass |
| journey 3: new project, folder outside home | New-project form (Create it): /etc. Saw: refused, names QUARTERDECK_PROJECT_ROOTS | pass |
| journey 3: new project, valid | New-project form (Create it): fresh-app in ~/Projects. Saw: folder made with git and README, path put in the Scan field | pass |
| journey 3: new project, 3000-char description | New-project form (Create it): 3000 chars. Saw: accepted; no limit stated | pass |
| action attachNew | Create it with 12 name/folder cases | pass |
| action attachLook | Scan by button and by Enter | pass |
| journey 3: already-attached note | scanned sample-react after attaching it. Saw: "Already attached as sample-react...", no Attach button offered | pass |
| 2B: hostile project description and name | New-project form (Create it): <script> name; "><img onerror> description. Saw: refused or text; no dialog, no CSP error | pass |
| journey 4: Draft a README (rdDraft) | project page > Ready > Docs > Draft a README; confirmed the dialog; waited. Saw: draft kept, content readable, nothing written to the project | pass |
| journey 4: scribe cannot write a second file | fake provider answered with README and docs/ARCHITECTURE.md. Saw: reply line: dropped docs/ARCHITECTURE.md: only README.md may be written here | pass |
| journey 4: Put it on a new branch, Cancel then Make the branch (rdApply) | cancelled once (no branch), confirmed once. Saw: branch docs/sample-react-20261022 with one commit, main untouched | pass |
| journey 4: double-click Draft a README | double-clicked rdDraft | BUG-4 |
| journey 5: Ready checklist in every state seen (not ready, drafts waiting, proven, failed, blocked) | project page Ready card, edited the verify command in the registry between runs | pass |
| journey 5: Run it once to prove it (rdNext, rdProve, rdUseVerify path) | clicked it, confirmed dialog, watched the live strip, waited for end. Saw: PROVEN, "node --test ran in the sandbox and passed (exit 0, 2 s)" | pass |
| journey 5: Stop (rdProveStop) on a hanging verify command | verify = sleep 300; Run; Stop after 3 s. Saw: "That did not finish. You stopped it. Nothing was kept" | pass |
| journey 5: Prove it again (rdProve) | clicked after a proven state, with a good and a failing command | pass |
| journey 5: failing verify command | verify prints "boom: the todo test failed" and exits 3. Saw: card shows "exited 3 in the sandbox. It stopped at: boom: the todo test failed" and Show the output | pass |
| journey 5: sandbox refusing a write | verify writes /etc/x. Saw: "Read-only file system" shown, advice to use a read-only command | pass |
| journey 5: verify command left to hang to its own limit | n/a | not tested: the limit is long; only the Stop path was tried |
| 2A.10: typed text survives the 3 s refresh, ticket request box (tk-request) | typed 58 chars, waited 7.5 s, read the value | pass |
| journey 6: draft tickets with the fake provider (tkDraft) | typed a request, pressed Draft tickets, waited. Saw: draft d1 with two tickets, nothing filed | pass |
| journey 6: "nothing drafted" message | fake provider answered NOTHING_TO_DRAFT. Saw: "The planner drafted no ticket. It may think this is already built, or too vague..." | pass |
| journey 6: a request holding a key is refused | typed a request containing a ghp_ token shape. Saw: "Your request looks like it holds a password or a key, so nothing was sent." | pass |
| journey 6: Discard draft (tkDiscard) | clicked, saw the confirm | pass |
| journey 6: file locally (tkFile local) | drafted, pressed Save 2 tickets on this computer. Saw: two tickets kept on this computer, no gh write | pass |
| journey 6: file a draft whose tickets already exist | drafted the same request again and saved | BUG-5 |
| action tkFile (double-click) | double-clicked Save 2 tickets on this computer | BUG-6 |
| journey 6: file to a repo, Cancel then File 2 issues (fake gh) | set repo x/tp via the Save box, drafted, cancelled once, confirmed once. Saw: confirm names the repo and visibility; 2 gh issue create calls only after yes; tickets show issue #901 | pass |
| journey 6: set the repo name (tkRepoSave, tkRepoName) | tried empty, nonsense, a/b/c, x/<script>, x/tp. Saw: bad ones say "Write it as owner/name"; good one saved | pass |
| journey 8: allow cycles (rdCycle) | Ready > Cycles > Allow cycles, confirmed | pass |
| journey 8: start a mission from a ticket (tkMission, startCycle, cycleCancel) | Start a mission on a local ticket; read the dialog (cost, ceiling, plain description); started; double-clicked Start the cycle. Saw: one POST /api/cycle/start; mission page opened | pass |
| journey 8: a cycle to a local branch | ticket 2, fake provider and builder hook, waited for the end. Saw: branch ticket/2-show-a-summary-line, one commit, steps needing a pull request shown as Skipped with the reason | pass |
| journey 7: open a stopped/blocked fix and cycle mission | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: opened issue#14, issue#20, the failed cycle. Saw: steps, reason, Open the log, Try again, Dismiss | pass |
| journey 7: Try again (retryMission) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: Cancel then Yes, start it on a failed fix. Saw: confirm text names budget and limits; POST retry; toast "Started again..." | pass |
| journey 7: Close the issue (closeIssueFor) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: on a "nothing to build" fix with an issue. Saw: confirm names issue and repo; one gh issue close with a comment; toast "Issue #11 closed." | pass |
| journey 7: Mark as merged (markMerged) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: fix whose PR is MERGED on gh | not tested: the page records the merge by itself when the mission is opened, so the button never appeared; mission shown as Merged |
| journey 7: Dismiss and Undo dismiss, "1 dismissed" fold (dismissMission, dismissedToggle) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: dismissed issue#14, double-clicked Dismiss | BUG-7 |
| journey 7: old missions fold, finished fold, Hide handled switch (oldToggle, trajToggle, toggleOld, setHideHandled) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: clicked each | pass |
| journey 7: merged mission page (Open the pull request) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: issue#22 | pass |
| journey 7: create a mission draft (toggleMissionForm, saveMissionDraft) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: filled objective, constraints, success; typed text waited 7 s; Save draft. Saw: toast "draft saved", lower case | pass |
| journey 7: edit draft, link a panel as evidence (saveMissionEdit, linkPanelToMission) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: edited the objective, linked a panel | pass |
| journey 7: propose and approve a plan (proposeMissionPlan, approveMissionPlan) | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: proposed; double-clicked Approve this plan | BUG-7 |
| journey 7: Start with a spec panel (startMissionPanel) on a plain objective | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: objective "Sort list by date", no constraints. Saw: "spec panel started" | pass |
| journey 7: Start with a spec panel on an objective with constraints or punctuation | Missions page, seeded fix and cycle records (state files written by the test), fake gh that serves PR state: objective "Sort the list (by date), please?" and one with Constraints/Success criteria | BUG-8 |
| 2A.10: typed text survives, mission draft form (mi-*) and mission edit (mid-*) | typed in each, waited 7 s | pass |
| journey 12: add a note, Enter key (noteAdd, capSubmit) | Notes page (no project selected): typed and pressed Enter; also hostile text <script> and "><img onerror>, RTL text, a 190 char word. Saw: stored and listed as text; no dialog, no console error | pass |
| 2B: hostile and RTL text in Notes | Notes page (no project selected): <script>alert(1)</script>, "><img src=x onerror=alert(2)>, U+202E mix | pass |
| journey 12: the 1000-character limit, one over | Notes page (no project selected): typed 1001 x characters in New note and pressed Enter | BUG-9 |
| journey 12: exactly 1000 characters | Notes page (no project selected): 1000 characters | pass |
| journey 12: blank note | Notes page (no project selected): spaces only, Enter. Saw: nothing sent | pass |
| journey 12: edit a note (noteEditStart, noteEditSave, noteEditStop) | Notes page (no project selected): Edit, changed text (waited 7 s), empty save, Save, Cancel | BUG-10 |
| journey 12: edit box limit | Notes page (no project selected): typed 1200 chars in Edit the note. Saw: maxlength 1000 on the box | pass |
| journey 12: tag a note with a project (noteTag) | Notes page (no project selected): chose sample-react in the select | pass |
| journey 12: Done and Reopen (noteDone, noteFilter) | Notes page (no project selected): Done (double-click), Done list, Reopen | pass |
| journey 12: search notes (noteFilter q) | Notes page (no project selected): typed plain, then cleared | pass |
| journey 12: promote to a mission draft (notePromote mission) | Notes page (no project selected): To a mission. Saw: toast "saved a mission draft", no confirm because nothing runs | pass |
| journey 12: promote to a plan (notePromote plan) | Notes page (no project selected): To a plan, confirmed. Saw: confirm says it spends tokens; "started a spec panel" | pass |
| 2A.10: typed text survives, Notes New note, Search, Edit the note | Notes page (no project selected): typed, waited 7.5 s | pass |
| journey 10: every card opens (connHelp x9) | Connections page: clicked each help button, read the dialog | pass |
| journey 10: Save with empty value (connSaveAll) | Connections page: Enter on an empty Slack token. Saw: "Enter a value first." | pass |
| journey 10: Save a pasted value (connSave, connSaveAll) | Connections page: pasted a padded fake token, Enter. Saw: "Saved. It will not be shown again." | pass |
| journey 10: typed credential values survive the 3 s refresh (13 fields) | Connections page: typed into every field, waited 7.5 s | pass |
| journey 10: Test (connTest) with no credentials and with a fake token | Connections page: GA4 and Slack Test. Saw: GA4 says "needs the GA4 property id"; Slack says "network error: could not reach the service" | pass |
| journey 10: switch a service on and off (connEnable) | Connections page: Slack switch | pass |
| journey 10: Remove a saved credential (connRemove) | Connections page: Remove Slack user token, confirmed. Saw: "Removed." | pass |
| journey 10: Add another account form (connAddOpen, connAddSave) | Connections page: opened and cancelled | pass |
| journey 10: agent source presets (asPreset) | Connections page: both presets fill the mapping fields | pass |
| journey 10: agent source form validation (asAdd) | Connections page: empty name, empty url, javascript:, ftp:, 169.254.169.254, "not a url", 620-char url. Saw: each refused in plain words | pass |
| journey 10: agent source on 127.0.0.1 with nothing listening | Connections page: preset address http://127.0.0.1:9/list. Saw: added; list says "Could not reach it. Check the address and your co..." | pass |
| journey 10: remove an agent source (asRemove) | Connections page: confirm, remove | pass |
| journey 10: parked social cards open and fail plainly | Connections page: Facebook and Instagram, Threads, X, LinkedIn: help opens, Test with no credentials. Saw: plain message about credentials | pass |
| 2B: hostile text in the agent source name | Connections page: "><img onerror> as the name. Saw: refused by the address check; text not run | pass |
| 2A.10 Home: Brain dump (cap-in) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; overview | pass |
| 2A.10 Project page: guardrail add box (gr-new) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; projects | pass |
| 2A.10 Missions: New mission draft (mi-objective, mi-constraints, mi-success) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; missions form open | pass |
| 2A.10 Showcase: new showcase form (sc-title, sc-summary, sc-before, sc-after, sc-role) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; showcase form open | pass |
| 2A.10 Operations: new schedule form (s-args, s-every, s-at) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; operations form open | pass |
| 2A.10 Notes: New note, Search notes | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; notes | pass |
| 2A.10 Settings: API key (set-apikey) and daily cap (set-capday) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; settings, also 42 s in isolation | pass |
| 2A.10 Connections: 13 credential fields, add-account field, 8 agent source fields | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; connections (a help dialog open makes the page behind it reset, which is not typeable) | pass |
| 2A.10 Attach drawer (at-path, nw-name, nw-about, nw-folder) | 2A.10 typed text vs the 3 s poll: typed in the field, waited 7.5 s (longer where noted), compared the value; drawer held open across polls in journey 3 | pass |
| journey 9: Brain opens, map draws (canvas, counts, legend) | Brain page, software WebGL in headless Chromium: opened the Brain, 1128x847 canvas, 7 need you, legend chips | pass |
| journey 9: Map and Rhythm modes (setBrainMode) | Brain page, software WebGL in headless Chromium: clicked Rhythm and Map. Saw: Rhythm says "Not enough yet" with no data | pass |
| journey 9: size by Agent activity / My attention (setSizeBy) | Brain page, software WebGL in headless Chromium: clicked both | pass |
| journey 9: list a count (need you, things under a project) and open a row | Brain page, software WebGL in headless Chromium: clicked the count chips, then Inspect, Open ledger, Show on map in a row | pass |
| journey 9: node panel (Back to the list, Open ledger, Focus 25 min, Close the details) | Brain page, software WebGL in headless Chromium: Show on map, then each button | pass |
| journey 9: My focus timer (+5 min, Stop, saveFocus) | Brain page, software WebGL in headless Chromium: Focus 25 min started a countdown; +5 min; Stop | pass |
| journey 9: More menu opened with the mouse (Replay, Attention, What changed, My focus) | Brain page, software WebGL in headless Chromium: clicked More, looked at the menu and tried to click each item | BUG-11 |
| journey 9: Replay tool (toggleReplay, replayStep, replayIdx) | Brain page, software WebGL in headless Chromium: item clicked by script (the mouse cannot reach it). Saw: panel "Replay: Thu, Oct 22" lists ledger rows with Open ledger; says "Nothing was recorded that week" for the week while the day lists 8 rows | pass |
| journey 9: Attention, What changed, My focus tools (openAttention, openWhatChanged, openFocusDrawer) | Brain page, software WebGL in headless Chromium: items clicked by script. Saw: My focus drawer opens with project picker, Cancel, Save focus | pass |
| journey 9: keyboard on the Brain (Tab to More, arrows in the menu, Esc leaves) | Brain page, software WebGL in headless Chromium: Tab from My attention landed on More; Enter and ArrowDown moved through the items; Esc went Home | pass |
| 2C: Brain canvas keyboard use (nodes reachable only through the list chips) | Brain page, software WebGL in headless Chromium: Tab order. Saw: every node is reachable through the chips and lists; the 3D scene itself has no focusable nodes | pass |
| journey 11: Available fold and Enable (crewEnable) | Agents (Crew) page, project selected: opened Available (16), Enable the marshal, confirmed. Saw: confirm says why it is suggested and that it stays report-only | pass |
| journey 11: switch an agent off again | Agents (Crew) page, project selected: looked for any control that removes a duty | BUG-12 |
| journey 11: Run dialog (openRun, runPaint, runGo, runCancel) | Agents (Crew) page, project selected: Run the surveyor with no target; the dialog shows Write for real off by default. Saw: "started the surveyor on sample-react", read-only | pass |
| journey 11: Run dialog Schedule button (crewSchedule) | Agents (Crew) page, project selected: opened Operations schedule form from the dialog | pass |
| journey 11: Stop a running duty (stopRun) | Agents (Crew) page, project selected: Stop button seen on a duty shown as running | BUG-13 |
| journey 11: Log buttons (showLog, go log) | Agents (Crew) page, project selected: Log on each card | pass |
| journey 11: guardrails edit, move, remove, add, save (grEdit, grMove, grRemove, grNew, grAdd, grSave) | project page; crawl clicked every guardrail control; Save guardrails. Saw: toast "Guardrails saved." | pass |
| journey 11: crew filter chips (crewFilter) and live jump (liveJump) | Agents (Crew) page, project selected: All, Running, Need attention | pass |
| journey 11: add a schedule, bad inputs (toggleSched, addSched) | Operations page: empty, banana, 25:99, "--evil; rm -rf /", "><img onerror> args. Saw: each refused plainly: "interval must look like 30m, 4h or 1d", "time must be HH:MM", "bad flag", "bad value" | pass |
| journey 11: schedule every 1m accepted | Operations page: every 1m for the foreman. Saw: accepted; no minimum interval is stated | pass |
| journey 11: Pause, Resume, Remove a schedule (schedAction) | Operations page: Pause (double-click), Resume, Remove with Cancel then confirm. Saw: Remove confirm is titled "Please confirm" with a bare "Continue" | pass |
| journey 13: theme select (setTheme) | Settings page: dark, light, auto | pass |
| journey 15: Calm switch (toggleCalm) | Settings page: on and off | pass |
| journey 13: API key Save, wrong, empty, Remove (setKeySave, setKeyRemove) | Settings page: empty, "not-a-key", a fake sk-ant key, Remove with confirm. Saw: plain messages; "Saved. It will not be shown again." | pass |
| journey 13: daily cap (setCapSave) | Settings page: -5, 0, 1000000000, 25, empty, 12.5 | BUG-14 |
| journey 13: billing per duty (setBilling) | Settings page: panel to API key and back | pass |
| journey 13: Settings links (openAttach, explainWrites, dockGo spend and connections) | Settings page: clicked | pass |
| journey 15: 375 px width, every page (20 pages) | 375x800 viewport, project selected: checked horizontal scroll, elements past the right edge, and that every visible control scrolled into view can be hit (elementFromPoint). Saw: no horizontal scroll; 211 controls all reachable; the tab strip under the title is cut off at the edge and scrolls; the round Helm button floats over content | pass |
| journey 15: 375 px width in Calm mode | calm class on, all pages | BUG-15 |
| journey 15: Calm mode at 1280 px | toggled Calm on Settings; all pages | pass |
| journey 15: 1280 px width, every page | same checks. Saw: a few controls under 24 px tall, listed in Accessibility findings | pass |
| 2B: hostile text on every form (page level) | typed <script>, "><img onerror>, U+202E RTL, two 300-letter words, SQL and template text into mission drafts, ticket request, guardrail, showcase, notes, agent source, palette, global search; then opened 12 pages. Saw: nothing executed, no img created, no CSP console violation, no page scroll width growth | pass |
| 2B: very long words render as text | notes with a 190 and a 300 letter word, at 375 and 1280. Saw: wrapped; no horizontal scroll | pass |
| 2B: console CSP violations across the whole run | listened for Content-Security-Policy messages on every script. Saw: zero | pass |
| journey 3: error toast over the drawer buttons | sent two bad New project submits in a row at 1280x900 and tried to press Create it again | BUG-16 |
| journey 8: Pull requests tab (prsReload, onlyOurs, mergePr) with fake gh | served one open PR through the fake gh; Refresh, Opened by Quarterdeck, Merge confirm cancelled. Saw: the PR body with <script> rendered as text; Merge confirm says it makes a real merge commit and deletes the branch | pass |
| journey 10: add-on `qtdeck addon new relay` (local add-on) | created relay, qtdeck addon list says "ready", restarted the dashboard, wrote an alert with <b> and <img onerror> text, opened Needs you, pressed Acknowledge. Saw: listed as loaded, alert shown as text, Acknowledge asks "It leaves the list for good", no toast after | pass |
| journey 14: Demo on and off changes nothing real | turned Demo on from the first-run screen and from the switch; compared checksums of config/, state/, workspace/ and the projects folder before and after; counted gh and model calls while Demo was on, and pressed Draft, Run and Fix in Demo. Saw: identical; zero gh calls and zero model calls; Fix selected in Demo says "2 queued" but writes nothing | pass |
| journey 14: Demo restart scenario | Restart scenario on the Demo banner | pass |
| 2D: reload mid-action (ticket draft, Prove, mission start) | pressed Draft tickets / Run it once / Start the cycle and reloaded within half a second. Saw: page stays paired; draft finished with one model call; Prove finished PROVEN; the mission page was reopened from the address | pass |
| 2D: double-click on every action that changes or costs something | double-clicked Attach, Save tickets, Dismiss, Approve plan, Done, Pause schedule, Start the cycle, First-run Demo, Draft a README, Publish | BUG-7 |
| 2C: keyboard: tab order and skip link | 30 Tabs on the Projects page; skip link, rail, search, scope, tabs, Ready card, ticket box, buttons in reading order | pass |
| 2C: every control has an accessible name | scripted check of buttons, links, switches, inputs and icon buttons on 20 pages. Saw: none without a name | pass |
| 2C: focus visible | Tab through; screenshot of a focused field. Saw: blue outline on buttons and fields | pass |
| 2C: dialogs trap focus and return it | opened the confirm dialog from a keyboard-focused button; Tab x 8; Escape; same for the Add a project drawer. Saw: 8 of 8 Tabs stayed inside; focus went back to the opener | pass |
| 2C: live regions announce | read #sr-live after navigating to Settings and after a field error. Saw: "Settings", "Paste the key first." | pass |
| 2C: tap targets of at least 24 px | measured buttons and links on six pages | BUG-17 |
| action seq | run in every form submit (Enter) and in dialog buttons across the journeys | pass |
| action preventDefault | run with every Enter-to-submit form | pass |
| action stopPropagation | run by the ledger row Open full log button | pass |
| action onActivateKey | Enter and Space on ledger rows | pass |
| action onEnter | Enter in the Scan path, guardrail, run argument and note fields | pass |
| action dockHome | clicked the Q logo | pass |
| action morePrivacy | More menu > What PRIVATE means at 375 px (the sheet lists it) | pass |
| action cycleCancel | Cancel in the cycle dialog | pass |
| action runCancel | Cancel in the Run dialog | pass |
| action briefClose | Cancel in the ask-for-changes box | pass |
| action briefNote | typed in the ask-for-changes box; kept across 7 s | pass |
| action tlClear | Clear filters appears only with a filter on; seen and clicked in the timeline sweep | pass |
| action selectBy | clicked in the sweep of every page (demo:missions, demo:panels); no console error, no failed request | pass |
| action cycleProject | project select in the cycle dialog (only one project, so it shows a fixed name) | pass |
| action cycleIssue | typed issue 999 and started: toast "Cycle started"; the mission later shows blocked "could not read issue #999" | pass |
| action caseStepBy | clicked in the sweep of every page (demo:showcase); no console error, no failed request | pass |
| action prsReload | clicked in the sweep of every page (demo:prs, real:prs); no console error, no failed request | pass |
| action onlyOurs | clicked in the sweep of every page (demo:prs, real:prs); no console error, no failed request | pass |
| action fetchCardSel | looked for the control; needs a GitHub project board; the fake gh serves none, so the Board has no cards | not tested: needs a GitHub project board; the fake gh serves none, so the Board has no cards |
| action replayIdx | the day slider in Replay (script-driven input) | pass |
| action calmShowAll | Calm Home: Show everything | pass |
| action crewFilter | clicked in the sweep of every page (demo:crew, real:crew); no console error, no failed request | pass |
| action reloadPage | looked for the control; shown only when the interface components or the agent list fail to load; could not be triggered without breaking the page | not tested: shown only when the interface components or the agent list fail to load; could not be triggered without breaking the page |
| action seeAttention | looked for the control; part of the My rhythm preview, which needs recorded activity (Demo concept preview); not reached | not tested: part of the My rhythm preview, which needs recorded activity (Demo concept preview); not reached |
| action brainErrClear | looked for the control; shown only when the 3D view fails to start; WebGL worked | not tested: shown only when the 3D view fails to start; WebGL worked |
| action copyCommand | clicked in the sweep of every page (real:overview); no console error, no failed request | pass |
| action firstRunDemo | first-run screen: Look around in Demo (double-click gave one POST) | pass |
| action firstRunSkip | first-run screen: Skip | pass |
| action homeTicket | Home next-step button path (See why) | pass |
| action ackInbox | Acknowledge on the add-on alert and a local alert; confirm asked | pass |
| action addSched | Operations > New schedule > Add schedule with bad and good values | pass |
| action approveMissionPlan | double-clicked Approve this plan | BUG-7 |
| action attachAdd | double-clicked Attach this project | BUG-3 |
| action backToLedger | Back to Ledger after Open full log | pass |
| action bargeInToggle | looked for the control; Helm voice; needs a microphone | not tested: Helm voice; needs a microphone |
| action briefAct | Approve the brief and Write the next version buttons (approve asks for confirmation) | pass |
| action briefAsk | Ask for changes opens the note box | pass |
| action briefForIssue | looked for the control; needs a project with the brief duty on and a mission with an issue; not set up | not tested: needs a project with the brief duty on and a mission with an issue; not set up |
| action briefRetry | looked for the control; needs a brief whose mock-ups failed; the fake provider makes no mock-ups | not tested: needs a brief whose mock-ups failed; the fake provider makes no mock-ups |
| action briefSend | Send my notes with a note and with an empty note ("Say what should change first.") | pass |
| action capDone | clicked in the sweep of every page (demo:overview); no console error, no failed request | pass |
| action capSubmit | Enter in the Brain dump box | pass |
| action caseStepTo | clicked in the sweep of every page (demo:showcase); no console error, no failed request | pass |
| action closeCard | looked for the control; needs a GitHub project board; the fake gh serves none | not tested: needs a GitHub project board; the fake gh serves none |
| action closeDrawer | Cancel in the focus drawer | pass |
| action closeMissionPage | pressed "All missions" on a mission page: lands on the Mission picker, not the list | BUG-18 |
| action closeMobileMenu | chose a place in the More sheet at 375 px; the sheet closed | pass |
| action closePalette | Esc and choosing a result | pass |
| action asAdd | agent source Add source with 7 inputs | pass |
| action asPreset | both presets | pass |
| action asRemove | Remove the agent source, confirm | pass |
| action connAddOpen | Add another account on Slack, opened and cancelled | pass |
| action connAddSave | Add account form with a label and a fake token | pass |
| action connEnable | Slack switch on and off | pass |
| action connHelp | all 9 help buttons | pass |
| action connRemove | Remove Slack user token, confirm; "Removed." | pass |
| action connRemoveAccount | clicked in the sweep of every page (demo:connections); no console error, no failed request | pass |
| action connSave | reached through connSaveAll (single-field cards) | pass |
| action connSaveAll | saved a Slack token: toast says Saved, but the card kept saying "needs credentials: create ~/.config/quarterdeck/integrations.env (see the README)" | BUG-19 |
| action connSignCancel | looked for the control; needs a real Google or Meta sign-in | not tested: needs a real Google or Meta sign-in |
| action connSignin | looked for the control; needs a real Google or Meta sign-in | not tested: needs a real Google or Meta sign-in |
| action connStore | looked for the control; the macOS Keychain is not available on this computer (the card says so) | not tested: the macOS Keychain is not available on this computer (the card says so) |
| action connTest | Test on GA4 and Slack with no and fake credentials | pass |
| action crewRun | clicked in the sweep of every page (demo:prs); no console error, no failed request | pass |
| action crewEnable | Available fold, Enable the marshal, confirmed | pass |
| action liveJump | clicked in the sweep of every page (demo:crew, real:crew); no console error, no failed request | pass |
| action crewSchedule | Schedule button in the Run dialog Advanced fold (opens Operations form) | pass |
| action openRun | Run on a duty card | pass |
| action runGo | Run the surveyor with no target; hostile extra argument refused ("bad value:") | pass |
| action runPaint | toggled Write for real in the Run dialog | pass |
| action dockStartOver | Helm dock Start over | pass |
| action dockGo | clicked in the sweep of every page (demo:overview, demo:projects, demo:prs, demo:settings); no console error, no failed request | pass |
| action dockToggle | clicked in the sweep of every page (demo:board, demo:brain, demo:connections, demo:crew); no console error, no failed request | pass |
| action explainWrites | clicked in the sweep of every page (demo:settings, real:settings); no console error, no failed request | pass |
| action fileAsIssues | clicked in the sweep of every page (demo:documents); no console error, no failed request | pass |
| action fixItem | clicked in the sweep of every page (demo:missions, demo:panels); no console error, no failed request | pass |
| action fixSelected | clicked in the sweep of every page (demo:missions, demo:panels); no console error, no failed request | pass |
| action fleetAct | clicked in the sweep of every page (demo:fleet); no console error, no failed request | pass |
| action focusEdit | project box and share in My focus | pass |
| action go | clicked in the sweep of every page (demo:inbox, demo:missions, demo:operations, demo:overview); no console error, no failed request | pass |
| action helmOrb | clicked in the sweep of every page (demo:board, demo:brain, demo:connections, demo:crew); no console error, no failed request | pass |
| action leaveBrain | clicked in the sweep of every page (demo:brain, real:brain); no console error, no failed request | pass |
| action linkPanelToMission | Link as evidence | pass |
| action loadBoard | clicked in the sweep of every page (demo:board); no console error, no failed request | pass |
| action markSeen | looked for the control; part of the My rhythm attention estimate; not reached | not tested: part of the My rhythm attention estimate; not reached |
| action mergePr | Merge button on the Pull requests page: the confirm names the PR and says it makes a real merge; cancelled (not confirmed on purpose) | pass |
| action noteAdd | typed 1001 characters and pressed Enter | BUG-9 |
| action noteDone | Done and Reopen (double-click sent two POSTs, harmless) | pass |
| action noteEditSave | Save with empty text ("A note cannot be empty.") and with text | pass |
| action noteEditStart | pressed Edit on a note; read the console | BUG-10 |
| action noteEditStop | Cancel in the note editor | pass |
| action noteFilter | Open, Done, All, and the search box | pass |
| action notePromote | To a mission (no confirm) and To a plan (confirm, spends tokens) | pass |
| action noteTag | chose a project for a note | pass |
| action nwMakeBrief | exercised in a journey | pass |
| action openScope | clicked in the sweep of every page (demo:board, demo:crew, demo:documents, demo:fleet); no console error, no failed request | pass |
| action openAttach | Add a project button | pass |
| action openAttention | More menu item cannot be clicked with a mouse; works by keyboard or script | BUG-11 |
| action openCard | looked for the control; needs a GitHub project board; the fake gh serves none | not tested: needs a GitHub project board; the fake gh serves none |
| action openCycleDialog | Start a full cycle on Operations | pass |
| action openDoc | clicked in the sweep of every page (demo:documents, demo:missions, demo:panels, real:documents); no console error, no failed request | pass |
| action openFocusDrawer | More menu item cannot be clicked with a mouse; works by keyboard or script | BUG-11 |
| action openFullLog | Open full log in a ledger row | pass |
| action openMission | opened a mission draft | pass |
| action openMissionPage | opened 9 missions | pass |
| action openPalette | Ctrl+K and the search box | pass |
| action openPanel | clicked in the sweep of every page (demo:missions, demo:panels, real:missions, real:panels); no console error, no failed request | pass |
| action openShowcase | exercised in a journey | pass |
| action openWhatChanged | More menu item cannot be clicked with a mouse (the Home dock button works) | BUG-11 |
| action palGo | chose a palette result | pass |
| action pickCase | clicked in the sweep of every page (demo:showcase); no console error, no failed request | pass |
| action planAct | looked for the control; needs a plan from the GitHub project board (qtdeck plan); not set up | not tested: needs a plan from the GitHub project board (qtdeck plan); not set up |
| action planMove | looked for the control; needs a plan from the GitHub project board; not set up | not tested: needs a plan from the GitHub project board; not set up |
| action projSwitch | scope select: all projects and sample-react | pass |
| action proposeMissionPlan | Propose a plan, confirmed | pass |
| action publishShowcase | Publish: confirm asked; payload escaped; public route needs the pairing cookie | pass |
| action queueAction | looked for the control; needs a real fix queue, which files GitHub issues and runs the fix pipeline; Demo only showed "2 queued" | not tested: needs a real fix queue, which files GitHub issues and runs the fix pipeline; Demo only showed "2 queued" |
| action replayStep | Previous day / Next day in Replay | pass |
| action restartDemo | Demo banner Restart scenario ("Scenario restarted from the beginning.") | pass |
| action rhythmScope | looked for the control; My rhythm project select needs recorded activity; not reached | not tested: My rhythm project select needs recorded activity; not reached |
| action rowClick | clicked in the sweep of every page (demo:board); no console error, no failed request | pass |
| action rowKey | Enter on a ledger row | pass |
| action runHarbourmaster | looked for the control; Reconcile needs a GitHub project board; not set up | not tested: Reconcile needs a GitHub project board; not set up |
| action runNext | Home See why | pass |
| action saveFocus | Save focus ("Focus saved on this Mac.") | pass |
| action saveMissionDraft | Save draft | pass |
| action saveMissionEdit | Save changes | pass |
| action saveShowcaseDraft | New case study draft with hostile text; "draft saved" | pass |
| action saveShowcaseEdit | Save changes then publish | pass |
| action schedAction | Pause, Resume, Remove (cancel then confirm) | pass |
| action selectAddon | looked for the control; no add-on with its own page place exists (a local add-on has no page script) | not tested: no add-on with its own page place exists (a local add-on has no page script) |
| action selectPlace | looked for the control; no add-on with its own page place exists | not tested: no add-on with its own page place exists |
| action selectProject | scope select and palette | pass |
| action setBilling | panel to API key and back | pass |
| action setBrainMode | Map and Rhythm | pass |
| action setCapSave | typed 12.5 in the daily cap | BUG-14 |
| action setFleetView | clicked in the sweep of every page (demo:projects); no console error, no failed request | pass |
| action setHandsFree | looked for the control; Helm voice; needs a microphone | not tested: Helm voice; needs a microphone |
| action setKeyRemove | Remove the API key, confirm | pass |
| action setKeySave | empty, wrong and fake key | pass |
| action setLens | looked for the control; needs mission evidence that carries a diff or plan; not set up | not tested: needs mission evidence that carries a diff or plan; not set up |
| action setSizeBy | Agent activity and My attention | pass |
| action setTheme | dark, light, auto | pass |
| action sgSpeakToggle | looked for the control; Helm voice; needs a speaker and a model | not tested: Helm voice; needs a speaker and a model |
| action showGuardrails | clicked in the sweep of every page (demo:board, demo:crew, demo:documents, demo:inbox); no console error, no failed request | pass |
| action showLog | clicked in the sweep of every page (demo:log); no console error, no failed request | pass |
| action showPrivacy | More menu at 375 px; the PRIVATE pill is not shown at 1280 px | pass |
| action setHideHandled | Hide handled missions switch | pass |
| action dismissedToggle | 1 dismissed fold | pass |
| action oldToggle | Older than 7 days fold | pass |
| action dismissMission | double-clicked Dismiss | BUG-7 |
| action markMerged | looked for the control; the page records a merge by itself when the mission is opened, so the button never appeared | not tested: the page records a merge by itself when the mission is opened, so the button never appeared |
| action closeIssueFor | Close the issue: confirm; one gh issue close with a comment | pass |
| action retryMission | Try again: cancel, then yes | pass |
| action startCycle | Start the cycle (double-click gave one POST) | pass |
| action startMissionPanel | pressed Start with a spec panel on an objective with punctuation or constraints | BUG-8 |
| action stopRun | looked for the control; no real run was running when a Stop button was present; the one Stop button seen belonged to a stale lock (BUG-13) | not tested: no real run was running when a Stop button was present; the one Stop button seen belonged to a stale lock (BUG-13) |
| action talkSubmit | looked for the control; Helm chat; needs a real model | not tested: Helm chat; needs a real model |
| action thinkToggle | looked for the control; Helm chat switch; needs a microphone or a real model | not tested: Helm chat switch; needs a microphone or a real model |
| action tlClick | timeline marker | pass |
| action tlHover | exercised in a journey | pass |
| action tlSet | timeline window and filters | pass |
| action toggleCalm | Settings Calm switch, on and off | pass |
| action toggleDemo | Demo switch on and off; data folder unchanged (checksums) | pass |
| action toggleLedger | ledger rows open and close | pass |
| action toggleMissionForm | New mission draft | pass |
| action toggleMobileMenu | More button at 375 px | pass |
| action toggleOld | looked for the control; needs older superseded documents; none exist | not tested: needs older superseded documents; none exist |
| action toggleReplay | More menu item cannot be clicked with a mouse; works by keyboard or script | BUG-11 |
| action toggleSched | New schedule | pass |
| action toggleSel | clicked in the sweep of every page (demo:missions, demo:panels); no console error, no failed request | pass |
| action toggleShowcaseForm | New case study draft | pass |
| action unpublishShowcase | Unpublish and remove access ("unpublished, access removed") | pass |
| action unqueue | looked for the control; needs a real fix queue; see queueAction | not tested: needs a real fix queue; see queueAction |
| action workOn | clicked in the sweep of every page (demo:board); no console error, no failed request | pass |
| action grEdit | typed in a guardrail | pass |
| action grNew | typed in the new guardrail box | pass |
| action grAdd | Add this guardrail | pass |
| action grRemove | removed a guardrail | pass |
| action grMove | moved a guardrail up and down | pass |
| action grSave | Save guardrails ("Guardrails saved.") | pass |
| action openProject | clicked in the sweep of every page (demo:projects); no console error, no failed request | pass |
| action openProjects | 1 thing needs you in 1 project | pass |
| action addonNeeds | clicked in the sweep of every page (demo:projects); no console error, no failed request | pass |
| action homeDay | clicked in the sweep of every page (demo:overview); no console error, no failed request | pass |
| action finToggle | clicked in the sweep of every page (demo:overview, real:overview); no console error, no failed request | pass |
| action trajToggle | Finished recently fold | pass |
| action tkRequest | typed a ticket request; counter shows N of 2000 | pass |
| action tkDraft | Draft tickets (no confirm: the page says it costs a few cents) | pass |
| action tkFile | saved a draft of tickets that already exist; double-click also adds an error toast (BUG-6) | BUG-5 |
| action tkDiscard | Discard draft, confirm | pass |
| action tkRepoName | typed a repo name | pass |
| action tkRepoSave | Save with 5 values | pass |
| action tkRepoCreate | Create a private GitHub repo: two confirms; fake gh refused plainly ("gh did not give a plain GitHub user name, so nothing was created.") | pass |
| action tkMission | clicked in the sweep of every page (real:projects); no console error, no failed request | pass |
| action rdShow | Ready? Show the checklist | pass |
| action rdToggle | all six rows | pass |
| action rdNext | Run it once to prove it / Start a mission | pass |
| action rdProve | Prove it again | pass |
| action rdDraft | single click works; double-click flashes the dialog and cancels | BUG-4 |
| action rdApply | Put it on a new branch: cancel then confirm | pass |
| action rdTurnOn | Turn on the joiner (attach drawer and Ready card) | pass |
| action rdCycle | Allow cycles, confirmed | pass |
| action rdProveStop | Stop the verify command after 3 s | pass |
| action rdUseVerify | looked for the control; needs a project where the scan finds only candidate commands and no verify command; the test projects all had one | not tested: needs a project where the scan finds only candidate commands and no verify command; the test projects all had one |

## Bugs

### BUG-1: A first tab that is overtaken by a second tab in the same browser says only "forbidden" on every write

- Severity: annoying
- Steps: 1. qtdeck dashboard link, open in tab A. 2. Make another link and open it in tab B of the same browser profile. 3. In tab A type a note in Brain dump and press Enter.
- Expected: Tab A says plainly that it was disconnected and offers a way back (a new link), as the unpaired screen does.
- Actual: Tab A keeps showing live data (reads still work because the cookie is shared) but every write fails; a toast says only "forbidden". Reloading tab A then shows the unpaired screen.
- Exact error text: forbidden (HTTP 403 on POST /api/capture)
- Suspected location: dashboard/index.html post() lines 408-416 (only 401 is handled; 403 falls into the generic toast); bin/dashboard.py pair handling replaces the cookie
- Fix size: small fix (treat a 403 token mismatch like 401 and show the unpaired screen)

### BUG-2: A folder that holds several projects can be scanned and attached as one project

- Severity: annoying
- Steps: 1. Projects > Add a project. 2. Paste the path of the Projects folder that contains sample-react and sample-web. 3. Press Scan.
- Expected: Refused like the home folder is: "is a whole folder of projects, not one project. Choose the project's own folder inside it".
- Actual: Step 2 of 5 shows a scan of the folder as one project named after the parent (here "Projects": React 18 with Vite ...), and Attach is offered.
- Exact error text: none (no refusal)
- Suspected location: bin/attach.py or the path check that produces "is a whole folder of projects" (only the home folder triggers it)
- Fix size: small fix (refuse a folder with no project markers of its own whose children are repositories), but the rule needs a decision

### BUG-3: Double-clicking Attach this project shows a raw Python error beside the success

- Severity: annoying
- Steps: 1. Projects > Add a project. 2. Scan <home>/Projects/sample-react. 3. Double-click Attach this project.
- Expected: One attach, one confirmation; the second click is ignored while the first is running.
- Actual: The project is added once, but two toasts appear: a red error with a Python errno and a green "Added sample-react.". The two requests race on one temporary file.
- Exact error text: [Errno 2] No such file or directory: '<data folder>/config/projects.tmp'
- Suspected location: dashboard/index.html attachAdd() (line ~4086, no busy guard); bin/attach.py or the registry writer that writes config/projects.tmp (needs a unique temp name or a lock)
- Fix size: small fix (busy flag in attachAdd, and a unique temp file name in the registry writer)

### BUG-4: Double-clicking an action that asks for confirmation flashes the dialog and cancels it

- Severity: cosmetic
- Steps: 1. Open a project with a missing README. 2. Ready > Docs > double-click Draft a README.
- Expected: One confirmation dialog stays open (the second click is ignored).
- Actual: The confirmation dialog opens and is closed again by the second click landing on the overlay; nothing is drafted and nothing is said. (No double effect, but a visitor who double-clicks sees nothing happen.)
- Exact error text: none
- Suspected location: dashboard/index.html confirmDlg() lines ~296-305 (sl-dialog closes on overlay click)
- Fix size: small fix (ignore a request-close that arrives in the first ~300 ms, or set the dialog to require a button)

### BUG-5: Saving a draft whose tickets already exist says "Saved 2 tickets" but saves none

- Severity: annoying
- Steps: 1. Project with local tickets "Clear the completed todos" and "Show a summary line". 2. Draft tickets again with the same request. 3. Press Save 2 tickets on this computer.
- Expected: Either two new tickets, or a plain message that they already exist.
- Actual: Toast "Saved 2 tickets on this computer."; the ticket list is unchanged (still 2, next id still 3) and the draft disappears.
- Exact error text: none (success toast)
- Suspected location: dashboard/index.html tkFile() line ~1861 (always toasts n tickets); bin/tickets.py file step drops duplicates silently
- Fix size: small fix (report the number actually saved)

### BUG-6: Double-clicking Save tickets adds a second error toast naming a CLI command

- Severity: cosmetic
- Steps: 1. Have a draft. 2. Double-click Save 2 tickets on this computer.
- Expected: One save; the second click ignored.
- Actual: Two POST /api/ticket/file are sent; the second returns an error shown as a red toast beside the green one. Tickets are not doubled.
- Exact error text: no draft d2 for sample-react (see: qtdeck ticket list sample-react)
- Suspected location: dashboard/index.html tkFile() lines 1851-1863 (no busy guard)
- Fix size: small fix (busy flag)

### BUG-7: Double-clicking Dismiss or Approve this plan records the action twice

- Severity: cosmetic
- Steps: 1. Open a finished mission, double-click Dismiss. 2. Open a mission with a proposed plan, double-click Approve this plan.
- Expected: One request, one toast, one history line.
- Actual: Two POST /api/mission(s) are sent; two identical toasts; the mission timeline shows "plan revision 1 approved" twice and the missions log has two dismiss lines.
- Exact error text: none
- Suspected location: dashboard/index.html dismissMission() ~2285 and approveMissionPlan() (no busy guard); bin/dashboard.py approve_plan does not ignore a repeat of the same revision
- Fix size: small fix (busy flag, and make a repeated approval of the same revision a no-op)

### BUG-8: "Start with a spec panel" fails with a raw error for any objective that has constraints, success criteria or punctuation

- Severity: annoying
- Steps: 1. Missions > New mission draft with objective "Sort the list (by date), please?" (or fill Constraints). 2. Open it, Propose a plan, Approve this plan. 3. Press Start with a spec panel and confirm.
- Expected: The panel starts, or the form says up front which characters are not allowed.
- Actual: A red toast shows the objective text prefixed by an internal message and nothing starts. Only plain words, up to 200 characters, on one line, work (so any mission with Constraints or Success criteria always fails).
- Exact error text: bad value: Sort the list (by date), please?   (HTTP 400 on POST /api/missions)
- Suspected location: bin/dashboard.py line 2838 and SAFE_VALUE at line 84 (the idea text is passed as a run argument and checked as a safe token); start_panel at lines 2717-2735 joins constraints with newlines
- Fix size: needs a design decision (pass the idea through a file or stdin instead of an argument)

### BUG-9: A note longer than 1000 characters is cut to 1000 and reported as Saved

- Severity: cosmetic
- Steps: 1. Notes > New note. 2. Paste 1001 characters. 3. Press Enter.
- Expected: The field stops at 1000 (as the Edit box does) or says the note is too long.
- Actual: Toast "Saved"; the stored note has 1000 characters; the last character is lost silently. The New note box has no maxlength, the Edit box has.
- Exact error text: none
- Suspected location: dashboard/index.html noteAdd()/slInput note-new (line ~4404, no maxlength); bin/dashboard.py capture (clip to 1000)
- Fix size: small fix (add maxlength=1000 to the New note and Brain dump inputs)

### BUG-10: Edit on a note throws a console TypeError

- Severity: cosmetic
- Steps: 1. Notes with at least one note. 2. Press Edit on a note. 3. Read the browser console.
- Expected: No error; the edit box is focused.
- Actual: The edit box opens, but an error is logged and focus may not move.
- Exact error text: TypeError: Cannot read properties of null (reading 'focus') at SlTextarea.focus (chunk.D4SUTPHP.js:137) at SlButton.noteEditStart (index.html:4417)
- Suspected location: dashboard/index.html noteEditStart() line 4417 (focuses the textarea before the component is upgraded; wait for updateComplete)
- Fix size: small fix

### BUG-11: The Brain's More menu opens behind the 3D map: Replay, Attention, What changed and My focus cannot be clicked

- Severity: annoying
- Steps: 1. Brain (left rail). 2. Click More in the toolbar. 3. Try to click Replay.
- Expected: A menu with five items appears over the map and each item can be clicked.
- Actual: Only a thin sliver of the menu shows under the More button; document.elementFromPoint at the Replay item returns the map canvas, so the mouse hits the canvas. The same items work when reached by keyboard or by script.
- Exact error text: none (Playwright: <canvas class="brain-canvas"> intercepts pointer events)
- Suspected location: dashboard/assets/ui.css line 734 (.brain-bar{container:bbar/inline-size;contain:layout} traps the dropdown popup in the bar's stacking level, under .brain-canvas at line 754)
- Fix size: small fix (give .brain-bar a higher z-index and drop contain:layout, or let the popup escape with hoist)

### BUG-12: The dashboard can turn an agent on but has no control to turn it off again

- Severity: annoying
- Steps: 1. Agents (Crew) page for a project. 2. Open Available and press Enable on any agent. 3. Look for a way to switch it back off (Crew, Projects Ready card, Settings).
- Expected: A control to switch the agent off, as the brief says ("switch each on and off").
- Actual: Only Enable / Turn on exist (rdTurnOn, crewEnable, rdCycle). Turning off needs the CLI (qtdeck disable).
- Exact error text: none
- Suspected location: dashboard/index.html lines 2143, 2149 and 2971 only ever POST /api/project/duties with add; no call sends remove
- Fix size: needs a design decision (a confirm-first Turn off button; the API already accepts remove)

### BUG-13: Finished panel and shipwright runs leave their lock folder behind; the Crew page can then show a finished run as Running with a Stop button

- Severity: annoying
- Steps: 1. Run a panel (Missions > Start with a spec panel) or a mission on a ticket. 2. Wait until the log says the run is done. 3. ls <data folder>/state/*.lock. 4. Open Agents for the project.
- Expected: No lock remains; the card says idle.
- Actual: state/panel-<project>-spec.lock, panel-<project>-ticket1.lock, shipwright-<project>-t2.lock stay after the runs exit. The folders are only treated as stale while their pid is dead; once a pid is reused the Crew page showed "panel running ... Running now 23:49" with a Stop button for a run whose log had finished, and a new run of the same duty would say "already running".
- Exact error text: none (observed in the UI as Running now 23:49 with no process)
- Suspected location: duties/panel.sh line 138 (trap 'rm -rf "$TMP"' EXIT replaces the lock release set by acquire_lock in bin/lib.sh line 529) and duties/shipwright.sh line 99 (trap 'cleanup_wt' EXIT); purser.sh line 230 has a comment warning of exactly this
- Fix size: small fix (call the lock release from the new trap)

### BUG-14: A daily cap with cents (12.5) is ignored without a message

- Severity: cosmetic
- Steps: 1. Settings > Billing. 2. Type 12.5 in the daily cap box and press Enter.
- Expected: Saved, or a message that whole dollars are needed.
- Actual: Nothing is sent and nothing is said (the number box rejects 12.5 as a step mismatch). The max-value message also says "or null for none".
- Exact error text: none (for 12.5); for 1000000000: a cap is a number of dollars, or null for none
- Suspected location: dashboard/index.html setCapSave() (number input with default step); bin/dashboard.py cap validation text
- Fix size: small fix (step="any" and plain wording)

### BUG-15: Calm mode at 375 px: the agent source preset button is wider than the screen

- Severity: cosmetic
- Steps: 1. Turn Calm on (Settings). 2. Open the page at 375 px width. 3. Connections, scroll to Agent sources.
- Expected: The button text wraps inside the screen.
- Actual: "A dashboard reached through my own SSH tunnel" is 377 px wide and is cut off at the right edge (its right edge is at 414 px).
- Exact error text: none
- Suspected location: dashboard/assets/ui.css (sl-button white-space: nowrap under .calm larger text); the preset buttons in dashboard/index.html asPreset row
- Fix size: small fix (allow the preset buttons to wrap)

### BUG-16: A red error toast covers the Create it button of the Add a project drawer

- Severity: cosmetic
- Steps: 1. Projects > Add a project. 2. Press Create it with an empty name (red toast). 3. Press Create it again within 9 seconds.
- Expected: The button can be pressed.
- Actual: The toast (closable, 9 s) sits over the button; the second press lands on the toast until it is closed or times out.
- Exact error text: none (Playwright: <sl-alert ...> from <div class="sl-toast-stack"> subtree intercepts pointer events)
- Suspected location: dashboard/assets/ui.css toast stack position (bottom right) over the drawer footer
- Fix size: small fix (move the toast stack or give errors a field message as the Scan box does)

### BUG-17: Text-style buttons and links are 16 to 21 px tall

- Severity: cosmetic
- Steps: 1. Home, Projects, Missions, Settings. 2. Measure the link-style buttons ("All notes", "Open the full timeline", "Ready? Show the checklist", "issue #901", "Finished recently").
- Expected: At least 24 by 24 px (WCAG 2.2, 2.5.8).
- Actual: 24 controls measured 16 to 21 px tall.
- Exact error text: none
- Suspected location: dashboard/assets/ui.css .link / .mlink styles
- Fix size: small fix (padding or min-height)

### BUG-18: The "All missions" button on a mission page leads to a Mission picker, not the Missions list

- Severity: cosmetic
- Steps: 1. Projects > a project > Missions. 2. Open any mission. 3. Press "← All missions".
- Expected: The Missions list the person came from.
- Actual: The page title becomes "<project> · Mission" and shows "Full cycle ... Start a full cycle" and "Pick one to focus on". The browser Back button returns to the mission.
- Exact error text: none
- Suspected location: dashboard/index.html closeMissionPage() line 1735 (clears the id but stays on the mission view)
- Fix size: small fix (go("missions") from closeMissionPage)

### BUG-19: After a credential is saved the card still says "needs credentials: create ~/.config/quarterdeck/integrations.env"

- Severity: cosmetic
- Steps: 1. Connections > Slack. 2. Paste a token, Enter (toast: Saved. It will not be shown again.). 3. Look at the Slack card.
- Expected: The card says the token is saved and what the next step is (switch it on, Test).
- Actual: The card keeps the old status line, which sends a first-time user to edit a file that the form on the same card just replaced, until the next scheduled refresh (and after enabling it says "network error: could not reach the service" without saying the token was accepted).
- Exact error text: needs credentials: create ~/.config/quarterdeck/integrations.env (see the README)
- Suspected location: dashboard/index.html connSaveAll() ~2607 (does not reload the status after saving); the status text comes from bin/integrations/*
- Fix size: small fix (refresh the card after a save; word the message for the form)

## Not tested

- Helm voice and chat (talkSubmit, setHandsFree, bargeInToggle, sgSpeakToggle, thinkToggle): need a microphone, a speaker or a real model.
- Google and Meta sign-in (connSignin, connSignCancel) and the macOS Keychain (connStore): need real accounts or a Mac.
- GitHub project board features (loadBoard cards, openCard, closeCard, fetchCardSel, runHarbourmaster, planAct, planMove): the fake gh serves no board. Mac owner steps: attach a project with a real board, open Board, press a card, press Reconcile.
- Fix queue (queueAction, unqueue): a real queue files GitHub issues and runs the pipeline; only the Demo path ("2 queued") was tried.
- Mark as merged (markMerged): the page records the merge by itself when the mission is opened, so the button never appeared. Steps: open a mission whose PR merged while gh was unreachable, then reachable.
- My rhythm and Attention estimate (seeAttention, rhythmScope, markSeen): need recorded activity; the real data folder had none and Demo shows a preview only.
- Add-ons with their own page (selectAddon, selectPlace): a local add-on cannot have page code; only an alert add-on was tried.
- Mission lens (setLens) and briefs for an issue (briefForIssue, briefRetry): need evidence with a diff, a project with the brief duty plus an issue mission, and a failed mock-up.
- reloadPage and brainErrClear: shown only when the interface components, the agent list or the 3D view fail to load; not triggered.
- A verify command that hangs until its own limit: only Stop was tried (the limit is long).
- rdUseVerify and toggleOld: need a project with no detected verify command and older superseded documents.
- Real clipboard denial path of Copy: only the allowed path and the fallback toast text were seen.
- Full disk and read-only data folder are not part of this part (other tester).
- Notes for the docs tester: qtdeck addon new prints "Guide: docs/public/ADDONS.md" but the guide is ADDONS.md at the repository root; the Home page says there is no live data because a hook is not installed and prints a path inside the fake data folder.

## Five worst things

1. The Brain's More menu opens behind the 3D map, so Replay, Attention, What changed and My focus cannot be clicked with a mouse (BUG-11).
2. Start with a spec panel refuses every mission that has Constraints or Success criteria, or any punctuation, with a raw "bad value:" toast (BUG-8).
3. Several actions have no busy guard: a double click on Attach shows a raw Python error beside the success, on Save tickets a CLI-flavoured error, on Dismiss and Approve a duplicate record (BUG-3, BUG-6, BUG-7).
4. Pairing a second tab in the same browser leaves the first tab looking live while every write says only "forbidden" (BUG-1).
5. Finished panel and shipwright runs leave their lock folders behind, so the Crew page can show a finished run as Running with a Stop button, and a reused process number would block the next run (BUG-13).

## Accessibility findings

- Pass: every button, link, switch, field and icon button on 20 pages has an accessible name (none found without one).
- Pass: skip link, one main landmark, two named navs, one visible h1 per page, lang set, heading order h1 > h2 > h3.
- Pass: Tab order follows reading order on Projects (skip link, rail, search, scope, tabs, Ready card, ticket box, buttons); focus is visibly outlined on buttons and fields.
- Pass: confirm dialogs and the Add a project drawer keep focus inside (8 of 8 Tabs), close on Escape and hand focus back to the button that opened them.
- Pass: live regions announce page changes ("Settings") and field errors ("Paste the key first."); toasts for success are spoken once, errors stay as alerts.
- Pass: the Brain can be left with Esc; every node is reachable through the count chips and lists with the keyboard; the Brain More menu items are reachable by keyboard (arrows) even though the mouse cannot reach them (BUG-11).
- Fail (cosmetic): 24 link-style buttons and links are 16 to 21 px tall, under the 24 px target size (BUG-17).
- Note: the 3D scene itself has no focusable nodes; its content is only reachable through the lists.
- Note: in the Replay panel the slider and the Previous day and Next day buttons were driven by script; a screen reader pass on the slider was not done.
- Not checked: real screen reader speech output (only the live region text and names were read), colour contrast, and zoom to 200 percent.
