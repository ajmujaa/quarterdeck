# 0004. Dashboard stays loopback-only, paired via one-time link, no login system

Status: accepted
Date: 2026-10-26
Panel: text-3174218d5474
Paths: GUIDE.md
Keywords: dashboard, loopback, 127.0.0.1, pairing, one-time link, login, session, remote access, authentication

## What was chosen

The dashboard binds only to 127.0.0.1 and is paired through a link valid for five minutes, used once, instead of a login/session system. Quarterdeck does not ship remote access; a user who exposes the dashboard to a network (e.g. their own tunnel or VPN) owns that decision and can record it in their own ADR.

## Options rejected, and what each costs

- **Add a username/password or token-based login for remote/multi-user access:** Would require building and maintaining a login/session system, and would mean Quarterdeck shipping remote access instead of staying loopback-only by design. (Not confirmed as weighed by the panel — a guess by the code reader.)

## What is hard to reverse

- Moving away from loopback-only to supporting remote/multi-user access would mean building a login/session system from scratch, a larger surface than the current one-time-link pairing.

## What would make this wrong

- The panel did not name a condition under which this decision would be wrong.
