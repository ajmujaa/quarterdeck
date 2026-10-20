# Tasks for the cloud session, round 2 (2026-10-20)

Base: branch `cloud/connections` (it has everything so far). Work on `cloud/projects-flow`, push it,
report in `docs/reports/cloud-projects-flow.md`. Same rules as before: no Co-Authored-By or
Claude-Session lines, no em dashes in user-facing text, no real home folders or secrets in tests,
nothing loads from the internet at runtime, never push to main, `python3 bin/check.py` green before you push.

## Why
The owner made a small React (Vite, Vitest) project with no Quarterdeck help and attached it. Findings:
1. `qtdeck attach` says "JavaScript (4)". It does not name React, Vite, Vitest or ESLint.
2. The duty set is always `surveyor, foreman, inspector` plus `shipwright` when a verify command exists.
   It never looks at the stack, so a UI project gets no UI-minded duty and the page does not say why.
3. A project with no GitHub repo can do nothing useful: `shipwright` and `cycle` start from a GitHub issue
   (`gh issue view`). There is no way to say "build me a page" and have the crew make the ticket.

## 1. A scan that knows the stack
In `bin/attach.py` (and what it prints and what the attach page shows): detect framework and tools from
the files (package.json deps and scripts, lockfiles, config files; Python, Go, Rust the same way): name them
("React 18 with Vite, tests by Vitest, lint by ESLint, package manager npm"), propose the build and lint
commands next to verify, and say per duty why it is on or off. Offer the duties that fit the stack as
suggestions, never switched on by themselves. Fixtures for React/Vite, Next, plain Node, Python, Go.

## 2. Tickets made by the crew, and a project without GitHub
- `qtdeck ticket new <project> "<plain request>"`: the planner drafts one to five tickets (title, body,
  acceptance check). Shows the draft. With `--apply` it files them as GitHub issues. Same on the dashboard
  (a "New ticket" box on the project page, drafts first, a click to file). Reuse the planner and the
  existing apply gates; the model never gets gh or credentials.
- Project with no repo: the page and the CLI say so in one sentence and offer, in this order:
  (a) "I already have a GitHub repo": `qtdeck repo <project> <owner/name>`;
  (b) "I have a GitHub account": `qtdeck repo create <project> --private` that runs `gh repo create`
      only after an explicit yes, and only if `gh auth status` is signed in; otherwise it prints `gh auth login`;
  (c) "I have no GitHub account": print the plain steps to sign up at github.com with their email (a person
      must do this: Quarterdeck never creates an account, never touches a password), then continue at (b);
  (d) "Not now": a local-only ticket list in the data folder (state/tickets/<project>.json) that the crew
      can read and `qtdeck cycle` can take, ending in a local branch the owner reviews. A local ticket
      never becomes a GitHub issue unless the owner connects a repo and clicks.
- Everything is also in the dashboard mission view: start a mission from a ticket, see the crew's steps.

## 3. A model-free end-to-end test
Add `fixtures/sample-react/` (a tiny Vite + React todo app, committed as files, git initialised by the
test) and `bin/selftest-flow.sh`: attach it, check the scan output names the stack, create tickets with the
stand-in provider (`providers/fake.sh`), run a cycle from a ticket on the CLI and the same through the
dashboard API (a mission), and check the branch and the verify command result. No network, no real model.
Also write down, in the report, anything in this flow that confuses a newcomer.

## Do not
Create a GitHub account or repo by yourself in any test, or call GitHub at all. Use the existing `gh`
stand-in (`QUARTERDECK_GH`) as the other suites do.

## 4. Attach is onboarding (added by the owner, 2026-10-20; do it after 1 to 3, same branch)
Picture a developer with any project. They attach it and Quarterdeck should get to know it, document what is
missing, set the crew up and then say "ready", with no further reading. The owner's words: "start scan and find out
all about it, make a README or an architecture document, attach the agents and show the user it is ready to work on".
1. **Survey, no model.** The harness gathers facts: folder layout, languages, frameworks, entry points, scripts, test
   and lint and build commands, dependencies of note, CI files, docs that exist and docs that are missing, size, git
   state. Saved as a profile in the data folder (`state/projects/<project>/profile.json`, plus a readable `profile.md`).
2. **Docs that are missing.** If the project has no README or no architecture overview, offer to draft them with a model
   (the existing read-only pattern, the facts above as the only input, hostile text in the repo treated as data). The
   draft is shown first. Only on an explicit yes (`--apply`, or a click) it goes onto a new branch as a pull request or
   a local branch. Never on the default branch, never overwriting a file that exists.
3. **Crew set up.** Duties chosen from the profile with reasons (section 1), the profile handed to the agents as their
   stable context so they do not re-read the project every run (the token diet idea; measure the saving if you can).
4. **A "ready" view.** CLI and dashboard show one checklist: scan done, verify command proven to run in the sandbox,
   repo linked or the four options (section 2), docs present or drafted, agents assigned with reasons. Exactly one
   next action at the bottom ("file your first ticket"). Real data only, calm wording, no em dashes.
5. **Both surfaces.** `qtdeck attach <dir>` shows the same flow as the attach page; a `--yes` flag is not needed:
   nothing is written outside the data folder until the owner says so.
Test it in `bin/selftest-flow.sh` with the sample React project and the stand-in provider. Report what a newcomer
would still find confusing.

