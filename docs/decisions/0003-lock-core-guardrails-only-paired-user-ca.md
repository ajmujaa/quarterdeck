# 0003. Lock core guardrails; the harness has no merge or default-branch push

Status: accepted
Date: 2026-10-26
Panel: text-6417ccf99523
Paths: bin/guardrails.py, bin/attach.py, bin/dashboard.py
Keywords: guardrails, never merge a PR, never push to default branch, never touch secrets, locked rules, merge button

## What was chosen

The three default guardrails (never merge a PR, never push to default branch, never touch secrets) are locked for every project. The guardrails page, the CLI and the API cannot edit them.

They are instructions given to the model, not a permission system. The harness has no step that merges a pull request or pushes to the default branch, so the model cannot do either whatever the text says. The only merge is the dashboard's Merge button, which is the paired user's own click.

For that reason there is no setting to turn the first two rules off. It would remove a sentence from a prompt and grant no capability, so it would only look like a control. Never touch secrets stays locked for the same reason it always was: a leaked credential cannot be unleaked.

## Options rejected, and what each costs

- **Make all guardrails user-editable:** removes the floor that keeps credentials out of the model's reach.
- **A dashboard override for the first two rules:** cosmetic today. Making it real means new harness code that merges or pushes on its own, which no user has asked for. Build it when someone needs it, as its own record.

## What is hard to reverse

- Never touch secrets has no override, by design.
- Adding any step to the harness that merges or pushes to the default branch changes what an agent can do. It needs its own record, a typed confirmation from the paired user, and tests.

## What would make this wrong

- A user needs Quarterdeck to merge their own green pull requests on their own projects. Then an opt-in auto-merge, per project, written as a new record that supersedes this one.
