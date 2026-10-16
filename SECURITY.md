# Security

Quarterdeck can start agents and run commands on your machine, so please report security problems privately.

## Reporting

Use GitHub's private vulnerability reporting: the **Security** tab of this repository, then **Report a vulnerability**. Please do not open a public issue for a vulnerability.

We aim to acknowledge a report within a few days and to say what we will do about it.

## How the dashboard is protected

- It binds to `127.0.0.1` only.
- Every change request carries a token that only a page served by the same process has seen; Host and Origin headers are checked.
- A run is an argument list, never a shell string; project, duty and values are validated against the registry.
- Agents never receive credentials or write tools; the harness performs every write, only after the reply parses as a contract, and only with an explicit apply.
- Reads that could expose private files are denied to agents, and an operating system sandbox is on by default for agent runs (`QUARTERDECK_SANDBOX=off` switches it off). It is not applied to a call that uses GitHub's command line, because that tool cannot reach GitHub from inside it; those calls rely on the read deny list instead.

## What to look at

The threat model, and what an agent can and cannot read, is being written up here. Until then, the code in `bin/dashboard.py` (the request checks) and `bin/lib.sh` (how agents are started) is the source of truth.
