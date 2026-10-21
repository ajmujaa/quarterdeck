# Round 4 report

Goal of the round: anyone can see their own agents in Quarterdeck, from one line of shell up to a small add-on, without touching the program folder.

## What was built

**A. Add-ons load from the data folder (`bin/addons.py`, `bin/dashboard.py`)**
- `load_extensions()` also imports `<data folder>/addons/ext_*.py`. The folder must be a real directory (not a link) owned by you with mode 0700, and each file a regular file owned by you and not writable by group or others. Anything else is skipped and logged with the reason, never fatal.
- `QUARTERDECK_ADDONS=off` loads none from there. They are labelled "local add-on" in the Add-ons list.
- The folder is in one list of protected write paths (`protected_write_paths` in `bin/lib.sh`), rendered both as the model's `Edit(...)` deny rules and as the sandbox's deny-write and the macOS project-command profile. `bin/selftest-security.sh` fails if the two renderings differ or if either lacks the folder.
- SECURITY.md and THREAT-MODEL.md say what loading code from this folder means, who can write there and how to turn it off.

**B. Level 1, report with one line (`bin/fleetreport.py`)**
- `qtdeck fleet source add <id> <label>` registers a reporting source; `qtdeck fleet report --source ... --kind ... --session ...` appends one line to `state/fleet-events/<source>.jsonl`, the file the sessions hook writes. Every field is checked against a pattern and a length cap, unknown kinds and options that would carry a prompt, a reply, a file or a transcript are refused, and an unregistered id is refused.
- The Fleet view and Home read those lines like the hook's.

**C. Level 2, an agent source you add in a form (`bin/agentsources.py`)**
- "Add an agent source" on the Connections page: name, address, token, and a field map (path to the list, then name, status, last run, detail). Two presets fill it with examples on `example.com` and `127.0.0.1`: "A JSON list over HTTPS" and "A dashboard reached through my own SSH tunnel".
- Config in `config/agent-sources.json` (mode 0600, git-ignored, no secrets). The token goes through `bin/integrations/manifest.py` into the same store as the other connections, as `AGENT_SOURCE_TOKEN@<id>`. Moving credentials between the private file and the Keychain carries those tokens too.
- Address: `https://`, or `http://127.0.0.1:<port>`, no user name or password, no secret in the query. No redirect is followed, 10 seconds in total, a reply of at most 256 KB, a source asked at most once every 60 seconds, from a background thread started by the state read and the Fleet read, so a slow source never holds a request.
- Only the mapped fields are kept (length-capped, as text). Snapshots go to `state/agent-sources/<id>/snapshot.json`; the reply is not stored. A failed read keeps the last good list and says so in plain words.
- Fleet shows the source with its agents. An agent whose status is running also shows in Running now on Home, labelled "agent source".
- API: `POST /api/agent-sources` (`add` or `remove`, both need `confirm: true`); the Connections data now carries `agent_sources` (rows, presets, never the token). The CLI token cannot call it, like the other write endpoints.
- A help paragraph on the card, and the full page in `docs/public/AGENTS.md` (Level 2), plus a paragraph in SECURITY.md about this one use of the network.

**D. Level 3, make building an add-on easy (`docs/public/ADDONS.md`, `agents/addon-builder.md`)**
- ADDONS.md: the contract (`install(core)` and the hooks), a working add-on named Relay (the test extracts it from the page and runs it), how to show a page, an alert, a timeline event and a confirmed action, what an add-on must never do, and how to test with a fake HOME.
- `qtdeck addon new <name>` scaffolds `ext_<name>.py` and a test in the data folder (0700 folder, 0600 files), never overwrites; `qtdeck addon list` shows loaded and skipped add-ons with the reason.
- `addon-builder` is a crew file that writes an add-on and its test from the contract and a short description, read-only toward the service, asks before any action button, never sees keys (the code reads a keychain entry by name), and shows a diff. It runs only when the owner starts it. It passes the same agent-file checks as the other crew files.

**Tests added**
- `bin/selftest-agents.sh` (levels 1 and 3) and `bin/selftest-sources.sh` (level 2), both in `bin/check.py` LABELS. Both use a copy of the program, a fake HOME and temp data and secrets folders, and never port 7878, the real data folder, `~/.config` or the keychain.
- `bin/selftest-security.sh` gained the protected-folder checks.

## What was not checked

- The macOS sandbox profile for the add-on folder is text only. No real `sandbox-exec` ran, so a project command being refused a write there on macOS is unproven.
- The model's shell sandbox could not be run here. The deny-write list is compared with the deny rules by a test, but a real model session trying to create `addons/ext_x.py` was not run.
- The Fleet page was not looked at in a browser with a reported source, and neither were the new Connections card and the Running now row for an agent source. Their code is covered by the page's static checks (labels, escaping, dead CSS) and by the data the server sends, not by a screenshot or a click. No headless browser was available for this part.
- Full pages cannot come from the data folder. An add-on there can add alerts, timeline events, state and confirmed actions, not a new page of its own.
- Local add-ons are run from memory: the add-on list shows what loaded at start, and a file changed afterwards is not seen until the dashboard restarts.
- The https path of an agent source was checked as an address rule only. No https server, certificate chain or proxy was exercised.
- The macOS Keychain store for the token was not run (the file store was). The move between stores was only checked as far as the key being listed.
- Behaviour on a very slow trickle of bytes is bounded by the 10 second deadline, but only the "no answer at all" case was tested.
- The full `bin/check.py`, macOS and CI were not run here. The suites of the touched files were.

## What still confuses a newcomer

- Three levels with three different homes: a script command (`qtdeck fleet report`), a form on the Connections page, and a file in `addons/`. The docs open with a table, but nothing in the app says "which one do I need?" at the moment someone looks at an empty Fleet page.
- A source must be registered before it can report (`fleet source add`), but the message that says so only appears when a report is refused.
- The field map is the hardest part of the form. A path such as `data.agents` is clear to someone who has seen the JSON and opaque to someone who has not. There is no "test this address and show me the first reply" button, because the rule is one read per minute and nothing stored from the reply.
- A source can look "waiting" for up to a minute after it is added, then unreachable with a reason. That is correct but easy to read as broken.
- A remote agent cannot write to your disk. People expect "report from the cloud" to work; it needs level 2 or a script on their machine.
- "Local add-on" versus the add-ons that ship in `bin/`: both appear in one list, and only the label tells them apart.
- Status words are fixed for the form. A service with unusual words shows "status unknown" until `status_words` is added by hand in `config/agent-sources.json`.

## Tested only against fake servers

- Agent sources: every request in `bin/selftest-sources.sh` went to a fake server on `127.0.0.1` in the same process (a good reply, a wrong token, a redirect to a second fake host, an oversized reply, a reply that is not JSON, a missing list, a 500, a slow reply, a closed port). No real service, no real tunnel, no real https.
- Level 1: events were written and read in a fake HOME; no real hook-driven session, GitHub Actions run, cloud agent or remote machine reported through it.
- Add-ons: the Relay sample, the scaffold and the broken add-on ran in a temp data folder against a copy of the program.
- The credential store was the file store in a fake secrets folder (`QUARTERDECK_SECRETS_DIR`), never the Keychain.
