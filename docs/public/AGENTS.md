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

(The form on the Connections page, the URL rules and the field map are described here once that level is built.)

## Level 3: write an add-on

For buttons, alerts and timeline events that a form cannot express, see [ADDONS.md](ADDONS.md). `qtdeck addon new <name>` creates the first files in your data folder.
