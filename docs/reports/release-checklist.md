# Release checklist

Facts and open decisions only. Nothing here was done.

## Facts found in the repository at 59566e3

- **Licence.** Apache-2.0 (`LICENSE`), explained in `LICENSING.md`: everything in the repository stays open; a paid team edition is "planned" (issues #40 and #41), nothing is for sale today. Contributions need a `Signed-off-by` line (`CONTRIBUTING.md`).
- **Documents present.** `README.md`, `GUIDE.md`, `SECURITY.md`, `THREAT-MODEL.md`, `LICENSE`, `NOTICE`, `LICENSING.md`, `CONTRIBUTING.md`.
- **Documents absent.** No `CHANGELOG`, no code of conduct, no issue templates, no pull request template in `.github/` (only `.github/workflows/ci.yml`).
- **Version.** No version file and no tag. `packaging/npm/package.json` and `packaging/homebrew/qtdeck.rb` carry `@VERSION@`, `@URL@` and `@SHA256@` placeholders that `bin/release.py` fills from a real tarball.
- **Packaging.** A Homebrew formula (a tap would hold only that file) and a thin npm wrapper (`qtdeck`, marked private) exist as files. Both dry-run offline. Neither is published; the formula was never run through a real `brew`.
- **CI.** A pull request runs the quick check on Linux (about 10 minutes); a merge to `main` and the nightly run test everything on Linux and macOS. PR text and commits are authored as the owner with no trailers.
- **Known open bugs.** 22 GitHub issues from this round (#138 to #148, #160 to #170); ten fix PRs (#149 to #158) waiting to merge.
- **Docs that are wrong until the fix PRs merge.** The onboarding example in `qtdeck help`, the `qtdeck packs list` sentence, the `docs/public/` paths, and the "narrow patterns" sentences about run arguments (see #142).
- **Reports in the public tree.** Reports for rounds 3 to 6 were merged into `docs/reports/`; pull request #130 removes the round 3 and 4 ones, and the publish step is described as never shipping `docs/reports/`.

## Open decisions for the owner

1. The version number and the tag (for example 0.1.0), and where release notes live (a `CHANGELOG`, or GitHub release text).
2. Whether to publish a Homebrew tap (a separate repository named like `homebrew-quarterdeck`) and what its tarball URL is.
3. The npm name: `qtdeck` was not checked against the registry from the cloud box. Decide the name, check it, decide whether to publish at all.
4. The PyPI name: not checked; decide whether a Python package is wanted.
5. A trademark and name search for "Quarterdeck" and "qtdeck" (not done).
6. Issue templates (bug, feature, question), a pull request template, a code of conduct, and where security reports go (GitHub private vulnerability reporting must be switched on, not checked).
7. Rules for the open decisions in the bugs: the `--apply` inside `args` rule (#142), whether the command line enforces "only under your home folder", whether a folder of projects may be attached, whether the dashboard gets a "Turn off" for an agent, and how a spec-panel idea is passed (a file or stdin, not an argument).
8. Whether reports stay out of the public tree for good (and whether to remove the round 5 and 6 reports as well).
9. A short note for testers: what works, what is parked (social connections, Helm voice), what to send back, and how to reach you.
10. Whether the nightly full run on macOS is required to be green before a tag.
