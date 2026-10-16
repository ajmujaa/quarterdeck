# Threat model

What Quarterdeck protects, from whom, and how. Written from the code in `bin/dashboard.py`, `bin/fleetview.py`, `bin/scan.py`, `bin/guard.py`, `bin/lib.sh`, `bin/claudeproc.py` and `bin/fleet-hook.sh`. Where something is not done, it says so. To report a problem, see [SECURITY.md](SECURITY.md).

This is a single-user tool for your own machine. It is not designed to be exposed to a network or shared between users.

## What runs where

- **Dashboard.** `bin/dashboard.py`, one Python process, bound to `127.0.0.1` only (default port 7878). It serves the page, reads state, and starts runs. Under launchd on macOS it is restarted if it exits.
- **Runs.** The dashboard (or you, or the scheduler) starts `bin/quarterdeck run <project> <duty>` as an argument list, never a shell string. A duty calls the model provider's command line tool with a read-only tool allowlist and a deny list. The harness script, not the model, performs any write, and only with `--apply`.
- **Data folder.** Your registry, state, logs and connector files live in `~/.quarterdeck` (mode 0700), apart from the program.
- **Local voice and chat model.** Started on first use by the dashboard, listening on `127.0.0.1` on its own port with a random per-process key, stopped when idle.
- **Optional hook.** `bin/fleet-hook.sh` can be installed into the provider tool's settings. It appends one line per session event to a file in the data folder.

## Assets

1. Credentials: provider login, GitHub login, connector tokens in `~/.config/quarterdeck/` and `state/connectors/`.
2. Your source code and the registered project folders.
3. Private notes: capture, agenda, intent, rhythm tasks, attention data in `state/`.
4. The ability to run agents and spend model usage.
5. The integrity of what gets pushed, commented or merged on your behalf.

## Trust boundaries

- Browser to dashboard: any web page you have open can send requests to your loopback port. Loopback is not authorisation.
- Dashboard to child processes: only registry-validated projects and duties, narrow argument patterns.
- Model to harness: model output is untrusted text. It becomes an action only by parsing as a contract, and only with an explicit apply.
- Project folder and issue text to model: content written by other people is untrusted input to a model that has read tools.
- Agent to data folder: private files must not be readable by an agent working on a project.

## Threats

