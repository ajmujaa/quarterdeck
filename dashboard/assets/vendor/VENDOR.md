# Vendored third-party files

Nothing here loads from the internet; the page and server stay local-first.

| What | Version | Source | Licence | Files |
|---|---|---|---|---|
| Shoelace (web components) | 2.20.1 | `npm pack @shoelace-style/shoelace@2.20.1`, `cdn/` build | MIT (`shoelace/LICENSE.md`) | `shoelace/shoelace-autoloader.js`, the components the page uses (`components/`), the chunks they import (`chunks/`), `themes/light.css` (the base variables; colours are themed from `ui.css`, so `dark.css` is not shipped), `utilities/base-path.js`, a subset of `assets/icons/*.svg` (Bootstrap Icons, MIT) |
| Space Grotesk (latin 400/500/600/700) | 5.3.0 | `npm pack @fontsource/space-grotesk` | SIL OFL 1.1 | `fonts/space-grotesk-latin-*.woff2` |
| three.js | see `THREE-LICENSE` | earlier vendor drop | MIT | `three.module.js`, `three.core.js`, `OrbitControls.js` |

Shoelace is loaded by `shoelace-autoloader.js`, which imports a component the first time its tag appears. The page calls
`setBasePath("/assets/vendor/shoelace")` so icons and components resolve locally. To add a component or icon: re-run the
copy from the npm pack (the autoloader's imports are followed, so only files a component needs are kept) and list it here.
Font licences are next to the fonts (`fonts/LICENSE-*.txt`).

## Pinned hashes

`HASHES.json` holds the sha256 of every file in this folder (except `HASHES.json` and `VENDOR.md`). `python3 bin/vendor-verify.py` fails and lists any file that was changed, added or removed since, so a vendored file cannot be altered silently (a bad merge, an editor, a tampered dependency drop). It also refuses symlinks. `python3 bin/selftest.py` runs the same check.

To update a vendored file on purpose:

1. Replace the file with the new upstream copy.
2. Run `python3 bin/vendor-verify.py --write`.
3. Review the diff of `HASHES.json`; only the files you meant to change should differ.
4. Record the source version and URL in the table above.

three.js: the exact revision of `three.module.js` and `three.core.js` is not recorded. Look it up (compare against upstream releases) and write it down here the next time they are updated.
