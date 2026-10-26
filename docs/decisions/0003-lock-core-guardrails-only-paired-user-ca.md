# 0003. Lock core guardrails; only paired user can relax two of three

Status: accepted
Date: 2026-10-26
Panel: text-6417ccf99523
Paths: GUIDE.md
Keywords: guardrails, never merge a PR, never push to default branch, never touch secrets, locked rules, paired user, typed confirmation, dashboard override

## What was chosen

The three default guardrails (never merge a PR, never push to default branch, never touch secrets) are locked for every project and cannot be edited via guardrails UI, CLI, or API. The owner decided the first two may be turned off only by the paired user, from the dashboard, per project and per rule, with a typed confirmation, never by an agent or an unpaired call. Never touch secrets stays locked for everyone so an agent can never leak a credential.

## Options rejected, and what each costs

- **Make all guardrails user-editable, including these three:** Would remove the floor preventing an agent from merging a PR, pushing to the default branch, or touching a secret, leaving credential leakage with no locked-off case; not known to have been weighed by the panel.

## What is hard to reverse

- Never touch secrets has no override mechanism for anyone, by design, since a leaked secret cannot be unleaked
- The only sanctioned relaxation of the other two rules is the paired user's per-project, per-rule, typed-confirmation dashboard action; any bypass of that path would undermine the whole guardrail model

## What would make this wrong

- The panel did not name conditions under which this decision would be wrong
