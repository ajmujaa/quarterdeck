#!/usr/bin/env python3
"""The fake provider's program (see providers/fake.sh). Records what it was given, answers from a script, never touches the network."""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
for a in ("workdir", "tools", "allow", "deny", "model", "effort", "budget", "sources", "settings", "record", "script", "replies", "cost", "hook"):
    ap.add_argument("--" + a, default="")
o = ap.parse_args()
prompt = sys.stdin.read()


def pick():
    """The reply for this prompt: the first entry whose match is found in it."""
    if o.script:
        s = json.load(open(o.script))
        for r in (s if isinstance(s, list) else [s]):
            if "match" not in r or re.search(r["match"], prompt):
                return r
        return {"output": "empty", "exit": 1}
    names = sorted(n for n in os.listdir(o.replies) if n.endswith(".match")) if os.path.isdir(o.replies) else []
    for n in names:
        if re.search(open(os.path.join(o.replies, n)).read(), prompt):
            return {"text": open(os.path.join(o.replies, n[:-6] + ".reply")).read(), "cost_usd": float(o.cost)}
    d = os.path.join(o.replies, "default.reply")
    return {"text": open(d).read() if os.path.exists(d) else "", "cost_usd": float(o.cost)}


settings, smode = "", ""
if o.settings:
    try:
        settings, smode = open(o.settings).read(), oct(os.stat(o.settings).st_mode & 0o777)
    except OSError as e:
        settings = "unreadable: %s" % e
rec = {"provider": "fake", "argv": sys.argv[1:], "prompt": prompt, "stdin": True,
       "prompt_in_argv": bool(prompt) and any(prompt in a for a in sys.argv[1:]),
       "tools": o.tools, "allow": o.allow, "deny": o.deny, "workdir": o.workdir, "cwd": os.getcwd(), "model": o.model, "effort": o.effort,
       "budget": o.budget, "sources": o.sources, "settings": settings, "settings_path": o.settings, "smode": smode, "env": sorted(os.environ)}
with open(o.record, "a") as f:
    fcntl.flock(f, fcntl.LOCK_EX)     # panel seats call at the same time
    f.write(json.dumps(rec) + "\n")
if o.hook and os.access(o.hook, os.X_OK):
    subprocess.run([o.hook, prompt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

r = pick()
if r.get("sleep"):
    time.sleep(float(r["sleep"]))
out = r.get("output", "json")
if out == "malformed":
    sys.stdout.write("not a reply {")
elif out != "empty":
    stop = r.get("stop")
    sys.stdout.write(json.dumps({"provider": "fake", "text": r.get("text", ""), "cost_usd": r.get("cost_usd", 0), "cost_known": r.get("cost_known", True),
                                 "input_tokens": r.get("input_tokens", 0), "output_tokens": r.get("output_tokens", 0), "turns": r.get("turns", 1),
                                 "model": r.get("model", "fake-model"), "error": stop == "error", "stop": stop}))
sys.exit(int(r.get("exit", 0)))
