# Model provider notes

How Quarterdeck talks to the model provider today, what to check before a public release, and how API keys could be supported. This page makes no statement about what the provider's terms say. Read them.

## How it calls the model today

Quarterdeck never talks to a model API itself. It starts the provider's own command line tool (`claude`) as a child process and reads what it prints. It holds no provider credential: the tool uses whatever login you already have on the machine, and Quarterdeck passes its own environment through unchanged.

Two paths:

1. **Duties** (`bin/lib.sh`, function `claude_run`). One non-interactive call per run: `claude -p <prompt> --permission-mode dontAsk --allowedTools ... --disallowedTools ... --output-format json`, with optional `--model`, `--effort`, `--max-budget-usd` and, if enabled, a sandbox setting. It runs in the project folder or a throwaway worktree, with a timeout. The reply is parsed as a contract; the script applies it only with `--apply`. Cost fields in the reply are written to a spend ledger.
2. **The assistant (Helm), deep brain** (`bin/claudeproc.py`, `bin/chatctx.py`). One long-lived `claude -p --input-format stream-json --output-format stream-json` process, started on the first turn, stopped after ten idle minutes and after a few turns, with every tool off, no MCP servers, nothing saved, started in an empty temporary folder, with a dollar cap for its life.

A local open model (voice and short answers) is separate and does not use the provider.

## Which parts are automated use

Be honest about this in the release notes. These start the tool without a person typing at it:

- The scheduler in the dashboard (`fire_due`, every 15 seconds) starts scheduled duties.
- The fix queue drain starts runs for queued items.
- Panels run several model calls from one click.
- Anything started from the dashboard or a board card runs headless.
- The assistant's deep brain runs when you speak or type to it (a person is present, but the process is long-lived and non-interactive).

Interactive use by a person at the tool itself is not what Quarterdeck does. A per-call cap (`QUARTERDECK_CALL_BUDGET`, default 6 dollars) and a daily budget (`QUARTERDECK_DAILY_BUDGET`, default 120) limit spend; on a subscription these measure usage consumed, and a "usage limit reached" reply is detected and the run is retried later without writing anything.

## Check before a public release

Tick each against the provider's current terms, usage policy and the command line tool's own documentation. Date it.

- [ ] Is non-interactive use of the tool (`-p`, stream-json) allowed on a consumer subscription login, and under which plans?
- [ ] Is a scheduler or other unattended automation that starts such calls allowed on a subscription login, or does it need an API key?
- [ ] Is a tool that wraps the command line and shows its output in another interface allowed? Is the rule different if other people install and run it?
- [ ] May the product's own account credentials be used by software the user installs, as opposed to the user typing at the tool?
- [ ] Are there limits on concurrency, or on running several sessions at once (panels, fix queue, helm together)?
- [ ] Are there rules on automated use against third party content (issue and pull request text from other people sent to the model)?
- [ ] Naming: can the project name or README say it works with the provider's tool, and what wording or logos are allowed? Does anything in the UI imply endorsement?
- [ ] Are the flags used here (`--permission-mode dontAsk`, `--disallowedTools`, `--settings` sandbox, `--max-budget-usd`, `--tools ""`, `--system-prompt`) documented and stable? They are the safety boundary, so a rename silently weakens it. Pin or detect the tool version in `doctor`.
- [ ] What does the provider say about data sent through the tool (retention, training) for the person who installs Quarterdeck? The README says nothing leaves the machine except the requests you ask for; keep that sentence accurate.
- [ ] Are there export, region or age restrictions the README should repeat?
- [ ] Re-check on each release; terms change.

If any answer is "no" or "unclear", the safe wording for the README is: Quarterdeck drives the provider's command line tool using your own login, you are responsible for using it within your plan, and API-key mode is the supported route for unattended use.

## Design sketch: API keys instead of a login

No code exists for this. A sketch only.

- **Behaviour.** The command line tool already reads a key from its environment, so the smallest design is: Quarterdeck keeps a key, and puts it in the child's environment for each call. No change to how the tool is called. Local login stays the default; a key is used only if one is configured.
- **Where the key lives.** Two options, in order of preference:
  1. The operating system keychain (macOS Keychain via `security`, Linux Secret Service via `secret-tool`). Read at spawn time, held in memory only for the call, never written to a file, a log, or `ps`.
  2. A file in the data folder, `state/connectors/provider.key`, mode 0600, in a folder that is 0700, refused at load if it is group or world readable (the integration env file already behaves this way). This is the fallback where no keychain exists.
- **Never in:** the registry, `config/*.env`, the repository, logs, the run envelope, or the dashboard page. `bin/guard.py` already matches the provider key format and would catch a commit.
- **Agents must not read it.** Add the key file to the private deny list and the sandbox's `denyRead` list, as the connector folder is now. Because the key is in the environment of the tool, a shell command an agent runs could print it; with a key in play the sandbox should be required, not optional, and `printenv`, `env` and `set` should join the deny list.
- **Setup.** `quarterdeck key set` reads the key from a hidden prompt (not an argument), stores it, and tests it with one tiny call. `key status` shows only the last four characters. `key remove` deletes it.
- **Spend.** With a key, cost is real money, not a usage measure: keep the per-call and daily caps, make the daily cap default lower, and show spend in currency.
- **Dashboard.** Show "using your login" or "using an API key" in plain words. Never show the key.
- **Open questions.** Rotation and revocation notes; whether a separate low-limit key for the scheduler is worth recommending; Windows (no keychain tool is assumed).
