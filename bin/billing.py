#!/usr/bin/env python3
"""Which account a duty's model calls are billed to: the claude CLI's own sign-in (your plan, the default) or an Anthropic API key.

The setting lives in your data folder, config/billing.json, and is plain data (no secret in it):
  {"default": "plan",
   "duties": {"shipwright": "api"},            a duty by its file name in duties/
   "seats":  {"modelmaker": "api"},            a crew seat (panel, marshal, pilot); a seat's own setting wins over its duty's
   "caps":   {"daily_usd": 20, "duty_usd": {"shipwright": 5, "*": 3}}}
The caps count only calls billed to the key, from the spend ledger (state/spend.jsonl), since local midnight. "*" is the cap of every duty
that has none of its own. No cap set means none: the per-call cap (QUARTERDECK_CALL_BUDGET) still holds.

The key itself is kept in the credential store the Connections page uses (the owner-only file ~/.config/quarterdeck/integrations.env, or
the macOS Keychain when chosen), under the fixed name anthropic_api_key. It goes in on standard input (`qtdeck keys set anthropic`) or
through the Settings page, and comes out in exactly one place: `key`, whose standard output the harness reads into a shell variable just
before a call billed to it. Nothing else here returns, prints or logs it: the rest says only whether it is present.

  billing.py mode <duty> [seat]     plan or api
  billing.py gate <duty> [--hold ID] [--budget USD]
                                    exit 0 and the dollars this call may spend: what is left under the caps less what calls running now hold,
                                    at most USD (empty: no cap); exit 4 and the reason when a cap is reached, 3 when the setting or the ledger
                                    cannot be read. --hold ID holds that amount until `settle ID` (review r9 A5)
  billing.py settle <ID>            the call that held ID has ended and its ledger row is written
  billing.py has-key                exit 0 when a key is stored, 1 when not; prints nothing (claude_run asks this, the adapter reads the key)
  billing.py key                    the key on standard output, for the harness only (refused on a terminal); exit 1 when none is stored
  billing.py set-key | remove-key   the key from standard input (one line); remove takes it out of the store
  billing.py set <duty> <plan|api>  | set-seat <seat> <plan|api> | cap daily <usd|off> | cap duty <duty|*> <usd|off>
  billing.py doctor                 one line per duty: its billing, and whether the key is present (never the value)
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from integrations import common, keychain                             # noqa: E402

KEY_NAME = common.EXTRA_KEYS[0]
MODES = ("plan", "api")
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
ROOT = Path(__file__).resolve().parents[1]
GATE_STOP = 4


def _home_dir():
    return common.HOME


def config_path():
    return _home_dir() / "config" / "billing.json"


class ConfigError(ValueError):
    """The setting, a cap or the spend ledger cannot be read as written. A call billed to the key must not start on a guess (review r9 A2, A3)."""


def _const(c):
    raise ValueError(f"{c} is not a number")


def _modes(d, what, names=None):
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ConfigError(f"config/billing.json: \"{what}\" is not an object")
    for k, v in d.items():
        if not (isinstance(k, str) and SAFE_NAME.match(k)) or (names is not None and k not in names):
            raise ConfigError(f"config/billing.json: \"{what}\" names {k!r}, which is not a {what[:-1]} of this version")
        if v not in MODES:
            raise ConfigError(f"config/billing.json: {what} {k} is {v!r}; it must be plan or api (lower case)")
    return dict(d)


def load():
    """The settings, validated. No file is the default: everything on the plan, no caps. A file that cannot be read, is not JSON, or holds a value
    this version does not understand (a mode in capitals, a duty that does not exist, a cap that is not a number of dollars) raises ConfigError
    with the reason: it is never read as the default, which would turn a duty billed to the key into a plan call or drop its cap."""
    try:
        raw = json.loads(config_path().read_text(), parse_constant=_const)
    except FileNotFoundError:
        raw = {}
    except OSError:
        raise ConfigError("config/billing.json cannot be read")
    except ValueError:
        raise ConfigError("config/billing.json is not valid JSON")
    if not isinstance(raw, dict):
        raise ConfigError("config/billing.json is not an object")
    if raw.get("default", "plan") not in MODES:
        raise ConfigError(f"config/billing.json: default is {raw.get('default')!r}; it must be plan or api (lower case)")
    caps = raw.get("caps", {})
    if not isinstance(caps, dict):
        raise ConfigError("config/billing.json: \"caps\" is not an object")
    daily = caps.get("daily_usd")
    if "daily_usd" in caps and _usd(daily) is None:
        raise ConfigError(f"config/billing.json: caps daily_usd is {daily!r}; it must be a number of dollars below a million")
    dc = caps.get("duty_usd", {})
    if not isinstance(dc, dict):
        raise ConfigError("config/billing.json: caps duty_usd is not an object")
    names = set(duty_names())
    for k, v in dc.items():
        if k != "*" and k not in names:
            raise ConfigError(f"config/billing.json: caps duty_usd names {k!r}, which is not a duty of this version")
        if _usd(v) is None:
            raise ConfigError(f"config/billing.json: caps duty_usd {k} is {v!r}; it must be a number of dollars below a million")
    return {"default": raw.get("default", "plan"), "duties": _modes(raw.get("duties"), "duties", names), "seats": _modes(raw.get("seats"), "seats"),
            "caps": {"daily_usd": _usd(daily), "duty_usd": {k: _usd(v) for k, v in dc.items()}}}


def _usd(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return None
    return float(v) if 0 <= v < 1e6 else None


def save(cfg):
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {"default": cfg["default"], "duties": cfg["duties"], "seats": cfg["seats"],
           "caps": {k: v for k, v in (("daily_usd", cfg["caps"]["daily_usd"]), ("duty_usd", cfg["caps"]["duty_usd"])) if v not in (None, {})}}
    common.write_private(p, json.dumps(out, indent=2) + "\n")


def mode(duty, seat="", cfg=None):
    cfg = load() if cfg is None else cfg
    if seat and seat in cfg["seats"]:
        return cfg["seats"][seat]
    return cfg["duties"].get(duty, cfg["default"])


# ---- the key: in through stdin or the Settings page, out only through `key` -------------------------------------------------

def key_present():
    """Whether the key is stored. A store that cannot be read counts as not present."""
    try:
        if common.store_kind() == "keychain":
            return keychain.has(KEY_NAME)
        return bool(common.read_env_file().get(KEY_NAME)) if common.env_path().is_file() else False
    except (common.IntegrationError, keychain.KeychainError, OSError):
        return False


def get_key(strict=False):
    """The value, or None. Callers: the `key` command (for the harness) and the outgoing-text scan, which passes strict=True to hear that the
    store could not be read (review r9 A7) rather than that there is no key. Never logged."""
    try:
        if common.store_kind() == "keychain":
            return keychain.get(KEY_NAME) or None
        return (common.read_env_file().get(KEY_NAME) or None) if common.env_path().is_file() else None
    except (common.IntegrationError, keychain.KeychainError, OSError):
        if strict:
            raise
        return None


def set_key(value):
    """Store the key (an empty value removes it). Returns whether it is now present. The value is never returned, logged or echoed in an error."""
    from integrations import manifest                                # lazy: it imports common, which is all this module needs otherwise
    value = str(value or "").strip()
    if "\n" in value or "\r" in value or len(value) > 400:
        raise ValueError("an API key is one line of at most 400 characters")
    if value and not re.fullmatch(r"[A-Za-z0-9_\-]{20,400}", value):
        raise ValueError("that does not look like an Anthropic API key (letters, digits, - and _ only)")
    manifest._write(common.store_kind(), KEY_NAME, value)
    return bool(value)


# ---- caps, from the spend ledger ----------------------------------------------------------------------------------------------

def _since():
    m = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return m.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def api_rows(since=None):
    """The rows billed to the key since local midnight. Raises ConfigError when the ledger cannot be read, holds a complete line that is not a row, or
    a row billed to the key whose cost is not a number: none of that may read as no spend (review r9 A3). A last line with no newline is a row still
    being written and is left for the next reader."""
    since = _since() if since is None else since
    out = []
    try:
        fh = open(_home_dir() / "state" / "spend.jsonl", errors="replace")
    except FileNotFoundError:
        return out
    except OSError:
        raise ConfigError("the spend ledger (state/spend.jsonl) cannot be read, so the API spend caps cannot be checked")
    with fh:
        try:
            lines = fh.readlines()
        except OSError:
            raise ConfigError("the spend ledger (state/spend.jsonl) cannot be read, so the API spend caps cannot be checked")
    for n, line in enumerate(lines, 1):
        if not line.endswith("\n") or not line.strip():
            continue
        try:
            r = json.loads(line, parse_constant=_const)
        except ValueError:
            r = None
        if not isinstance(r, dict):
            raise ConfigError(f"the spend ledger (state/spend.jsonl) has a line that is not a row (line {n}), so the API spend caps cannot be checked")
        if r.get("billing") == "api" and str(r.get("at") or "") >= since:
            if _usd(r.get("cost")) is None:
                raise ConfigError(f"the spend ledger (state/spend.jsonl) has a row billed to the key whose cost is not a number (line {n})")
            out.append(r)
    return out


def _cost(r):
    return _usd(r.get("cost")) or 0.0


def gate(duty, cfg=None, rows=None):
    """(ok, reason, dollars_left). dollars_left is None when no cap applies. The reason is plain words, never a value of the key.
    Raises ConfigError when the setting or the ledger cannot be read."""
    cfg = load() if cfg is None else cfg
    daily = cfg["caps"]["daily_usd"]
    dc = cfg["caps"]["duty_usd"].get(duty, cfg["caps"]["duty_usd"].get("*"))
    if daily is None and dc is None:
        return True, "", None
    rows = api_rows() if rows is None else rows
    day = sum(_cost(r) for r in rows)
    mine = sum(_cost(r) for r in rows if r.get("duty") == duty)
    left = []
    if daily is not None:
        if day >= daily:
            return False, f"the daily API spend cap is reached: ${day:.2f} of ${daily:.2f} billed to the API key today", 0.0
        left.append(daily - day)
    if dc is not None:
        if mine >= dc:
            return False, f"the API spend cap of the {duty} duty is reached: ${mine:.2f} of ${dc:.2f} billed to the API key today", 0.0
        left.append(dc - mine)
    return True, "", min(left)


# ---- holds: what calls running now may still spend (review r9 A5) ---------------------------------------------------------------
# The ledger is booked when a call ends. A call billed to the key that starts while others run must see what they may still spend, or each is handed
# the whole of what is left. So `gate --hold ID` books a hold for the budget it hands out, under a lock, in state/billing-holds.jsonl, and the call's
# end (`settle ID`, after its ledger row is written) takes the hold out. A hold that is never settled (the duty was killed) counts until midnight.

def _holds_path():
    return _home_dir() / "state" / "billing-holds.jsonl"


def _lock():
    import fcntl
    p = _home_dir() / "state" / "billing.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _hold_lines():
    try:
        return _holds_path().read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return []
    except OSError:
        raise ConfigError("the API spend holds (state/billing-holds.jsonl) cannot be read, so the API spend caps cannot be checked")


def open_holds(lines=None, since=None):
    """The holds of today that no settle has taken out, as ledger-like rows {duty, cost, hold}."""
    since = _since() if since is None else since
    held, done = {}, set()
    for n, line in enumerate(_hold_lines() if lines is None else lines, 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line, parse_constant=_const)
        except ValueError:
            r = None
        if isinstance(r, dict) and isinstance(r.get("settle"), str):
            done.add(r["settle"])
        elif isinstance(r, dict) and isinstance(r.get("hold"), str) and _usd(r.get("cost")) is not None:
            held[r["hold"]] = r
        else:
            raise ConfigError(f"the API spend holds (state/billing-holds.jsonl) have a line that cannot be read (line {n})")
    return [r for k, r in held.items() if k not in done and str(r.get("at") or "") >= since]


def _write_holds(lines):
    common.write_private(_holds_path(), "".join(line + "\n" for line in lines))


def _has_cap(cfg, duty):
    return cfg["caps"]["daily_usd"] is not None or cfg["caps"]["duty_usd"].get(duty, cfg["caps"]["duty_usd"].get("*")) is not None


def gate_hold(duty, hold="", budget=None):
    """gate() with the open holds counted, and when it passes and a cap applies, a hold booked for what this call may spend: min(left, budget).
    Returns (ok, reason, amount); amount None when no cap applies (nothing is held, nothing needs to be)."""
    fd = _lock()
    try:
        cfg = load()
        if not _has_cap(cfg, duty):
            return True, "", None
        lines = _hold_lines()
        ok, why, left = gate(duty, cfg=cfg, rows=api_rows() + open_holds(lines))
        if not ok:
            return ok, why, None
        amount = left if budget is None else min(left, budget)
        if hold:
            keep = lines if len(lines) < 200 else [json.dumps(r) for r in open_holds(lines)]
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_holds(keep + [json.dumps({"hold": hold, "at": now, "duty": duty, "cost": round(amount, 4)})])
        return True, "", amount
    finally:
        os.close(fd)


def settle(hold):
    fd = _lock()
    try:
        lines = _hold_lines()
        if any(json.dumps(hold) in line for line in lines):
            _write_holds(lines + [json.dumps({"settle": hold})])
    finally:
        os.close(fd)


# ---- what the owner sees: names, modes, presence, figures; never the key ---------------------------------------------------

def duty_names():
    return sorted(p.stem for p in (ROOT / "duties").glob("*.sh") if not p.name.startswith("_"))


def summary():
    try:
        cfg, problem = load(), ""
    except ConfigError as e:
        cfg, problem = {"default": "plan", "duties": {}, "seats": {}, "caps": {"daily_usd": None, "duty_usd": {}}}, str(e)
    try:
        rows = api_rows()
    except ConfigError as e:
        rows, problem = [], problem or str(e)
    return {"problem": problem, "key_present": key_present(), "key_store": common.store_kind(), "default": cfg["default"],
            "duties": [{"duty": d, "billing": "stopped" if problem else mode(d, cfg=cfg)} for d in duty_names()],
            "seats": [{"seat": s, "billing": m} for s, m in sorted(cfg["seats"].items())],
            "caps": cfg["caps"], "api_spent_today": round(sum(_cost(r) for r in rows), 4)}


def doctor_lines():
    s = summary()
    store = "the macOS Keychain" if s["key_store"] == "keychain" else "the private file"
    api = [d["duty"] for d in s["duties"] if d["billing"] == "api"] + [f"seat {x['seat']}" for x in s["seats"] if x["billing"] == "api"]
    if s["problem"]:
        return [("no", "billing", s["problem"] + "; every call of the claude provider stops with NEEDS_HUMAN until it is fixed")]
    lines = [("ok" if s["key_present"] or not api else "no", "API key",
              (f"present (in {store})" if s["key_present"] else "not stored") + ("" if api else "; every duty is billed to your plan"))]
    for d in s["duties"]:
        lines.append(("ok" if d["billing"] == "plan" or s["key_present"] else "no", f"billing: {d['duty']}",
                      "your plan (the claude sign-in)" if d["billing"] == "plan" else "API key" + ("" if s["key_present"] else ": NO KEY STORED, it will stop with NEEDS_HUMAN")))
    for x in s["seats"]:
        lines.append(("ok" if x["billing"] == "plan" or s["key_present"] else "no", f"billing: seat {x['seat']}", "your plan" if x["billing"] == "plan" else "API key"))
    c = s["caps"]
    if api:
        lines.append(("ok", "API spend caps", f"daily {('$%.2f' % c['daily_usd']) if c['daily_usd'] is not None else 'none'}; per duty "
                      + (", ".join(f"{k} ${v:.2f}" for k, v in sorted(c["duty_usd"].items())) or "none") + f"; billed to the key today ${s['api_spent_today']:.2f}"))
    return lines


# ---- command line ---------------------------------------------------------------------------------------------------------------

def _amount(v):
    if v == "off":
        return None
    if not re.fullmatch(r"\d{1,6}(\.\d{1,2})?", v or ""):
        raise ValueError("a cap is dollars (like 5 or 2.50), or off")
    return float(v)


def main(argv):
    cmd = argv[0] if argv else ""
    try:
        if cmd == "mode" and len(argv) in (2, 3):
            try:
                print(mode(argv[1], argv[2] if len(argv) == 3 else ""))
            except ConfigError as e:                                  # on stdout: claude_run puts it in the NEEDS_HUMAN row
                print(e)
                return 3
            return 0
        if cmd == "gate" and len(argv) in (2, 4, 6):
            opts = dict(zip(argv[2::2], argv[3::2]))
            if set(opts) - {"--hold", "--budget"} or not re.fullmatch(r"[A-Za-z0-9._-]{0,120}", opts.get("--hold", "")) \
                    or not re.fullmatch(r"(\d{1,6}(\.\d{1,6})?)?", opts.get("--budget", "")):
                print("billing: gate <duty> [--hold ID] [--budget USD]")
                return 2
            try:
                b = opts.get("--budget")
                ok, why, left = gate_hold(argv[1], opts.get("--hold", ""), float(b) if b else None)
            except ConfigError as e:
                print(e)
                return 3
            print(why if not ok else ("" if left is None else f"{left:.4f}"))
            return 0 if ok else GATE_STOP
        if cmd == "settle" and len(argv) == 2:
            try:
                settle(argv[1])
            except (ConfigError, OSError) as e:
                print(e)
                return 3
            return 0
        if cmd == "has-key" and len(argv) == 1:                      # whether a key is stored: the exit status only, never the value
            return 0 if key_present() else 1
        if cmd == "key" and len(argv) == 1:
            if sys.stdout.isatty():
                print("billing: the key is only handed to the harness, never shown on a terminal", file=sys.stderr)
                return 2
            k = get_key()
            if not k:
                return 1
            sys.stdout.write(k)
            return 0
        if cmd in ("set-key", "remove-key") and len(argv) == 1:
            if cmd == "remove-key":
                set_key("")
                print("the API key is removed")
                return 0
            if sys.stdin.isatty():
                print("billing: paste the key and press Enter, then Ctrl-D", file=sys.stderr)
            v = sys.stdin.readline().strip()
            if not v:
                print("billing: nothing was given on standard input; nothing changed", file=sys.stderr)
                return 2
            set_key(v)
            print("the API key is stored (it is not shown again)")
            return 0
        if cmd in ("set", "set-seat") and len(argv) == 3 and argv[2] in MODES and SAFE_NAME.match(argv[1]):
            cfg = load()
            if cmd == "set" and argv[1] not in duty_names():
                raise ValueError(f"no duty called {argv[1]}")
            cfg["duties" if cmd == "set" else "seats"][argv[1]] = argv[2]
            save(cfg)
            print(f"{argv[1]}: billed to {'the API key' if argv[2] == 'api' else 'your plan'}")
            return 0
        if cmd == "cap" and ((len(argv) == 3 and argv[1] == "daily") or (len(argv) == 4 and argv[1] == "duty" and (argv[2] == "*" or SAFE_NAME.match(argv[2])))):
            v = _amount(argv[-1])
            if argv[1] == "duty" and v is not None and argv[2] != "*" and argv[2] not in duty_names():
                raise ValueError(f"no duty called {argv[2]}")
            try:
                cfg = load()
            except ConfigError:
                if not (argv[1] == "duty" and v is None):
                    raise
                cfg = None   # removing a duty cap must work even when the file names a duty this version does not have
            if cfg is None:
                try:
                    raw = json.loads(config_path().read_text())
                    raw["caps"]["duty_usd"].pop(argv[2])
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    raise ConfigError(f"config/billing.json cannot be repaired here; there is no cap for {argv[2]} to remove")
                common.write_private(config_path(), json.dumps(raw, indent=2) + "\n")
            else:
                if argv[1] == "daily":
                    cfg["caps"]["daily_usd"] = v
                elif v is None:
                    cfg["caps"]["duty_usd"].pop(argv[2], None)
                else:
                    cfg["caps"]["duty_usd"][argv[2]] = v
                save(cfg)
            print("cap " + ("removed" if v is None else f"set to ${v:.2f} a " + ("day" if argv[1] == "daily" else "day for " + argv[2])))
            return 0
        if cmd == "doctor" and len(argv) == 1:
            for ok, label, detail in doctor_lines():
                print(f"{ok}\t{label}\t{detail}")
            return 0
    except ValueError as e:
        print(f"billing: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print("billing: " + common.why_not_saved(e), file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
