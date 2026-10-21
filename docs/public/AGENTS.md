# Show your own agents

Quarterdeck's Fleet view and the "Running now" strip show the agents it can see. By default that is the crew it runs itself and the sessions the sessions hook sees in your registered repositories. This page is how you put any other agent, script or job on the same screen, in three levels. Pick the smallest one that does what you need.

| Level | What you do | What you get | Section |
|---|---|---|---|
| 1 | Run one command per event from a script | A source in Fleet with its sessions and agents, live on Home | [Level 1](#level-1-report-with-one-line) |
| 2 | Fill in a form on the Connections page | A read-only source polled from a small JSON API | [Level 2](#level-2-an-agent-source-you-add-in-a-form) |
| 3 | Write a small add-on | Your own alerts, timeline events and buttons | [Level 3](#level-3-write-an-add-on) |

Everything here is read-only toward your agents, and nothing here collects keystrokes, your screen, apps or sites, the clipboard, your location, or files outside the projects you registered and the data folder.

## Level 1: report with one line

A source that reports is an id you register once. After that, anything running on this machine can append one line per event to a file in your data folder, and the Fleet view and Home read it. It is the same file and the same line the sessions hook (`bin/fleet-hook.sh`) writes.

### Register the source

```
qtdeck fleet source add relay "Relay jobs"
```

The id is lower case letters, digits, `-` or `_` (up to 31 characters). The label is what the Fleet view shows (up to 80 characters). The command writes `config/fleet.local.json` in your data folder (mode 0600) and keeps every source already in it. Only you do this: `qtdeck fleet report` refuses an id that was not registered, so a stray script cannot invent a source.

### Report an event

```
qtdeck fleet report --source relay --kind session_start --session run-42 --worktree nightly --branch main
qtdeck fleet report --source relay --kind agent_start   --session run-42 --agent checker
qtdeck fleet report --source relay --kind agent_stop    --session run-42 --agent checker
qtdeck fleet report --source relay --kind stop          --session run-42
qtdeck fleet report --source relay --kind session_end   --session run-42
```

| Option | Required | Rule |
|---|---|---|
| `--source` | yes | A registered source id. |
| `--kind` | yes | One of the kinds below. Anything else is refused. |
| `--session` | yes | Letters, digits, `-` or `_`, up to 80. One id for one run, job or session. |
| `--worktree` | no | A task or folder name: letters, digits, `.`, `-`, `_`, up to 60. |
| `--branch` | no | Letters, digits and `. _ / @ + -`, up to 80. |
| `--agent` | with `agent_start` and `agent_stop` | Letters, digits, `.`, `-`, `_`, up to 40. Refused with any other kind. |

| Kind | Meaning on screen |
|---|---|
| `session_start` | A session or run opened (idle until something happens). |
| `prompt` | A turn started: the session is working. Only the fact is recorded; no text is taken. |
| `stop` | The turn finished: the session is waiting for you. |
| `session_end` | The session closed. It moves to "Earlier today". |
| `agent_start` | An agent started inside the session: "Running the checker agent". |
| `agent_stop` | That agent stopped. |

A session that sends nothing for half an hour shows as quiet; one that ends or has been silent for a day drops off the list.

There is no option for a prompt, a reply, a file name or a transcript. Passing one is an error, and every value must match its pattern, so control characters and over-long text are refused. The command exits 0 when the line was written and 1 with a plain reason when it was not.

### The line, exactly

Each report appends one JSON object and a newline to `state/fleet-events/<source>.jsonl` (mode 0600, written with a single append so two reporters never interleave):

```
{"t":1760000000.5,"event":"agent_start","session":"run-42","worktree":"nightly","branch":"main","agent":"checker"}
```

| Field | Content |
|---|---|
| `t` | Seconds since 1970, a number. |
| `event` | One of the six kinds above. |
| `session` | The session id. |
| `worktree` | The task or folder name, or `""`. |
| `branch` | The branch, or `""`. |
| `agent` | The agent name for `agent_*` events, otherwise `""`. |

You can append that line yourself from any language if you prefer not to call `qtdeck`, but then nothing checks it: Quarterdeck ignores a line that does not parse or has an unknown `event`, and keeps the file small by dropping all but the newest 3000 lines once it passes two megabytes.

### Examples

A bash script:

```bash
#!/bin/bash
sid="nightly-$(date +%Y%m%d)"
qtdeck fleet report --source relay --kind session_start --session "$sid" --worktree nightly
qtdeck fleet report --source relay --kind agent_start   --session "$sid" --agent checker
./run-the-checks.sh
qtdeck fleet report --source relay --kind agent_stop    --session "$sid" --agent checker
qtdeck fleet report --source relay --kind session_end   --session "$sid"
```

A Python one-liner, for the start of a job:

```
python3 -c "import subprocess; subprocess.run(['qtdeck', 'fleet', 'report', '--source', 'relay', '--kind', 'session_start', '--session', 'job-7'], check=True)"
```

A GitHub Actions step. This only works on a runner that is your own machine (a self-hosted runner), because the step has to write to your disk:

```yaml
jobs:
  checks:
    runs-on: [self-hosted]
    steps:
      - run: qtdeck fleet report --source relay --kind session_start --session "gh-${{ github.run_id }}" --branch "${{ github.ref_name }}"
      - run: ./run-the-checks.sh
      - if: always()
        run: qtdeck fleet report --source relay --kind session_end --session "gh-${{ github.run_id }}"
```

A cloud agent that runs on your machine (a command-line agent that calls a hosted model but executes here) is just a script: wrap its start and end.

```bash
sid="agent-$$"
qtdeck fleet report --source relay --kind session_start --session "$sid"
my-agent-cli run --task "$1"
qtdeck fleet report --source relay --kind session_end --session "$sid"
```

### A remote agent cannot do this

An agent that runs somewhere else (a hosted runner, a cloud service, another computer) cannot write to your disk, and Quarterdeck does not open a port for it to do so. It reaches you in one of two ways:

- through level 2, if it exposes a small JSON API that Quarterdeck can read, or
- through a script you run on your machine that asks the remote side what is happening and then calls `qtdeck fleet report`.

### Where it shows

The source appears in Fleet under its label, with "Sessions now" and "Earlier today". Sessions that are working or waiting for you also appear in the Running now strip on Home. To stop showing a source, remove its entry from `config/fleet.local.json` and delete its file under `state/fleet-events/`.

## Level 2: an agent source you add in a form

Use this when your agents live somewhere else (a service, a server, a dashboard of your own) and that place can answer a plain web request with a small JSON list. You fill in a form once; Quarterdeck asks for the list in the background and shows what comes back. It only reads. It cannot start, stop or change anything over there.

### Add a source

Open the Connections page and scroll to "Add an agent source". The form asks for:

| Field | What to put |
|---|---|
| Name | A short label. It is the title of the source in Fleet. |
| Address | `https://...`, or `http://127.0.0.1:<port>/...` for a tunnel you run yourself. |
| Token | Optional. Sent as `Authorization: Bearer <token>`. |
| Path to the list | Where the list of agents or tasks is in the reply: `tasks`, or `data.agents` for a list inside an object. Leave it empty if the reply is the list itself. |
| Field: name | Where each agent's name is, relative to one entry. Required. |
| Field: status | Where its status is. Required. |
| Field: last run | Where the time of its last run is. Optional. |
| Field: detail | One short line about it. Optional. |

Two buttons above the form fill it in with examples to change: "A JSON list over HTTPS" and "A dashboard reached through my own SSH tunnel". Their addresses use `example.com`; replace them with yours.

A path is names separated by dots, and a number picks an entry of a list: `data.agents`, `runs.0.state`. It holds letters, digits, `-` and `_` only.

With an address of `https://agents.example.com/api/tasks` and a reply like this:

```json
{"tasks": [
  {"title": "Nightly report", "state": "running", "finished_at": "2026-01-05T08:00:00Z", "message": "3 of 10 done"},
  {"title": "Weekly sync", "state": "completed", "finished_at": "2026-01-04T17:30:00Z", "message": ""}
]}
```

the field map is list `tasks`, name `title`, status `state`, last run `finished_at`, detail `message`.

### Status words

Whatever your service calls a state, Quarterdeck shows one of four, or "status unknown":

| Shown as | Words it recognises (any capitals) |
|---|---|
| running | running, active, in_progress, started, busy, working, executing, processing, live, on |
| waiting | waiting, pending, queued, paused, idle, blocked, needs_input, scheduled |
| done | done, success, succeeded, completed, complete, ok, finished, passed |
| failed | failed, failure, error, errored, crashed, cancelled, aborted, timeout |

If your service uses other words, add them in `config/agent-sources.json` as `"status_words": {"running": ["go"], "done": ["landed"]}` on that source.

### The rules it keeps

- **Address.** `https://` only, or `http://127.0.0.1:<port>`. Quarterdeck never starts ssh or a tunnel: if you use one, you start it and leave it running. An address with a user name, a password or a secret in its query is refused. Put the token in the token field.
- **No redirects.** A reply that sends Quarterdeck to another address is not followed, because the token would go with it. The source shows as unreachable and says why.
- **Limits.** 10 seconds for the whole request, a reply of at most 256 KB, and no more often than once a minute per source. The request runs on a background thread, so a slow source never slows the dashboard or any other page.
- **The token.** It is saved in the same place as the other connections (the private file in `~/.config/quarterdeck`, or the macOS Keychain if you chose that), under the name `AGENT_SOURCE_TOKEN@<source id>`. It is never written to `config/agent-sources.json`, to a snapshot or to a log, and it is never shown again. Removing the source deletes it.
- **Only the mapped fields are kept.** Name (80 characters), status, last run (40) and detail (200). Everything else in the reply, and the reply itself, is dropped. They are shown as text: if a name holds `<b>` or a script tag you see those characters, nothing runs.
- **Where things are kept.** The setup is in `config/agent-sources.json` (mode 0600, no secrets). The last answer is in `state/agent-sources/<id>/snapshot.json`.

### Where you see it

- **Fleet** lists each source under its name with its agents, their status and last run. If a source cannot be reached, the page says so in plain words ("Could not reach it. Check the address and your connection, and that the tunnel is running if you use one.") and keeps showing the last list with how old it is. Nothing else on the page changes.
- **Home**, in the Running now strip, shows an agent from a source while its status is running, labelled "agent source".

### Take it away

Press Remove on the source in the Connections page. Its entry, its token and its snapshots are deleted. Nothing is touched on the service.

### What it is not

It is not a way to control agents, to see their transcripts or to read their files. A service that needs a login page, a cookie, or a sign-in flow cannot be used here; for that, write an [add-on](ADDONS.md). A remote agent still cannot write to your disk. If you cannot offer a JSON address, report from a script on your machine instead (level 1).

## Level 3: write an add-on

For buttons, alerts and timeline events that a form cannot express, see [ADDONS.md](ADDONS.md). `qtdeck addon new <name>` creates the first files in your data folder.
