# What confuses a newcomer in the attach, ticket and cycle flow

Found by driving bin/selftest-flow.sh by hand and reading every message. "Fixed" means the code now says it and bin/selftest-flow.sh checks it.
"Not fixed" items are for the lead.

## Fixed

1. A ticket cycle after a plain attach failed late. attach turns on only the read-only duties and the shipwright, so the purser and the dev
   panel were skipped ("not enabled ... duties[] in the registry", bin/cycle:270) and the shipwright then died with "no such plan". Now
   `qtdeck cycle <p> --ticket n` refuses first and names the missing duties and the registry file (bin/cycle:139). GUIDE.md says it too.
2. A request with a key in it (`ticket new ... "log in with ghp_..."`) was sent to the model, printed back in "asked:" and kept in the draft;
   only the drafted tickets were scanned. The planner now stops before any model call, exit 3 (duties/planner.sh); the page shows a plain
   sentence (bin/dashboard.py, `_ticket_error`).
3. A check that exits 127 (a tool that is not installed, such as vite) looked like a pass: the cycle ended "awaiting-review" with
   "checks: verify exit 127". The shipwright now says what 127 means, that the crew never installs, and what to change (duties/shipwright.sh).
4. Asking for the same tickets again printed "saved as local tickets: ticket 1, ticket 2" though nothing was added. Each line now says
   "(already on the list, not added again)" (bin/tickets.py, `file`).
5. After `attach --apply` on a folder with no repo, the only "next:" was `qtdeck repo <p> <owner/name>`, which steers a person to GitHub. A
   second line now names the way to stay local: `qtdeck ticket new <p> "<what you want built>"` (bin/attach.py:465).
6. "has not opted in ... opens real pull requests" was printed for a local ticket, which never opens one (bin/cycle:138). Now it says only
   that a cycle spends money when it is for a ticket.

## Not fixed

7. `"cycle": true` and the duty list are edited by hand in config/projects.json. No command and no page does it; the dashboard only shows the
   line to add. Fix: `qtdeck enable <project> cycle purser panel`, and an "Allow cycles" switch on the project page.
8. The verify command attach proposes is `npm test` (Vitest), which fails with exit 127 until `npm install` has run. `node --test` works
   offline, but nothing says so. Fix: when node_modules is missing, attach says "run npm install first, or pass --verify".
9. `attach` on a registered name only says "already registered" (bin/attach.py:321). To change verify a person must edit the registry.
   Fix: `qtdeck attach <dir> --apply --update`, or a `qtdeck set <p> verify "..."`.
10. A report-only cycle (`cycle <p> --ticket 1`, no --apply) still runs the purser and the dev panel and spends about 25 cents. "Report
    only" reads as free. Fix: print the cost up front, or say "report only still asks the model".
11. The stage table prints "SKIPPED (skipped)" for every stage that needs a pull request (bin/cycle:282). Fix: print the reason column
    instead of repeating the word, and show it in `--status` too.
12. The dev panel prints "build it with: qtdeck run <p> shipwright --ticket n --plan ... --apply" inside a cycle that is about to do
    exactly that (duties/panel.sh:624). Fix: print that line only when the panel is run alone.
13. `qtdeck ticket show` ends with `git diff <base>...<branch>` with a placeholder (bin/tickets.py:568). Fix: print the real command, as
    the shipwright does.
14. Seat and crew names (inspector, naval-architect, shipwright, dockmaster) appear in the output with no explanation. Fix: one line in
    `qtdeck cycle` saying who they are, or a link to the Words section of GUIDE.md.
15. The cycle id is `cyc-<project>-t1-<unix time>` and `--resume`/`--status` need it. Fix: let `--status` and `--resume` take
    `<project> --ticket n`, or default to the latest cycle.
16. Many messages still use a long dash as punctuation ("skipped" lines in bin/cycle:283 and :301, "usage limit reached" in
    duties/planner.sh:201). Fix: a full stop or a colon. Not changed here because other suites match these strings.
17. `node --test` versus `npm test`: the verify command in the registry is not the project's own test script, and `qtdeck status` does not
    show which one is used. Fix: show verify, build and lint in `qtdeck projects`.
18. To review the local branch a person must know `git -C <path> diff main...<branch>` and then `git merge`. The cycle prints both, but the
    dashboard shows them as text to copy. Fix: a "Copy" button next to each command.
