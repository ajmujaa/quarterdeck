# Round 6: the Brain shows which project uses which service

Rules: same as `docs/CLOUD-TASKS-3.md` section 0 (commits authored as Mujahid <500292+ajmujaa@users.noreply.github.com>, never mention Claude, an AI or a session anywhere, no em dashes in user-facing text, nothing from the internet at runtime, fake HOME and temp folders in tests, never port 7878 or the real data folder). Do not run the full `bin/check.py` locally: open a PR into `main`, let CI run it on macOS and Ubuntu, read the log, fix if red. Do this after rounds 4 and 5 are merged.

Never collect anything new. This round only reads snapshots and registry data Quarterdeck already holds, and writes only to the data folder.

## Background (what the owner saw)
In the Brain a service node (Gmail, Slack, Analytics) is a separate cluster in the "world" region: its items link to it, but nothing links a service to a project, because Quarterdeck has no data on which project uses which service. The owner also found that every known service was drawn even when not connected; the page now draws a service only when it has a snapshot or a refresh was tried (`brainGraph` in `dashboard/index.html`, the loop over `S.connectors`). If that line is not on `main` yet, keep it.

## A. Services a project uses, chosen by the owner (solid links)
1. A new optional field in the project registry (`config/projects.json` in the data folder): `"services": ["gmail", "slack"]`, ids from the Connections manifest. `qtdeck attach` and the registry code must keep working when it is absent. Validate ids against the manifest; unknown ids are refused with the list of valid ones.
2. `qtdeck project services <project> [add <service> | remove <service>]` and `POST /api/project/services` (same pairing, origin, token and confirm rules as the other project writes; a line in the project log, never content).
3. On the project page, a small card "Services this project uses": every connected service as a checkbox, plus the others in a quiet second group ("not connected yet", with a link to Connections). Saving is one button.
4. In the Brain, a solid link from the project hub to each chosen service's node, only when that service node exists (it is connected). A chosen but unconnected service shows no node and the project card says "Gmail is chosen but not connected".

## B. Guessed links (dashed, labelled "guessed")
1. Computed on the server from snapshots already on disk, with no model and no network: an item of a service (an email subject, a Slack channel or message line, a calendar event title, a site name) that names a project (word-boundary, case-insensitive match on the project name or its repo name, at least 4 characters, never on a stop-word list of common words such as "project", "test", "main") creates a guessed link from that item's service to the project. At most 3 per project per service. Store nothing but ids; never copy item text anywhere new.
2. The Brain draws guessed links dashed and dimmer than solid ones. A node's side panel says why in one line ("a subject mentions nomi") and has two buttons: "That is right" (turns it into a solid choice from A) and "Not this project" (hides it; kept in `brain-links.json` in the data folder, 0600, ids only).
3. A toggle "Show guessed links" in the Brain controls, on by default, remembered.
4. A legend line: solid means you chose it, dashed means a guess from names.

## C. Tests and docs
1. Tests with a fake HOME and fixture snapshots: a project with and without `services`, an unknown service id refused, the API's guards, a guess found, a guess on a stop word not made, the cap of 3, "Not this project" sticks, a solid link only when the service is connected, nothing written outside the data folder, no item text in `brain-links.json`.
2. A short section in `docs/public/GUIDE.md` (Brain and Projects) and a line in `SECURITY.md` (what is read, what is written).
3. `docs/reports/cloud-round-6.md`: what was built, what was not checked, what still confuses a newcomer.
