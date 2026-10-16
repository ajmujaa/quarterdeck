# Vendored third-party files

Nothing here loads from the internet; the page and server stay local-first.

| What | Version | Source | Licence | Files |
|---|---|---|---|---|
| Shoelace (web components) | 2.20.1 | `npm pack @shoelace-style/shoelace@2.20.1`, `cdn/` build | MIT (`shoelace/LICENSE.md`) | `shoelace/shoelace-autoloader.js`, the components the page uses (`components/`), the chunks they import (`chunks/`), `themes/light.css` (the base variables; colours are themed from `ui.css`, so `dark.css` is not shipped), `utilities/base-path.js`, a subset of `assets/icons/*.svg` (Bootstrap Icons, MIT) |
| Fraunces (variable, latin) | 5.3.0 | `npm pack @fontsource-variable/fraunces` | SIL OFL 1.1 | `fonts/fraunces-latin-wght-normal.woff2` |
| Space Grotesk (latin 400/500/600/700) | 5.3.0 | `npm pack @fontsource/space-grotesk` | SIL OFL 1.1 | `fonts/space-grotesk-latin-*.woff2` |
| IBM Plex Mono (latin 400/500) | 5.3.0 | `npm pack @fontsource/ibm-plex-mono` | SIL OFL 1.1 | `fonts/ibm-plex-mono-latin-*.woff2` |
| three.js | see `THREE-LICENSE` | earlier vendor drop | MIT | `three.module.js`, `three.core.js`, `OrbitControls.js` |

Shoelace is loaded by `shoelace-autoloader.js`, which imports a component the first time its tag appears. The page calls
`setBasePath("/assets/vendor/shoelace")` so icons and components resolve locally. To add a component or icon: re-run the
copy from the npm pack (the autoloader's imports are followed, so only files a component needs are kept) and list it here.
Font licences are next to the fonts (`fonts/LICENSE-*.txt`).
