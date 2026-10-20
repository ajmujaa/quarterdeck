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

```bash
git clone https://github.com/ajmujaa/quarterdeck.git && cd quarterdeck
bin/qtdeck setup
bin/qtdeck dashboard      # switch Demo on to look around with invented data
```

`bin/qtdeck attach ~/Projects/my-app` registers your first project. The [guide](GUIDE.md) has the rest.

## Why Quarterdeck

- **The model thinks, the harness acts.** Agents never hold credentials or write tools. A script does the privileged step, only with an explicit `--apply`.
- **Safe by test.** 701 real runs against planted prompt injections: none obeyed. 400 control runs without the guard: 2 obeyed.
- **Calm.** One next action on Home. Calm mode shows one column of larger text.
- **Yours.** No keystrokes, screen, apps, clipboard or location, ever. A test scans the code for the APIs that would do it.
- **Your plan or your key.** Use your Claude plan, or an API key with spending caps.

## What is in it

Dashboard · Crew · Brain map · Fleet · Connections · Helm (optional voice)

## Status

Early. Built and used daily on macOS. The Linux sandbox is run in CI only. Read [SECURITY.md](SECURITY.md) before you trust it with anything you care about.

[Guide](GUIDE.md) · [Security](SECURITY.md) · [Threat model](THREAT-MODEL.md) · [Apache-2.0](LICENSE)
