# Round 5 report

## What was built

**A. A live view while Prove runs**
- The Ready card shows, while the verify command runs: a calm moving strip (no percentage, because nobody knows how long a command takes), the elapsed time, and the last lines of the output in a small monospace box you can scroll. A Stop button ends the run and keeps nothing.
- The box is one reusable piece, `dashboard/assets/livebox.js`. It is used by Prove and by the attach scan (which now shows its stages: reading the folder, the stack it found, surveying). Any other long action can use it by giving the box a key.
- The page polls one small JSON once a second: `GET /api/live?key=prove:<project>&since=N` answers `{state, seconds, lines, next, total, replace}`. No stream, no websocket, no third-party code. `since` makes it send only new lines; when the run ends it sends the kept tail once (`replace: true`).
- The work was already a detached process (`qtdeck ready <p> --prove`), so nothing runs on the request thread. `bin/prove` now writes the output to a private file in `workspace/` while it runs and removes it at the end. `POST /api/ready/prove-stop` ends the process group.
- Text only: terminal escapes and control characters are removed, every line is clipped, and the whole chunk goes through `outscan.redact`, the same credential scan as every log. The page puts lines in with `textContent`, never as markup.
- `verify.json` now also keeps the last 60 lines (`tail`, redacted, 0600). A failed run is described by the line it stopped at (the last line that names a failure, else the last line that is not a pass line), not by its first line. The card shows the tail under "Show the output", open by default when the run failed.
- The failure text on the Ready card ends with one sentence about what to do next: install what it needs (exit 127), choose a quicker command (timeout), choose a command that only reads and tests the project's own files (the sandbox refused something), or open the output and fix the line it stopped at.
- Accessibility: the log is a focusable `role="log"` region with a label; it is `aria-live="off"` on purpose, so a new line every second is not announced. The start and the end are announced once, politely, through the page's existing status line. The strip has an accessible name and no value. It stops moving in Calm mode and under `prefers-reduced-motion`.

**B. Why `python3 bin/selftest.py` exits 1 in the macOS sandbox**
- Cause (as found by hand, not reproduced here, see below): exactly one check asks the system which process owns a listening port. The sandbox forbids listing other processes on purpose, so the answer is empty and the check failed. The sandbox is right; the check cannot run there.
- Fix: the check now treats "this process, which is the listener, is not in the answer" as "processes cannot be inspected here" and prints `skip` with the reason. The check that follows it (`llm_stream` refuses) is skipped for the same reason. The code that protects the key (`llm_ours`) is unchanged and still refuses when it cannot be sure.
- The harness sets `QUARTERDECK_IN_SANDBOX=1` for project commands whenever a sandbox is applied (seatbelt or bubblewrap), and only then. It is the only `QUARTERDECK_` word a project command receives. Two older checks that asserted "no `QUARTERDECK_*` in the environment" now allow exactly that one.
- Decision between the two options in the brief: it is a bug in the test (option 2), not a command that needs more than the sandbox allows. The repo's own verify command can stay `python3 bin/selftest.py`. When a command does need more than the sandbox allows, the card now says so in one sentence.

**C. Verify candidates found by name**
- For a repo with no manifest, the scan cannot guess a verify command. The Ready card now lists up to six commands found by name: `bin/selftest*`, `bin/test*`, `scripts/test*` and `scripts/check*`, `test.sh` and `check.sh` at the top, and a Makefile `test` or `check` target. Library and helper files (`selftest-lib.sh`) are left out.
- Each one is marked "Not run yet". "Use this" only sets it (after a confirm); the server accepts only a command from the current list and refuses a second set. It is then an ordinary "not run yet" verify command, and proving it still asks first.

## What was not checked

- macOS. The sandbox failure was reproduced by hand on macOS (seatbelt) by the owner; here everything ran on Linux. On Linux the check does not fail even without the fix: bubblewrap does not hide a process's own sockets, so `lsof`/`ss` still name the listener. I proved the new skip path by running the suite with `lsof` and `ss` missing from `PATH` and `QUARTERDECK_IN_SANDBOX=1`; I did not run it under seatbelt. The seatbelt profile and the exact text sandbox-exec prints are untested.
- The other suites inside the sandbox: see the list below. That was done with the repo's own helper (`project_exec` in check mode, the way Prove runs a command), with bubblewrap on Linux. It says nothing about seatbelt, which has different rules (for example the process list, `launchctl`, unix sockets).
- The page in a browser. No headless browser is installed here, so `bin/ready-ui-page.mjs` and the other page tests skipped. The live box's logic is tested under node (`bin/selftest-livebox.mjs`), the API end to end by `bin/selftest-prove-live.sh`, and the page script parses, but nobody has looked at the card, the strip's animation or the focus order in a real browser.
- Long output. A command that prints megabytes was reasoned about (the server counts lines in a stream and reads the last megabyte) but not measured.
- A dashboard restarted during a run: the page starts watching again from the lock, but that path was not run.

### The other suites, run inside the sandbox

Run with the repo's own helper (`project_exec`, check mode, bubblewrap on Linux), from a clone of this branch, 39 suites plus `bin/selftest.py`:

- `bin/selftest.py` passes (36 s). On Linux the listener check also ran and passed, because bubblewrap does not hide the process's own sockets.
- Pass inside the sandbox: billing, bosun, brief, connections, firstrun, fix, guardrails, harbourmaster, infra, injection, live, logkeeper, lookout, marshal, missions, mockup, nav, onboarding, packs, panel, portable, projects, providers, purser, security, stack, tickets-ui, untrusted. Suites that need a browser skip, as they do outside.
- Fail only inside the sandbox: assayer (7 checks), caulker (1), checks (32), cycle (2), diet (1), pilot (7), prove-live (4), quartermaster (4), terraform (5), tickets (3). All of them pass outside. The cause is the same for the ones I opened (assayer, caulker, tickets, pilot, and by the same shape the rest): these suites run a project command through the sandbox themselves, and bubblewrap cannot start inside bubblewrap (`_qd_bwrap_usable` is false inside). So they need more than the sandbox allows, which is option 1 of the brief for them. They are not verify candidates for this repo; the repo's verify command is `python3 bin/selftest.py`, which passes. I did not change those suites. They could skip on `QUARTERDECK_IN_SANDBOX=1` when `_qd_bwrap_usable` fails; that is a follow-up.
- planner failed once with 12 suites running in parallel and passed alone, and `selftest-flow.sh` failed one check once under the same load and passed alone: load, not the sandbox.
- Not run in the sandbox: `selftest.sh`, `selftest-round8.sh`, `selftest-machlookup.py`, `selftest-procs.py` and the `.mjs` tests.

## What still confuses a newcomer

- Two words for the output: the live box while it runs and "Show the output" afterwards are the same text, but the first is the whole stream and the second only the last 60 lines.
- A stopped run is not a failed run. It keeps nothing and the card says "You stopped it", which is easy to read as an error.
- Candidates are suggestions found by file name. A file called `selftest.py` may not be a test, which is why each is marked "not run yet" and why setting one does not run it.
- `QUARTERDECK_IN_SANDBOX=1` exists only inside a sandbox. A test that skips on it will run everywhere else, so a skip in Prove and a pass on a laptop are both expected.
- The Ready card's "First line" wording is gone: a failed run now says "It stopped at: ...". Anyone who learned the old wording will look for it.
