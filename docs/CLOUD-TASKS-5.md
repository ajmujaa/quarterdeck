# Round 5: see what is happening while Prove runs, and why this repo's Prove fails

Rules: same as `docs/CLOUD-TASKS-3.md` section 0 (commits authored as Mujahid, never mention Claude or an AI or a session, no em dashes in user-facing text, nothing from the internet at runtime, fake HOME and temp folders in tests, never port 7878 or the real data folder). Do not run the full `bin/check.py` locally; open a PR into `main` and let CI run it. If you are already busy with round 4, finish that PR first.

## A. A live view while a long action runs
The owner pressed "Run it once to prove it" on the Ready card and saw only a static "Proving" box for about 30 seconds, then "blocked ... First line: ok an overdue interval is due now". They want to see what is happening, as an animation or the real log.
1. While Prove runs, the card shows a progress strip (a calm moving indicator, honest: no fake percentage), the elapsed seconds, and the last lines of the command's output streaming in a small log box (monospace, scrollable, the last 200 lines, redacted by the same credential scan as every log; text only, never markup). A "Stop" button ends the run.
2. The same live box is a reusable piece: use it for any other action that takes more than a few seconds and has output (attach survey, a mission step, scribe drafting) where it fits without a rewrite; at least Prove and attach.
3. Keep the output tail after the run: `state/projects/<p>/verify.json` also holds the last 60 lines (redacted, 0600), and the card shows them under "Show the output". Today only `first_line` is kept, and it is often a passing line, not the failure. When the command fails, show the line that failed (the last line that is not a pass line), not the first line.
4. Prove runs in a worker, never on the request thread; the page polls or streams a small JSON of {state, seconds, lines since N}. No third-party code, no websocket library.
5. Tests with a fake HOME: a fake verify command that prints lines slowly, passes or fails; the card shows lines while it runs, the tail after, and a stop works.

## B. Why `python3 bin/selftest.py` exits 1 inside the sandbox for this repo
Attaching `~/Projects/Quarterdeck` (a clone of the public repo) with verify `python3 bin/selftest.py` gives "exited 1 in the sandbox" after 26 seconds on macOS (seatbelt); the same command passes in GitHub CI and outside the sandbox. Find out why using the output tail from A, and decide between:
1. The selftest legitimately needs things the sandbox forbids (it starts processes, binds ports, uses unix sockets or launchctl, writes outside the clone, runs the sandbox itself). Then Quarterdeck's own repo needs a different, sandbox-friendly verify command (for example a quick suite that needs none of that), documented for the maintainers, and the scan should say plainly "this command needs more than the sandbox allows".
2. A real bug in the sandbox profile or the selftest. Fix it.
Either way, the failure text on the Ready card must say what to do next in one sentence, not only an exit code.

## C. The scan cannot guess a verify command for a script-driven repo
The scan found no verify command for a repo whose tests are `bin/selftest.py` and `bin/*.sh`. Offer candidates found by name (`bin/selftest*`, `scripts/test*`, a `check` or `test` target) as one-click suggestions on the Ready card, never set silently, each marked "not run yet".

## D. Report
`docs/reports/cloud-round-5.md`: what was built, what was not checked, what still confuses a newcomer.
