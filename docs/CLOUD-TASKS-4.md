# Round 4: bring your own agents (three levels) and an add-on folder

Goal: anyone can see their own agents in Quarterdeck, from a one-line report up to a small add-on, without touching the program folder. Read `docs/CLOUD-TASKS-3.md` section 0 first: the same rules apply (commits authored as Mujahid, never mention Claude or an AI or a session, no em dashes in user-facing text, nothing loads from the internet at runtime, tests use a fake HOME and temp folders, never port 7878 or the real data folder, sample names are Relay or Example, never a real product). Do not run the full `bin/check.py` locally; push a branch, open a PR into `main`, let CI run it on macOS and Ubuntu, read the log and fix if red. Run only the suites of the files you touch while working.

Never collect keystrokes, screen, apps or sites, clipboard, location, or files outside registered projects and the data folder. Everything here is read-only unless a section says otherwise.

## A. Add-ons load from the data folder too
Today `load_extensions()` in `bin/dashboard.py` imports `bin/ext_*.py`. Also import `<data folder>/addons/ext_*.py`.
1. The folder must be a real directory (not a link) owned by the user with mode 0700, and each file regular, owned by the user, not group or world writable. Anything else is skipped and logged with the reason, never fatal.
2. Models and project commands must not be able to write there. Add the folder to the model deny-write list and to the sandbox rules (see the credential list in `bin/lib.sh` and the guard); the existing test that compares the two lists must fail if one lacks it. A test proves a model's shell cannot create `addons/ext_x.py`.
3. A switch: `QUARTERDECK_ADDONS=off` loads none from the data folder. Add-ons from there are labelled "local add-on" in the Add-ons list.
4. Update SECURITY.md and THREAT-MODEL.md: what loading code from this folder means, who can write there, how to turn it off.

## B. Level 1: report agents with one line
Any agent, script or CI job can show up in the Fleet view by appending a line to `state/fleet-events/<source>.jsonl`, the file the Claude Code hook already writes.
1. Document the exact line format (time, kind of event: session started or ended, a turn finished, an agent started or stopped; session id, worktree or task name, branch, agent name). Read `bin/fleet-hook.sh` and `bin/fleetview.py` for what exists.
2. Add `qtdeck fleet report --source <id> --kind <kind> --session <id> [--worktree <n>] [--branch <b>] [--agent <a>]`. It validates every field (id pattern, length caps, no control characters), refuses unknown kinds, writes one line atomically with mode 0600, and never accepts a prompt, reply, file name or transcript. Unknown source ids are created only after the owner registers the source (`qtdeck fleet source add <id> <label>`), so a stray script cannot invent one.
3. Docs page `docs/public/AGENTS.md` ("Show your own agents"): copy-paste examples for a bash script, a Python one-liner, a GitHub Actions step and a cloud agent that runs on your machine. Say plainly that a remote agent cannot write to your disk; it reports through level 2 or through a script you run.
4. A test with a fake HOME: report events, see them in `/api/state` and the Fleet view; bad fields are refused.

## C. Level 2: an agent source you add in a form
A read-only source for agents that live elsewhere and expose a small JSON API.
1. A form on the Connections page, "Add an agent source": a name, a base URL, a token, and a field map. The token goes to the keychain like the other connections, never to a config file or a log. Config lives in the data folder (`config/agent-sources.json`, mode 0600, no secrets).
2. URL rules: `https://` only, or `http://127.0.0.1:<port>` (a tunnel the owner runs; Quarterdeck never starts ssh or a tunnel). No redirects to another host. Timeout 10 s, response capped at 256 KB, refresh no faster than every 60 s, done off the request thread so a slow source cannot stall the dashboard.
3. The field map names a path to the list of agents or tasks and, for each, where to find: name, status (mapped to running, waiting, done, failed), last run time, one short detail. Only those mapped fields are kept (each length-capped and shown as text, never as markup). Snapshots go to `state/agent-sources/<id>/`; the response body is not stored.
4. The agents show in Fleet under the source's name; a status of running also shows in the Running now strip on Home. An unreachable source says so in plain words and does not break anything else.
5. Ship two generic presets in the form ("A JSON list over HTTPS", "A dashboard reached through my own SSH tunnel") with example fields and `example.com` hosts. No product names.
6. Test against a fake local server (fixture) with a fake HOME: a good source, an unreachable one, a redirect, an oversized reply, markup in a name (shown as text), a token that is never written to a file or log.
7. Docs in `docs/public/AGENTS.md`, and a Connections-page help line.

## D. Level 3: make building an add-on easy
For people who need buttons or something the form cannot express.
1. Write `docs/public/ADDONS.md`: the contract (`install(core)`, the hooks list in `bin/dashboard.py` above `EXT`), a minimal working add-on of about 30 lines named Relay, how to show a page, an alert, a timeline event and a safe action (a button the owner presses and confirms, one log line per action), what an add-on must never do (read keys, collect keystrokes or screen, write outside its own state folder, send data out), and how to test it with a fake HOME.
2. `qtdeck addon new <name>` scaffolds `<data folder>/addons/ext_<name>.py` and a small test skeleton from a template, never overwrites an existing file, and prints the next step. `qtdeck addon list` shows loaded and skipped add-ons with the reason.
3. An agent for building one: `agents/addon-builder.md`, a crew helper that is given the ADDONS.md contract and a short description of the service ("my agents are at ..., they report status like ..."), and writes the add-on and its test into the data folder's `addons/` using the scaffold. It is read-only toward the service by default, asks before adding any action button, never sees the owner's keys (it writes code that reads a keychain entry by name), and its output is shown as a diff for the owner to accept. It runs only when the owner starts it.
4. Test: the scaffold loads, appears in the Add-ons list, a broken add-on is skipped and logged, and the builder agent's file passes the same agent-file checks the other crew files do.

## E. Report
Write `docs/reports/cloud-round-4.md`: what was built, what was not checked, what still confuses a newcomer, and which parts were tested only against fake servers.
