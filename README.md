# Quarterdeck

**A calm, local-first control room for AI software-development agents.**

Quarterdeck runs on your own machine. It gives you one dashboard for all your projects, a built-in crew of agents that take work from an issue to a reviewed pull request, and a map of everything in one view called the Brain. Nothing leaves your computer except the requests you ask for.

> Status: early. Built and used daily on macOS; Linux is next. Expect rough edges, and read what is tested and what is not before you trust it with anything you care about.

## Words used here

- **Quarterdeck**: the product, and the name of its command (`bin/qtdeck`).
- **Project**: a repository you have registered, with its guardrails and the command that proves a change works.
- **Crew**: the built-in agents. Each is a short markdown file describing one point of view.
- **Duty**: one script that does one job, such as reviewing a pull request.
- **Run**: one execution of a duty, with a one-line verdict kept in the ledger.
- **Ledger**: the record of every run, what it cost and what it said.
- **Panel**: several crew members looking at the same thing from different angles, with a chair who rules.
- **Brain**: the map of your projects, agents and connected services.
- **Helm**: the optional voice assistant.
- **Calm mode**: a switch that shows one column of larger text and only what needs you.

## The one rule

**The model thinks, the harness acts.** No agent is given credentials or write tools. An agent reads, reasons and ends its reply with a machine-readable contract. A script parses the contract and does the privileged thing (posts a comment, opens a branch, files an issue), only with an explicit `--apply`. A reply that does not parse is a failed run that writes nothing.

## Install on macOS

You need:

- macOS (the tested system) or Linux, with Python 3.10 or newer, bash, and git. On Linux, project commands need `bubblewrap` (`bwrap`) or they are refused; that backend has not been run on a real Linux machine (see SECURITY.md).
- [jq](https://jqlang.github.io/jq/), for example `brew install jq`.
- The [GitHub CLI](https://cli.github.com/), signed in: `brew install gh`, then `gh auth login`.
- [Claude Code](https://claude.com/claude-code), signed in: the `claude` command must work in a terminal.
- Optional: Node 20 or newer. It runs the page-logic tests; without it those tests are skipped.

Then:

```bash
git clone https://github.com/ajmujaa/quarterdeck.git
cd quarterdeck
bin/qtdeck home init     # makes ~/.quarterdeck, your data folder, apart from the program
bin/qtdeck doctor        # checks the wiring and says what is missing
```

`doctor` lists each problem in plain words. Fix what it names and run it again until it is quiet. There is no installer and nothing is placed outside the program folder, your data folder and the private file where credentials you enter are kept.

## Connect Claude Code

Quarterdeck has no login of its own. It runs the `claude` command that is already on your machine, as you.

1. Install Claude Code from https://claude.com/claude-code.
2. Run `claude` once in a terminal and sign in with your Claude account or an API key.
3. Run `gh auth login` for the GitHub CLI.
4. Run `qtdeck doctor`. It says whether both are found and signed in.

Every model call uses your own account and your own usage limits. Quarterdeck never stores or passes on your sign-in, and never uses anyone else's. Read the provider's terms for automated use before you schedule many runs: https://code.claude.com/docs/en/legal-and-compliance

## First run

```bash
bin/qtdeck dashboard
```

This starts the dashboard and opens a one-time pairing link to `http://127.0.0.1:7878`. The server listens on your own machine only (loopback).

- The page holds no secret. It works only in a browser opened from that link, which is good for five minutes and works once.
- A tab opened without the link says how to get one. `bin/qtdeck dashboard link` prints a fresh link, for example to pair a second browser.
- The **Demo** switch fills the dashboard with invented data, so you can look around before you connect anything. Everything in the screenshots here is made up.

![Home, in demo mode](images/home.png)

## Attach a project

Use **Add a project** in the dashboard, or the command line. Quarterdeck reads the folder first: languages, test command, CI, where it deploys, folders that need care. It says what it found and what the crew would do, and registers the project only when you say so. It never opens secret files and never changes the project. What it proposed and what you approved are kept in your data folder.

```bash
bin/qtdeck attach ~/Projects/my-app            # shows what it found and proposes a set-up; changes nothing
bin/qtdeck attach ~/Projects/my-app --apply    # registers it
```

Adding a project accepts folders under your home directory only, never a hidden folder. `QUARTERDECK_PROJECT_ROOTS` in `config/quarterdeck.env` allows others. Attach only folders you trust: the crew reads their files and the harness runs their test and build commands (with a minimal environment, no secrets, and inside the macOS sandbox where there is one).

Then run an agent on it. Nothing is written until you add `--apply`:

```bash
bin/qtdeck run my-app surveyor --pr 12           # reports only
bin/qtdeck run my-app surveyor --pr 12 --apply   # posts the review
```

`bin/qtdeck crew` lists the crew, `bin/qtdeck duties` the jobs, and `bin/qtdeck check` runs every test.

## The crew and what each does

A run starts cold, reads only what its job needs, and ends with a one-line verdict. These are the duties you can run, each by `bin/qtdeck run <project> <duty>`:

| Duty | What it does |
| --- | --- |
| surveyor | Reads a pull request and posts findings as review comments. |
| marshal | Reads a pull request for security. |
| joiner | Reviews the interface: accessibility, states, responsive behaviour. |
| inspector | Checks that a pull request does what it claims. |
| foreman | Turns a findings document into well-formed, deduplicated GitHub issues. |
| purser | Turns a backlog issue into something a stranger could start cold. |
| harbourmaster | Keeps the project board honest about what is actually happening. |
| planner | Turns the open backlog into a sprint plan you read. It moves nothing until you approve. |
| shipwright | Takes one issue to a branch and a pull request, in a throwaway worktree. |
| trials | Writes the test that reproduces a bug and proves it fails first. |
| caulker | Fixes exactly the problem that was found. |
| assayer | Writes tests, as a different agent from the one that built the change. |
| lookout | Takes screenshots of the running app at three widths and judges them. |
| pilot | Runs the app and walks through it. |
| quartermaster | Checks what comes in: dependencies and what they actually are. |
| bosun | Reports drift: stale branches, dead settings, docs that name things that are gone. |
| infra | Reads Terraform, CDK, CloudFormation, SAM, serverless, Vercel and Supabase files and reports risk and how to undo a change. It runs nothing against a cloud and holds no credentials. |
| brief and mockup | Turn an idea into a one-page design brief you approve, then one static page per screen. |
| logkeeper | Keeps the log of decisions. |
| panel | Puts several crew members on one question and makes them disagree before a chair rules. |

Beyond the single duties:

- **One bounded cycle.** `bin/qtdeck cycle <project> --issue <n>` takes one issue through requirements, a plan, a build, tests written by a different agent, five reviewers side by side and a capped number of fixes, then stops for you to read the pull request and merge it. It is off unless the project opts in, report-only unless you pass `--apply`, resumable, and it stops before any stage that would cross your daily or per-run budget.
- **Sprint planning you approve.** `bin/qtdeck run <project> planner` writes an order that respects dependencies, a size (S, M or L) with a reason for each item, what needs a decision from you first, and what to leave out. Cost is the number your own finished runs measured, or plainly "unknown" when there are none. Nothing on your board changes until you run `bin/qtdeck plan approve`.
- **A brief and mock-ups you approve before anything is built.** `bin/qtdeck brief --idea "..."` writes a one-page brief in plain words, with what it assumed and what only you can answer. After you approve it, `bin/qtdeck mockup <id>` makes one static page per screen. The harness checks each against an allowlist (no script, no external address, visible keyboard focus, readable contrast) and shows it only in a sandboxed frame.

The crew themselves are files in `crew/`. Each knows no project and holds one point of view, such as a security reviewer, a copy editor, or someone whose only question is what an earlier fix could have broken. Read `crew/_README.md` to add one.

## Packs

A pack is a short note about one stack that the crew reads before it works on a matching project. `qtdeck packs list` shows the packs found. The six infrastructure packs (aws, vercel-supabase, azure, google-cloud, cloudflare, fly) are labelled **experimental**: they were tested on small examples only, and every infra report says so in its footer. Read such a report as a second opinion, not a verdict. The tag shows in `qtdeck packs list`, in Settings and when you attach a project. The python and typescript-node packs carry no tag.

## Calm mode

Calm mode is a switch in the top bar. It shows larger text in one column and only what needs you, and folds the rest behind **Show everything**. It starts on by itself if your system asks for reduced motion. The dashboard in every mode has one clear next thing to do, shows real data or nothing, and puts every change behind a click.

## The Brain

The Brain is one map of your projects, your agents and the services you connect. It is built from what you have added, so adding or removing a project or a connection changes it with no code edit. Click any dot to see what it is, what state it is in and where it leads. The counts on the map are buttons that open a list.

![Fleet, in demo mode](images/fleet.png)

### Connecting services

Gmail or Mac Mail, team chat, web analytics, the numbers for your posts on Facebook, Instagram, LinkedIn, Threads and X, and your Mac's calendar and reminders can be shown in the Brain. Each is a small script that calls the service's own API with a read-only credential, with no model in the path. Set them up from the **Connections** page: each service shows where it stands, when it last refreshed and what it still needs, and a credential you enter goes into a private file on your computer and is never shown again.

Each service has a help icon that says what it reads and never reads, how to get what it needs, the steps, the permissions to grant, how to revoke access and what was tested. Nothing is claimed as tested against a real service unless its file says so. Quarterdeck never posts to a social account. A service is one small JSON file, so adding another does not mean touching the core.

![Connections, in demo mode](images/connections.png)

## Helm, the optional voice

Helm is an assistant you can talk to and listen to. It is off until you set it up, and the rest of Quarterdeck works without it. Speech recognition (whisper.cpp), the voice (Kokoro) and the small language model that answers (llama.cpp) all run on your machine. You choose the voice and speed with `QUARTERDECK_HELM_VOICE` and `QUARTERDECK_HELM_SPEED` in `config/quarterdeck.env`.

Helm can optionally think with Claude for open questions. That is off by default, capped per day, never on in demo mode, and when you switch it on you choose what it may be told. By default no calendar title, reminder, mail subject or note text goes with the question.

## What it will never do

- Collect keystrokes, screenshots, screen contents, which apps or websites you use, the clipboard, your location, or any file outside the projects you register and its own data folder. A test scans the code for the APIs that would do it.
- Change anything without a click or an explicit `--apply`.
- Send your data anywhere except the request you asked for.

## Security

Agents run with no credentials and no write tools. Text from a pull request, an issue or a web page is treated as data and never as instructions, and this was tested with 50 injection fixtures and over a thousand real runs on two models. The dashboard binds to loopback, pairs through a one-time link, and checks a session token and a loopback origin on every change. Builders run inside an operating-system sandbox with no network. Read [SECURITY.md](SECURITY.md) for the full list, what was tested and what was not, and how to report a problem. [THREAT-MODEL.md](THREAT-MODEL.md) describes who and what the design defends against.

## How it is organised

Four things, and nothing else:

1. **A project**: a registered repository, with its guardrails and the command that verifies a change.
2. **A crew member**: a short markdown file describing a point of view. It knows no project.
3. **A duty**: one script that does one job.
4. **A run**: one execution of a duty, with a recorded verdict.

Adding capability means adding an instance of one of these, never editing the machinery.

## Your data stays yours

The program and your data are separate folders. The program (`bin/`, `duties/`, `crew/`, `dashboard/`) is what you cloned. Your registry, runs, notes, logs and settings live in your data folder, `~/.quarterdeck` by default (`QUARTERDECK_HOME` to change it). Update or delete the program any time without touching your data. `bin/qtdeck home` shows where everything is. The repository ships example files only (`config/projects.example.json` and others); your real registry is never inside it.

## Vendored files are hash-checked

The third-party files in `dashboard/assets/vendor/` (Shoelace, fonts, three.js) are pinned by sha256 in `dashboard/assets/vendor/HASHES.json`. `python3 bin/vendor-verify.py` fails and lists any file that changed, was added or was removed; `python3 bin/selftest.py` runs it too. After updating a vendored file on purpose, run `python3 bin/vendor-verify.py --write` and review the diff (see `dashboard/assets/vendor/VENDOR.md`).

## Contributing

Issues and pull requests are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) first. To report a security problem, read [SECURITY.md](SECURITY.md); please do not open a public issue.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
