# Dashboard UI kit

One stylesheet (`assets/ui.css`), one token scheme, Shoelace web components from `assets/vendor/shoelace` (see `assets/vendor/VENDOR.md`).
No build step, nothing loads from the internet. One font, Space Grotesk, vendored in `assets/vendor/fonts` (the head and mono tokens are aliases of it, so every use is still named for what it is).

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
`bin/a11y-check.mjs` starts its own throwaway dashboard, opens every view (both themes, Calm on and off) in Playwright's Chromium and checks names (from the browser's accessibility tree), ids, headings, landmarks, `img` alt, aria validity, `tabindex`, text contrast (4.5:1, 3:1 large) and, with `--focus`, a visible focus indicator on every Tab stop; with `--flows`, the skip link, the dialog trap, Esc and focus return, the poll keeping focus, and the Brain's Esc. `--quick` is three views and the flows (what selftest runs). It needs Playwright and a Chromium; without them it exits 3 and selftest prints a skip. Selftest also checks without a browser: every icon-only button has a name, every field has a label, no positive `tabindex`, no click action on a bare div or span, every dialog has a label, no text under 12px, the focus ring token, the landmarks, and the contrast of every colour token in both themes.

## The Brain workspace
The Brain and My rhythm are two modes of one immersive workspace with one toolbar (`brainBar()`), so neither is a window you have to come back from.
Left to right: Leave, a Map | Rhythm switch (`sl-button-group`, same place and size in both modes), then the mode's own controls.
Map mode: Size by (segmented), then Replay, Attention, What changed and My focus as icon and label buttons of one size. Below 1160px the four tools fold into a More menu, below 700px Size by joins them.
Rhythm mode: the project choice, in the first slot after the switch.
Every control is a small `sl-button` or `sl-select`, so heights and centres match. Group names use the mono micro label. The Brain has no project filter; the scene is always every project.
Esc and Leave go back to where you came from, from either mode.

## The rules, in one place (issue 53)
Everything below is one rule set. Each line says what enforces it. `selftest` reads the files; `a11y-check` measures the running page (`ui-*` rules, every view, both themes, Calm on and off, any size with `--size`).

| Rule | Enforced by |
|---|---|
| Every component has its place: the same slots on every page (rail, top bar, page header, tabs, cards, drawer footer). | the table below; `selftest` for the kit parts |
| The project selector is the first control of the top bar, in the same box on every page. The Brain has none (the whole bar is hidden); My rhythm keeps one, the same scope, in its toolbar. | `selftest` (markup order, one id, bar hidden in the Brain); `a11y-check` `ui-selector` (same box on every view, none in the Brain) |
| Calm is visibly different: larger text, one column, Helm folded, secondary things hidden, muted colour, nothing moving. | `selftest` (the Calm rules exist); read "What Calm does" |
| The Crew page is clear: grouped by job, one row per agent (in All projects the row says how many projects it is on and Run asks which), a header that counts what is running and what needs attention. | `selftest`, node crew test |
| One font. | `selftest` (one `@font-face` family, no other `font-family` or canvas font, no other font file); `a11y-check` `ui-font` |
| Calm and literal: one next action, real data only, no invented numbers. | review; the Demo says it is made up |
| No em dash in user-facing copy. | `selftest` (dashboard markup, strings and the demo text) |
| Nothing loads from the internet. | `selftest` (no http script, style, image, font, import or fetch) |
| Text is never under 12px. | `selftest` (every file the page loads); `a11y-check` `ui-small` (computed) |
| Targets are at least 40px (at 900px and under, and on any coarse pointer). | `selftest` (the touch floor); `a11y-check` `ui-target` (measured) |

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

## What Calm does
Calm is fewer things, quieter, steadier. One switch in the top bar (labelled Calm, tooltip "Larger text, one column, only what needs you"), also in Settings; it is remembered in this browser and the class is set in `<head>` before first paint.
1. Type and space: body text 14px to 16.5px, spacing tokens `--s2..--s6` up by about half, card padding 20px to 28px, controls 44px.
2. One column: split, home, mission and settings layouts collapse; the page is at most 800px wide.
3. Helm folds to its rail. The choice saved in this browser is not touched; the Expand button opens it for this visit.
4. Secondary things are out of sight: any element with `data-calm="hide"` (or built with `calmHide(html)`). Home keeps the headline, the next step and Needs you; stats rows, side columns (Operations, Spend, Fleet), the Notes search, the Needs you intro and Crew detail lines are hidden. A line under the page header says how many, with one Show everything button.
5. Muted colour: running, done and idle pills and tinted cards lose their fill (`.calm` rules in `ui.css`, tokens only). Blocked, bad and needs-you states keep strong colour.
6. Steady: nothing animates or transitions, and nothing ticks. A running clock reads "since 14:32" (`elapsedSpan`), a schedule "at 14:35", the freshness text "up to date". The 3 second poll rewrites only what changed (`setHtml`).
7. The Brain keeps the map and the stats strip; Size by and the tools sit in More.
To make something secondary, add `data-calm="hide"` to it.

