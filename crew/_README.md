# Crew

One file per agent. A crew member is **data, not code**: a persona the panel
duty loads and speaks through. Adding a third UI reviewer or a fourth developer
is a markdown file here and a name in a panel roster — never a change to the
machinery.

Frontmatter:

```yaml
---
name: loftsman          # must match the filename
discipline: design      # which panel this one sits on: design | dev | spec | qa
seat: visual system     # a few words, shown on the dashboard
bias: fewer elements, stricter rhythm    # what this one argues FOR, in a phrase
model:                  # empty = the account default (Opus); see below
provider:               # optional; empty = the install default (claude). See docs/design-providers.md
---
```

**Which model.** Matched to the seat, per the fleet owner's policy: a seat that
reviews, writes or builds is routine work and runs on Sonnet; the seats whose
job is structure and rulings — the naval-architect and the dockmaster — are the
hard-to-reverse calls and stay on Opus. A fix can override this for its tier,
and a decision panel puts every seat on Opus at xhigh.

**Which provider.** Empty for every seat today: the install default is Claude
Code. `provider:` names the adapter that seat's calls go through, and only the
names `qtdeck doctor` lists are accepted; anything else stops the seat before a
model runs.

The body is the persona. Three rules it must hold to:

1. **Know no project.** No repo name, no framework, no product. The registry
   supplies those through the prompt preamble. A persona that names a stack
   stops being reusable the moment you register a second project.
2. **Have a bias worth hearing.** A panel exists to surface disagreement. Three
   personas that all say "be careful and thorough" cost three times as much as
   one and tell you nothing new. Say what this one over-weights, and what it is
   willing to be wrong about.
3. **Argue from evidence.** Every claim points at a file. A persona that
   theorises is one the dockmaster will rule against.
