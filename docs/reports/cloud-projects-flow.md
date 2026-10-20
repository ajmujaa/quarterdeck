# Cloud projects flow: round 2 (2026-10-20)

Branch `cloud/projects-flow`, built on `cloud/connections`, with the current `main` (ea7183c) merged in. Everything below was built and tested with the stand-in
provider and the `gh` stand-in: no network, no real model, no GitHub, no real home folder. `python3 bin/check.py` result at the end of this file.

## 1. A scan that knows the stack
- `bin/scan.py` adds a `stack` object (sentence, facts with evidence, app kind, runnable commands) from files only: Node (React, Next, Vue, Nuxt, Svelte, Astro, Angular, Express, Fastify, NestJS; Vite, webpack; Vitest, Jest, Playwright, Cypress; ESLint, Biome, Prettier, TypeScript, Tailwind; the package manager from `packageManager` or the lockfile), Python, Go and Rust.
  For the React fixture: "React 18 with Vite, tests by Vitest, lint by ESLint, package manager npm". Commands use the detected runner (pnpm, yarn, bun, npm).
- `qtdeck attach` shows build and lint next to verify, the duties that are on with a reason, and `also fit this stack (off)`: joiner, lookout, pilot, marshal, assayer, caulker, quartermaster, trials, each with a reason under `--verbose`. Suggestions are never switched on by themselves.
- `build` is already read by the Shipwright's checks, so it runs inside the existing sandbox; `lint` and `typecheck` are recorded for the owner's review only.
- Fixtures `fixtures/stacks/{react-vite,next,node-plain,python,go,rust}`, suite `bin/selftest-stack.sh` (145 checks), including a hostile package.json that never reaches a command.

## 2. Tickets made by the crew, and a project without GitHub
- `qtdeck ticket new|list|show|file|remove`: the planner (`planner --request`) drafts one to five tickets (title, body, acceptance checks); report-only keeps a draft and files nothing; `--apply` files GitHub issues through foreman's filing code and `gh_post` (credential scan, dedupe by title), or saves LOCAL tickets (`state/tickets/<project>.json`) when there is no repo or `--local` is given. A credential-shaped request is refused before any model call.
- `qtdeck repo <project>` prints one sentence and the four options in order: (a) I have a repo, (b) I have a GitHub account (`repo create --private`, only after a typed yes, only when `gh auth status` is signed in, a second yes before the one push of the default branch), (c) I have no account (plain sign-up steps; a person must do it, Quarterdeck never creates an account or touches a password), (d) not now (local tickets).
- `--ticket n` through purser, dev panel, shipwright and `qtdeck cycle`: the cycle ends on a local branch `ticket/<n>-<slug>` with one commit and a review command; the stages that need a pull request are recorded as Skipped with the reason; nothing is pushed and gh is never called.
- Dashboard: a tickets card (draft first, a click to file or save, the list with status, Start a mission), a repo options card for a project with no repo, and the mission view of a ticket cycle (steps, Skipped stages, branch, review command). API: `GET /api/tickets`, `POST /api/ticket/draft|file|discard`, `POST /api/repo`, `POST /api/cycle/start {ticket}`; all behind pairing, origin, token and `confirm`; Demo mode refuses every write.
- Suites: `selftest-tickets.sh` (172 checks), `selftest-tickets-ui.sh` (80 checks with a real paired dashboard and a headless browser).

## 3. The model-free end-to-end test
`fixtures/sample-react/` (a tiny Vite and React todo app, no README and no architecture document on purpose) and `bin/selftest-flow.sh`: attach, tickets with the stand-in provider, a cycle from a ticket on the CLI (branch, one commit, the diff touches only allowed files, nothing pushed, verify before and after) and the same through the dashboard API (a mission with its steps), negative cases, then the sections 4 and 5 parts. About 230 checks, about 2 minutes.
`docs/reports/flow-confusions.md` lists what confused a newcomer (items 1 to 24; fixed and open are marked).

