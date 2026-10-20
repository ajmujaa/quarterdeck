# Cloud test pass: the whole app on Linux (2026-10-20)

Base: `main` at 268b806. Branch: `cloud/test-pass` (fixes and this report). Machine: a clean Ubuntu container, Python 3.11, bash 5.2,
bubblewrap 0.9.0 with user namespaces, Node 22 with Playwright and Chromium, running as root, no Claude or GitHub sign-in used.
Nothing real was contacted. All tests used temporary data folders and a temporary HOME.

## Result in one line
`python3 bin/check.py` was RED on `main` here (7 suites). One cause is a real bug that breaks `qtdeck attach` on Python 3.10 and 3.11;
the rest were tests that assumed macOS or a non-root user. After the fixes `check.py` is GREEN (19 min 55 s, run on a quiet machine).

## 1. check.py and selftest.py on main
First run: RED, 19 min 27 s. Every failing suite, with the first error line, and the cause:

| Suite | First error line | Cause | Status |
|---|---|---|---|
| logic (`bin/selftest.py`) | `File ".../bin/attach.py", line 262 SyntaxError: f-string expression part cannot include a backslash` | real bug, see 2.1 | fixed |
| first use (`selftest-firstrun.sh`), 9 checks | the same SyntaxError | same bug | fixed |
| security (`selftest-security.sh`), F2, F6, R5, F8 | the same SyntaxError (they call attach) | same bug | fixed |
| smoke (`bin/smoke.py`) | the same SyntaxError | same bug | fixed |
| billing | `FAIL with a daily cap, a spend ledger that cannot be read stops the api duty` | the check makes the file unreadable with `chmod 000`, which does nothing for root | test fixed |
| providers | `FAIL and so does a registry that cannot be read` | same `chmod 000` assumption | test fixed |
| project commands (`selftest-checks.sh`) | `FAIL R6 control: a pull request from a branch of the repository itself does run its build, start and verify commands` | on Linux an app start is refused unless `QUARTERDECK_APP_NET=share` (SECURITY.md says so); the control did not set it | test fixed |

After the fixes every suite passes on a quiet machine (full run on `cloud/test-pass` before merging main: GREEN in 19 min 55 s; after merging main and the README fix, `selftest.py` was re-run and passes, and the full run was repeated on `cloud/connections`, which contains the same fixes). Skipped, by design: the macOS-only checks (sandbox-exec profiles R1, R5, S2 to S5,
the macOS pairing-link opener), 4 pilot checks and 2 lookout checks that need a real app, and some injection and mock-up cases.

## 2. Bugs found
2.1 **High, fixed: `qtdeck attach` crashes on Python 3.10 and 3.11.** `bin/attach.py:262` had a backslash inside an f-string expression, valid only
from Python 3.12. README says "Python 3.10 or newer", and `attach` is step 5 of the quick start, so a stranger on Debian 12 or Ubuntu 22.04 (3.10, 3.11)
hits a traceback on the first project. It also stopped `selftest.py` half way, which hid everything after it. Fix: build the text before the f-string.
Test added to `bin/selftest-portable.sh`: every `bin/*.py` must compile, and no f-string expression may hold a backslash or its own quote
(verified to fail on the old file). I could not run 3.10 itself; 3.11 shows the same error.

2.2 **Medium, not fixed: the planner selftest is flaky under load.** `selftest-planner.sh` passes alone (2 of 2) and passed in 2 of 3 full runs, but failed
3 checks in the other full run while another agent was running tests on the same machine, and failed 1 check in 4 of 6 copies run in parallel.
Failing lines: `and the forged END line is indented inside it`, `and only Backlog and Ready items were offered`, `and cost was said to be unknown to it`,
`a dry run on a proposed plan only previews`. Each run has its own temp folder, so it looks like a timing race (for example the fixed `sleep 1` at
`selftest-planner.sh:175`, or reading `claude-calls` before the stand-in finishes writing it). A CI box that runs suites in parallel will see random reds.

2.3 **Low, not fixed: `check.py` takes about 20 minutes** and says nothing about progress until each suite ends. No per-suite timing is printed.
A `--quick` mode (logic, security, first use) would make the "run check before you push" rule realistic.

2.4 **Low, test environment only: the pilot driver cannot start Chromium here unless the container allows it.** Earlier, on an older snapshot, the pilot
selftest failed with `no browser could be started`; on `main` today it passes (34 ok, 4 skipped). Not reproduced, so nothing to fix.

2.5 **Medium, fixed: `main` at c94dc63 (the README restyle) was RED again.** The new short README no longer contained the words `qtdeck check`, and
`selftest.py` asserts them (`FAIL qtdeck check is wired into the command line, its help and the README`), so `python3 bin/check.py` failed in the logic suite after
the restyle. Fix: one sentence in the README quick start (`bin/qtdeck check` runs every test). `selftest.py` passes with it. This branch merges `main` at c94dc63 first (clean merge).
Also on that commit: the Helm "think with Claude" default is now off, which closes the config-versus-docs mismatch raised in the earlier review.

