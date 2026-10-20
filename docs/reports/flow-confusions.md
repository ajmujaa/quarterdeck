# What confuses a newcomer in the attach, ticket and cycle flow

Found by driving bin/selftest-flow.sh by hand and reading every message. "Fixed" means the code now says it and bin/selftest-flow.sh checks it.
"Not fixed" items are for the lead. Round 2 (attach as onboarding) fixed 7, 8, 9, 13, 15 and 17.

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

7. `"cycle": true` and the duty list were edited by hand in config/projects.json. Now `qtdeck enable <project> cycle` sets `"cycle": true` and turns on
   the purser and the dev panel (and says so), `qtdeck enable|disable <project> <duty>...` switch a duty through the same checks as the attach review
   (bin/attach.py `set_duties`), the log names the project and the duties, and the Ready card has "Turn on" and "Allow cycles" buttons.
8. The verify command attach proposes is `npm test` (Vitest), which fails with exit 127 until `npm install` has run. Now attach (and `qtdeck ready`) say
   "run npm install first, or set a verify command that needs no install" when the verify command is a Node tool and node_modules is absent
   (bin/ready.py `install_hint`), and `qtdeck ready <p> --prove` explains exit 127 in the plain words the shipwright uses.
9. `attach` on a registered folder only said "already registered". Now it surveys the folder again, refreshes the profile in the data folder and says what
   changed since the last survey; `--verify`, `--build` and `--lint` on a registered folder are announced, and `--apply` writes them (same limits as the review).
13. `qtdeck ticket show` ended with `git diff <base>...<branch>` and a placeholder. Now it prints the real review and merge commands (bin/tickets.py `review_command`).
15. The cycle id is `cyc-<project>-t1-<unix time>`. Now `qtdeck cycle --status` and `--resume` take `<project> --ticket n`, or a project alone for its latest cycle.
17. `qtdeck status` did not show which verify command a project uses. Now `qtdeck projects` shows verify, build and lint under each project.

## Not fixed

10. A report-only cycle (`cycle <p> --ticket 1`, no --apply) still runs the purser and the dev panel and spends about 25 cents. "Report
    only" reads as free. Fix: print the cost up front, or say "report only still asks the model".
11. The stage table prints "SKIPPED (skipped)" for every stage that needs a pull request (bin/cycle:282). Fix: print the reason column
    instead of repeating the word, and show it in `--status` too.
12. The dev panel prints "build it with: qtdeck run <p> shipwright --ticket n --plan ... --apply" inside a cycle that is about to do
    exactly that (duties/panel.sh:624). Fix: print that line only when the panel is run alone.
14. Seat and crew names (inspector, naval-architect, shipwright, dockmaster) appear in the output with no explanation. Fix: one line in
    `qtdeck cycle` saying who they are, or a link to the Words section of GUIDE.md.
16. Many messages still use a long dash as punctuation ("skipped" lines in bin/cycle:283 and :301, "usage limit reached" in
    duties/planner.sh:201). Fix: a full stop or a colon. Not changed here because other suites match these strings.
18. To review the local branch a person must know `git -C <path> diff main...<branch>` and then `git merge`. The cycle prints both, but the
    dashboard shows them as text to copy. Fix: a "Copy" button next to each command.

## Still confusing after round 2 (found by driving the onboarding flow by hand and reading the screenshot)

19. Three words for nearly the same thing: "scan" (what attach reads), "survey" (the profile it keeps) and "profile" (the files). The checklist says Scan; the
    docs say survey. A glossary line in the Words section of GUIDE.md would settle it.
20. `qtdeck docs <p>` is the scribe, but the duty list also has a `scribe` that needs no switch. A newcomer who runs `qtdeck duties` sees a duty they never
    enable and cannot run with `qtdeck run`; the Crew page's Run dialog for it explains nothing.
21. "Prove it" runs the project's own verify command, which for most projects needs an install. The first proof of a fresh clone will often be exit 127, and the
    fix (run the install yourself) lives outside Quarterdeck. The hint is there, but it takes two steps and one of them is in another terminal.
22. The Ready card hides itself once the verify command is proven. The "Ready? Show the checklist" link is easy to miss, so a person who wants to see the docs
    offer again has to know to look for it. A permanent small "Ready" entry in the project header would help.
23. The survey counts lines by reading source files (newlines only). That is local and read-only, but the SECURITY note says "reads files only", and a person
    who expects "metadata only" may be surprised.
24. `qtdeck enable <p> cycle` turns on the purser and the dev panel, which spend model money in a cycle. The command says so, but "enable" does not read like
    "this can cost money". The dashboard asks first; the command line does not.
