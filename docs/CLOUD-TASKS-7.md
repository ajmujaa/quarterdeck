# Round 7: test everything, fix only what is broken, get ready to release

No new features this round. The owner wants to share Quarterdeck with other people, so the job is to find out, by trying every action the app has, what does not work, fix the small things, and say plainly what is left.

## 0. Rules (same as earlier rounds, read them again)

- **Author.** Commit as the repository's configured user. Never put Claude, an AI, a session link or a co-author line in a commit message, a pull request or a file. Run `git log --format='%an <%ae>%n%B' origin/main..HEAD` before you push and check it.
- **CI, not your machine.** Do not run the whole check locally. Push the branch, open the pull request, and let CI run it (a pull request runs the quick check on Linux, about 10 minutes; a merge to main and the nightly run test everything on Linux and macOS). For the full check on a branch before you finish, run `gh workflow run ci.yml --ref <branch>`. Keep pushes few.
- **Small, separate pull requests.** One fix, one pull request, with the test that fails without it. A bug that needs a design decision or a big change is not fixed: file an issue (title, steps, expected, actual, the exact text of any error) and move on.
- **Public tree only.** No private names (the banned-word check in `bin/guard.py` and CI will refuse them), no secrets, no real accounts, no money spent on models: use `providers/fake` or the existing fixtures wherever a model would be called.
- **Say what you could not test.** A row marked "not tested" with the reason is worth more than a guess marked pass.
- **Start from the latest main.** `git fetch origin && git checkout -B cloud/tasks-7 origin/main` (the pull request "Add a project: a visible button..." may land first; rebase on it).

## 1. Make the list of everything first

