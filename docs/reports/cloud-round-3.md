# Round 3 report

## What was built

**A. Missions that tell the truth**
- Every fix record with a pull request link is read back from GitHub (`gh pr view`) on the ten-minute sync and when a mission opens, so merged and closed pull requests show as such.
- A fix that found nothing to change (`NO_CHANGE`) shows as "nothing to build", in its own style, and is left out of the project counts.
- Mission actions: Hide (writes only `state/dismissed-missions.json`), Undo, Close the issue (one `gh issue close` with a comment, after a confirm), Retry, Mark as merged. Handled and older-than-7-days missions fold away, with a count of what is hidden.
- Demo shows each case.

**6b. Live work on Home and Projects**
- One server function composes sessions and running duties into `live` in the state: project, branch, worktree, what it is doing, since when, whether it waits on you, and its pull request.
- Home has a "Running now" strip; each project has a "Live work" card; the header says how many sessions and duties are running.

**6c. A calmer Crew page**
- Enabled agents come first. The rest fold under "Available (N)", each with an Enable button.

**7. A smoother first run**
- Files only, nothing published: a Homebrew formula with placeholders, a thin npm wrapper, and `bin/release.py`, which fills copies offline.
- A first-run screen with the same checks as `qtdeck doctor`, the exact fix for each missing item and a Copy button. "Look around in Demo" or "Skip".
- One guided Attach panel: Folder, Scan, Missing docs, Crew, Ready. Pasted paths are cleaned and a bad path gets one plain line.
- One next action after the first project.
- Copy buttons use one narrow, write-only clipboard call in one named function. The privacy scan allows exactly that and still forbids every other clipboard use. It is stated in SECURITY.md.

Before and after for a clean machine, to ready: 4 commands and 7 clicks (11) before; 3 commands and 8 clicks (11) now; 2 and 8 (10) once brew or npm exists. Clicks did not go down: the first-run Skip adds one. Details in `docs/reports/first-run-steps.md`.

## What was not checked

- macOS. Everything ran on Linux; the CI macOS job is the first run there.
- Real `brew` and real `npm`. The formula passes `ruby -c` and the shim is tested offline. The formula's Python PATH line is untested.
- A real GitHub. The pull request read-back, the issue close and the live work all ran against a stand-in `gh` and fake sessions.
- The page was driven in headless Chromium only. No one has walked it by keyboard or with a screen reader, and the first-run screen is not in the accessibility check.
- "Waiting on you" is a guess: an idle session after its turn, for under 30 minutes.
- Existing checks changed: the mission step checks expect `nothing`; the stack-pack check expects the npm package the repo now holds; the Home and Crew page checks follow the new layout.

## What still confuses a newcomer

- Signing in to the coding tool and to `gh` is still done by hand in a terminal. The screen shows the command but cannot do it.
- "Nothing to build" is easy to read as a failure. It means the fix was run and found nothing to change.
- A session that has not reported what it is doing shows "no detail reported" until the sessions hook is installed.
- Cold-start worktrees can take a few seconds to appear in Running now.
- The brew and npm lines in the docs do not work yet; nothing is published.
