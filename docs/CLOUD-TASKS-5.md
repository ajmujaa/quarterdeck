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

**Finding (reproduced by hand, 2026-10-21):** in the sandbox exactly one check of `bin/selftest.py` fails, everything else passes: `FAIL  a listener that is not the helper's child is refused, and one that is the child is accepted; the key stays unsent otherwise`. That check looks at which process owns a listening port, and the sandbox deliberately forbids listing or inspecting other processes (SECURITY.md, project-command sandbox). So the sandbox is right and the test cannot run there. Fix: make that check detect it cannot inspect processes and report `skip` with the reason (not FAIL), and add a small marker the harness sets for project commands (for example `QUARTERDECK_IN_SANDBOX=1`) so any test can skip what the sandbox forbids on purpose. Then `python3 bin/selftest.py` passes in Prove for this repo. Check that no other suite has the same problem (run `bin/selftest*.sh` and `*.py` the same way and list any that fail only inside the sandbox).

## C. The scan cannot guess a verify command for a script-driven repo
The scan found no verify command for a repo whose tests are `bin/selftest.py` and `bin/*.sh`. Offer candidates found by name (`bin/selftest*`, `scripts/test*`, a `check` or `test` target) as one-click suggestions on the Ready card, never set silently, each marked "not run yet".

## D. Sign in from the Connections page, never from a terminal
After saving the Google client id and secret, the Gmail card says "run python3 bin/integrations/google_oauth.py gmail" in a terminal. A connection page must not ask for that. The sign-in code already exists (`authorize()` in `bin/integrations/google_oauth.py`: loopback redirect on 127.0.0.1, PKCE, a `state` check, token file 0600).
1. The moment the last required credential of an account is saved, the page starts the sign-in itself. A new `POST /api/connections` action `signin` (same pairing, origin, token and confirm rules as the other writes) runs `authorize()` in a worker thread with `open_browser=False` and returns the Google address. The page shows a primary button "Continue with Google" (and also tries to open it; if the browser blocks that, the button is there), a calm "Waiting for you in the browser, 3:58 left" with a Cancel button, then "Signed in as ..." or the plain reason it stopped (cancelled, timed out, Google gave no refresh token, with the one thing to do next). The Test runs by itself after a successful sign-in.
2. The listener is one loopback socket on a random port, single use, closed on success, cancel or after 4 minutes; the callback is checked against `state`; nothing about it is logged except "sign-in started/finished" with the service and account label, never the code, token or address.
3. Gmail's second and later accounts use the same flow from "Add another account".
4. The Gmail card's help text and the manifest (`bin/integrations/services/gmail.json`) stop telling people to run a command; they describe the button. `qtdeck connect gmail` keeps working for people who prefer the terminal.
5. Tests with a stand-in Google endpoint (fixture token and auth server on loopback): sign-in succeeds, user cancels, timeout, wrong `state` is refused, the page never receives a token, a second account works.
6. Same rule for any other connection that today needs a terminal step: list them in the report; fix the ones that are the same shape.

## E. Report
`docs/reports/cloud-round-5.md`: what was built, what was not checked, what still confuses a newcomer.
