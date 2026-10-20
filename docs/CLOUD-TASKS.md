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