## The Crew page
Agents are grouped by job (`GROUPS` in `assets/crew.js`: Review, Build, Plan, Check and keep, Infrastructure, Design and make; a duty not listed goes to Other, so a new duty always shows). The duty files name a duty but not its job, so that one table is the source. Each row: name, one plain sentence (`INFO[duty].does`), its state (running with elapsed, idle with last result, needs attention, never run, not enabled) and Run. Run opens one `sl-dialog` (`#run-dlg`): what it does, the one to three inputs that matter, the Write for real switch (off by default, with its consequence under it), and Advanced (raw flags, extra arguments, Schedule). `buildRun()` builds the same `/api/run` body the page always sent. The header sentence is built from the data: how many agents, on one project or across N, how many are running and how many need attention. With one project chosen every agent the machine has is listed (those not switched on say so); in All projects there is one row per agent, with a pill saying how many projects it is on, its state the worst of them, and the Run dialog asking which project in a labelled field. Run is the plain `sl-button` in a row (the kit rule for repeated rows); the dialog Run is the one primary.

## Responsive rules
Four widths are the test set: 390 (phone), 768 (tablet), 1100 (laptop, Helm open), 1500 (desktop); plus 844x390 (landscape phone). Both themes, Calm on and off, the Demo state and an empty install. These are rules; the table below says what the last sweep of them found.

