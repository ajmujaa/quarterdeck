#!/usr/bin/env python3
"""The owner's hard privacy limit, enforced. Quarterdeck must NEVER collect: keystrokes, screenshots or screen contents,
which apps or websites he uses, the clipboard, his location, or any file outside his registered projects and its own
state/ folder (the few approved exceptions are listed in docs/cloud-tasks/README.md and are timestamps/metadata only).
This scans code (not docs or tests) for the APIs that would do those things and fails if it finds one.

    python3 bin/forbidden_signals.py [root]      # exit 1 and a list of hits if anything crosses the line
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = {".py", ".js", ".mjs", ".swift", ".sh", ".html"}
SKIP_DIRS = {"vendor", "node_modules", ".git", "docs", "state", "logs", "workspace", "__pycache__"}
SKIP_FILES = {"forbidden_signals.py"}          # this file names the patterns on purpose
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
}
COMPILED = {k: re.compile(v, re.I) for k, v in RULES.items()}


def scan(root=ROOT):
    root = Path(root)
    hits = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in CODE or not p.is_file() or p.name in SKIP_FILES or p.name.startswith("selftest"):
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.parts[:1] == ("tools",) and "agenda" not in rel.parts and False:
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for kind, rx in COMPILED.items():
                if rx.search(line):
                    hits.append((kind, str(rel), n, line.strip()[:110]))
    return hits


if __name__ == "__main__":
    found = scan(sys.argv[1] if len(sys.argv) > 1 else ROOT)
    for kind, f, n, line in found:
        print(f"  CROSSES THE LINE  [{kind}] {f}:{n}  {line}")
    print(f"{len(found)} hit(s)" if found else "  ok    none of: keystrokes, screen, apps and websites, clipboard, location")
    sys.exit(1 if found else 0)
