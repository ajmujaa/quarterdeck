# Cloud round 6

## What changed

Ten suites failed only when a project command ran them inside the sandbox (bubblewrap on Linux), because they start a sandboxed project command of their own and a sandbox cannot start inside a sandbox. They now notice that and skip what cannot run. Outside the sandbox (`QUARTERDECK_IN_SANDBOX` unset) nothing changes: the helper returns at once and no assertion was touched or weakened.

- `bin/selftest-lib.sh` gets two helpers. `st_can_nest_sandbox` is true when the marker is not `1`; with the marker set it asks whether a new sandbox can start (`_qd_bwrap_usable` on Linux, a `sandbox-exec` probe on macOS). `st_skip_if_nested_sandbox <suite>` prints one `  skip  <suite>: <reason>` line and exits 0 when that is false.
- Whole suite skips (one line, exit 0): assayer, caulker, cycle, diet, pilot, quartermaster, tickets.
- terraform: the protect.py and shipwright parts still run. Only the sandboxed terraform run is replaced by the existing `QUARTERDECK_CHECK_SANDBOX=off` path, with a skip line saying so.
- checks: a `ckn` wrapper (same as `ck`, but skipped with a line when a sandbox cannot nest) replaces `ck` on the 32 assertions that depend on a real sandboxed run. The rest of the suite (protect.py, bwrap argument lists, fakes) still runs inside the sandbox.
- prove-live: only section 1 (the live box over a slow passing command, which starts a real Prove) is skipped; the other sections run.
- `bin/selftest-nested.sh` (label in `bin/check.py`) proves: marker set and no nesting gives one skip line and exit 0; marker set and nesting possible runs; marker unset runs even if nesting would fail.

## How it was checked

Each changed suite was run normally (all pass) and once inside the sandbox with the repo's `project_exec` in check mode and bubblewrap, from this worktree. The results are in the hand-back of the round; the full `bin/check.py` was not run.

## Not checked

- macOS seatbelt: `sandbox-exec` nesting was not run on a Mac. The Darwin probe in `st_can_nest_sandbox` (`sandbox-exec -p '(version 1)(allow default)' /usr/bin/true`) is the same one `qd_sandbox_status` uses, but whether it fails inside a seatbelt-sandboxed command is untested. If it succeeds there, the suites will run and may fail as before.
- The `ckn` assertions in checks are skipped, not proven, inside the sandbox; they are still run outside it.
- Suites not on the list were not re-run inside the sandbox this round.
