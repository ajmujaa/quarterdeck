#!/usr/bin/env python3
"""projagents: the agents a registered project defines for itself (.claude/agents/*.md), and which Quarterdeck jobs they plausibly cover.

Read-only. Only the front matter fields name, description, tools and model are read; the prompt body is never returned.
Everything in a file is untrusted text: lengths are capped, control characters and angle brackets are dropped, YAML tags, anchors and aliases
are not interpreted. The folders are never followed through a link. A file that is a link is read only when its real target is a regular .md file inside the same project
(and not under .git); any other link is ignored. At most 50 files of 64 KB each. Standard library only.
"""
import fcntl
import os
import re
import stat
import time

MAX_FILES, MAX_READ = 50, 64 * 1024
CAP = {"name": 60, "description": 240, "model": 40, "tool": 40}
MAX_TOOLS = 12

# One place for the suggestion table. Job ids are those of dashboard/assets/crew.js (selftest keeps them equal). A match is a suggestion only.
JOB_WORDS = {
    "review": ("review", "audit", "critic", "inspect", "lint"),
    "build": ("implement", "build", "mason", "draft", "develop", "engineer"),
    "plan": ("plan", "architect", "spec", "roadmap"),
    "check": ("test", "verify", "check", "qa", "quality"),
    "infra": ("deploy", "infra", "ferry", "terraform", "devops"),
    "design": ("design", "ui", "ux", "mockup", "mock-up"),
}

_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿<>]")
_BLOCK = re.compile(r"^[|>][+-]?\d*$")
_TTL, _cache = 20, {}


def _clean(v, n):
    v = str(v).strip()
    v = re.sub(r"^(?:[!&]\S*\s+)+", "", v)                          # a YAML tag or anchor in front of the value
    if v.startswith("*"):                                           # an alias: not followed, not shown
        return ""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return re.sub(r"\s+", " ", _CTRL.sub(" ", v)).strip()[:n]


def parse(text, stem):
    """{name, description, tools, model} from the front matter of `text`; the body is not looked at. Never raises."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    raw = {}
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        fm = lines[1:end] if end else []
        i = 0
        while i < len(fm):
            m = re.match(r"^(name|description|tools|model)\s*:\s*(.*)$", fm[i])
            i += 1
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip()
            more = []
            while i < len(fm) and (fm[i].startswith((" ", "\t")) or (key == "tools" and fm[i].startswith("- "))):
                more.append(fm[i].strip()); i += 1
            if val == "" or _BLOCK.match(val):
                val = ("\n" if key == "tools" else " ").join(more)
            raw.setdefault(key, val)
    tools = [t for t in (_clean(t.lstrip("- "), CAP["tool"]) for t in re.split(r"[,\n]", raw.get("tools", "").strip().strip("[]"))) if t][:MAX_TOOLS]
    return {"name": _clean(raw.get("name", ""), CAP["name"]) or _clean(stem, CAP["name"]),
            "description": _clean(raw.get("description", ""), CAP["description"]),
            "tools": tools, "model": _clean(raw.get("model", ""), CAP["model"])}


def _agents_fd(path):
    """The .claude/agents folder opened without following a link at any step, or None."""
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in (".claude", "agents"):
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        return fd
    except OSError:
        if fd is not None:
            os.close(fd)
        return None


def _fd_path(f):
    """Where an open file really lives (macOS F_GETPATH, Linux /proc), or None when that cannot be told."""
    try:
        if hasattr(fcntl, "F_GETPATH"):
            return os.path.realpath(fcntl.fcntl(f, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0].decode("utf-8", "replace"))
        return os.path.realpath(os.readlink("/proc/self/fd/%d" % f))
    except (OSError, ValueError):
        return None


def _inside(path, root):
    parts = path.split(os.sep)
    return path.startswith(root + os.sep) and ".git" not in parts[len(root.split(os.sep)):]


def _open_inside_link(dirfd, fn, root):
    """An open descriptor for a link whose real target is a regular .md file inside the project root, else None.

    The target is resolved, opened without following a last-component link, and then checked again from the open file itself,
    so a folder swapped for a link between the two steps is caught. Anything that cannot be proven inside is refused."""
    try:
        if not stat.S_ISLNK(os.lstat(fn, dir_fd=dirfd).st_mode):
            return None
        target = os.path.realpath(os.path.join(root, ".claude", "agents", os.readlink(fn, dir_fd=dirfd)))
        if not target.endswith(".md") or not _inside(target, root):
            return None
        f = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    real = _fd_path(f)
    if real is None or real != target or not _inside(real, root):
        os.close(f)
        return None
    return f


def agents_of(path):
    """The project's own agents, sorted by name: [{file, name, description, tools, model}]. Empty when there are none."""
    fd = _agents_fd(str(path))
    if fd is None:
        return []
    root = os.path.realpath(str(path))
    out = []
    try:
        for fn in sorted(os.listdir(fd)):
            if len(out) >= MAX_FILES:
                break
            if not fn.endswith(".md") or fn.startswith("."):
                continue
            try:
                f = os.open(fn, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)      # a link is refused here; a fifo or device fails the check below
            except OSError:
                f = _open_inside_link(fd, fn, root)                                           # a link to a file inside this project is the one exception
                if f is None:
                    continue
            try:
                if not stat.S_ISREG(os.fstat(f).st_mode):
                    continue
                data = os.read(f, MAX_READ)
            finally:
                os.close(f)
            a = parse(data.decode("utf-8", "replace"), fn[:-3])
            a["file"] = _clean(fn, 80)
            out.append(a)
    except OSError:
        pass
    finally:
        os.close(fd)
    return sorted(out, key=lambda a: (a["name"].lower(), a["file"]))


def coverage(agents):
    """One entry per job: the agents whose name or description plausibly fit it (a suggestion, not confirmed), else none."""
    out = []
    for job, words in JOB_WORDS.items():
        pat = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + ")", re.I)
        out.append({"job": job, "fits": [a["name"] for a in agents if pat.search(a["name"]) or pat.search(a["description"])][:5]})
    return out


def project_agents(path):
    """What /api/project-agents returns for a registered project's folder. Cached for a few seconds; nothing is written."""
    now = time.monotonic()
    hit = _cache.get(path)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    ag = agents_of(path)
    res = {"agents": ag, "coverage": coverage(ag)}
    if len(_cache) > 64:
        _cache.clear()
    _cache[path] = (now, res)
    return res
