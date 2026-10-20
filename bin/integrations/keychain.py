"""The macOS Keychain as an optional place for credentials (the private 0600 file stays the default).

Runs /usr/bin/security. A secret is never a process argument (argv is visible to every process of the user):
it goes in on stdin, hex-encoded, to `security -i`, and comes out on stdout. Reading, presence checks and
deletes carry no secret in their arguments. Nothing here prints, logs or returns a value except get(),
whose caller is the feed that needs it. Linux and any Mac without the binary: available() is False.
"""
import binascii
import os
import re
import subprocess
import sys

SECURITY = "/usr/bin/security"          # tests point this at a stub; the real keychain is never touched by a test
SERVICE = "quarterdeck.integrations"
PLATFORM = sys.platform                  # tests set it to "linux" to see the clean "not available"
NOT_FOUND = 44                           # `security` exit code for "item could not be found"


class KeychainError(OSError):
    """Short and secret-free: what failed, never a value."""


def available():
    return PLATFORM == "darwin" and os.access(SECURITY, os.X_OK)


def _run(args, stdin=None):
    if not available():
        raise KeychainError("the macOS Keychain is not available on this computer")
    try:
        return subprocess.run([SECURITY, *args], input=stdin, capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        raise KeychainError("the keychain did not answer (is it locked?)")


def has(key):
    r = _run(["find-generic-password", "-s", SERVICE, "-a", key])          # no -w: attributes only, no secret
    if r.returncode not in (0, NOT_FOUND):
        raise KeychainError("the keychain could not be read")
    return r.returncode == 0


def get(key):
    r = _run(["find-generic-password", "-s", SERVICE, "-a", key, "-w"])
    if r.returncode == NOT_FOUND:
        return None
    if r.returncode != 0:
        raise KeychainError("the keychain could not be read")
    return r.stdout.rstrip("\n")


MAX_LINE = 4000                          # `security -i` reads about 4,094 bytes a line and runs the rest as a new command
MAX_CHARS = 1950                         # what that leaves for a value, said in plain words


SAFE_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,100}$")      # KEY or KEY@label: one word, so the account name can never end the line or add a command


def _line(key, value):
    if not SAFE_NAME.match(key):
        raise KeychainError("that credential name is not one the keychain takes")
    return f"add-generic-password -U -s {SERVICE} -a {key} -X {binascii.hexlify(value.encode()).decode()}\n"


def fits(key, value):
    """Whether `security -i` can take this value whole. A longer line would be cut short and the item replaced with the cut value."""
    return len(_line(key, value).encode()) <= MAX_LINE


def put(key, value):
    """Add or replace one item. The value reaches `security` as hex on its stdin, never as an argument; read back to be sure."""
    if not fits(key, value):
        raise KeychainError(f"the keychain takes at most about {MAX_CHARS:,} characters per credential; this one is longer, so it was not stored")
    _run(["-i"], stdin=_line(key, value))
    if get(key) != value:
        raise KeychainError("the keychain did not keep the value")


def delete(key):
    r = _run(["delete-generic-password", "-s", SERVICE, "-a", key])
    if r.returncode not in (0, NOT_FOUND):
        raise KeychainError("the keychain could not remove it")
