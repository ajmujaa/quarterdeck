# Cloud connections: several accounts per service, and correct instructions (2026-10-20)

Base: `main` at 268b806. Branch: `cloud/connections` (6 commits: instructions, three for accounts, the Python 3.10/3.11 attach fix also made on
`cloud/test-pass` (cherry-picked so this branch passes `python3 bin/check.py` on a stock Python 3.11), and one demo-data fix). Fake services only; nothing real was contacted.

## Section 1: several accounts per service
What a person can do now:
- **Page.** Each service card that can have accounts shows its default account as before, then one block per extra account (label, state pill, on/off switch, its own
  credential fields, Save and Remove, a Test button, "Remove account") and an "Add another account" button with a label field. Labels: lowercase letters, digits and dashes,
  at most 24, starting with a letter or digit (`work`, `personal`, default `default`). Calendar, LinkedIn and Mac Mail stay single (a helper app or a file import, no credential).
- **CLI.** `qtdeck connect list`, `qtdeck connect <service> [--account <label>]` (asks for each credential; secrets are read without echo from the terminal or from standard input, never from an argument), `qtdeck connect remove <service> [--account <label>] [--yes]`.
- **Credentials.** Per service and per label, strict: a labelled account never falls back to the default account's keys. They are stored as `KEY@label` in the same private 0600 file or the same Keychain, still write-only
  (no API or command returns a value). A second Gmail account therefore needs its own client id and secret entered once for that label, and its own sign-in (`python3 bin/integrations/google_oauth.py gmail --account work`, token in `google-gmail-work-token.json`).
- **Snapshots and refresh.** Every account writes `state/connectors/<service>/<label>/<snapshot>.json` (folders 0700, files 0600). The default account also keeps writing the older `state/connectors/<snapshot>.json`, so nothing needs a migration
  and older readers keep working. Status records are keyed `<snapshot>` for the default account and `<snapshot>@<label>` for others. The background loop and `run.py all` refresh each enabled account in its own process;
  one failing account records its own failure and does not stop or mark the others.
- **Readers.** A service with one account is the same Brain entry as before. A service with more than one account gets one Brain entry per account (`account`, a unique `key`, label such as "Gmail (work)"), the assistant's counts line names each account
  ("3 gmail (work), 5 gmail (personal)"), and the suggestion code looks at every account. Items of two accounts are never one list with the account hidden.
- **Existing installs** keep working as label `default` with no migration step and no new files until a refresh (tested with a data folder written in the old shape).
- **Demo** shows two invented Gmail accounts (`work`, `personal`) so the feature is visible; nothing real is read.
- **API.** `POST /api/connections` keeps its three actions (`credential`, `enable`, `store`) and gains a `label` field (validated; a bad label is a 400 with a plain sentence). `enable` with `on:true` or `add:true` creates an account,
  `enable` with `on:false, remove:true` removes it (credentials, config entry, token file, snapshot folder, status), `enable` with `test:true` refreshes it once in its own process and answers `{ok, message}`; demo mode refuses the test.
  `connections.log` records the action, the service and the label, never a value.

Tests: `bin/selftest-connections.sh` (new suite, picked up by `check.py`): label rules, per-label storage in the file and in the Keychain (stub `security`, never the real one), `move_store` both ways, separate snapshots,
one account failing while the other works, loop work items and `--account`, Brain and assistant output for one and two accounts, the old-install case, the API actions, the CLI, and no em dash in the new copy.

## Section 2: instructions corrected (checked against current provider documentation where I could search)
- **Gmail:** a sign-in token made while the consent screen is in Testing expires after 7 days (Google's own limit for External apps); added the publish step (publishing status In production, the unverified-app click-through for a personal app)
  before the sign-in step, and a note on what to do if the token later expires. Tokens made in Testing keep the 7-day limit, so the order matters and is said.
- **Site analytics (GA4):** a "GA4 property id" field on the page (stored like a credential, optional, wins over `ga4.property_id` in the config file, which still works); the steps name the exact path
  `<data folder>/config/integrations.json` for `ga4.site_url`; the property id is said to be digits, not the `G-` Measurement ID, found under Admin, Property settings.
- **Slack:** the app asked for ten scopes; the code never reads channel history (history is read only for direct messages). Now eight: `im:read im:history mpim:read mpim:history channels:read groups:read users:read search:read`.
  `channels:history` and `groups:history` are removed from the manifest, the steps and the module's comment. A test runs the module against a fake workspace and proves history is read for the direct message only. Slack documents `chat.getPermalink` as needing no scope.
- **Calendar helper:** already correct on main (`QuarterdeckAgenda.app`, `bash tools/agenda/build.sh`); I added that it is for a Mac only. Meta, Threads, X, LinkedIn and Mac Mail steps were read against the code and left alone.

## What `check.py` said
The first full run on this branch was RED in one suite: the rehearsal (3 steps). With two Gmail accounts the Brain judges each account on its own, so the invented personal account's 35 hour old mail added a second
"waiting" suggestion and the scripted tour no longer had exactly one. The behaviour is the intended one (two accounts, two suggestions); the invented personal data is now fresher, so the tour is unchanged. After that fix `python3 bin/check.py` on this branch is GREEN (first fix run: 20 min 58 s). Then `main` moved (c94dc63: README restyle, long README moved to GUIDE.md, Helm default off). I merged it into this branch, moved the two paragraphs about accounts into GUIDE.md, and took the one-sentence README fix that `cloud/test-pass` carries (main itself failed `selftest.py` without it). Final `python3 bin/check.py` on this branch: GREEN, 21 min 39 s, every suite, quiet machine, the dashboard not running so its health was not asked.

## What I could not check
- A second account with real Google, Slack, Meta, GA4, X or Threads; the real macOS Keychain (the stub covers `KEY@label`, `move_store` there and back, and one-line `security -i` input); the hidden-entry prompt of `qtdeck connect` on a real terminal (only the piped path ran).
- The new page was syntax-checked and exercised through the dashboard API and the node page tests; `a11y-check --quick` passed but covers three views and I did not confirm the Connections view is among them. I did not click through the new blocks in a browser.
- Slack's `conversations.info` scopes were taken from the code's calls and Slack's documentation of that method as I know it; the search could not confirm them. If a real workspace answers `missing_scope`, add the named scope.

## Design notes and decisions for you
- Strict per-label credentials cost a second Gmail account one extra paste of the client id and secret. Sharing the app's client id between accounts would be friendlier; it was not done because the request said "credentials stored per service and label".
- The Test button runs the refresh in a separate process and waits for it (up to 180 s, the loop's limit), so the page can sit on "testing" that long for a slow service.
- `loop.minimal_env()` passes only PATH, HOME and LANG, so a loop run does not see `QUARTERDECK_HOME` or `QUARTERDECK_SECRETS_DIR` when they are set only by environment variable (already the case; an existing check pins it). The Test button does pass them.
- Merging with `cloud/test-pass`: both contain the same attach fix commit contents; git will merge them without a conflict.
