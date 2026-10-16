# Dashboard UI kit

One stylesheet (`assets/ui.css`), one token scheme, Shoelace web components from `assets/vendor/shoelace` (see `assets/vendor/VENDOR.md`).
No build step, nothing loads from the internet. Fonts (Fraunces, Space Grotesk, IBM Plex Mono) are vendored in `assets/vendor/fonts`.

## Tokens (assets/ui.css section 2)
Dark is the default; `:root[data-theme="light"]` and the OS light setting use one light set. Colour appears only in that section.
`--bg --card --card2 --raised` surfaces, `--line --line-2` borders, `--ink --ink-2 --dim --dimmer` text, state colours
`--accent --ok --bad --await` each with `-ink`, `-bg`, `-edge`; `--series-1..7` and `--heat-0..4` for charts.
The legacy aliases are gone: use only these names.
Spacing `--s1..--s7`, radius `--r` (12px) and `--r-sm` (8px).

## Helpers (index.html, "UI kit" block)
`kicker(text)`, `pill(state, label)`, `btn(label, {click, variant, size, href})`, `card(title, body, {kicker, count, actions, tone})`,
`li({title, sub, end, icon})`, `callout(tone, title, body, {meta, actions})`, `emptyState({kicker, title, body, label, click})`,
`stat(label, value, {tone, sub, click})`, `tbl(head, rowsHtml, {cls, none})` (a head entry `[text]` aligns right), `seatPill(seat)`,
`slSelect / slInput / slTextarea / slSwitch / slCheckbox`, `slIcon(name)`, `setHtml(el, html)`, `confirmDlg(message, {ok, danger})`, `toast(msg, bad)`.
A control reports changes with `data-onchange="code using el"` (sl-change) or `data-oninput` (sl-input). An empty select value is stored as `_`; read it with `selVal(el)`.

## Shell
Icon rail (`NAV_GROUPS` + `EXT.places`), top bar (project `sl-select`, search, status, Demo and Calm switches), page header (`pageMeta(view)` gives kicker,
title, description, actions), place tabs (`renderTabs`, an `sl-tab-group` wired to `go(view)`), right drawer (`#drawer`, `openDrawer()`), dialogs
(`#palette`, `#confirm-dlg`), Helm panel. Below 760px the rail becomes a bottom bar with a Menu drawer.
The Brain is not a page of a project: `body.brain-mode` hides the top bar, page header and tabs, shows one slim toolbar (`#brain-bar`, `brainBar()`), collapses Helm to its rail for the visit, and lets the map fill the page. `leaveBrain()` (also Esc) returns to where you were.
The Start a full cycle dialog (`#cycle-dlg`, `cycleCard()`) is the one place a cycle is started: only for a project with `cycle: true`, and only its Start button posts.

## Pages
Every page is a function that returns a string made of the helpers above: a row of `stat`s, then `card`s (a two-column `.split`, 2fr and 1fr, where the page has a side), `li` rows inside a card,
`tbl` for tables, `pill` for state, `emptyState` with one next action when there is nothing to show. Actions are `btn` (an `sl-button`); a bare `<button>` is only a text link (`.mlink`),
a chip, or a marker on a chart. Section 9 of `ui.css` holds the layouts these pages share (stats, split, toolbar, run cards, ledger, drawer items, the card panel, Brain chrome, search).
Add-on views (`assets/ext-*.js`) use the same helpers; they run in the page's global scope.

## Checks
`bin/ui-dead-css.py` lists classes `ui.css` defines that no markup uses (selftest runs it). Delete a rule when its markup goes.

## The Brain workspace
The Brain and My rhythm are two modes of one immersive workspace with one toolbar (`brainBar()`), so neither is a window you have to come back from.
Left to right: Leave, a Map | Rhythm switch (`sl-button-group`, same place and size in both modes), then the mode's own controls.
Map mode: Size by (segmented), then Replay, Attention, What changed and My focus as icon and label buttons of one size. Below 1160px the four tools fold into a More menu, below 700px Size by joins them.
Rhythm mode: the project choice, in the first slot after the switch.
Every control is a small `sl-button` or `sl-select`, so heights and centres match. Group names use the mono micro label. The Brain has no project filter; the scene is always every project.
Esc and Leave go back to where you came from, from either mode.

## Consistency rules
These are rules, not a diary. A new page or drawer follows them; `bin/selftest.py` greps for the ones that can be checked.

| Area | Rule | Where it stands |
|---|---|---|
| Project selector | One, `#proj-switch`, first control of the top bar, right of the rail (`108,15` at 1500px, `16,10` on a phone), 32px high, no visible label. Nothing else is a project scope. | Measured on every view: same box everywhere. The Brain hides the top bar, so My rhythm shows the same choice (the same `sel`) in its toolbar. |
| Local project fields | A project inside a form (a mission, a schedule, a cycle, the project of one note) is a labelled field in that form, not a filter. | Fixed: Timeline and Notes had their own project filter next to the top bar's. They now use the top bar's. |
| Page header | Kicker, `h1`, one description, in that order, at the same position on every view; tabs below it. Page level actions go in `#pacts` or in the first card. | Measured: kicker `y=91`, title `y=111` on every view at 1500px. |
| Primary action | One primary `btn` per view. A row of repeated forms uses the plain button. | Fixed: Connections had ten primary Save buttons. Overview, Notes and Needs you still show two. |
| Button sizes | Page and form actions are medium. Actions inside a row or a toolbar are small. | Not fixed: Overview, Notes and Needs you mix both in one view. |
| Drawers | Title in `#dtitle`, content in `#dbody`, buttons in the footer through `drawerFoot()`. The footer sits bottom right, Cancel or Close left of the primary. | Fixed: My focus and the connection help. Not fixed: the showcase, mission and panel drawers and Add a project keep their buttons in the body. |
| Dialogs | `#confirm-dlg` through `confirmDlg()` and the cycle dialog. Cancel left of the primary. No native `confirm`, `alert` or `prompt`. | Both follow it. The only `window.confirm` is the fallback when Shoelace has not loaded. |
| Controls | `sl-select`, `sl-input`, `sl-switch`: never a raw `<select>`. | No raw `<select>` anywhere. |
| Headings | `h1` is the page title only. A card title is an `h2` in the kit. Drawer sections are `h2`, their items `h3`. | Showcase uses `h3` inside cards. Not fixed. |
| Empty states | `emptyState` with one next action. | Followed. |
| Badges and pills | `pill(state, label)`: good, bad, warn or neutral. A Tested pill appears only for a service whose manifest says it was tested against the real service. | Followed. |
| Icon buttons | `sl-icon-button` with a label, 40px target (`.x` closes). The help button sits at the right of a row header, after the switch. | Followed on Connections. |
| Spacing | Sections `--s5` apart, cards `--s4` inside, tokens only. | Followed. |
