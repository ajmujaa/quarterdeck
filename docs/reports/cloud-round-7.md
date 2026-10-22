# Round 7: test everything, fix only what is broken

Nothing new was built. Two testers tried every action the program has, in throwaway data folders with a fake HOME, the fake provider and a fake `gh`. The full list with a result per row is `docs/reports/release-test-matrix.md`.

## The numbers

573 rows tried against `main` at 59566e3.

| | Rows |
| --- | --- |
| pass | 437 |
| bug (41 distinct bugs) | 75 |
| not tested, with the reason | 61 |

41 bugs: 22 from the API, command-line, document and fresh-install part, 19 from the dashboard part. They are filed as GitHub issues #138 to #148 and #160 to #170 (grouped by theme, so 22 issues cover 41 bugs). Ten small fixes are open as pull requests #149 to #158; all ten were green on Ubuntu CI at their last push. Four issues need an owner decision before any code (#142, #161, #164, #167), and so do two parts of #145.

## What works well

- Pairing, the Origin and Host checks and the loopback-only server held up in every case tried: a used or expired link, a wrong token, a foreign origin.
- About 4000 hostile-input requests (script tags, control characters, right-to-left text, 5000-character words, paths with quotes) executed nothing and wrote nothing outside the data folder. No Content-Security-Policy violation appeared in the browser.
- Typed text survived the 3-second refresh on every form. Demo mode changed nothing in the data folder and made no `gh` or model call.
- Fresh install from an empty folder to a paired dashboard took about 15 seconds of commands plus a 4-second start. The Homebrew formula and the npm shim dry-ran offline and downloaded nothing.
- Dialogs and the Add a project drawer keep focus inside and return it. Every button, link and field has an accessible name. At 375 px nothing scrolls sideways and all 211 controls are reachable.
- The licence, notice, security and threat-model documents exist and their checkable facts hold.

## The five worst things found

1. `qtdeck add` followed by `qtdeck run <name> review`, the help's own two-step onboarding, fails with "unknown duty 'review'" (#138).
2. One mistyped duty in `qtdeck billing cap duty` breaks every billing command and every model call, and the command line cannot repair it (#139).
3. Two writes at the same moment collide on one fixed temp file name, so a double click on Create, Save repo, Schedule or Attach can show a raw `[Errno 2]` (#140, #162).
4. The Brain's More menu opens behind the 3D map, so Replay, Attention, What changed and My focus cannot be clicked with a mouse (#166).
5. "Start with a spec panel" refuses every mission that has constraints, success criteria or any punctuation, with a raw "bad value" toast (#164).

Close behind: a read-only or full data folder gives Python tracebacks (#141), finished panel and shipwright runs leave lock folders that can make the Crew page show a finished run as running (#168), and a second browser tab leaves the first one looking live while every write says only "forbidden" (#160).

## What I would not show a stranger yet

- The Brain's More menu (#166), the spec panel start (#164) and the missing Turn off for an agent (#167). Each is a visible dead end in a main journey.
- Anything on a read-only or nearly full disk (#141).
- The README, GUIDE and help text until #138, #145 and #146 are merged: a few commands and file paths in them do not exist.
- The Helm voice and the social connections, which were parked and not tested.

## What was not tested (61 rows, reasons in the matrix)

Helm voice and chat; Google and Meta sign-in; the macOS Keychain; the macOS `sandbox-exec` profile; the GitHub project board with a real board; the fix queue against a real queue; a successful cycle, brief or mock-up (the fake provider's canned answers do not satisfy the stage contracts, so only refusal and failure paths ran); real GitHub; external links; a real screen reader (names and live-region text were read, not speech); colour contrast; zoom to 200 percent; a verify command that runs until its own limit (only Stop was tried); the full `qtdeck check`. The Mac steps for the ones that need a Mac are in `docs/reports/mac-checklist.md`.

## Things that went wrong during the testing

- The two testers' scratch folders briefly shared a path. For about a minute one test project was registered in the container's own data folder. It was removed with `qtdeck remove`, the leftover files were deleted, and `projects.json` is back to `{}`. Nothing outside the container was touched.
- A container restart stopped both testers mid-run. They were resumed and rewrote their results to disk as they went.
- Two of the ten fix PRs failed CI at first, for reasons that only show on CI: one test assumed Python 3.11 behaviour (Python 3.12 parses very deeply nested JSON, so the failure moved later), and one read-only test could not work for a non-root owner (a user can chmod their own folder, and `qtdeck` resets its own permissions). Both were fixed and are green. The read-only test now runs only as root with `setpriv`, so CI skips it; it was run here as root and passes.

## What this round did not do

No new feature, no change to the outside-home rule, no change to how run arguments are checked (#142). The release checklist (`docs/reports/release-checklist.md`) lists what remains before telling people.
