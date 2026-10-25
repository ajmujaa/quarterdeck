<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/logo-dark.png">
    <img src="images/logo.png" width="160" alt="Quarterdeck">
  </picture>
</p>

<h1 align="center">Quarterdeck</h1>

<p align="center">
  <strong>A calm control room for your AI coding agents. Runs on your machine. Nothing leaves it.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0 license"></a>
  <img src="https://img.shields.io/badge/macOS-supported-black" alt="macOS">
  <img src="https://img.shields.io/badge/Linux-tested%20in%20CI-orange" alt="Linux, tested in CI">
</p>

<p align="center">
  <img src="images/home.png" width="880" alt="The Quarterdeck dashboard, in demo mode">
</p>

One dashboard for all your projects. A built-in crew of agents takes an issue to a reviewed pull request. You approve every change with a click.

## Quick start

New here? **[SETUP.md](SETUP.md)** walks you from nothing installed to a reviewed pull request, step by step, with what you should see at each step. The short version:

Pick one:

```bash
brew tap ajmujaa/quarterdeck && brew install qtdeck     # macOS
npm install -g qtdeck                                   # needs Node 20+ and Python 3.10+
git clone https://github.com/ajmujaa/quarterdeck.git && cd quarterdeck && export PATH="$PWD/bin:$PATH"
```

Then:

```bash
qtdeck dashboard      # the first time, a first-run screen lists what this machine has and lacks
```

That is the whole path today: the dashboard opens with a first-run screen that shows the same checks as `qtdeck doctor` (with the exact command to run, and a Copy button, for anything missing) and one button, "Look around in Demo". When you are ready, press **Add a project**, paste a folder path, and it walks you through scan, missing docs, crew and ready. `qtdeck setup` is still there if you prefer the terminal.

`bin/qtdeck attach ~/Projects/my-app` registers a project from the command line too. It names the stack it found (for example React 18 with Vite, tests by Vitest), proposes build and lint commands next to the verify command, and says why each duty is on or off; duties that also fit the stack are listed as "also fit this stack" and stay off until you tick them. **What attach does.** Attaching is onboarding. It surveys the folder from its files alone (layout, entry points, scripts, dependencies worth knowing, which documents exist, size, git), says which documents are missing and offers to draft them (`bin/qtdeck docs my-app`; you read the draft, and only your yes puts it on a new branch), chooses the crew with a reason for each duty, hands the survey to the agents as their stable context so they do not re-read the project every run, and ends with one checklist (`bin/qtdeck ready my-app`) and one next action, such as filing your first ticket. The dry run writes nothing. The [guide](GUIDE.md) has the rest. `bin/qtdeck check` runs every test.

## Why Quarterdeck

- **The model thinks, the harness acts.** Agents never hold credentials or write tools. A script does the privileged step, only with an explicit `--apply`.
- **Safe by test.** 701 real runs against planted prompt injections: none obeyed. 400 control runs without the guard: 2 obeyed.
- **Every pull request reviewed.** The surveyor reviews each new pull request once per commit, on a timer you set, including ones other collaborators open. Drafts, bots and strangers are skipped unless you say otherwise. The model only reads; a script posts the comment; merging stays yours.
- **Decisions the agents follow.** Attach a project with no `docs/decisions` and the logkeeper reads the code and suggests the decisions it already makes. You give the reason, and each record you choose becomes a pull request. Reviewers are shown the records that match what a change touches, and builders are shown the ones that match their ticket.
- **Your limits.** Set the most one call, one cycle and one day of automatic work may spend, in Settings, Spend limits.
- **Calm.** One next action on Home. Calm mode shows one column of larger text.
- **Home is you, Projects is where the work is.** Home holds your day, your notes, the fleet timeline and the day's budget; Projects opens on every project together and filters to one when you open it. The project scope lives in the address.
- **Yours.** No keystrokes, screen, apps, clipboard or location, ever. A test scans the code for the APIs that would do it.
- **Your plan or your key.** Use your Claude plan, or an API key with spending caps.
- **Say what you want, with or without GitHub.** `qtdeck ticket new my-app "a page with a counter"` has the planner draft one to five tickets (title, body, acceptance checks) and keeps the draft; `--apply` files them as GitHub issues. A project with no GitHub repo keeps them as local tickets on your computer, and `qtdeck cycle my-app --ticket 1` builds one on a local branch for you to review, with nothing pushed. `qtdeck repo my-app` lists the ways to get a repo: use yours, make one (`qtdeck repo create`, only after you type yes), sign up first, or stay local. The dashboard's Missions page has the same: a New ticket box that shows the draft before anything is filed, the ticket list with a Start a mission button, and, for a project with no repo, the four options as short rows.

The dashboard keeps its place in the address: Back, Forward, reload and links work, and the address holds the page, the project and the open mission.

## What is in it

Dashboard · Crew · Brain map · Fleet · Connections · Helm (optional voice)

<p align="center">
  <img src="images/brain.png" width="720" alt="The Brain page: a head made of dots, with every project, agent and connected service placed inside it as a labelled node">
  <br>
  <sub>The Brain: your projects, agents and connected services on one map. Demo data, nothing real.</sub>
</p>

Home has a **Running now** strip: every session and duty working across your projects, one line each, with how long and whether it waits for you. Each project's page has a **Live work** card with its worktrees, pull requests and who is working in each. Sessions come from the hook you install with `bin/fleet-hook.sh install`; without it the strip says so and still shows duties. On the Crew page the agents a project uses come first and the rest are folded into an **Available (N)** list with an Enable button.

Guardrails, the rules every agent is given for a project, are editable on the project page and with `qtdeck guardrail <project> list|add|remove|move`. Three are locked and cannot be removed: never merge, never push to the default branch, never touch secrets.

## Status

Early. Built and used daily on macOS. The Linux sandbox is run in CI only. Read [SECURITY.md](SECURITY.md) before you trust it with anything you care about.

[Setup](SETUP.md) · [Guide](GUIDE.md) · [Security](SECURITY.md) · [Threat model](THREAT-MODEL.md) · [Apache-2.0](LICENSE) · [Licensing](LICENSING.md)
