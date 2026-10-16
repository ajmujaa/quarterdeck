# Quarterdeck

**A calm, local-first control room for AI software-development agents.**

Quarterdeck runs on your own machine. It gives you one dashboard for all your projects, a built-in crew of agents that take work from an issue to a reviewed pull request, and a map of everything in one view called the Brain. Nothing leaves your computer except the requests you ask for.

> Status: early. Built and used daily on macOS; Linux is next. Expect rough edges and read what is tested and what is not before you trust it with anything you care about.

## What you get

- **A crew, not a chatbot.** Small agents with one job each: read a pull request, file issues from a document, plan an issue with a panel that argues, build a change in a throwaway worktree, check that a fix does what it claims. A run starts cold, reads only what its job needs, and ends with a one-line verdict.
- **One bounded cycle.** `bin/quarterdeck cycle <project> --issue <n>` takes one issue through requirements, a plan, a build, tests written by a different agent, five reviewers side by side and a capped number of fixes, then stops for you to read the pull request and merge it. It is off unless the project opts in, report-only unless you pass `--apply`, resumable, and it stops before any stage that would cross your daily or per-run budget.
- **Sprint planning you approve.** `bin/quarterdeck run <project> planner` reads your open backlog and writes a plan document: an order that respects dependencies, a size (S, M or L) with a reason for each item, what needs a decision from you first, and what to leave out. Cost is the number your own finished runs measured, or plainly "unknown" when there are none. Nothing on your board changes until you run `bin/quarterdeck plan approve`, and then only the sprint's cards move, one at a time.
- **A brief and mock-ups you approve before anything is built.** `bin/quarterdeck brief --idea "..."` (or `run <project> brief --issue N`) turns an idea or an issue into a one-page design brief in plain words, with what it assumed and what only you can answer. Once you approve it, `bin/quarterdeck mockup <id>` makes one static page per screen, checked by the harness against an allowlist (no script, no external address, visible keyboard focus, readable contrast) and shown only in a sandboxed frame. Everything stays in your data folder.
- **Infrastructure files, read as files.** The `infra` duty reads a change to Terraform, CDK, CloudFormation or SAM, a serverless config, or Vercel and Supabase files and writes a change report: risk, how far it reaches, how to undo it. It never runs anything against a cloud and holds no credentials, so it cannot see drift between the files and the live account, and it says so. Packs for AWS and for Vercel with Supabase ship with it, each with a plain statement of what was and was not tested.
- **Panels.** Where one opinion is worse than three that disagree, several crew members look at the same thing from different angles and a chair rules.
- **A dashboard that stays calm.** One clear next thing to do, real data or nothing, every change behind a click.
- **The Brain.** One map of your projects, agents and connected services. Click any dot to see what it is and where it leads.
- **Your projects, your way.** Attach a project you already have, with or without agents of its own; Quarterdeck shows its agents, its worktrees and its pull requests, and whether it runs on its own agents or on the built-in crew.

![Fleet, in demo mode](images/fleet.png)
- **Optional voice.** Talk to the assistant (Helm). Speech recognition and the voice run locally.

## The one rule

**The model thinks, the harness acts.** No agent is given credentials or write tools. An agent reads, reasons and ends its reply with a machine-readable contract. A script parses the contract and does the privileged thing (posts a comment, opens a branch, files an issue), only with an explicit `--apply`. A reply that does not parse is a failed run that writes nothing.

## What it will never do

- Collect keystrokes, screenshots, screen contents, which apps or websites you use, the clipboard, your location, or any file outside the projects you register and its own data folder. A test scans the code for the APIs that would do it.
- Change anything without a click or an explicit `--apply`.
- Send your data anywhere except the request you asked for.

## Quick start

You need: macOS or Linux (macOS is the tested one), Python 3.10 or newer, bash, git, [jq](https://jqlang.github.io/jq/), the [GitHub CLI](https://cli.github.com/) (`gh`, signed in) and [Claude Code](https://claude.com/claude-code) (`claude`, signed in). Node 20 or newer is optional and runs the page-logic tests; without it those tests are skipped.

```bash
git clone https://github.com/ajmujaa/quarterdeck.git
cd quarterdeck
bin/quarterdeck home init        # makes ~/.quarterdeck, your data folder, apart from the program
bin/quarterdeck doctor           # checks the wiring and says what is missing
bin/quarterdeck dashboard        # opens http://127.0.0.1:7878 (loopback only)
```

The dashboard has a **Demo** switch that fills it with invented data, so you can look around before you connect anything. Everything in the screenshots below is made up.

![Home, in demo mode](images/home.png)

Add a project with **Add a project** in the dashboard, or from the command line. Quarterdeck reads the folder first (languages, test command, CI, where it deploys, folders that need care), says what it found and what the crew would do, and registers the project only when you say so. It never opens secret files and never changes the project.

```bash
bin/quarterdeck attach ~/Projects/my-app            # shows what it found and proposes a set-up; changes nothing
bin/quarterdeck attach ~/Projects/my-app --apply    # registers it
```

Then run an agent on it. Nothing is written until you add `--apply`:

```bash
bin/quarterdeck run my-app surveyor --pr 12           # reports only
bin/quarterdeck run my-app surveyor --pr 12 --apply   # posts the review
```

`bin/quarterdeck crew` lists the crew, `bin/quarterdeck duties` the jobs, `bin/quarterdeck check` runs every test.

## How it is organised

Four things, and nothing else:

1. **A project**: a registered repository, with its guardrails and the command that verifies a change.
2. **A crew member**: a short markdown file describing a point of view. It knows no project.
3. **A duty**: one script that does one job.
4. **A run**: one execution of a duty, with a recorded verdict.

Adding capability means adding an instance of one of these, never editing the machinery.

## Your data stays yours

The program and your data are separate folders. The program (`bin/`, `duties/`, `crew/`, `dashboard/`) is what you cloned. Your registry, runs, notes, logs and settings live in your data folder, `~/.quarterdeck` by default (`QUARTERDECK_HOME` to change it). Update or delete the program any time without touching your data. `bin/quarterdeck home` shows where everything is.

## Connecting services

Gmail or Mac Mail, team chat, web analytics, the numbers for your posts on Facebook, Instagram, LinkedIn, Threads and X, and your Mac's calendar and reminders can be shown in the Brain. Each is a small script that calls the service's own API with a read-only credential, with no model in the path. Set them up from the **Connections** page: each service shows where it stands, when it last refreshed and what it still needs, and a credential you enter goes into a private file on your computer and is never shown again. Each service has a help icon that says what it reads and never reads, how to get what it needs, the steps, the permissions to grant, how to revoke access and what was tested. Nothing is claimed as tested against a real service unless its file says so. Quarterdeck never posts to a social account. A service is one small JSON file, so adding another does not mean touching the core.

![Connections, in demo mode](images/connections.png)

## Contributing

Issues and pull requests are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) first. To report a security problem, read [SECURITY.md](SECURITY.md); please do not open a public issue.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