1. The page never scrolls sideways. Only a table, a `pre` or a chip row inside its own `overflow-x:auto` box may be wider than the screen. Every grid child has `min-width:0`.
2. Breakpoints, and what changes. Rail and Menu: below 760px the rail becomes the bottom bar and the Menu drawer. Top bar: below 940px of *main column* (a container query, so it holds at 1500px with the Helm panel open and at 768px with its rail) the Demo and Calm switches, the freshness text, the run-permission pill and PRIVATE fold into one More menu (`.tb-more`) at the right, so row 1 is always the project choice and the search. A phone has no More button: the Menu drawer holds the same four things. The search's shortcut button reads `⌘K` where there is a keyboard and `All` on a phone. Brain: a side panel above 900px wide and 520px high; a bottom sheet (half the stage) below that, and in a short landscape screen the stats and legend are one scrolling row each. Helm: dock above 1100px, rail below, a sheet and an orb at 700px and under.
3. Touch targets: at 900px and under, and on any coarse pointer, every control is at least 40px in both directions (`--sl-input-height-small:40px`, switches, tabs, icon buttons, chips, the map's count labels by hit area). Text links inside a sentence are exempt; a link that stands alone (`.mlink.link`, `.mlink.title`) is not. Above 900px the floor is 24px.
4. Text is never under 12px, in any theme or mode (a static test reads `ui.css`). The kicker, pill and mono micro labels are 12px.
5. Dialogs and drawers scroll inside, never the page: panel `max-height:calc(100dvh - 24px)` (`100dvh - 8px` in short landscape), the body scrolls, the footer stays. Use `dvh`, not `vh`, for anything tied to the screen height. The viewport meta says `interactive-widget=resizes-content`, and while a field has focus on a phone the bottom bar and the orb step aside so the keyboard leaves room.
6. The Helm orb floats at the bottom right of a phone, 74px above the edge. Every page keeps 150px of bottom padding (bar plus orb), checked by scrolling each view to its end and testing that nothing is under the bar or the orb. It covers content while you scroll; that is what a floating control does.
7. Sticky things never cover what you reach: the top bar is sticky except in short landscape, the Demo banner is not sticky, and `html{scroll-padding}` keeps a focused control clear of the top bar, the bottom bar and the orb.
8. Safe areas: the bottom bar pads by `env(safe-area-inset-bottom)`, the page and top bar by the left and right insets (landscape notches).
9. Text zoom: the rail is `4.75rem` wide, so it grows with the text; bar labels clip rather than spill.
10. If the interface components do not load, the page still reads: an `sl-select`, `sl-input` and `sl-textarea` show their label, a banner (`#sl-fail`) says why some controls are blank and offers Reload, and a confirm falls back to `window.confirm`.

What the sweep found (a Playwright script, not committed: every view at each size and theme, plus the overlays; it measures horizontal overflow, elements wider than the screen, controls under 40px, text under 12px, controls covered by another control, clipped text):

| Where | Found | Fixed or left |
|---|---|---|
| Every view, every size | Text at 10, 10.5, 11 and 11.5px (kickers, pills, rail labels, counts, Timeline lane counts, code) | Fixed: 12px floor; static test |
| Top bar at 768 and 1100 (Helm open) | Wrapped to two or three rows, PRIVATE alone on row 2 | Fixed: More menu under 940px (rule 2) |
| Top bar, any width | The sticky Demo banner sat over the sticky top bar once scrolled | Fixed: the banner is not sticky |
| Top bar, any width | The freshness element lost its `tb-wide` class on every poll (its className was rewritten) | Fixed: classList |
| Phone top bar | The search's `⌘K` button, no keyboard to press it on | Fixed: reads `All` |
| 390 and 768, all views | 150 controls under 40px: small buttons, selects, inputs (32), switches (21), tabs (37), the rail logo (30), icon buttons (36), Brain chips and counts (30), Brain hub counts (15x16), stand-alone text links (18 to 22) | Fixed (rule 3) |
| Timeline, all sizes | Chart markers are 12x16 | Fixed: each marker is a 40px button around its mark, and the lanes are binned so markers are at least 44px apart (`buckets` from the track width). |
| Brain, all sizes | Hub count labels on the map overlap where two hubs project to nearly one spot | Fixed: each frame the nearer label keeps its place and the other steps down until the boxes do not overlap, and a label is kept inside the stage. |
| Page tabs when they scroll | The scroll arrow sits over a half-visible tab | Left: that is what the arrow is for |
| Brain at 768 and 844x390 | The side panel left the map 264 and 340px wide | Fixed: bottom sheet up to 900px and in short landscape; HUD in one row |
| Helm sheet on a phone | Taller than the sheet, clipped, its header scrolled out of reach by the focus | Fixed: the sheet scrolls, height from `dvh` |
| Phone, keyboard up | Bottom bar and orb rode above the keyboard | Fixed (rule 5) |
| Landscape phone | The sticky top bar took a quarter of the height | Fixed: static there |
| Phone, 200% text | Bottom bar labels spilled into each other | Fixed: clip; rail grows (rule 9) |
| Notes with notes in them | `names is not defined`: the page threw | Fixed |
| Fleet with a scheduled job | The job's button helper shadowed `act` and recursed until the stack ran out | Fixed |
| Mission pages (fix, run, panel, cycle, brief, plan, attention), unpaired screen, Add a project (incl. Describe your idea), palette, Run dialog, cycle dialog, confirm, Connections help drawer | Clean at all four widths and landscape, both themes | n/a |
| Empty install, every view | Clean | n/a |

## Accessibility rules
1. One focus ring, from tokens: `--focus` (the accent), `--focus-w:2px`, `--focus-off:2px`. `:focus-visible` and Shoelace's own ring (`--sl-focus-ring-*`) both read them, so a plain button, a link, a row, a rail item, a Brain chip and an `sl-button`, `sl-select`, `sl-input`, `sl-switch`, `sl-tab`, `sl-checkbox`, `sl-details` summary look the same when focused. The accent is at least 3:1 on `--bg`, `--card`, `--card2` and `--raised` in both themes (a selftest checks the numbers). A control inside a box that clips (a pill, the search field, the bottom bar) draws its ring inward (`outline-offset:-3px`). Nothing sets `outline:none` without drawing another.
2. Landmarks: the Places `nav` (the rail), the bottom bar `nav` ("Primary navigation"), one `header` (the top bar; the Brain has none, its toolbar stands in), one `main` (`#view`, the skip link's target), Helm as `complementary`. One `h1` per view (the Brain keeps a hidden one); a card title is `h2`, a drawer section `h2`, its items `h3`.
3. Names: an icon-only control carries its name (`sl-icon-button label`, or `aria-label`); every `sl-input`, `sl-select`, `sl-textarea` has a `label` (`class="nolabel"` hides it visually, it stays in the accessible name); the rail badge's count is in its button's name. The browser's own accessibility tree is the test (`bin/a11y-check.mjs`).
4. State: the active rail item, bottom-bar item and Menu item carry `aria-current="page"`; the active tab is `aria-selected` and the only tab stop (arrow keys move between tabs, Enter activates). A pill always has its word; colour is never the only carrier. Exception: the Timeline's marker colours (a legend and each marker's name carry the same words).
5. Rows that act as buttons (Ledger, Board) are one Tab stop; the arrow keys, Home and End move between them.
6. Dialogs and drawers trap focus, close on Esc, and give focus back to the control that opened them (Shoelace does this; the checker proves it for the palette, the Run dialog and a drawer). Every dialog and drawer has a label.
7. Announcements (`announce()`, the polite `#sr-live` region): the page you moved to, a run that finished, the count of things that need you changing, a success toast, a field error. Never on first load, at most one message per poll. A problem toast stays an alert. A field error is the field's help text (tied to the input), in the error colour, with focus put there.
8. The poll redraws a region whenever one word in it changes; `setHtml` hands keyboard focus back to the same control (same place, else same kind and label), so Tab never restarts from the top.
9. Reduced motion: the OS setting turns Calm on before first paint (unless Calm was chosen explicitly), a global `prefers-reduced-motion` rule stops every animation and transition, and the Brain stops turning.
10. Zoom: page zoom of 200% and 400% is the 768px and 390px layouts; text-only zoom is covered by the `rem` rail and by clipping instead of spilling.

## Accessibility checklist
Result of `node bin/a11y-check.mjs --focus --flows` (1500x900, Demo data, dark and light, Calm on and off: 76 view states, 3092 Tab stops, 0 findings), plus the manual rows below it. "Tab order" means every stop is reached once, in document order, with no trap and no jump back up the page; "focus visible" means a pixel difference around every stop when it gets focus; "names" means every control has a name in the browser's accessibility tree; contrast is 4.5:1 (3:1 large) on all text, Shoelace internals included.

| View | Tab order | Focus visible | Names | Live regions | Status |
|---|---|---|---|---|---|
| Home | ok | ok | ok | page name, needs-you count, run finished | pass |
| Brain (map, Rhythm) | ok | ok | ok | page name, needs-you count, run finished | pass |
| Needs you | ok | ok | ok | page name, needs-you count, run finished | pass |
| Missions | ok | ok | ok | page name, needs-you count, run finished | pass |
| Pull requests | ok | ok | ok | page name, needs-you count, run finished | pass |
| Board | ok | ok | ok | page name, needs-you count, run finished | pass |
| Timeline | ok | ok | ok | page name, needs-you count, run finished | pass |
| Operations | ok | ok | ok | page name, needs-you count, run finished | pass |
| Ledger | ok | ok | ok | page name, needs-you count, run finished | pass |
| Spend | ok | ok | ok | page name, needs-you count, run finished | pass |
| Log | ok | ok | ok | page name, needs-you count, run finished | pass |
| Crew | ok | ok | ok | page name, needs-you count, run finished | pass |
| Fleet | ok | ok | ok | page name, needs-you count, run finished | pass |
| Connections | ok | ok | ok | page name, needs-you count, run finished | pass |
| Documents | ok | ok | ok | page name, needs-you count, run finished | pass |
| Panels | ok | ok | ok | page name, needs-you count, run finished | pass |
| Notes | ok | ok | ok | page name, needs-you count, run finished | pass |
| Showcase | ok | ok | ok | page name, needs-you count, run finished | pass |
| Settings | ok | ok | ok | page name, needs-you count, run finished | pass |

Notes on the table: the live regions are page wide (`#sr-live`), not per view. The Brain's canvas has no accessible content of its own; the stats, chips and counts around it list the same things as buttons, and those are what the checker walks. Text drawn over the map (hub labels) is not contrast-checked (it sits on a canvas).

| Flow | Result |
|---|---|
| Skip link is the first Tab stop and lands in `main` | pass |
| Search everywhere, Run dialog, what PRIVATE means (drawer): open from the keyboard, focus inside, Tab never leaves, Esc closes, focus returns to the opener, labelled, contrast inside, both themes | pass |
| Brain: Esc leaves | pass |
| Keyboard focus survives the 3 second poll redrawing the region | pass (was a defect: focus fell to the top of the page; fixed in `setHtml`) |
| Page tabs: Tab enters the active tab only, arrows move, Enter activates, Home goes to the first | pass (was a defect: every tab was a stop; fixed) |
| Focus ring contrast, the one token on the four surfaces, both themes | pass (3:1 or better) |
| Shoelace vendor folder blocked | page reads: labels show for blank fields, a banner explains and offers Reload; Calm-less controls (switches, drawers) are inert, by nature |
| Not run | A real screen reader (VoiceOver, NVDA): everything above is the browser's accessibility tree and DOM, not what a screen reader says. |

Found by the checker and fixed on the way: Ledger rows were 184 Tab stops; every page tab was a Tab stop; focus was lost on every poll that changed the region; the Brain had no `h1`; the page header was a second banner landmark; the rail badge count was not in the button's name; a success toast was an assertive alert; `--dimmer` on `--raised` was 4.36:1 in dark; focus rings were clipped inside the Brain legend pills, the search field and the bottom bar.
