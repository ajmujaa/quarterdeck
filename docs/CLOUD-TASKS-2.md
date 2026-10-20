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
