#!/usr/bin/env python3
"""qtdeck connect: connect a service, one account at a time, from the terminal. The same store and the same rules as the Connections page.

  connect.py list                                       every service and every account: its state and when it last refreshed (never a value)
  connect.py <service> [--account <label>]              ask for each credential of that account, save it, switch the account on, say what to do next
  connect.py remove <service> [--account <label>] [--yes]   forget that account: credentials, sign-in, saved data

A label is lowercase letters, digits and dashes, at most 24 (default: "default"). A secret is read from the terminal with nothing shown, or from
standard input when that is not a terminal. It is never taken from an argument: an argument is visible to every process on the computer and
stays in the shell history. Press Enter on a prompt to keep what is saved.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from integrations import accounts, common, google_oauth, manifest      # noqa: E402

NO_ARG_SECRET = "a credential is never given as an argument (it would show in the process list and the shell history): run the command without it and type or pipe the value"


def say(msg):
    print(msg)


def fail(msg, code=2):
    print("qtdeck connect: " + msg, file=sys.stderr)
    return code


def _parse(argv, flags=()):
    """(positionals, account, flags_found) or raises ValueError with a plain sentence."""
    pos, label, found, i = [], None, set(), 0
    while i < len(argv):
        a = argv[i]
        if a == "--account":
            if i + 1 >= len(argv):
                raise ValueError("--account needs a label such as work")
            label, i = argv[i + 1], i + 1
        elif a.startswith("--account="):
            label = a.split("=", 1)[1]
        elif a in flags:
            found.add(a)
        elif a.startswith("-"):
            raise ValueError(NO_ARG_SECRET if a.lstrip("-").split("=")[0] in ("token", "secret", "key", "value", "password", "client-secret") else f"unknown option {a}")
        else:
            pos.append(a)
        i += 1
    return pos, accounts.norm(label), found


def _service(sid):
    s = next((x for x in manifest.load_services() if x["id"] == sid), None)
    if s is None:
        raise ValueError(f"no service called {sid}: qtdeck connect list shows them all")
    return s


def cmd_list():
    rows = manifest.status()
    say(f"  {'SERVICE':<12} {'ACCOUNT':<14} {'STATE':<13} LAST REFRESH")
    for r in rows:
        for a in r["accounts"]:
            say(f"  {r['id']:<12} {a['label']:<14} {a['state']:<13} {a['last_at'] or 'never'}")
    say("")
    say("  add an account:  qtdeck connect <service> --account <label>")
    return 0


def _ask(c, who, have, secret_ok=True):
    """One value from the terminal (hidden for a secret) or from a line of standard input. "" keeps what is saved."""
    note = " (saved, Enter keeps it)" if have else ""
    prompt = f"{c['label']} for {who}{note}: "
    if sys.stdin.isatty():
        return (getpass.getpass(prompt) if c["secret"] else input(prompt)).strip()
    return sys.stdin.readline().strip()


def cmd_connect(argv):
    pos, label, _ = _parse(argv)
    if len(pos) != 1:
        raise ValueError(NO_ARG_SECRET if len(pos) > 1 else "usage: qtdeck connect <service> [--account <label>] | list | remove <service> [--account <label>]")
    s = _service(pos[0])
    if s["local"] or not s["credentials"]:
        say(f"{s['label']} needs nothing entered here. {s['what']} Follow its steps on the Connections page.")
        return 0
    if label != accounts.DEFAULT:
        manifest.add_account(s["id"], label)
    have = manifest.env_keys(label)
    who = s["label"] + ("" if label == accounts.DEFAULT else f", {label} account")
    changed = 0
    for c in s["credentials"]:
        v = _ask(c, who, c["key"] in have)
        if v:
            manifest.set_credential(c["key"], v, label=label)
            changed += 1
    if not changed and not any(c["key"] in have for c in s["credentials"]):
        raise ValueError(f"nothing was given for {who}; nothing was saved and it stays off")
    manifest.set_enabled(s["id"], True, label=label)
    say(f"Saved {changed} credential{'' if changed == 1 else 's'} for {who}, and switched it on. Values are not shown again.")
    more = "" if label == accounts.DEFAULT else f" --account {label}"
    if s["id"] in google_oauth.SCOPES:
        say(f"Next: sign in with   python3 bin/integrations/google_oauth.py {s['id']}{more}")
    say(f"Then test it with   python3 bin/integrations/run.py {s['module'] or s['id']}{more}")
    return 0


def cmd_remove(argv):
    pos, label, found = _parse(argv, ("--yes",))
    if len(pos) != 1:
        raise ValueError("usage: qtdeck connect remove <service> [--account <label>] [--yes]")
    s = _service(pos[0])
    who = s["label"] + ("" if label == accounts.DEFAULT else f", {label} account")
    if "--yes" not in found:
        if not sys.stdin.isatty():
            raise ValueError("removing forgets saved credentials and data: add --yes to confirm when there is no terminal")
        if input(f"Forget {who}: its credentials, sign-in and saved data? Type y to confirm: ").strip().lower() != "y":
            say("Nothing was changed.")
            return 1
    manifest.remove_account(s["id"], label)
    say(f"Removed {who}." + ("" if label != accounts.DEFAULT else " The service card stays, switched off."))
    return 0


def main(argv):
    try:
        if not argv:
            raise ValueError("usage: qtdeck connect <service> [--account <label>] | list | remove <service> [--account <label>]")
        if argv[0] == "list" and len(argv) == 1:
            return cmd_list()
        if argv[0] == "remove":
            return cmd_remove(argv[1:])
        return cmd_connect(argv)
    except ValueError as e:
        return fail(str(e))
    except (common.IntegrationError, OSError) as e:
        if isinstance(e, OSError) and common.is_write_failure(e):
            return fail(common.why_not_saved(e), 1)
        return fail(getattr(e, "short", None) or f"could not do that ({type(e).__name__})", 1)
    except (KeyboardInterrupt, EOFError):
        return fail("stopped; nothing more was changed", 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
