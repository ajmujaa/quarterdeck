# Proposed CI workflows

These files are proposals. They live under `docs/ci/` because the owner's token cannot push workflow files. To enable them, copy each `*.yml` into `.github/workflows/` yourself. Nothing here runs until then.

## What each does

| File | Trigger | Does |
| --- | --- | --- |
| `ci.yml` | push to main, pull requests | Matrix of macOS and Ubuntu (latest) by Python 3.10 and 3.12. Checks out, sets up Python and Node 20, installs `jq` (and `bubblewrap` on Linux), then runs `python3 bin/selftest.py`, `bin/qtdeck doctor` and `bin/qtdeck check`. |
| `secret-scan.yml` | push to main, pull requests | Runs `python3 bin/guard.py` over every tracked file. It exits 1 on any credential-shaped hit, which fails the job. The denylist of private names is deliberately not used in CI, because that list lives outside the repository. |
| `dependencies.yml` | push to main, pull requests | Runs `python3 bin/vendor-verify.py`, which compares every file under `dashboard/assets/vendor/` with the sha256 pins in `HASHES.json`. It installs nothing and uses no network at test time. |

## Public command name

The task pointed at `docs/public/README.md`, which does not exist on this branch. The command name was confirmed from `bin/qtdeck` itself: its usage text lists `doctor`, and its `check` case runs `bin/check.py`. `bin/publish.py` also does not exist. Re-check the names if a public README lands later.

## Permissions

Every workflow sets `permissions: contents: read` at the top level and no job widens it. Checkout uses `persist-credentials: false`, so the token is not left in the git config for later steps. No secrets are referenced. No workflow uses `pull_request_target`.

## Pinning actions

Third-party actions should be pinned to a full commit sha. I could not verify real shas from the actions' official repositories in this session (access was limited to this repository), so I did not invent any. Each `uses:` line has a `# TODO(pin)` comment above it naming the tag. To resolve one, look up the sha the tag points to in the action's own repository, and write `uses: owner/action@<40-hex-sha> # v4`. The self-test accepts either a 40-hex sha or a TODO marker, and fails on a bare tag without one.

## Self-test guard

`bin/selftest.py` parses everything in `docs/ci/*.yml` with a minimal line check (no YAML dependency) and fails if a workflow requests any `write` permission, has no `contents: read` permission block, or uses an unpinned third-party action without a TODO marker.

## Not verified

- None of these workflows has run on GitHub. YAML syntax was only checked by the minimal line parser, not by GitHub's schema.
- Whether `bubblewrap` works on `ubuntu-latest`: newer images may restrict unprivileged user namespaces, so Linux sandbox tests may skip or fail. The workflow prints whether they are available.
- The macOS and Linux matrix has not been run on all four combinations. Tests that need macOS sandboxing skip on Linux by design.
- `bin/qtdeck doctor` exits 1 when `claude`, `gh` or `gh auth` is missing, which the runners will not have. The step is marked `continue-on-error: true`, so it only reports. A CI mode would be needed to make it a gate.
- The action sha pins (see above).
