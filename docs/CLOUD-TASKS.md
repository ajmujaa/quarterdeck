# Tasks for the cloud session (2026-10-20)

Repo: this one, branch `main`. Work on branch `cloud/connections`, push it, write
`docs/reports/cloud-connections.md` with what you did and what you could not check.
Rules: no Co-Authored-By or Claude-Session lines in commits; no em dashes in user-facing
text; nothing loads from the internet at runtime; never touch real home folders in tests
(use temp folders and QUARTERDECK_HOME with the `.quarterdeck-home` marker); no secrets
in chat or files; run `python3 bin/check.py` before you push.

## 1. Several accounts per service (the owner asked for this)
A person must be able to connect more than one account of the same service, for example
two Gmail accounts (work and personal), from the Connections page.
- Give each connection an account label (`work`, `personal`; default `default`).
- Credentials stored per service and label (private 0600 file or macOS Keychain), still write-only.
- Snapshots in `state/connectors/<service>/<label>/`; the background loop refreshes each.
- Page: "Add another account" on each service card, per-account enable, test and remove.
  Page actions stay `store`, `credential`, `enable` (add the label as a field, validate it:
  lowercase letters, digits, dash, max 24).
- CLI: `qtdeck connect <service> [--account <label>]` (also list and remove).
- Readers (Brain, assistant, Home) must merge or show each account, never mix them silently.
- Existing single-account installs keep working as label `default`, no migration step.
- Tests: fake services only; add a selftest suite for it.

## 2. Fix Connections instructions
- Correct the steps in `bin/integrations/services/*.json` that are wrong or stale.
- Gmail: add the 7-day expiry note for apps in Testing mode and the publish-to-production step.
- GA4: a property-id field on the page and the exact data-folder path in the steps.
- Slack: review scope breadth, request the narrowest set that still works.
- Calendar helper: name is `QuarterdeckAgenda.app`, build with `bash tools/agenda/build.sh`.

## 3. Linux check
CI on GitHub is blocked by billing, so you are the Linux check. Run `python3 bin/check.py`
on this repo and report every failure with the first error line.

## 0. Do this first: test the whole app on Linux (the repo is going public)
Goal: find anything broken in what already exists, before the public launch.
1. `python3 bin/check.py` and `python3 bin/selftest.py`; list every failure with its first error line.
2. Follow README.md exactly as a stranger would on a fresh Linux box (install, `qtdeck setup`,
   `qtdeck dashboard`, demo mode). Note every step that fails or confuses.
3. Walk each dashboard page in demo mode with a headless browser (Home, Brain, Crew, Fleet,
   Connections, Settings); screenshot problems, check the console for errors.
4. Try the security claims in SECURITY.md that can be tried on Linux (sandbox, pairing,
   protected paths) and say which hold.
5. Fix small real bugs on branch `cloud/test-pass` with a test each; list the bigger ones
   in `docs/reports/cloud-test-pass.md` ranked by severity. Do not weaken any check.