Write `docs/reports/release-test-matrix.md` as a table: item, how it was tried, result (pass, fixed in PR #N, issue #N, not tested and why). Build it from the code, so nothing is left out:

1. **Every button and control on the dashboard.** The table of actions at the end of `dashboard/index.html` (about 200 names: `act("...")`, `actOn(...)`). One row per action.
2. **Every API route** in `bin/dashboard.py` (about 60 paths, GET and POST, including each `action` value of the routes that take one: `/api/connections`, `/api/capture`, `/api/ready/*`, `/api/attach`, `/api/tickets/*`, `/api/missions/*`, `/api/guardrails`, `/api/duties`, and the rest). One row per route and action.
3. **Every command** shown by `bin/qtdeck help` and its sub-commands (`attach`, `ready`, `docs`, `ticket`, `plan`, `fleet`, `addon`, `check`, `doctor`, `setup`, `dashboard`, `run`, `projects`, `connections`, and the rest). One row per command and flag that is documented.
4. **Every pull-request and README/GUIDE/SECURITY claim.** One row per sentence that says Quarterdeck does something.

## 2. Try them, in this order

Use a throwaway data folder and fake HOME (`QUARTERDECK_HOME`), a free port, and the fixtures (`fixtures/`, the sample React app the flow suite builds). Never touch the real `~/.quarterdeck` or port 7878.

**A. Journeys, end to end, in a real headless browser (Playwright, if the box has it; if not, say so and use the API with the page's own requests):**

1. First run on an empty data folder: the checks, the Copy buttons, Demo, Skip.
2. Pairing: a fresh link works once; a used link, an expired link and a wrong token each fail with a plain message; the session lasts; two tabs.
3. Add a project: the visible Add a project button on Projects, Scan, the already-attached note, missing docs, the crew switches, the ready checklist, Attach; the new-project form; a bad path, a file, a symlink, a folder outside the home folder, a hidden folder.
4. Docs drafting with the fake provider: draft, read, say yes, the new branch. Never over an existing file.
5. Ready and Prove: Run it once to prove it, the live strip, Stop, Prove it again, a failing verify command (the failing line is shown), a verify command that hangs, the sandbox refusing.
6. Tickets: draft with the fake provider, "nothing drafted" message, file locally, file to a repo (fake `gh`), a request holding a key (refused).
7. Missions: create, every button on a finished, stopped, blocked and merged mission (Dismiss, Close issue, Try again, Mark as merged), the old-missions fold.
8. A cycle to a local branch, the cycle and the Pull requests tab (fake `gh`).
9. Brain: Map, Rhythm, every tool (Replay, Attention, What changed, My focus), open a node, every button in its panel, the legend, keyboard use.
10. Connections: every card opens; Save with empty, wrong and pasted values; typed values survive the 3-second refresh while you type (this has broken before: test every form on every page for typed text vanishing on a poll); Test; remove; the agent-source form with the 127.0.0.1 preset and nothing listening (a plain message); add-ons: `qtdeck addon new relay`, listed as local, loads, an action asks for confirmation.
11. Agents and duties: switch each on and off, Available folds, guardrails edit, move, remove, save.
12. Notes (Brain Dump): add, edit, tag a project, done, reopen, promote to a mission draft, promote to a plan (confirm), the 1000-character limit.
13. Settings, Library, Spend, Log, Ledger, Timeline, Board, Operations tabs: every control, every empty state, every error state.
14. Demo mode on and off: nothing real is called or changed while it is on.
15. Calm mode and the narrow layout (375 px): nothing overlaps, nothing is cut off, every action is reachable.

**B. Hostile and odd input, on every form and API route that takes text:** empty, 1 character, the maximum, one over the maximum, control characters, right-to-left text, `<script>` and `"><img onerror>`, very long words, a path with spaces and quotes, a name that is already taken. Nothing may execute, break the page or write outside the data folder. Check the Content-Security-Policy still holds (no console violations).

**C. Keyboard and screen-reader basics on the main journeys:** tab order, focus visible, every button has a name, dialogs trap and return focus, the live regions announce. Report what fails; fix only what is a one-line change.

**D. Concurrency and recovery:** double-click every action that costs something or changes something (one effect only); press an action, reload mid-way; stop the dashboard mid-run and start it again; kill a running verify command; a full disk and a read-only data folder produce a plain message, not a stack trace.

**E. Docs against reality:** run every command in README.md, GUIDE.md and `qtdeck help` literally. A command that does not exist, a flag that is not accepted, an output that differs from the text, a broken link or a screenshot of something that is gone is a bug. Fix the text, or the code if the text is right.

**F. Fresh install, as a stranger would:** clone the public repo into an empty folder with a fake HOME, follow only the README, no private knowledge. Time it. Run `qtdeck doctor`, `qtdeck setup`, the dashboard, Demo. Dry-run the Homebrew formula and the npm shim offline (`packaging/`): nothing may download or run an install script. Check `LICENSE`, `NOTICE`, `LICENSING.md`, `SECURITY.md`, `THREAT-MODEL.md` exist and say true things.

## 3. What not to spend time on

- Facebook, Instagram, LinkedIn and every other live social connection: parked. Test only that their cards open, say plainly what is missing, and fail with a plain message when no credentials are saved.
- The Helm voice assistant and anything that needs a microphone, a real Google, Meta or Slack account, the Hermes box, macOS `sandbox-exec`, the Keychain or a real model: list each under "not tested", with the exact steps the owner should run on a Mac (section 4).
- One known local-only failure: `selftest-flow.sh` fails one line on Node 24; CI uses Node 20. Do not chase it.

## 4. What to hand back

1. `docs/reports/release-test-matrix.md` (section 1), every row filled.
2. `docs/reports/cloud-round-7.md`: how many rows passed, were fixed, are open issues, are not tested; the five worst things found; what you would not show a stranger yet.
3. The fixes, as small pull requests, each with its test.
4. Issues for what was not fixed.
5. `docs/reports/mac-checklist.md`: at most 20 short steps, in order, for the owner to run on a real Mac to cover what the cloud box could not (sandbox, Keychain, a real Google sign-in, a real model call, the first-run on a clean Mac, the Homebrew path). Each step says what to press and what should happen.
6. `docs/reports/release-checklist.md`: what remains before telling people (the tag and version, the Homebrew tap, the npm name check, the PyPI name, a trademark search, issue templates, a short note for testers). Facts and open decisions only: do not do any of it.

Report when the matrix is complete and every fix is merged or an issue. If a section cannot be done on this box, say so at the top of the report instead of skipping it quietly.
