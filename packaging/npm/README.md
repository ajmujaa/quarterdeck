# qtdeck (npm wrapper)

A thin wrapper so `npm install -g qtdeck` gives you the `qtdeck` command. It does not contain a second copy of the logic: it finds Python 3.10 or newer, finds the Quarterdeck program, and runs `bin/qtdeck` with your arguments.

- Python is looked for as `QUARTERDECK_PYTHON` (if set), then `python3`, then `python`. Its version is checked without running any project code.
- The program is looked for as `QUARTERDECK_APP` (a Quarterdeck folder), then the package's own `app/` folder, then the clone this file sits in.
- Arguments reach the program exactly as typed (no shell). The environment is passed through unchanged. The exit status is the program's.
- If Python or the program is missing it prints two lines saying what to install and exits 127.
- It has no dependencies and no install scripts, and it never uses the network.

The `app/` folder is not committed. `bin/release.py --npm` fills it from the tracked files when the owner prepares a release (see `packaging/README.md`). The package stays `"private": true` until the owner removes that line.
