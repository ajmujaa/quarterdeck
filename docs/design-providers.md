# Design: a provider layer behind `claude_run`

Status: steps 1 and 2 of the migration plan are built, with the fake adapter and the provider setting (ticket #100; see "Found while implementing" at the end). Everything else is a proposal for review.

Today every model call goes through `claude_run` in `bin/lib.sh`, and `claude_run` starts one tool, the `claude` command line program. This document describes how to put an adapter layer behind it so that Quarterdeck can also use OpenAI Codex CLI, Gemini CLI, any OpenAI-compatible HTTP API, and a local model, without weakening any safety guarantee that the threat model ([THREAT-MODEL.md](../THREAT-MODEL.md)) lists today.

The rule that governs everything below: **a guarantee that a provider cannot enforce must be enforced by the harness, or the duty refuses to run on that provider.** It is never quietly dropped.

## What is decided

- `claude_run` keeps its name, its arguments and its return codes (0 text on stdout, 1 failure, 2 usage limit, 3 per-call cap). Duties do not change. The provider is chosen inside it.
- Everything that is about safety and not about a provider's flags stays in `claude_run` or moves to a shared function in `bin/lib.sh`: the tool-list checks, the path rules, the secret screen of the working folder, the clean environment, the timeout, the spend record, the output scan. Only the last step, "start this provider with these inputs and give back text and cost", is an adapter.
- An adapter declares what it can enforce (a capability list). A duty declares what it needs. If the need is not covered, the call is refused before any model runs, with a message that names the missing guarantee.
- Review duties (no shell, read-only) may run on any provider whose adapter can show a read-only file view limited to the working folder, or on a provider where the harness itself serves the files (see "API providers" below).
- Builder duties (the shipwright and anything else that edits) run only on adapters that can run a model's shell and file edits inside an operating system sandbox the harness controls, or where the harness applies the edits itself.
- The default provider stays Claude Code. A provider is opt-in per crew seat. A new install changes nothing.
- API keys live in the credential store and are never a process argument.
- The injection suite runs once per adapter and its report is a release gate for that adapter.

## What the owner must decide

1. Which providers to ship first. Recommendation: Claude Code (as is), a fake provider (tests), and one OpenAI-compatible HTTP adapter. That last one covers a hosted API and local servers with one piece of code. Codex CLI and Gemini CLI come after, because each brings its own agent loop that has to be proven against the guarantees.
2. Whether a duty that a provider cannot serve safely should refuse (recommended) or fall back to Claude Code with a visible notice.
3. Whether to ever allow a provider's own agent loop to run a shell for a review duty. Recommendation: no.
4. Whether builder duties are offered at all on non-Claude providers in the first release. Recommendation: not in the first release.
5. The terms question in [MODEL-PROVIDER-NOTES.md](../MODEL-PROVIDER-NOTES.md) must be answered for each new provider before it ships.

## The two kinds of provider

**Agent CLIs** (Claude Code, Codex CLI, Gemini CLI). A program that runs its own loop with its own tools, reads files and may run commands. Quarterdeck starts it and constrains it from outside, with whatever flags and sandbox the program offers. The harness cannot see inside the loop, so the guarantees depend on the program.

**Plain model endpoints** (OpenAI-compatible HTTP API, local models). A request in, text out, and optionally tool calls the client must carry out. There is no agent loop to constrain, because the harness is the loop. For these, the harness can give the model exactly the tools it chooses to implement. This is the stronger position: a "read file" tool that the harness itself implements can refuse any path outside the working folder, and no shell tool exists unless the harness writes one.

This split drives the design. For an agent CLI the harness asks the program to restrict itself and checks that it can. For an endpoint the harness restricts by construction.

## The adapter interface

An adapter is a shell function pair in `providers/<name>.sh` (sourced by `bin/lib.sh`), plus an optional small Python helper where shell is awkward (the HTTP adapter). No adapter does anything the shell layer has not already approved.

Inputs, all prepared by `claude_run` before the adapter is called:

| Input | Meaning |
|---|---|
| prompt | The full prompt text. Always given on standard input or in a 0600 file in `state/tmp`, never as an argument. |
| tools | The already validated tool names from the duty (`Read`, `Grep`, `Glob`, `Edit`, `Write`, named commands). The adapter maps these to its own tool vocabulary, or reports that it cannot. |
| deny | The already built deny list (private paths, secret-screen results). |
| workdir | A physical absolute path, already checked. |
| model | The model name for this seat and duty, or empty for the provider default. |
| effort | An effort level, or empty. An adapter that has no such setting ignores it and says so in the call record. |
| budget | The per-call cap in dollars (`QUARTERDECK_CALL_BUDGET`), or empty. |
| timeout | Seconds (`QUARTERDECK_RUN_TIMEOUT`). Applied by the existing `guard`, not by the adapter. |
| sandbox | Whether the harness requires an operating system sandbox for this call (it does whenever a shell is among the tools). |
| env | The minimal environment, built per provider (see "Minimal environment"). |

Outputs, written to the adapter's standard output as one JSON object, so that everything after the call stays provider-neutral:

```
{"text": "...", "cost_usd": 0.0, "cost_known": true|false,
 "input_tokens": 0, "output_tokens": 0, "turns": 0,
 "model": "...", "stop": null | "cap" | "limit" | "error" | "turns",
 "enforced": ["readonly-view","path-scope","no-shell", ...]}
```

`claude_run` turns this into what the callers already see: the text on stdout; return 3 for `stop: cap`; return 2 for `stop: limit` (and writes `state/usage-limit` as today); a spend record via `record_spend`, which becomes provider-neutral; the raw envelope in `logs/runs/`.

Capabilities. Each adapter has a function `<name>_capabilities` that prints the guarantees it can keep for a call:

| Capability | Meaning |
|---|---|
| `readonly-view` | The model can read files and cannot change anything. |
| `path-scope` | Reads are limited to the working folder, symlinks and `..` included, with the deny list applied. |
| `no-shell` | The model has no way to run a command. |
| `shell-sandboxed` | If a shell exists, it runs in the harness's sandbox (or one the harness has verified). |
| `edit-scoped` | Edits and writes are limited to the working folder and exclude its `.git`. |
| `clean-env` | The program starts with the minimal environment and cannot be made to inherit more. |
| `no-project-config` | The program does not load the working folder's own settings, hooks or tool servers. |
| `budget` | The program or the adapter can stop a call at a dollar or token cap. |
| `cost-report` | The program reports cost or token use. |

A duty has a needs list in its header (for example review duties need `readonly-view path-scope no-shell clean-env no-project-config`). `claude_run` compares and refuses when a need is missing.

## How each safety guarantee is kept

The list follows the table "What a model call can do" in the threat model.

### No shell for review duties

- Claude Code: `--tools "Read,Grep,Glob"`, as today.
- Gemini CLI: its settings have `tools.core` ("Restrict the set of built-in tools with an allowlist") and `tools.exclude` ("Tool names to exclude from discovery"). The adapter would write a settings file naming only read tools and keep the shell tool out. Verified in the Gemini CLI configuration reference. Not verified: the exact built-in tool names for the current release, and whether settings from the working folder can be switched off (see `no-project-config`). Until both are checked on a real install, `no-shell` for Gemini is marked **unproven** and the doctor check below must test it.
- Codex CLI: the sandbox modes are `read-only`, `workspace-write` and `danger-full-access`, and approval policies are separate. In `read-only` the documentation says Codex can inspect files but cannot edit files or run commands without approval. That is not the same as having no shell tool: the model can still ask to run a command and the approval policy decides. With `never` as the approval policy a command that would need approval is not run. Whether this is a reliable "no shell" is **unverified**; treat Codex as `readonly-view` only, not `no-shell`, until a test proves a requested command does not run.
- OpenAI-compatible API and local models: no shell exists, because the harness does not offer one. `no-shell` holds by construction.

If an adapter cannot claim `no-shell`, review duties on it are refused unless the owner turns on a setting named in plain words (`allow_shell_review_on_<provider>`), recorded in the run ledger. Recommended default: refuse.

### Path-scoped reads and the deny list

- Claude Code: allow rules scoped to the working folder, the deny list, and the secret screen (`bin/guard.py --worktree-secrets`), as today.
- Agent CLIs without an equivalent rule syntax: the harness gives the program a **view** of the project and not the project. For a review duty the harness copies (or bind-mounts read-only) the files the duty needs into a scratch folder, after removing every file the secret screen denied and every path on the private list, and starts the program there. Then path scope is a property of the folder, not of the program's rules. This costs time on a large repository, so it is bounded by the same size budgets the duties already use.
- API and local providers: the harness implements `read_file`, `list_files` and `search` tools itself, resolving every path with the same physical-path check `claude_run` uses, refusing anything outside the working folder, anything on the deny list and anything the secret screen denied. It never follows a link out.

The secret screen of the working folder runs before every call that can read, for every provider, and its fail-closed behaviour is unchanged.

### Protected-path gate

This is not a provider feature at all. `model_diff_gate` and `bin/protect.py` look at what changed in the worktree after the model stopped and refuse before any check runs. They work on any provider as they are. This is the most useful property of the existing design for this work: **the check on the result does not depend on who produced it.**

### Sandbox

- Claude Code: the CLI's sandbox settings, as today.
- Gemini CLI: documents `--sandbox`, `GEMINI_SANDBOX` (values `true`, `docker`, `podman`, `sandbox-exec`, `runsc`, `lxc`) and, on macOS, Seatbelt profiles selected by `SEATBELT_PROFILE` with a default of `permissive-open`. Verified in the sandbox page. The default profile is permissive, so the adapter would have to choose a stricter one and the doctor check must prove it holds. Not verified: whether a stricter profile blocks reading the private list.
- Codex CLI: sandbox modes as above; the default for `codex exec` is documented as read-only (from search results quoting the official page; the page itself could not be fetched here). The Linux and macOS implementation is **unverified** in this work.
- When the program's own sandbox is not trusted, the harness wraps the whole program in the sandbox it already has for project commands (`px_prepare`: `sandbox-exec` on macOS, `bwrap` on Linux). That wrapper already denies the private list, allows writes only in the working folder, and limits the network. For an agent CLI the network must reach the provider's API host. That needs a network rule that allows named hosts only, which neither backend does today (the macOS profile allows loopback only in check mode). This is the largest piece of new work in the design and is listed under "Open questions".

### Minimal environment

`_qd_claude_env` builds a per-call environment from a fixed list. Each adapter supplies its own list in the same shape: the variables that program needs to start and sign in, and nothing else. The credential for an API provider is not in the list; it is passed as described under "API keys". A test, as for Claude today, starts the adapter with decoy values in the owner's environment and checks none arrive.

### Outgoing secret scan

`bin/outscan.py` already scans what the harness posts or pushes. Two additions for providers:

- **Before sending to a hosted provider**, the prompt is scanned with `outscan.py`. A hit stops the call (return 1, logged by label, never the value). This matters more once the prompt may go to a service the owner has not used before. For Claude Code the prompt is not scanned today; this document recommends adding the scan for all providers so the behaviour is the same everywhere.
- **After the call**, the returned text is scanned before the duty acts on it, as the harness does for every post. This is unchanged.

### Untrusted wrapping

`untrusted()` is plain text built by the harness and works for any provider. The injection suite (below) is how each provider's response to it is measured.

### Settings and tool servers from the project folder

Claude Code gets `--setting-sources ""` and `--strict-mcp-config`. For other agent CLIs the capability `no-project-config` must be proven: Gemini and Codex both read configuration files, and whether a repository's own files can change their behaviour is **unverified here**. Where it cannot be proven, the adapter runs the program with the view folder described above (a copy without the repository's configuration folders) and a home folder the harness controls.

