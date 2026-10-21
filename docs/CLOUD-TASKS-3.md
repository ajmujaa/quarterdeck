# Round 3: missions that tell the truth, then the rest of round 2

## 0. Rules (read first, no exceptions)
- Author every commit as `Mujahid <500292+ajmujaa@users.noreply.github.com>` (`git -c user.name=Mujahid -c user.email=500292+ajmujaa@users.noreply.github.com commit`).
- Never mention Claude, an AI, an assistant or a session link anywhere: commits, code, comments, docs, PR text, reports. No `Co-Authored-By`, no `Claude-Session`.
- No em dashes in user-facing text. Nothing loads from the internet at runtime.
- Do not run the full `bin/check.py` locally; GitHub CI runs it for free on both macOS and Ubuntu. Run only the suites for the files you touched (`python3 bin/selftest.py` and the matching `bin/selftest-*.sh`). Push the branch and open a PR into `main` (it is protected; both CI jobs must pass). Read the CI log, fix, and push again if it is red. Keep pushes few: each CI run takes about 35 minutes.
- Use the name Relay for any sample add-on in tests and demos. Never name real products.
- Tests use temp folders and a fake HOME. Never touch port 7878, real `~/.quarterdeck`, `~/.config`, LaunchAgents or the keychain.
- Write `docs/reports/cloud-round-3.md`: what was built, what was not checked, what still confuses a newcomer.

## A. Missions that tell the truth (three bugs the owner hit on a real project)
1. **A merged pull request still says "Awaiting you / Pull request is open".** Cause: `reconcile_fixes` in `bin/dashboard.py` only reconciles records tied to a panel ruling. A fix started from a GitHub issue is stored as `state/fixes/issue-<n>.json` (panel `issue`), has status `pr` and is never checked against GitHub again. Fix: reconcile every fix record that has a `pr` URL, whatever its panel, so a merged PR becomes `merged` (Review: Done) and a closed one becomes `closed`. Also refresh when the mission is opened, not only every 10 minutes. Test with a fixture `gh` that returns MERGED for an `issue-<n>` record.
2. **"Blocked" for work that needs nothing.** A shipwright result `NO_CHANGE` (already fixed on main) is shown as red Blocked with "Open it to see why it stopped". It is not a failure. Show it as "Nothing to build" in a calm colour with the reason in plain words ("Already fixed on main in <commit>"), and keep Blocked for real stops (NEEDS_HUMAN, failed).
3. **No actions on a finished or stopped mission.** The page has only "Open the log". Add, per state: **Dismiss** (hide it from the list, kept in History, undoable), **Close the issue** (only after an explicit yes; `gh issue close` with a comment) for "Nothing to build", **Try again** for Blocked, **Open the pull request** and **Mark as merged** when GitHub says merged. List pages get a "Hide handled" filter and a count of dismissed ones. Dismiss writes only to Quarterdeck's own data folder.
4. The hint "To make a brief for this issue, add brief to the duties of <project>" appears on every mission. Show it only when the project really lacks the duty and the mission has no brief.
5. Old stopped missions (weeks old) should not look urgent: sort by recency, group "Older than 7 days" collapsed.

## B. The rest of round 2
Do sections 6b (live work visible on Home), 6c (calmer Crew page) and 7 (Homebrew formula and npm wrapper as files only, first-run screen, guided attach, one next action; do not publish anything) of `docs/CLOUD-TASKS-2.md`, which lives on the branch `cloud/tasks-2`. Read it there.
