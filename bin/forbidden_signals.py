#!/usr/bin/env python3
"""The owner's hard privacy limit, enforced. Quarterdeck must NEVER collect: keystrokes, screenshots or screen contents,
which apps or websites he uses, the clipboard, his location, or any file outside his registered projects and its own
state/ folder (the few approved exceptions are listed in docs/cloud-tasks/README.md and are timestamps/metadata only).
This scans code and docs folders, selftests included, for the APIs that would do those things and fails if it finds one. It puts split and
concatenated string pieces back together first. It is a net for mistakes and casual hiding, not proof: the run-time sandbox is the enforcement.

    python3 bin/forbidden_signals.py [root]      # exit 1 and a list of hits if anything crosses the line
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = {".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx", ".swift", ".sh", ".bash", ".zsh", ".html"}   # and any extensionless file that starts with a #! line
SKIP_DIRS = {".claude", "vendor", "state", "logs", "workspace"}        # only at the root (audit 7, L5: bin/state/ and bin/vendor/ were skipped too)
SKIP_ANY = {"node_modules", ".git", "__pycache__"}                     # at any depth: other people's code, git's own store, compiled files
SKIP_FILES = {"forbidden_signals.py"}          # this file names the patterns on purpose
# The only exemptions: exact strings, in one named file each, that must exist because they DENY or TEST these things. Everything else in those files,
# selftests included, is scanned. An entry whose string is no longer in its file is reported, so the list cannot quietly outlive its reason.
ALLOW = {
    "bin/lib.sh": [
        'pb""copy pb""paste',                                                         # the sandbox profile denies running the clipboard programs
        ".bash_history .zsh_history",                                                # the sandbox denies reading shell history
        'Library/Cookies|Library/Sa"fari"|Library/Messages|Library/Mail|Library/Group Containers|Library/Containers|Library/Mobile Documents|Library/Accounts|Library/Calendars|Library/Reminders|Library/HomeKit',
    ],
    "bin/selftest-security.sh": [
        "and pbpaste is not started",
        '! s5 "$T/s5c.sb" pbpaste >',
        '! s5 "$T/s5i.sb" pbpaste >',
        '"$S5F/.zsh_history"', ".env .zsh_history .npmrc", ".env .zsh_history; do",   # decoys the sandbox must refuse to read
    ],
    "bin/selftest.py": [
        '"pynput", "pyautogui", "pbpaste", "screencapture", "CGEvent", "NSWorkspace", "CoreLocation"',
        "pbpaste|screencapture|NSWorkspace|geolocation",
        """'subprocess.run(["screen" "capture", "-x"])'""",
        """'subprocess.run(["pb" + "paste"])'""",
        """'cmd = ("screen"\\n       "capture")'""",
        """'navigator["clip"+"board"]["read"+"Text"]()'""",
        """'subprocess.run(["screencapture", "-x"])'""",
        """'tool = "".join(["pb", "paste"])'""",
        """'tool = "etsapbp"[::-1]'""",
        """'open(os.path.expanduser("~/Library/Messages/chat.db"))'""",
        '_fbad = "x = pb" + "paste\\n"',                                           # the B1b sample file body, written to a temp folder
    ],
}
RULES = {
    "keystrokes": r"CGEventTap|CGEventSource|IOHIDManager|pynput|NSEvent\s*\.\s*addGlobalMonitor|addGlobalMonitorForEvents|keyboard\.Listener|"
                  r"key[_ ]?logger|keylog|getKeyState|GetAsyncKeyState",
    "screen": r"screencapture|CGWindowListCreateImage|CGDisplayCreateImage|ScreenCaptureKit|SCStream|getDisplayMedia|pyautogui\.screenshot|"
              r"ImageGrab|take_screenshot|captureVisibleTab|screenshot_capture",
    "apps and websites": r"frontmostApplication|NSWorkspace|lsappinfo|activeApplication|get\s+frontmost|System Events[^\n]*process|"
                         r"History\.db|places\.sqlite|Library/Safari|Application Support/(?:Google/Chrome|Firefox|BraveSoftware|Arc)|"
                         r"BrowserHistory|chrome://history|browsingData|chrome\.history|webNavigation|tabs\.query",
    "clipboard": r"pbpaste|pbcopy|NSPasteboard|UIPasteboard|clipboard\.read|navigator\.clipboard\.read|readText\s*\(|"
                 r"clipboardData\.getData|ClipboardEvent",
    "location": r"CoreLocation|CLLocationManager|navigator\.geolocation|ipinfo\.io|ip-api\.com|geoip|geolocation",
    # The other half of the promise: no file outside the registered projects and state/. Most of that is the sandbox's job at run time; this catches
    # code that names another app's personal data store outright.
    "files outside projects": r"chat\.db|knowledgeC\.db|NoteStore\.sqlite|AddressBook|Photos Library|(?:zsh|bash)_history|"
                              r"Library/(?:Messages|Mail|Calendars|Reminders|Accounts|Cookies|Containers|Group Containers|Mobile Documents|HomeKit)",
}
COMPILED = {k: re.compile(v, re.I) for k, v in RULES.items()}
# Names that are flagged when they appear only once a file's string pieces are put together ("pb" + x + "paste", "".join([...]), "...".reverse).
BUILT = re.compile(r"screencapture|pbpaste|pbcopy|cgeventtap|nspasteboard|keylog|frontmostapplication|nsworkspace|lsappinfo|cllocationmanager|"
                   r"corelocation|getdisplaymedia|capturevisibletab|cgwindowlistcreateimage|cgdisplaycreateimage|clipboardread|geolocation|chatdb")
_JOIN = re.compile(r"""["']\s*(?:\+|\\)?\s*["']""")        # "a" "b", "a" + "b", "a"\n"b", pb""copy: the quotes between two pieces go
_BRACKET = re.compile(r"""\[\s*["']?(\w+)["']?\s*\]""")      # x["clipboard"] reads as x.clipboard
_LIT = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')


def normalise(text):
    """The text with string pieces put back together, so a name split across literals or lines still reads as itself."""
    out, pending, pos = [], 0, 0
    for m in list(_JOIN.finditer(text)) + [None]:
        chunk = text[pos:m.start() if m else len(text)]
        if pending and "\n" in chunk:                   # a join that swallowed line breaks gives them back at the next one, so line numbers hold
            i = chunk.index("\n"); chunk, pending = chunk[:i] + "\n" * pending + chunk[i:], 0
        out.append(chunk)
        if m:
            pending += m.group(0).count("\n"); pos = m.end()
    text = "".join(out) + "\n" * pending
    return _BRACKET.sub(r".\1", text).replace('"', "").replace("'", "")


def _is_script(p):
    """An extensionless file is code when it starts with a #! line (a symbolic link is not followed)."""
    try:
        if p.is_symlink():
            return False
        with open(p, "rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def scan(root=ROOT):
    # ponytail: a net for honest mistakes and casual hiding, not proof; hex, base64 or chr() spelling still gets through. The sandbox is the enforcement.
    root = Path(root)
    hits = []
    for p in sorted(root.rglob("*")):
        if (p.suffix and p.suffix not in CODE) or not p.is_file() or p.name in SKIP_FILES:
            continue
        rel = p.relative_to(root)
        if rel.parts[0] in SKIP_DIRS or any(part in SKIP_ANY for part in rel.parts[:-1]):
            continue
        if not p.suffix and not _is_script(p):
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for allowed in ALLOW.get(rel.as_posix(), []):
            if allowed not in text:
                hits.append(("allow-list", str(rel), 0, f"stale entry, no longer in the file: {allowed[:80]}"))
            text = text.replace(allowed, "")
        for n, line in enumerate(normalise(text).splitlines(), 1):
            for kind, rx in COMPILED.items():
                if rx.search(line):
                    hits.append((kind, str(rel), n, line.strip()[:110]))
        pieces = "".join(re.sub(r"[^a-z]", "", (a or b).lower()) for a, b in _LIT.findall(text))
        for name in sorted(set(BUILT.findall(pieces) + BUILT.findall(pieces[::-1]))):
            hits.append(("built at run time", str(rel), 0, f"string pieces in this file spell {name}"))
    return hits


if __name__ == "__main__":
    found = scan(sys.argv[1] if len(sys.argv) > 1 else ROOT)
    for kind, f, n, line in found:
        print(f"  CROSSES THE LINE  [{kind}] {f}:{n}  {line}")
    print(f"{len(found)} hit(s)" if found else "  ok    none of: keystrokes, screen, apps and websites, clipboard, location, files outside projects")
    sys.exit(1 if found else 0)
