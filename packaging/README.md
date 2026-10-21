# Packaging

Files only. Nothing here is published, and nothing in this repository publishes it.

- `homebrew/qtdeck.rb` is the formula for a tap. It keeps three placeholders (`@URL@`, `@SHA256@`, `@VERSION@`) that `bin/release.py` fills into a copy.
- `npm/` is a thin wrapper package (`npm install -g qtdeck`): a `bin` shim that finds Python 3.10 or newer and runs the program. Its `app/` folder is not committed; `bin/release.py --npm` fills it from the tracked files. The package stays `"private": true`.

## How the owner publishes, later

Nothing below has been run. Each step is yours to take.

1. Choose the version, for example `1.0.0`, and commit everything. Tag it `v1.0.0` and push the tag. GitHub then serves the source tarball at `https://github.com/ajmujaa/quarterdeck/archive/refs/tags/v1.0.0.tar.gz`.
2. Download that tarball and prepare the files from it:
   `python3 bin/release.py 1.0.0 --tarball path/to/v1.0.0.tar.gz --npm`
   This writes `dist/release/homebrew/qtdeck.rb` and `dist/release/npm/`. To try the steps on this machine first, `python3 bin/release.py --make-tarball 1.0.0` builds a tarball of the tracked files in `dist/release/`.
3. Homebrew: make a repository named `ajmujaa/homebrew-quarterdeck`, put the filled `qtdeck.rb` in its `Formula/` folder, commit and push. Then `brew install ajmujaa/quarterdeck/qtdeck` works, and `brew test qtdeck` runs the formula's own check. Try `brew install --build-from-source ./qtdeck.rb` on a Mac before you announce it.
4. npm: in `dist/release/npm/`, remove the `"private": true` line from `package.json`, run `npm pack` and read the file list, sign in to npm, and publish it yourself.
5. After either, `qtdeck setup` is the first command a newcomer runs; the dashboard's first-run screen then lists what is missing.

`bin/release.py` refuses a malformed version and a missing tarball, uses no network, and never runs git push, npm or brew.