## 4. Attach is onboarding
- Survey (no model): `bin/survey.py` writes `state/projects/<project>/profile.json` and `profile.md` (layout, entry points, scripts, notable dependencies, docs present and missing, size, git state); re-attaching a registered folder refreshes it and says what changed.
- Docs: a new `scribe` duty (`qtdeck docs <project> [readme|architecture] [--apply]`) drafts a missing README or `docs/ARCHITECTURE.md` with read-only tools; the harness decides the paths; the draft is shown and kept; `--apply` re-checks that the file is still absent, writes a NEW branch only (a pull request when the project has a repo, a local branch otherwise), never the default branch, never overwrites.
- Crew context: the profile reaches every prompt as one bounded data block (at most 3000 characters, about 270 tokens for the sample app, byte-stable, neutralised) and its hash is part of the reuse key. The saving in real runs needs real calls and could not be measured here.
- Ready view: `qtdeck ready <project> [--prove]` and a Ready card: scan, verify (proven by one real run in the sandbox, only on request), repo, docs, agents with reasons, cycles; exactly one next action. `qtdeck enable|disable <project> <duty>|cycle` replaces hand-editing the registry.

## 5. Navigation and clear missions
- A hash router (`dashboard/assets/route.js`): `#/<group>/<view>[/<id>][?project=|addon=]`; only user actions push history; polling never does; Back, Forward, reload, pasted links and a mission link work; the pairing hash is removed at once; bad addresses fall back to Home. Browser test: five pages, Back four times, Forward, reload, deep links, 12 hostile addresses.
- A finished mission shows no "Not started" step (steps its kind does not need are Skipped with a reason) and one sentence under Done; open missions come first and large, finished ones are one small collapsed line; the mission page names the project in its heading; a scope chip; add-ons are labelled "Add-on: <name>" and have a group in the scope box.

## 6. Home, Projects, guardrails
- Home is the person: one calm next action, Your Day, Brain Dump, a fleet timeline, Recently finished, Budget today, and one count line to Projects. Mission trajectory, the Needs you card, the project chips and the add-on block left Home.
- Projects replaces Work in the rail: a card per project (state, needs you, last run, spend, missions, stack, Ready link), an Add-ons strip, and a chosen project's own page with filtered tabs. Old `#/work/...` addresses still open the right page. Scope shows only where it means something (table in `dashboard/UI.md`).
- The Brain tab-order bug (`a11y-check --focus --flows`, 4 findings, present before this round) is fixed: 0 issues in 96 views.
- Editable guardrails (`bin/guardrails.py`): edit, add, remove, reorder on the project page and `qtdeck guardrail <project> list|add|remove|move`, through `attach.edit`; the three built-ins (never merge, never push to the default branch, never touch secrets) are locked in the page, the CLI and the API (a post that drops or edits one is a 400 naming it, registry untouched); credential-shaped rules and prompt markers are refused; every change is logged; the page shows the exact text the crew receives, checked byte for byte against a recorded prompt.

## CI findings fixed on the way
CI (run 39460805590) was red on Ubuntu and macOS. Causes: the flow suite read `verify.json` that only its browser step creates (CI has no browser); `duties/scribe.sh` used a `case` inside `$( )`, a syntax error in macOS bash 3.2 (the whole script is one block, so every scribe check failed); and tests compared paths that differ under macOS `/var` to `/private/var`. Fixed, plus a static check in `selftest-portable.sh` for the `case` form and a real-path temp folder in `selftest-lib.sh`. The macOS fixes come from reading the logs and the code; only a CI run on macOS confirms them.

## What still confuses a newcomer
Open items 10, 11, 12, 14, 16, 18 of `docs/reports/flow-confusions.md`, plus: "scan", "survey" and "profile" are three words for one idea; Spend sits under Projects but has no scope; the Projects overview tab is titled "Projects"; a project card's needs-you count leaves out waiting pull requests; ten tabs in Projects; a reminder outranks a failed run as the next action; an add-on alert shows under every project's Needs you tab but not in the card count; a mission page shows "PROJECT x" and may still show an All projects chip elsewhere.

## Not checked
macOS and Safari and Firefox (only Linux and headless Chromium ran here); real GitHub, a real model, a real calendar, a real screen reader; Python 3.10 itself; the saving from the profile block in real runs. The pilot and lookout browser checks skip in this container because `bin/browse.mjs` cannot start Chromium as root.

## python3 bin/check.py on the merged branch
One full run on the merged tree (sections 1 to 6, the CI fixes, `main` at ea7183c), 28 min 54 s: every step green except one, "secrets" (3 hits: credential-shaped decoys written literally in the new guardrails test files `bin/selftest-guardrails.sh` and `bin/guardrails-page.mjs`). The decoys are now built at run time. After that fix `bin/guard.py` ("nothing private or secret is tracked") and `bin/selftest-guardrails.sh` pass. To save cost the whole check was not repeated: the fix touched only those two test files.