## 3. README as a stranger, fresh clone, temporary HOME
- `git clone`, `bin/qtdeck setup` (1.4 s): says which tools are present, prints `gh auth login`, and makes `~/.quarterdeck` ("made now"). Matches README.
- `bin/qtdeck doctor` (under 1 s): ends with `1 problem: gh sign-in`, the true result with no login. Sandbox line says bubblewrap and notes the host network. Good.
- `bin/qtdeck status`, `help`, `doctor` in a fresh clone write nothing into the program folder and make the home folder: the earlier "writes into the program folder" problem is gone.
- `bin/qtdeck attach <tiny repo>`: crashed on `main` (2.1). After the fix it shows languages, duties, `verify python -m pytest (test_app.py)`, and the exact next command.
- `bin/qtdeck dashboard --no-open`: started in under 2 s, printed the one-time link and a Demo hint. `curl /api/health` 200, `/` 200, `/api/state` without pairing 401.
- Confusing: a clone that already holds data (for example one where the test suites were run) is treated as an existing install: `setup` says "your data is
  still inside the program folder" and does not make `~/.quarterdeck`. Correct by design, but a contributor who runs `check.py` first sees a different first run than a stranger.

## 4. Dashboard pages, demo mode, headless Chromium 1440x900
All 19 views were opened one after another with Demo switched on through the page's own switch: Home, Brain, Crew, Fleet, Connections, Settings, Needs you, Missions,
Pull requests, Board, Timeline, Operations, Ledger, Spend, Log, Documents, Panels, Notes, Showcase. Each has its own heading and real content (116 to 9,388 characters of text; Board,
Log and Documents are the short ones because Demo has little there), no horizontal overflow, no page error, no failed request, no HTTP 4xx or 5xx.
Console: 5 warnings, all on the Brain, all Chromium software WebGL messages (`Automatic fallback to software WebGL has been deprecated`, `GPU stall due to ReadPixels`).
That is this container having no GPU, not the app. `node bin/a11y-check.mjs --quick` (Home, Crew, Settings): 0 issues. Not walked: other widths, light theme, Calm mode, keyboard order
(the a11y checker covers those and ran clean in the suite). With Demo off the fresh Home says "No projects yet" with one clear next step.

## 5. Security claims tried on Linux
Held (each tried for real):
- **Project-command sandbox (real bubblewrap).** Decoy files in a decoy home outside /tmp (`~/.ssh`, `~/.config/quarterdeck/integrations.env`, `~/Documents`, the data folder's `state/`): none visible inside, all "No such file".
  Writing `/etc` fails (read-only file system). A write to the home path lands only in the private scratch home. `GH_TOKEN`, `ANTHROPIC_API_KEY` and a `QUARTERDECK_*` variable set in the caller are absent inside; `HOME` is a scratch folder.
  No internet (connect to 1.1.1.1 fails), no host loopback (a server on the host's 127.0.0.1 is unreachable), no name lookup. The worktree is writable (control).
- **Pairing and request checks (curl).** A good nonce pairs (200) and the replay is refused (401). A foreign Origin on pairing is 403. API with no session is 401. A cookie with `Host: evil.example` is 403.
  A write with the cookie but no token is 403. A write with cookie and token but a foreign Origin is 403, and with `Sec-Fetch-Site: cross-site` and no Origin 403. Twelve wrong nonces: 401 nine times, then 429.
  The cookie is `HttpOnly; SameSite=Strict`. The server answers on 127.0.0.1 and refuses on the machine's own non-loopback address.
- **Protected paths.** `bin/protect.py` blocks workflow files, `package.json`, `Makefile`, `.env` and `.env.*`, `*.tf`, `*.tfvars`, `*.tfvars.json`, `*.auto.tfvars.json`, `*.tfbackend`, `terraform.tfstate`, the lock file,
  `CLAUDE.md`, `AGENTS.md`, `pyproject.toml`, `scripts/`, `Dockerfile`, `.vscode/` and a differently cased `INFRA/Main.TF`; it allows `src/app.py`, `README.md`, `docs/guide.md`.
  (The Terraform variable-file gaps from the earlier review are closed on main.)
Not tried here: the macOS sandbox-exec claims, the `QUARTERDECK_APP_NET=share` app run end to end with a real app, abstract unix sockets, secret scanning against real credential shapes, prompt-injection behaviour with a real model
(the offline fixtures pass in `check.py`), and the claim that the Keychain protects less than it seems.

## 6. What was fixed on cloud/test-pass (one commit, each with a test)
- `bin/attach.py`: the SyntaxError; test in `selftest-portable.sh` (fails before, passes after).
- `selftest-billing.sh`, `selftest-providers.sh`: an unreadable file is a directory when run as root, a `chmod 000` file otherwise.
- `selftest-checks.sh`: the R6 control opts in to the Linux app network, as `selftest-pilot.sh` already does.
No check was weakened; the three test changes make a check run where it was silently impossible.

## 7. Open items, ranked
1. Medium: planner selftest flakes under load (2.2).
2. Low: `check.py` has no quick mode and no progress lines (2.3).
3. Low: help a contributor see why their clone is an "existing install" (section 3, last bullet).
4. Info: Python 3.10 itself was not run; macOS-only claims were not tried.
