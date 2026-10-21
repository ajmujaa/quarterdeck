# First run: steps from a clean machine to "ready"

Counted by hand from the code paths, not timed. A command typed is one command (a pasted line counts as one). A click or a paste into a field is one step each. A confirm dialog is one click. "Attached" means the project is registered and its checklist is showing. "Ready" means the checklist's verify command has been proven once, which is what `qtdeck ready` calls ready.

## Before this section (clone, then the dashboard)

| Step | Commands | Clicks or pastes |
| --- | --- | --- |
| Get the program: `git clone ...`, `cd quarterdeck` | 2 | 0 |
| `bin/qtdeck setup` (read what is missing, install it, run it again if anything was) | 1 | 0 |
| `bin/qtdeck dashboard` (the link opens by itself) | 1 | 0 |
| Add a project: Add a project, paste the path, Look at it, Add this project | 0 | 4 |
| Ready: Open the Ready card, Run it once, confirm | 0 | 3 |
| **Total to ready** | **4** | **7** (11 steps) |

Attached, before the ready steps: 4 commands and 4 clicks or pastes (8 steps). From the terminal instead of the page: `qtdeck attach <dir>`, `qtdeck attach <dir> --apply`, `qtdeck ready <name> --prove` is 3 more commands (7 in all).

## After this section

| Step | Commands | Clicks or pastes |
| --- | --- | --- |
| Get the program: `git clone ...`, `cd quarterdeck` (later: one `brew install ajmujaa/quarterdeck/qtdeck` or `npm install -g qtdeck`) | 2 (later 1) | 0 |
| `bin/qtdeck dashboard`, which opens on the first-run screen (no separate `setup` needed: the screen lists what is missing, with a Copy button on each fix) | 1 | 0 |
| First-run screen: Skip, or Look around in Demo | 0 | 1 |
| Add a project: Add a project, paste the path, Scan, Attach | 0 | 4 |
| Ready: Open the Ready card, Run it once, confirm | 0 | 3 |
| **Total to ready** | **3** (later 2) | **8** (11 steps, 10 later) |

Attached: 3 commands and 5 clicks or pastes (8 steps); 2 commands (7 steps) once the package install exists.

## What changed, plainly

- The separate `setup` command is gone from the path, and so is reading its output in one window and acting in another: the first screen shows the same checks as `qtdeck doctor`, with the exact fix and a Copy button.
- With brew or npm the clone and `cd` become one command. Neither is published yet.
- The first-run screen adds one click for someone who wants to go straight to a project. The guided panel does not save clicks; it puts the four things attach already did (scan, docs, crew, ready) in order on one page, with one plain line under the field when a path is wrong.
- After the first project there is one next action, not a list.

## Still manual, on purpose

Signing in to the coding tool and to `gh` is done by the owner in a terminal. Quarterdeck shows the command and never signs in, installs, or stores a sign-in for you. Proving the verify command and filing the first ticket are separate clicks you make when you choose.