## 5. Navigation and clear missions (found by the owner using the dashboard, 2026-10-20; do after 4, same branch)
Findings, from the page code and the owner's screenshots:
1. **No browser history.** `dashboard/index.html` keeps the page in a variable and `localStorage` (`go(v)`), and the
   address bar never changes. So Back and Forward do nothing useful, a reload returns to Home, a mission cannot be linked
   or bookmarked, and after Missions to Pull requests and back, the open mission is forgotten (a different view appears).
   Fix: one small router. Page, project scope and open mission live in the URL hash (`#/work/missions/<id>?project=x`),
   `go()` pushes a history entry, `popstate`/`hashchange` restores it, reload and a pasted link open the same place.
   The one-time pairing hash (`#pair=...`) keeps working and is still removed from the address bar. Keep the page's
   security rules (CSP, no new inline script). Test with a headless browser: click through five pages, Back four
   times, Forward, reload, deep link.
2. **A mission marked Done shows steps "Not started".** A design-panel mission has Brief and Panel done, then Build, Verify,
   Review "Not started" under a green Done badge. It reads as unfinished or contradictory. Fix: a mission shows only the
   steps its kind needs; the rest show "Not needed" (the page already has a "Skipped" state) or are hidden, and Done is
   explained in one line ("The panel ruled on 10 items; fixing them is optional, start it from the Work tab").
3. **Mission trajectory on Home lists finished missions at full size.** Open missions first and large; finished ones in a
   small collapsed "Finished recently" line. Every row names its project and what is next. Keep it calm.
4. **A project named only by a small label.** On a mission page the project is a tiny crumb (`MISSION · DRYDOCK · DESIGN
   PANEL`). Show the project clearly in the heading area, and make the "All projects" scope visible on every page so the
   owner knows what they are looking at.
5. **Add-ons are not in the project list.** An add-on's alert (for example Hermes) shows under Needs you while the
   "All projects" box and the project list do not mention it. Label such items "Add-on: <name>" and let the scope box
   include the add-on when it is installed, or say plainly why it is separate.
Report what you tested and what still confuses.

## 6. Home is the owner's, Projects is its own page, guardrails are editable (the owner's design, 2026-10-20; ticket #124)
The owner's words: "it feels it all messed up". Home mixes things that belong to one project (Mission trajectory, Needs
you, a Hermes alert on top) with things that belong to the person (Your Day, Brain Dump). Design:
1. **Home = the person, across everything.** Only: Your Day, Brain Dump, a fleet timeline of all projects together,
   Recently finished (small), and Budget today. One calm next action at the top may stay, but it must be about the
   person's day or the single most urgent thing across projects, labelled with its project or add-on.
2. **A Projects page** (own place in the rail). Opens on all projects together: one row or card per project (state, what
   needs the owner, last run, spend). Choosing a project filters the page to that project: its Needs you, Missions
   (open first, finished small), Pull requests, Board, Ledger. The project scope lives in the URL (section 5) and
   shows on every page. Remove the row of project chips under the Home list ("agent-fleet Idle, drydock Idle...") and the
   "All projects" box on pages where it means nothing; the Projects page is where scope is chosen.
3. **Needs you and Mission trajectory move to Projects** (Home keeps at most a count that links there).
4. **Add-on alerts** (Hermes) get their own small "Add-ons" strip or the add-on's own page, never the top of Home.
5. **Guardrails can be edited.** The project page shows them read-only today (a dialog from "N guardrails"). Add:
   edit, add, remove, reorder, with a Save that goes through the existing attach edit path (`_attach.edit`), keeps the
   built-in "never merge / never push to the default branch / never touch secrets" ones locked on (shown, not removable,
   with the reason), and records the change in the log. Same from the CLI: `qtdeck guardrail <project> add|remove "..."`.
   Show the effective list the crew really receives.
6. Keep Calm mode working, keep every page real-data-only, no em dashes, no inline script (CSP).
Test with the headless browser: Home shows only the five things; Projects filters; guardrail edit round-trips and a
locked guardrail cannot be removed through the API either.

## 6b. Live work must be visible (owner, 2026-10-20): this is the main reason for the dashboard
The owner: "now the drydock project is running and I don't see any indication in the dashboard about the tasks or what's
going on ... that's the main reason I wanted the dashboard: to see all the projects, and in each project all the git
worktrees and tasks in one place, and in the all-projects view every session running, and which agent does what."
Today the data exists (the fleet hook writes `state/fleet-events/<source>.jsonl`, up to the minute on the owner's machine)
and the Fleet tab shows worktrees, pull requests and live sessions, but it is a tab under Agents, and Home shows none of it.
Change, as part of section 6:
1. **Home gets a "Running now" strip** across all projects: one line per live session or running duty (project, worktree
   or branch, which agent or duty, what it is doing in plain words, how long, waiting on the owner or not). Empty says so.
2. **The Projects page** shows, for the chosen project: its worktrees (branch, state, last activity, linked pull request,
   the session working in it) and the running duties, so every task in flight in that project is on one page. With all
   projects chosen it is the same list across projects, grouped by project.
3. **Which agent does what:** each running item names the crew member or duty and the session (a Claude Code session from
   the hook is a session, a Quarterdeck run is a duty). Never invent: if the hook gives no detail, say "no detail reported".
4. Fleet stays a page, but its content is reachable from Home and from each project, not hidden behind Agents.
5. A header line shows when the live data was last updated and says plainly when the hook is not installed.
Test with fixture events (a session working, one idle, one finished; two projects; a worktree with a draft PR).
