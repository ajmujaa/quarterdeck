# Write an add-on

An add-on is one Python file with one function. Quarterdeck imports it when the dashboard starts and hands it the dashboard's own names; the add-on fills in a few lists (alerts, timeline events, state, buttons) and the dashboard does the rest. With no add-ons the dashboard is exactly what it is without them.

Use an add-on when the two simpler ways are not enough: [level 1](AGENTS.md#level-1-report-with-one-line) (one line per event) and [level 2](AGENTS.md#level-2-an-agent-source-you-add-in-a-form) (a form) only show agents. An add-on can raise an alert, put events on the timeline, and offer a button you press and confirm.

## Where it lives

```
qtdeck addon new relay        # writes <data folder>/addons/ext_relay.py and test_relay.py
qtdeck addon list             # what loaded, what was skipped, and why
```

`qtdeck addon new` never overwrites a file. The dashboard loads `addons/ext_*.py` from your data folder (and `bin/ext_*.py` from the program folder) when it starts, so restart it after a change.

An add-on from your data folder is code that runs as you, so it is only loaded when this holds:

- `addons/` is a real folder (not a link), owned by you, mode 0700;
- each `ext_*.py` is a regular file (not a link), owned by you, not writable by group or others;
- the name after `ext_` is lower case letters, digits and `_`.

Anything else is skipped, logged with the reason (`logs/dashboard-server.log`) and shown by `qtdeck addon list`; it never stops the dashboard. Start the dashboard with `QUARTERDECK_ADDONS=off` to load none of them. Models and project commands cannot write to this folder. In the Add-ons list these show as "local add-on".

A local add-on has no page script of its own: the dashboard serves page scripts only from the program folder. Everything below works from the data folder; a full page of your own is a built-in add-on (`bin/ext_<name>.py` with `dashboard/assets/ext-<name>.js`) and is outside this guide.

## The contract

```python
def install(core):
    ...
```

`core` gives read access, live, to the dashboard module's own names, for example `core.STATE` (the `state/` folder), `core.LOGS`, `core.iso(dt)`, `core.now_utc()`. Optional module names: `ADDON_NAME` (a short label shown in the Add-ons list; default is the file name made readable).

`install` fills these lists in `core.EXT` (the hooks are listed in `bin/dashboard.py` above `EXT`):

| Hook | Shape | Shows up as |
|---|---|---|
| `EXT["state"]` | `key -> fn()` returning JSON | A key in `/api/state` |
| `EXT["health"]` | `key -> fn(now)` | A key in `/api/health` |
| `EXT["attention"]` | `fn(ack)` returning alert dicts | Items on the Needs you list |
| `EXT["events"]` | `fn(cutoff)` returning event dicts | Rows on the timeline |
| `EXT["post"]` | `"/api/path" -> fn(body)`, raise `ValueError` for a 400 | A button's action |
| `EXT["start"]` | `fn()` | A background loop, started with the server |

(`words`, `misheard`, `commands`, `describe`, `rules`, `schema`, `shots` and `vet` extend what Helm may say; leave them alone unless you read the comment above `EXT`.)

An alert is a dict with `id` (stable and unique), `source`, `project` (or `""`), `severity` (a word such as `FAILED`), `text`, `at` (an ISO time ending in `Z`), `stale` and `acknowledged` (`id in ack`). A timeline event is `at`, `project`, `duty`, `verdict`, `detail`, `kind` (`run` or `merge`) and `url` (`https://...` or `None`). Keep every text short; the page shows it as plain text, never as markup.

## A working add-on: Relay

Relay reads a list of jobs that a script of yours writes to `state/relay/jobs.json`, raises an alert for each failed one, puts every job on the timeline, and offers one confirmed button that clears a failed job. It writes only inside `state/relay/` and its own log.

```python
# ext_relay.py
import json
from pathlib import Path

ADDON_NAME = "Relay"


def install(core):
    folder = Path(core.STATE) / "relay"           # the only place this add-on writes

    def jobs():
        try:
            data = json.loads((folder / "jobs.json").read_text())
        except (OSError, ValueError):
            return []
        return [j for j in data if isinstance(j, dict)][:50] if isinstance(data, list) else []

    def alerts(ack):
        return [{"id": "relay:" + str(j.get("id"))[:40], "source": "relay", "project": "", "severity": "FAILED",
                 "text": "Relay job %s failed" % str(j.get("name", "?"))[:60], "at": str(j.get("at") or core.iso(core.now_utc())),
                 "stale": False, "acknowledged": ("relay:" + str(j.get("id"))[:40]) in ack} for j in jobs() if j.get("status") == "failed"]

    def events(cutoff):
        return [{"at": j["at"], "project": "", "duty": "relay", "verdict": str(j.get("status", ""))[:40], "detail": str(j.get("name", ""))[:140],
                 "kind": "run", "url": None} for j in jobs() if isinstance(j.get("at"), str) and j["at"] >= cutoff]

    def clear(body):                              # a button the owner pressed and confirmed
        if body.get("confirm") is not True or not isinstance(body.get("id"), str):
            raise ValueError("confirm is required")
        left = [j for j in jobs() if str(j.get("id")) != body["id"]]
        (folder / "jobs.json").write_text(json.dumps(left))
        with open(Path(core.LOGS) / "addon-relay.log", "a") as f:
            f.write("%s cleared job %s\n" % (core.iso(core.now_utc()), body["id"][:40]))

    core.EXT["state"]["relay"] = lambda: {"jobs": len(jobs()), "failed": sum(1 for j in jobs() if j.get("status") == "failed")}
    core.EXT["attention"].append(alerts)
    core.EXT["events"].append(events)
    core.EXT["post"]["/api/relay/clear"] = clear
```

## Showing things

- **An alert.** Append a function to `EXT["attention"]`. It runs every time the page asks for the Needs you list, so keep it cheap and let it return `[]` when there is nothing to say.
- **A timeline event.** Append a function to `EXT["events"]`. It is given the oldest time the window shows and returns events newer than that.
- **Numbers or a list for the page.** Put a function in `EXT["state"]`; its result appears under your key in `/api/state`. Keep it small.
- **A page.** See "Where it lives": a page of your own needs a built-in add-on.

## A safe action

An action is a route in `EXT["post"]`. The dashboard has already checked the session token and that the request came from its own page. Keep to these rules:

1. The page button asks the owner to confirm, and the route refuses a body without `"confirm": true`.
2. It does one thing that the owner named, to something the add-on owns (its own state folder), and writes one line to a log saying what it did.
3. It validates every field it reads from the body and raises `ValueError` with a plain reason for anything else. It never builds a command or a path from the body.
4. Reading an outside service stays read-only unless the owner asked for the action by name.

## What an add-on must never do

- Read the owner's keys: the keychain, `~/.ssh`, `~/.aws`, `~/.config`, the dashboard token, or any `.env` file. If it needs a secret, it reads a keychain entry by name that the owner stored on the Connections page.
- Collect keystrokes, the screen, other apps or sites, the clipboard or the location.
- Write outside its own state folder (`state/<name>/`) and its own log.
- Send data out. An add-on that fetches from a service the owner named may read from it; it never posts the owner's data to anywhere.
- Run a command built from text it did not write, or import code from anywhere but the standard library and its own folder.
- Put text from outside (a service's reply, a job name) into the page as markup. Short plain strings only.

## Testing it

`qtdeck addon new <name>` writes `test_<name>.py` beside the add-on. A test needs no dashboard and no real data: it makes a temporary folder, points `HOME` at it, hands `install` a stand-in `core` with the few names the add-on uses, and calls the functions.

```python
import os, sys, tempfile
from pathlib import Path


class Core:
    EXT = {"state": {}, "attention": [], "events": [], "post": {}}
    iso = staticmethod(lambda t: "2026-01-01T00:00:00Z")
    now_utc = staticmethod(lambda: None)


with tempfile.TemporaryDirectory() as t:
    os.environ["HOME"] = t
    core = Core()
    core.STATE, core.LOGS = Path(t) / "state", Path(t)
    (core.STATE / "relay").mkdir(parents=True)
    (core.STATE / "relay" / "jobs.json").write_text('[{"id": "1", "name": "Example", "status": "failed", "at": "2026-01-01T00:00:00Z"}]')
    sys.path.insert(0, "/path/to/addons")
    import ext_relay
    ext_relay.install(core)
    assert core.EXT["attention"][0]({})[0]["text"] == "Relay job Example failed"
```

Never point a test at port 7878, your real `~/.quarterdeck`, `~/.config` or the keychain.

## Have it built for you

`agents/addon-builder.md` is a helper you start yourself. Give it this page and a few lines about the service ("my agents are at ..., they report status like ..."); it writes the add-on and its test into `addons/` using the scaffold and shows you the result as a diff to accept. It reads from the service only, asks before it adds any button, and never sees your keys.
