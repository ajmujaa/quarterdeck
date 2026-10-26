# 0002. The dependency graph is worked out from the base branch, with an optional declared file

Paths: bin/depgraph.py, docs/architecture/dependencies.json, bin/decisions.sh
Keywords: dependency graph, depgraph, dependencies.json, what depends on, impact

## Decision

Reviews are told which parts of a project depend on the parts a change touches. The graph is worked out each time from the project's base branch (git objects only) by `bin/depgraph.py`. No model builds it and no graph file is stored.

- Scanned: every folder with a `package.json` is a unit; A depends on B when B's package name is in A's dependencies.
- Declared, optional: `docs/architecture/dependencies.json` lists what a scan cannot see (queues, HTTP calls, other languages).
- `qtdeck graph <project> --check` reports where the declared file and the code disagree. The shipwright refuses to commit a change that adds such a disagreement. It never rewrites the file on its own.

## Rejected

- **Regenerating the declared file on every build.** The check would then always pass, and a new dependency would not stand out in review. A person (or the builder, in the same change) states a new call.
- **A stored graph file written by a tool.** It goes stale; a graph worked out from the base branch cannot.

## Known limits

- The scan reads `package.json` only. A call added in code (a queue, an HTTP request) is not seen unless declared.
- The result is a lead for the reviewer, not a verdict.
