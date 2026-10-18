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
  billing.py gate <duty>            exit 0 and the dollars left under the caps (empty: no cap); exit 4 and the reason when a cap is reached
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


def load():
    """The settings, validated. A missing or broken file is the default: everything on the plan, no caps. Never raises."""
    try:
        raw = json.loads(config_path().read_text())
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    pick = lambda d: {k: v for k, v in (d if isinstance(d, dict) else {}).items() if isinstance(k, str) and SAFE_NAME.match(k) and v in MODES}
    caps = raw.get("caps") if isinstance(raw.get("caps"), dict) else {}
    duty_caps = {k: float(v) for k, v in (caps.get("duty_usd") if isinstance(caps.get("duty_usd"), dict) else {}).items()
                 if (k == "*" or (isinstance(k, str) and SAFE_NAME.match(k))) and _usd(v) is not None}
    return {"default": raw.get("default") if raw.get("default") in MODES else "plan", "duties": pick(raw.get("duties")), "seats": pick(raw.get("seats")),
            "caps": {"daily_usd": _usd(caps.get("daily_usd")), "duty_usd": duty_caps}}


def _usd(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
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


def get_key():
    """The value, or None. Callers: the `key` command (for the harness) and the outgoing-text scan. Never logged."""
    try:
        if common.store_kind() == "keychain":
            return keychain.get(KEY_NAME) or None
        return (common.read_env_file().get(KEY_NAME) or None) if common.env_path().is_file() else None
    except (common.IntegrationError, keychain.KeychainError, OSError):
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
    since = _since() if since is None else since
    out = []
    try:
        with open(_home_dir() / "state" / "spend.jsonl", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("billing") == "api" and str(r.get("at") or "") >= since:
                    out.append(r)
    except OSError:
        pass
    return out


def _cost(r):
    try:
        return max(0.0, float(r.get("cost") or 0))
    except (TypeError, ValueError):
        return 0.0


def gate(duty, cfg=None, rows=None):
    """(ok, reason, dollars_left). dollars_left is None when no cap applies. The reason is plain words, never a value of the key."""
    cfg = load() if cfg is None else cfg
    rows = api_rows() if rows is None else rows
    day = sum(_cost(r) for r in rows)
    mine = sum(_cost(r) for r in rows if r.get("duty") == duty)
    left = []
    daily = cfg["caps"]["daily_usd"]
    if daily is not None:
        if day >= daily:
            return False, f"the daily API spend cap is reached: ${day:.2f} of ${daily:.2f} billed to the API key today", 0.0
        left.append(daily - day)
    dc = cfg["caps"]["duty_usd"].get(duty, cfg["caps"]["duty_usd"].get("*"))
    if dc is not None:
        if mine >= dc:
            return False, f"the API spend cap of the {duty} duty is reached: ${mine:.2f} of ${dc:.2f} billed to the API key today", 0.0
        left.append(dc - mine)
    return True, "", (min(left) if left else None)


# ---- what the owner sees: names, modes, presence, figures; never the key ---------------------------------------------------

def duty_names():
    return sorted(p.stem for p in (ROOT / "duties").glob("*.sh") if not p.name.startswith("_"))


def summary():
    cfg = load()
    rows = api_rows()
    return {"key_present": key_present(), "key_store": common.store_kind(), "default": cfg["default"],
            "duties": [{"duty": d, "billing": mode(d, cfg=cfg)} for d in duty_names()],
            "seats": [{"seat": s, "billing": m} for s, m in sorted(cfg["seats"].items())],
            "caps": cfg["caps"], "api_spent_today": round(sum(_cost(r) for r in rows), 4)}


def doctor_lines():
    s = summary()
    store = "the macOS Keychain" if s["key_store"] == "keychain" else "the private file"
    api = [d["duty"] for d in s["duties"] if d["billing"] == "api"] + [f"seat {x['seat']}" for x in s["seats"] if x["billing"] == "api"]
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
            print(mode(argv[1], argv[2] if len(argv) == 3 else ""))
            return 0
        if cmd == "gate" and len(argv) == 2:
            ok, why, left = gate(argv[1])
            print(why if not ok else ("" if left is None else f"{left:.4f}"))
            return 0 if ok else GATE_STOP
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
            cfg = load()
            v = _amount(argv[-1])
            if argv[1] == "daily":
                cfg["caps"]["daily_usd"] = v
            elif v is None:
                cfg["caps"]["duty_usd"].pop(argv[2], None)
            else:
                cfg["caps"]["duty_usd"][argv[2]] = v
            save(cfg)
            print("cap " + ("removed" if v is None else f"set to ${v:.2f} a day"))
            return 0
        if cmd == "doctor" and len(argv) == 1:
            for ok, label, detail in doctor_lines():
                print(f"{ok}\t{label}\t{detail}")
            return 0
    except ValueError as e:
        print(f"billing: {e}", file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