## API providers (OpenAI-compatible HTTP, local models)

One adapter, `providers/openai-compatible.sh`, with a Python helper. Configuration: a base URL, a key name in the credential store (empty for a local server), and a model name.

Facts verified in official documentation: Ollama serves an OpenAI-compatible API at `http://localhost:11434/v1/`, "The client requires an API key value, but Ollama ignores it", chat completions support tools and streaming, and `stream_options.include_usage` is supported. Ollama's cloud API at `https://ollama.com/v1` takes a key in `OLLAMA_API_KEY`.

Unverified (the OpenAI documentation host could not be reached from the build environment): the exact field names of the chat completions request and the usage object of OpenAI's own API. They are widely known and match what Ollama documents, but this document does not rely on them as verified. The adapter must be written against the official reference at that time.

Design:

- The helper sends one request, runs the tool loop itself (`read_file`, `list_files`, `search`, and for builders `write_file` limited to the working folder), counts turns, stops at a turn limit, and returns the final text.
- It reads cost from the response's token counts and a price table in `config/prices.json` (model name to price per million tokens, owner-editable). A model without a price entry has `cost_known: false`, and the daily budget treats an unknown cost conservatively (see "Cost and limits").
- Tool calls from models are weaker than from an agent CLI's trained loop. A local model may produce malformed calls. The helper allows a small number of retries and then returns `stop: error`.
- Because the harness is the loop, `readonly-view`, `path-scope`, `no-shell`, `edit-scoped`, `clean-env` and `no-project-config` are all true by construction. `shell-sandboxed` is not applicable.
- A local server on the same machine needs no key and no outbound network. A hosted endpoint sends the prompt, which can quote private code, off the machine. The dashboard says so in plain words on the seat.

