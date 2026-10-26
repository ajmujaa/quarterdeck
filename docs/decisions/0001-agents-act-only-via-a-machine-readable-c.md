# 0001. Agents act only via a machine-readable contract, never with direct credentials

Status: accepted
Date: 2026-10-26
Panel: text-09ba8e97b078
Paths: bin/lib.sh, duties/
Keywords: credentials, agent permissions, contract, --apply, secrets leakage, write tools, gh_post

## What was chosen

Agents never receive credentials or write tools; they end replies with a machine-readable contract that the duty's own script (duties/*.sh, with the helpers in bin/lib.sh) parses and acts on, posting and pushing only with --apply. Chosen to prevent agents or LLM logs from capturing credentials on their own servers or leaking them into public repositories.

## Options rejected, and what each costs

- **Give agents direct API/gh credentials and let them act directly:** Not known to have been weighed by the panel itself (a guess from reading the code); its cost would be the credential-exposure and leak risk the chosen design is meant to avoid.

## What is hard to reverse

- The panel named nothing as hard to reverse.

## What would make this wrong

- The panel did not say what would make this wrong.