| Threat | Mitigation in the code | Residual |
|---|---|---|
| A web page you visit POSTs to `127.0.0.1:7878` (CSRF) | Every POST needs a `X-Quarterdeck-Token` header, a custom header that forces a CORS preflight; the server sends no CORS headers, so a cross-site page cannot send it. An `Origin` that is not loopback is refused (including `null`). Token compared with `secrets.compare_digest`. | None known for this path. |
| DNS rebinding: a page re-points its own name at 127.0.0.1 and reads the server as same-origin | `Host` must be `127.0.0.1` or `localhost` on every GET and POST. A rebound name sends its own name as Host and gets 403. | `[::1]` is refused (safe, but unsupported). |
| Another page reads responses cross-origin | No CORS headers are sent, so the browser blocks the read. | A cross-site page can still trigger a GET it cannot read; the GET routes read state and I found none that changes it. |
| Another local user or local process | Binds loopback only. Token file `state/dashboard.token` is 0600. | **Gap.** The token is in the HTML that `GET /` returns, and `GET /` needs no token. Any local user who can reach the port can fetch the page, read the token, and then POST. See finding 1. |
| Clickjacking: the page framed by another site | None. | **Gap.** No `X-Frame-Options` or CSP `frame-ancestors`. See finding 3. |
| Injection into a command | A run is `argv`. Project and duty must already be in the registry; flags match `^--[a-z][a-z-]{0,20}$`; values match a narrow pattern, no `..`, no leading `/`. Fleet actions come from the local config, not from the request. | Values may still contain characters that matter to the program receiving them (for example `#`, `@`). They are passed as separate arguments. |
| A malicious project folder is scanned (`attach`, `scan.py`) | The scan only reads. It does not follow links (symlinked files and folders are skipped), skips dependency folders, caps depth (4), file count (20000) and manifest size (400 KB). Files named like secrets (`.env`, keys, credentials) are listed by name and never opened. It runs no code from the folder and no git command; the git branch and origin are read from `.git/HEAD` and `.git/config` as text, with credentials stripped from the address. Registering needs `apply` plus `confirm: true`. | The folder path in `/api/attach` can be any directory on the machine, not only one you registered. Needs the token. See finding 5. |
| Fleet view reads a registered repository | Paths must resolve inside the source's own folder (`realpath`, links out are refused). Git is run with `core.fsmonitor=false` and a timeout, as an argument list. Commands are only `status`, `pause`, `resume`, `test` against jobs named in the local config. | Running git in a repository you did not write can still honour that repository's own configuration. Only register repositories you trust. |
| Prompt injection: an issue, pull request, comment or file tells the agent to do something else | The model has no write tools. The default deny list blocks `Write`, `Edit`, web fetch and search, `git push`, `git commit`, `gh pr/issue` writes, `gh api`, `npm publish`, `rm`, `curl`, `ssh`. Output must parse as a contract; the harness applies it only with `--apply`. Each call has a hard dollar cap and timeout. Agents are denied reading the private files in `state/` and `~/.config/quarterdeck`. | An injected agent can still write misleading text into the contract (a false review, a bad issue body), which a person reads before applying. The build duty edits files, but only in a throwaway worktree, and push and PR creation stay with the harness. Nothing wraps untrusted text in a "this is data" marker for the model. See finding 4. |
| Agent reads private files (notes, connector tokens, SSH and cloud keys) | Read denied by path in the deny list. OS sandbox (on by default, `QUARTERDECK_SANDBOX`) also blocks shell commands from reading those paths. | **The sandbox is off by default**, and is never applied to calls that use `gh`. Deny-by-path covers listed paths only. See finding 2. |
| Secrets in the data folder | Folder mode 0700; token, connector and attention files 0600; integration env file refused if group or world readable. Logs hold run envelopes and tails, not connector tokens. | The data folder is not encrypted. Anyone with your account, or a backup of it, can read it. |
| Secrets committed to the repository | `bin/guard.py` scans every tracked file (and history with `--history`) for provider, GitHub, Slack, AWS, Google, Stripe keys and private keys; masks hits; optional pre-commit hook; runs in CI and in the publish step. | Pattern based: an unusual secret format will not match. |
| Local voice and chat model | Model server on loopback only, with a random Bearer key held in memory and passed in the environment, not on the command line. Audio size is capped. The deep-brain process has every tool turned off, no MCP, nothing saved, and runs in an empty temporary folder. | Another local user can still connect to the model port but cannot use it without the key. |
| The optional hook | Records time, event kind, session id, folder name, branch and agent name, only for registered repositories, `umask 077`, always exits 0, asynchronous. It does not read prompts, replies or tool input. Install and uninstall edit the settings file with a backup and only touch their own entries. | It runs on every session event on your machine; the script is short and in the repository. Events are plain text in the data folder. |
| Runaway spend or a loop | Per-call cap, a daily budget, and an idle stop on long processes. Scheduler skips a duty already holding its lock. | Caps are limits, not alarms. |

## What is not in scope

- An attacker who already runs code as you. They can read the data folder and the token file.
- A malicious provider command line tool or a compromised `gh`, `git` or `jq` on your PATH.
- Exposing the dashboard beyond loopback (a reverse proxy or a tunnel). Do not.
- Multi-user machines (see finding 1).

## Findings

Found while writing this page. None is fixed by this document.

| # | Severity | Where | What |
|---|---|---|---|
| 1 | Medium on a shared machine, Low on a single-user one | `bin/dashboard.py`, `do_GET` for `/` | The token is substituted into the page for any request with a loopback Host header. Another local user can read it and then POST (run duties, apply fixes, register projects). |
| 2 | Medium | `bin/lib.sh`, `claude_run`; contradicts SECURITY.md | CORRECTED: the operating system sandbox is on by default (`config/quarterdeck.env` sets `QUARTERDECK_SANDBOX` to on; an earlier reading of `lib.sh` alone missed that). It is skipped for any call whose tools include `gh`. Those calls rely on the path deny list alone. |
| 3 | Low | `bin/dashboard.py`, `_send` | No `X-Frame-Options`, `frame-ancestors`, `X-Content-Type-Options` or CSP on any response. |
| 4 | Medium | `duties/*.sh`, `bin/lib.sh` | Issue, pull request and file text reaches the model with no untrusted-data framing. The harness limits what an injected model can do, not what it can say. |
| 5 | Low | `bin/dashboard.py`, `attach_api` | `path` may name any folder, not only a registered one; the profile (file and folder names, secret file names) comes back to anyone holding the token. |
| 6 | Low | `bin/dashboard.py`, `_body` | The request body is read to `Content-Length` with no upper bound (only audio is capped). A token holder can make the process allocate a lot. |
| 7 | Low | `bin/dashboard.py`, `main` | `dashboard.token` is written with `write_text` and then `chmod 0600`: for a moment the file has the default mode. The data folder is 0700 when created by `home init`, which hides it, but the fallback state folder inside the program folder has no such guard. |