## Settings per crew seat

Crew files already carry a `model:` line. Extend the frontmatter, optional, empty means "the install default":

```yaml
provider:            # claude | codex | gemini | openai-compatible | fake
model:               # unchanged; meaning depends on provider
effort:              # unchanged where the provider has it
endpoint:            # openai-compatible only: a name from config/providers.json, not a URL
```

Endpoints and their key names are defined once in `config/providers.json` (base URL, key name, local or hosted). The crew file only names an endpoint. The existing order of precedence in `claude_run` (override, persona, duty default, fleet default) is kept and applied to the provider as well as the model, so a decision panel can still put every seat on one provider.

A panel may mix providers across seats. That is a feature (different views) and a cost (each provider's terms, limits and prices apply). Each seat's call is recorded with its provider.

## Doctor checks

`qtdeck doctor` already checks binaries and runs the self-tests. For each provider that is configured on any seat:

1. The program or endpoint is present and its version is recorded. A version outside the range the adapter was tested against is a warning, because flags are the safety boundary (this is also on the list in [MODEL-PROVIDER-NOTES.md](../MODEL-PROVIDER-NOTES.md)).
2. Sign-in works, using the cheapest possible call. No prompt content from a project.
3. The capability probes, each against a throwaway folder with decoy files, using the real program (these cost a little and are run on request, `doctor --deep`, not every time):
   - a read of a file outside the folder is refused;
   - a read of a decoy credential file inside the folder is refused;
   - a request to run a command in a review call does not run (a marker file is not created);
   - an edit to `.git` is refused;
   - the decoy value of an environment variable set in the owner's shell is not visible to the model.
4. The offline checks with the fake provider (below) always run.
5. A provider whose probes fail is shown as unavailable for the duties that need the failed capability, with the reason.

## A fake provider for tests

`providers/fake.sh` implements the adapter interface with no network and no program. It reads a script of canned replies from a file named by the test, can be told to return text, a cost, a limit message, a cap stop, malformed output, or nothing, and records every input it was given (prompt, tool list, deny list, environment names, working folder, whether stdin or an argument carried the prompt) to a file the test reads.

It does two jobs:

- It tests `claude_run` and every duty with no cost, as the existing stand-in model does for Claude (`QUARTERDECK_CLAUDE_ENV=inherit` exists for that today). The capability refusal paths, the cost record, the limit mark and the cap return code are all tested with it.
- It is the "obeying model" for the injection structural checks: it can be scripted to do what the hostile text asks, to show the harness contains it.

The fake declares every capability so that all duties can run on it, plus a switch to remove one capability, to test that the refusal fires.

## Running the injection suite per adapter

The suite is `bin/inject-eval.py` with fixtures in `injection/fixtures.py`. The structural check already builds each duty's real prompt with every fixture in every input place and inspects the recorded prompt, tool list and flags. Per adapter:

1. Structural (offline, fake provider): unchanged. Runs always.
2. Adapter structural: the recorded call for each adapter is checked for the guarantees (no argument holds the prompt or a key, the tool mapping is what the capability list says, the environment holds no decoy).
3. Real model (costs money): `inject-eval.py real --provider <name>` runs each reviewed duty against all fixtures with the adapter's model. A new report is written to `docs/` with the date, the provider, the program version and the numbers, in the format of the existing report.
4. Positive control: once per provider, with the wrapper removed, to show the measurement can see obedience on that provider.
5. Gate: an adapter is not offered for a duty until its report shows zero effects landed for that duty, and every flagged run was read by a person.

Local models are expected to obey more often than the large hosted ones. The suite measures that, and the answer decides whether a local model is offered for review duties at all. The harness checks (contract parsing, no shell, scanned output, apply only on request) are what contain an obeying model, and the report must show that they did.

## Cost and limit handling

- **Cost.** `record_spend` reads the adapter's neutral fields. A provider that reports cost (Claude Code does today) is recorded as given. A provider that reports tokens only is priced from `config/prices.json`. A provider with neither is recorded with `cost_known: false`.
- **Daily budget.** Unknown cost is counted at a configurable per-call estimate (default: the per-call cap) so that the daily budget cannot be bypassed by a provider that does not report. The dashboard shows "estimated" next to such figures.
- **Per-call cap.** Claude Code has `--max-budget-usd`. For adapters without an equivalent the cap is enforced by the harness: a token limit on the request, a turn limit in the helper, and for an agent CLI the timeout plus the daily budget, with the limitation stated. The Gemini CLI configuration has `model.maxSessionTurns` and its headless mode exits with code 53 when the turn limit is exceeded (both in the Gemini documentation); there is no dollar cap that is documented there. Codex: **unverified** whether a dollar or turn cap exists.
- **Limit replies.** Each adapter maps its provider's rate and quota errors to `stop: limit`. `claude_run` then writes `state/usage-limit` and returns 2 exactly as today, so the queue waits instead of failing every item. The text patterns that Claude Code uses are provider specific; the adapter owns its own. Gemini's documented exit code 1 (general error or API failure) is not specific enough, so the adapter must read the error body (unverified what it contains).
- **Concurrency.** A panel runs several calls at once. Each provider gets a concurrency limit in `config/providers.json`, so a hosted API's rate limit is not exceeded by a panel.

## API-key storage

- A key is held in the credential store that connections already use: the 0600 file in a 0700 folder under `~/.config/quarterdeck/` by default, or the macOS Keychain when the owner opted in (`bin/integrations/keychain.py`: the secret goes in on standard input, hex-encoded, to `security -i`, never as an argument). Linux without a secret service uses the file.
- A key is **never** a process argument, never in `config/*.env`, never in the registry, a log, the run envelope or the dashboard page (the page shows only "set" or "not set" and the last four characters).
- Entering a key: `qtdeck key set <name>` reads it from a hidden prompt on the terminal, or from standard input.
- Using a key: the adapter reads it at spawn time, in the harness process. For an agent CLI that wants it in an environment variable (Gemini documents `GEMINI_API_KEY`), the harness puts that one variable into the clean environment of that one child for that one call. Because the child's shell commands could print its environment, a call that has both a key in its environment and a shell is only allowed under the harness's sandbox, and `printenv`, `env` and `set` join the shell deny list. For the HTTP helper the key is read by the helper from a file descriptor or standard input and sent in a header; it is never in the helper's arguments or environment.
- The key's file path is added to the private path list, so the deny list, the sandbox read rules and the project-command sandbox all cover it from the one list (a test already fails if the lists differ).
- A hosted-provider call gets the outgoing prompt scan described above.
- Rotation: `key set` replaces. `key remove` deletes. Revocation at the provider is the owner's step; the doctor check shows the first failed sign-in.

## Migration plan, in small steps

Each step is one change that can be merged and reverted alone, with its tests.

1. **Name the seam.** Move the last part of `claude_run` (the `claude` invocation and its result handling) into a function `provider_call_claude`, called through a one-line dispatch on `QUARTERDECK_PROVIDER` (default `claude`). Behaviour identical. All existing tests pass unchanged.
2. **The neutral result.** Make `record_spend` and the cap and limit checks read the neutral JSON; the Claude adapter produces it from the CLI's envelope. Identical behaviour, new fields in the spend ledger.
3. **Capabilities and needs.** Add the capability functions and the needs line to duties. The Claude adapter declares everything it does today. Add the refusal path and its test with a capability removed.
4. **The fake provider** and the tests that use it: input recording, refusal, cost, limit and cap paths. Move the existing stand-in model tests onto it where that is simple.
5. **Provider in crew and config.** The `provider:` and `endpoint:` keys, `config/providers.json`, the precedence rule, the dashboard showing the provider per seat. Only `claude` and `fake` are accepted.
6. **Outgoing prompt scan** for all providers, including Claude. Separate step because it changes today's behaviour: a prompt that holds a credential-shaped string would now stop a call.
7. **API-key storage:** `key set/status/remove`, store lookup, private path list entry, tests with a stub store.
8. **OpenAI-compatible adapter**, local server first (no key, no outbound network), review duties only. Doctor probes. Injection report for it.
9. **Hosted OpenAI-compatible endpoint:** key, price table, outgoing scan, concurrency limits. Injection report.
10. **Gemini CLI adapter,** review duties only, after the probes in "No shell" and "no-project-config" are run against a real install and the results written down here.
11. **Codex CLI adapter,** same conditions.
12. **Builders on other providers,** only if the owner decides yes, and only through the harness's own sandbox wrapper with a host allow-list network rule.

## Open questions

- A network rule that allows named hosts only, in the macOS and Linux sandboxes, is needed to wrap an agent CLI that must reach its provider. Neither backend has one now. Is it worth building, or should agent CLIs other than Claude Code rely on their own sandbox with the doctor probes as the evidence?
- The terms of each provider for unattended use, wrapping, and automated use against third-party content. Each has to be read for that provider (see [MODEL-PROVIDER-NOTES.md](../MODEL-PROVIDER-NOTES.md)). This document states nothing about them.
- Whether a local model can be trusted with review duties at all. The injection numbers will say.
- Output parsing: contracts are plain text lines the models are told to print. Smaller models drop fields. Does a provider need a repair pass, and is a second call for that acceptable?
- Price table upkeep: prices change. Who updates `config/prices.json`, and what does the dashboard say when it is old?
- Helm's chat process (`bin/claudeproc.py`) is a separate path from `claude_run` and a long-lived stream. It is not covered by this design. Moving it is a second project.
- Windows: no sandbox or keychain tool is assumed.

## Facts about other providers, and how sure they are

Verified in official documentation during this work:

- Gemini CLI headless mode: runs with `-p`/`--prompt` or in a non-TTY; `--output-format json` returns an object with `response`, `stats` and an optional `error`; `stream-json` emits JSON Lines events (`init`, `message`, `tool_use`, `tool_result`, `error`, `result`); exit codes 0, 1, 42, 53. (Headless page.)
- Gemini CLI sandbox: `-s`/`--sandbox`, `GEMINI_SANDBOX` values, Seatbelt via `sandbox-exec` with default profile `permissive-open`, Docker and Podman, gVisor and LXC on Linux. (Sandbox page and configuration reference.)
- Gemini CLI settings: `tools.core`, `tools.allowed`, `tools.exclude`, `--approval-mode` values `default`, `auto_edit`, `yolo`, `plan` (plan is documented as not fully functional), `--allowed-tools`, `model.maxSessionTurns`, `GEMINI_API_KEY`, and `.env` file loading from the current directory upward. (Configuration reference.)
- Ollama: OpenAI-compatible base URL, key ignored locally, tools and streaming on chat completions, `include_usage`, cloud base URL and `OLLAMA_API_KEY`. (Ollama's documentation in its repository.)
- Codex CLI sandbox modes `read-only`, `workspace-write`, `danger-full-access`; approval policies `untrusted`, `on-request`, `never`; network off by default in `workspace-write`; `codex exec` is read-only by default. These come from the official pages as quoted by a search tool; the pages themselves could not be fetched from the build environment, so treat them as **verified by quotation only** and re-read them before writing the adapter.

Marked unverified (not to be relied on until checked):

- Codex CLI: how a prompt is read from standard input (the official page is reported to treat piped input as extra context when a prompt argument is also given; reading the prompt from standard input with `-` came from a third-party page), the JSON event format and flags, any dollar or turn cap, the Linux and macOS sandbox implementation, whether a repository's own files can change its configuration, and whether a requested command in `read-only` really does not run.
- Gemini CLI: how a prompt is read from standard input, the `--model` flag, the contents of the `stats` object, the built-in tool names, whether the working folder's settings can be switched off, whether a stricter Seatbelt profile blocks the private list, and what an error body holds for a rate limit.
- OpenAI's own HTTP API: request and usage field names, price handling (the documentation host could not be reached).
- Anything about any provider's terms, retention or training policy.

## Found while implementing

Ticket #100 built steps 1 and 2, the fake adapter (part of step 4) and the provider setting (part of step 5). What the code taught, and where it differs from the text above:

- **The timeout cannot be applied around an adapter.** `guard` is `perl -e 'alarm; exec'`: it can wrap a program, not a shell function. Each adapter therefore calls `guard "$QD_CALL_TIMEOUT"` around its own program. The interface table says the adapter does not apply the timeout; in practice it must, and a test per adapter has to prove it (the fake's does).
- **The tool and deny lists are not neutral.** `claude_run` builds them in Claude Code's rule syntax (`Read(//abs/path/**)`, `Bash(git*)`), and the secret screen writes its results in the same syntax. There is no provider-neutral form of "deny" today, so a second real adapter would have to parse Claude's rules. Before step 8, `claude_run` should keep a neutral list (tool names, paths to deny, commands to deny) and the claude adapter should render it. The fake receives the Claude-syntax lists as they are, which is what the injection checks read.
- **The sandbox input is a rule set, not a yes or no.** The table lists `sandbox` as "whether the harness requires an operating system sandbox". The adapter needs the rules themselves (the private list, the paths the secret screen denied, the worktree's own `.git` closed to writes). It gets the sandbox settings JSON that `claude_sandbox_json` builds, and writes it to a 0600 file as before. That JSON is Claude's settings format; the same note as for the tool lists applies.
- **An adapter in its own file would have broken every existing test.** The self-tests copy a fixed list of harness files into each throwaway Quarterdeck (`st_init` in `bin/selftest-lib.sh`). A claude adapter in `providers/claude.sh` would be missing from all of them. The claude adapter therefore lives in `bin/lib.sh` (`provider_call_claude`); other adapters live in `providers/<name>.sh` and are sourced only when a call names them. `st_init` copies `providers/` only when a test asks for the fake (`ST_PROVIDER=fake`).
- **`record_spend` cannot change its argument.** A stand-in duty in `bin/selftest-cycle.sh` calls `record_spend` with a Claude envelope. `record_spend` keeps that contract (it converts and calls on); the provider-neutral function is `record_spend_neutral`. The ledger gained two fields, `provider` and `cost_known`.
- **One `stop` field cannot say both "error" and "limit".** The ledger's `stopped: error` comes from Claude's `is_error`, independently of the usage-limit text, and the limit is only acted on when the program exited 0. The envelope has an `error` boolean next to `stop` so the ledger stays as it was. `stop: error` does not by itself fail a call; the program's exit status does, as before.
- **Unreadable output was a success.** When `claude` exits 0 and prints something that is not JSON, `claude_run` returned 0 with no text (the duty then fails at contract parsing). This is kept for identical behaviour (the envelope says `unparsed: true`) and is pinned by the recorded test. An adapter whose own output is not an envelope at all is a failure (return 1). Making the Claude case a failure too is a small, separate change.
- **The registry had no place in the precedence list.** The ticket asks for a provider per duty in the registry as well as per seat. The order built is: `QUARTERDECK_PROVIDER_OVERRIDE`, the seat's `provider:` (`QUARTERDECK_PROVIDER_PERSONA`), the project's `"providers": {"<duty>": "<name>"}` in `projects.json`, `QUARTERDECK_PROVIDER_<DUTY>`, `QUARTERDECK_PROVIDER`, then `claude`. `default` means `claude`. A name that is not a plain word, or names no adapter this version has, is refused before the secret screen or any model runs, with the name, where it was set and the list of known providers.
- **Model defaults are Claude names.** `QUARTERDECK_MODEL_<DUTY>` defaults to `claude-sonnet-5` and similar, and the rule that drops effort for Haiku matches on the model name. A seat moved to another provider inherits a Claude model name unless it also sets `model:`. Before a second real provider ships, model defaults need to be per provider, or the adapter must ignore a model name it does not know and say so in the envelope.
- **Not built here, and needed later:** the capability list and the `enforced` envelope field (step 3); the dashboard showing the provider per seat, `endpoint:` and `config/providers.json` (rest of step 5); the outgoing prompt scan (step 6). The fake does not declare capabilities yet, because there are none to declare.
- **The fake ignores `QUARTERDECK_CLAUDE_ENV=inherit`.** It always starts with `env -i` and a short list (`HOME`, `PATH`, `TMPDIR`, locale, `USER`, `LOGNAME`, `SHELL`, `TERM`, `TZ`); everything it needs is an argument and the prompt is on standard input. That is what lets the injection suite assert at the seam that an adapter's environment holds nothing of the owner's.
- **Proof of "identical".** `bin/selftest-providers.sh` holds `fixtures/providers/claude-call.golden`, recorded from `claude_run` before the seam existed: for sixteen cases (one is a tool list refused before any call; two are the turn cap and the stable system prompt of issue 121), every argument, the environment in order, the folder, standard input, the sandbox file and its mode, the return code, the output, the ledger line, the kept envelope and the log lines. `bin/selftest-providers.sh --against <old lib.sh>` compares two versions of `lib.sh` with nothing normalised. The golden file was recorded on macOS; the folders `lib.sh` puts before `PATH` differ per system and are a placeholder in the record, but it has not been compared on Linux.
- **The turn cap and reuse (issue 121) go through the seam too.** The turn cap is an input (`QD_CALL_TURNS`) and a fourth `stop` value, `turns`; the stable system prompt flag is an input (`QD_CALL_STABLE`). A reused answer is stored as the reply envelope, and the provider is one of the inputs that must match, so an answer one provider gave is never handed back for another.
- **Billing (ticket #38) is the claude adapter's alone.** `claude_run` decides who pays, from `bin/billing.py`, only when the provider is `claude`: the API caps and whether a key is stored are checked there, and a call that cannot go ahead stops with NEEDS_HUMAN and returns 5 (4 is the turn cap). The key itself is read, put into the call's environment and taken back out of its output and error text only inside `provider_call_claude`. Another provider's calls are booked as `billing: "none"`, the API caps do not count them, and the fake adapter, which starts with `env -i`, never sees the key. The ledger takes the billing as `record_spend`'s fifth argument; the fourth is the reuse key.
