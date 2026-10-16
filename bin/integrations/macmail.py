"""Mac Mail, on this Mac: how many messages are unread in the inbox and how long the oldest has waited.

It asks the Mail app through AppleScript (osascript). The script reads the unread count, and the date each unread message arrived.
It never asks for a sender, a subject or a body. The first time it runs, macOS asks whether this is allowed to control Mail
(System Settings, Privacy and Security, Automation). No credential is stored and nothing leaves this Mac.
"""
import shutil
import subprocess

from integrations import common

SNAPSHOTS = ("macmail",)
OSASCRIPT = "osascript"
TIMEOUT = 40
SCRIPT = '''tell application "Mail"
  set u to unread count of inbox
  if u is 0 then return "0|0"
  set ds to date received of (messages of inbox whose read status is false)
  set oldest to item 1 of ds
  repeat with d in ds
    if d < oldest then set oldest to d
  end repeat
  return (u as string) & "|" & (((current date) - oldest) as integer as string)
end tell'''


def _ask():
    """The raw text the script printed. Raises IntegrationError with a short sentence for every way it can fail."""
    exe = shutil.which(OSASCRIPT)
    if not exe:
        raise common.IntegrationError("osascript was not found: Mac Mail only works on a Mac")
    try:
        r = subprocess.run([exe, "-e", SCRIPT], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise common.IntegrationError("Mail did not answer in time: open Mail once and try again")
    except OSError:
        raise common.IntegrationError("osascript could not be started")
    if r.returncode != 0:
        err = r.stderr or ""
        if "-1743" in err or "not authorized" in err.lower() or "not allowed" in err.lower():
            raise common.IntegrationError("macOS has not allowed this: turn on Mail for this app in System Settings, Privacy and Security, Automation")
        if "-1728" in err or "-1719" in err or "can't get" in err.lower() or "can’t get" in err.lower():
            raise common.IntegrationError("Mail has no inbox to read: open Mail and add an account first")
        if "-600" in err or "-10810" in err or "isn't running" in err.lower():
            raise common.IntegrationError("Mail could not be opened: open it once by hand and try again")
        raise common.IntegrationError("Mail did not answer: see the README")
    return r.stdout


def parse(text):
    """(unread, oldest age in seconds) from 'count|seconds', or None when the text is not that."""
    try:
        a, b = str(text).strip().split("|")
        n, secs = int(a), int(b)
    except ValueError:
        return None
    return (n, secs) if n >= 0 and secs >= 0 else None


def age_words(secs):
    if secs < 3600:
        return "less than an hour"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''}"
    d = secs // 86400
    return f"{d} day{'s' if d != 1 else ''}"


def fetch(env, cfg):
    got = parse(_ask())
    if got is None:
        raise common.IntegrationError("Mail answered with something unexpected: see the README")
    n, secs = got
    if n == 0:
        return {"macmail": {"items": [], "unread": 0}}
    item = common.make_item(f"{common.fmt_int(n)} unread in Mail", f"The oldest has waited {age_words(secs)}.", "", True)
    return {"macmail": {"items": [item], "unread": n}}
