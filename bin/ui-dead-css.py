#!/usr/bin/env python3
"""List the classes ui.css defines that no markup uses. Usage: ui-dead-css.py [dashboard dir]. Exit 1 if any are dead.
A class is used when its name is a token of a class attribute, a cls/kcls/tone argument, a classList or className call, or
the class argument of a DOM helper, anywhere in index.html or assets/*.js. Names built by concatenation (tone-, c-, a stance's
own word) are matched by their prefix; Shoelace's own toast stack class is set by the library."""
import re, sys, pathlib

d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dashboard")
css = re.sub(r"/\*.*?\*/", "", (d / "assets/ui.css").read_text(), flags=re.S)
css = re.sub(r"@font-face\{[^}]*\}", "", css)
sel_text = " ".join(m for m in re.findall(r"([^{}]+)\{", css) if not m.strip().startswith("@"))
sel_text = re.sub(r"\[[^\]]*\]", "", sel_text)
sel_text = re.sub(r'"[^"]*"', "", sel_text)
classes = set(re.findall(r"\.([A-Za-z_][\w-]*)", sel_text))
src = (d / "index.html").read_text() + "\n".join(p.read_text() for p in sorted((d / "assets").glob("*.js")))
used = set()
def take(text):
    for e in re.findall(r"\$\{([^}]*)\}", text): used.update(w for q in re.findall(r"""["']([^"']*)["']""", e) for w in re.findall(r"[A-Za-z_][\w-]*", q))
    text = re.sub(r"\$\{[^}]*\}", " ", text)
    used.update(re.findall(r"[A-Za-z_][\w-]*", text))
for m in re.finditer(r"""class=\\?["']((?:\$\{[^}]*\}|[^"'])*)["']""", src): take(m.group(1))
for m in re.finditer(r"""\b(?:cls|kcls|className|tone)\s*[:=]\s*(?:\w+\s*\?\s*)?["'`]([^"'`]*)""", src): take(m.group(1))
for m in re.finditer(r"classList\.(?:add|remove|toggle|contains)\(([^)]*)\)", src): take(m.group(1))
for m in re.finditer(r"""\bel\(\s*["']\w+["']\s*,\s*["']([^"']*)["']""", src): take(m.group(1))
for m in re.finditer(r"""\b(?:querySelector(?:All)?|closest|matches)\(\s*["'`]([^"'`]*)""", src): take(m.group(1).replace(".", " "))
for m in re.finditer(r"""(?:"|\b)(tone-|c-|dot |pill |sev|stance |rowcard |node |callout |chip )[\w${}\-. ]*""", src): take(m.group(0))
# tone-<state>, c-<class>, <state> words and a stance's own word are built by concatenation
dyn = ("tone-", "c-")
KEEP = {"good", "dead", "stale", "skipped", "nothing", "dismissed", "you", "off", "sl-toast-stack", "agree", "dispute", "extend", "sev2", "sev3"}
dead = sorted(c for c in classes if c not in used and c not in KEEP and not c.startswith(dyn))
dead += sorted(c for c in classes if c.startswith(dyn) and not re.search(re.escape(c.split("-")[0] + "-"), src))
print("\n".join(dead) if dead else "no dead classes")
sys.exit(1 if dead else 0)
