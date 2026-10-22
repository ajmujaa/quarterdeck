# Mac checklist

For the owner, on a real Mac, to cover what the cloud box could not. Use a throwaway data folder so nothing touches your real one:
`export QUARTERDECK_HOME=$(mktemp -d)` and `export HOME=$(mktemp -d)` in a new terminal, then `git clone https://github.com/ajmujaa/quarterdeck && cd quarterdeck`. Tick each step. Note exact text for anything that differs.

1. **First run on a clean Mac.** `bin/qtdeck dashboard`. The first-run screen should open with eight rows, a Copy button on each missing tool, "Look around in Demo" as the main button and Skip beside it.
2. **Doctor and setup.** `bin/qtdeck doctor` then `bin/qtdeck setup`. It should list what is missing with the right `brew` commands and install nothing by itself.
3. **Pairing.** Open the link the dashboard prints. It should work once. Open the same link again: a plain message that it was used. Open the page in a second tab after pairing a second link: the first tab should not just say "forbidden" (known bug #160).
4. **Prove in the macOS sandbox.** Attach a clone of this repo with verify `python3 bin/selftest.py`. Press "Run it once to prove it". You should see the progress strip, elapsed seconds, streaming lines, and a pass, with the process-listing check shown as skipped. Press Stop on a second run.
5. **Nested sandbox.** Inside Prove, run `bash bin/selftest-assayer.sh`. It should print one skip line and exit 0 (it cannot start a second sandbox).
6. **Add-ons folder is protected.** `bin/qtdeck addon new relay`, then from a sandboxed project command try to create a file in `<data>/addons/`. It should be refused.
7. **Keychain.** Settings: move credentials to the Keychain, save a fake token on a Connections card, move them back. The token should survive both moves and never be shown.
8. **A real Google sign-in.** Connections, Google: press Save on the last value. "Continue with Google", the countdown and Cancel should appear; finish sign-in and the Test should pass. Then remove it.
9. **A real model call, once, with a spend cap of a few cents.** Set a daily cap, attach a small project, draft one README. Check the Spend tab shows the cost and the cap stops a second call.
10. **GitHub.** `gh auth login`, then file one ticket to a scratch repo from the Tickets tab. Check it appears on GitHub and "Close the issue" on a finished mission closes it with a comment.
11. **GitHub project board.** Attach a project that has a real board; open Board, press a card, press Reconcile.
12. **Brain with a mouse.** Brain, More: Replay, Attention, What changed, My focus should open (known bug #166; if it fails, note which browser).
13. **Keyboard and VoiceOver.** On Projects, Ready and the Add a project drawer: Tab order follows reading order, focus is visible, dialogs trap and return focus, VoiceOver reads the live status line once.
14. **Double click.** Double-click Attach this project, Save tickets, Dismiss and Approve this plan. Each should do one thing (known bugs #162, #163).
15. **Launch at login.** If you use it: restart the dashboard through launchd and check the link still works and no old process is left.
16. **Helm voice.** Turn voice on, speak a short request, check it answers and "barge in" stops it. Note what is missing if the voice model is not installed (known message #148).
17. **Homebrew.** Run `python3 bin/release.py` to fill a copy of `packaging/homebrew/qtdeck.rb` from a local tarball, then `brew install --formula ./qtdeck.rb` from a temp tap. `qtdeck doctor` should work from the installed copy.
18. **npm wrapper.** `cd packaging/npm && npm pack`, install the tarball in a temp folder, run `npx qtdeck doctor`. It must not download or run an install script.
19. **Read-only and full disk.** Make the data folder read-only (`chmod -R a-w`), run `bin/qtdeck enable demo planner`: one plain line, no traceback (known bug #141, fixed for root only in CI).
20. **Calm mode at a narrow window.** Settings: Calm on, shrink the window to 375 px wide, open Connections > Agent sources: no button should be cut off (known bug #170).
