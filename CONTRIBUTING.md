# Contributing to Quarterdeck

Thank you for helping. A few rules keep the project calm and safe.

## Before you start

- Open an issue first for anything larger than a fix, so we agree on the shape before you spend time.
- Read the principles in the README ("The one rule" and "What it will never do"). A change that breaks one will not be merged, however useful it is.

## Making a change

- One change per pull request, with a test that fails without it. `bin/qtdeck check` must be green.
- Python uses the standard library only. Shell must run on macOS bash 3.2 and BSD tools (no `${x:-{}}`, no `timeout`, no GNU-only flags).
- Plain words in the interface. No decoration or motion that carries no meaning.
- Never commit a credential, a private name or a personal path. `bin/guard.py` checks this; install the hook with `bin/guard.py install-hook`.

## Sign-off

By contributing you agree your work is licensed under Apache-2.0. Sign off each commit (`git commit -s`) to say you have the right to submit it.
