#!/usr/bin/env python3
"""attach: scan a project folder, propose how the crew should work on it, and register it only when you say so.

    bin/attach.py PATH [--name NAME] [--verify "CMD"] [--verbose]   a short summary of the proposal; changes nothing
    bin/attach.py PATH [--name NAME] [--verify "CMD"] --apply       register it in your registry and keep the profile and a record of what was proposed
    bin/attach.py set-repo NAME OWNER/REPO                         set the GitHub repo of a registered project

--verify sets the command that proves a change works when the scan found none (or found the wrong one). --verbose shows the whole scan and every
protected path.

The proposal is what the scan supports and no more: the read-only duties first, the verify command only if the project has one, the
paths the crew may not touch taken from the sensitive folders and secret files found. Nothing is written into the project itself.
The registry, the profile and the record all live in your data folder. Standard library only; reads files, never the network.
"""
import json
import os
import platform
import re
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home
import scan as _scan
import packs as _packs
import protect as _protect
import safegit as _safegit

READ_ONLY_DUTIES = ["surveyor", "foreman", "inspector"]
GUARDRAILS = ["Never merge a pull request.", "Never push to the default branch; every change goes on its own branch.",
              "Never touch .env files or anything that holds a secret.", "Follow the repository's own AGENTS.md or CLAUDE.md where it has one."]


def default_branch(root, prof):
    """The folder's default branch, from its own .git (untrusted text), only if it is a plain branch name; otherwise main."""
    ref = Path(root) / ".git" / "refs" / "remotes" / "origin" / "HEAD"
    try:
        m = re.search(r"refs/remotes/origin/(\S+)", ref.read_text())
        if m and _safegit.valid_branch(m.group(1)):
            return m.group(1)
    except OSError:
        pass
    for b in ("main", "master"):
        if (Path(root) / ".git" / "refs" / "heads" / b).exists():
            return b
    b = prof["git"].get("branch")
    return b if _safegit.valid_branch(b) else "main"


def warning(system=None):
    """The attach warning, naming the sandbox this platform has: macOS sandbox-exec, Linux bubblewrap."""
    system = system or platform.system()
    sandbox = "inside the macOS sandbox" if system == "Darwin" else "inside the bubblewrap sandbox; without it they are not run" if system == "Linux" else "inside the operating-system sandbox where there is one"
    return ("Attaching a folder lets it influence what runs on this machine: the crew reads its files, and the harness runs its verify, test and build commands "
            f"(with a minimal environment and no secrets, {sandbox}). Its own agent set-up (.claude/settings.json, hooks, .mcp.json) is never loaded by the crew. Attach only folders you trust.")


WARNING = warning()
REPO_OK = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}")   # a GitHub owner/name; never a leading dash, quote, $ or ;


def repo_of(prof):
    """owner/repo from the origin URL, only if it is a plain GitHub name: a folder's .git/config is untrusted text and this ends up in gh -R and URLs."""
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", prof["git"].get("origin", ""))
    return m.group(1) if m and REPO_OK.fullmatch(m.group(1)) and ".." not in m.group(1) else ""


def tilde(root):
    """~/... for a folder inside the home folder (as given, or with its links resolved), else the path as it is. A plain text replace turned
    /private/var/x/home/p into /private~/p when the home folder itself sits behind a link."""
    root = Path(root)
    for h in dict.fromkeys((Path.home(), Path.home().resolve())):
        try:
            return "~/" + str(root.relative_to(h)) if root != h else "~"
        except ValueError:
            continue
    return str(root)


def propose(prof, name=None):
    """The registry entry the scan supports, with a reason for each part. A dict: entry, reasons."""
    root = Path(prof["path"])
    tests = [c for c in prof["commands"] if c["name"].startswith("test:")]
    verify = tests[0]["name"].split(": ", 1)[1] if tests else ""
    forbidden = [d["evidence"][0] for d in prof["sensitive"] if d["name"] in ("database migrations", "secrets", "encryption", "payments")]
    forbidden += _protect.prefixes()          # CI, manifests, lockfiles, tool configs, scripts: the harness also refuses these on any model-made change
    forbidden += [s["evidence"][0] for s in prof["secret_files"]] + [i["evidence"][0].rsplit("/", 1)[0] + "/" for i in prof["infrastructure"] if "/" in i["evidence"][0] and "prod" in i["evidence"][0].lower()]
    odd = [x for x in forbidden if CONTROL.search(x)]             # a file name may hold a line break; it must not become a line of AGENTS.md or the registry
    forbidden = [x for x in forbidden if x not in odd]
    duties = list(READ_ONLY_DUTIES) + (["shipwright"] if verify else [])
    why = {"duties": "read-only duties first" + ("; the Shipwright too, since there is a command to prove its work" if verify else "; no Shipwright until a verify command is set"),
           "verify": tests[0]["evidence"][0] if tests else "no test command was found",
           "forbidden_paths": "sensitive folders and secret files found by the scan, and the build, CI and dependency files no model-made change may touch (bin/protect.py)"}
    fit = _packs.select(prof)
    why["packs"] = ("stack notes for " + ", ".join(p["label"] for p, _ in fit) + ": " + "; ".join(h[0] for _, h in fit)) if fit else "no stack pack fits this project"
    entry = {"repo": repo_of(prof), "path": tilde(root), "summary": "", "default_branch": default_branch(root, prof),
             "duties": duties, "guardrails": list(GUARDRAILS), "verify": verify, "forbidden_paths": sorted(dict.fromkeys(forbidden)),
             "packs": [p["id"] for p, _ in fit]}
    agent = [f"{c['name']}: {', '.join(c['evidence'][:3])}" for c in prof.get("agent_config", [])]
    return {"name": (name or prof["name"]).lower(), "entry": entry, "reasons": why, "agent_config": agent,
            "warning": WARNING + (" Agent set-up found in the folder: " + "; ".join(agent) + "." if agent else " No agent set-up was found in the folder.")
            + (f" {len(odd)} secret file or folder name holds a control character or line break, so it is not on the protected list: rename it and look again." if odd else "")}


# ---- review: the owner may change the proposal before it is registered; the same limits hold for the dashboard and anything else that edits it ----
CONTROL = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")
PATH_OK = re.compile(r"[A-Za-z0-9_.@+][A-Za-z0-9_.@+ /-]{0,198}")      # a relative path or prefix; no glob, quote, $ or ; in it
VERIFY_OK = re.compile(r"[A-Za-z0-9_./:=@+ -]{1,200}")                 # one plain command line: no ; & | $ ` < > ( ) quotes or line breaks
MAX_FORBIDDEN = len(_protect.prefixes()) + 100      # the harness's own prefixes, which an edit may not drop, plus room for the owner's


def known_duties():
    return {f.stem for f in (Path(__file__).resolve().parent.parent / "duties").glob("*.sh") if not f.name.startswith("_")}


def edit(prop, edits):
    """A copy of the proposal with the owner's changes, or ValueError saying what is wrong. Only duties, verify, forbidden_paths and guardrails
    can change. The Shipwright needs a verify command; the harness's own protected paths and the two standing rules about merging and pushing stay."""
    if not isinstance(edits, dict):
        raise ValueError("edits must be an object")
    out = json.loads(json.dumps(prop))
    e = out["entry"]
    unknown = set(edits) - {"duties", "verify", "forbidden_paths", "guardrails"}
    if unknown:
        raise ValueError("cannot change: " + ", ".join(sorted(unknown)))
    if "duties" in edits:
        d = edits["duties"]
        if not isinstance(d, list) or not all(isinstance(x, str) for x in d) or not d or len(set(d)) != len(d):
            raise ValueError("duties must be a list of duty names, each once, at least one")
        bad = [x for x in d if x not in known_duties()]
        if bad:
            raise ValueError("no such duty: " + ", ".join(bad[:3]))
        e["duties"] = d
    if "verify" in edits:
        v = edits["verify"]
        if not isinstance(v, str) or (v.strip() and not VERIFY_OK.fullmatch(v.strip())):
            raise ValueError("the verify command may be one plain command of up to 200 characters, without ; & | $ ` < > ( ) or quotes")
        e["verify"] = v.strip()
    if "forbidden_paths" in edits:
        f = edits["forbidden_paths"]
        if not isinstance(f, list) or not all(isinstance(x, str) for x in f) or len(f) > MAX_FORBIDDEN:
            raise ValueError(f"forbidden paths must be a list of at most {MAX_FORBIDDEN} paths")
        scanned = set(prop["entry"]["forbidden_paths"])      # the scan's own entries come back as they are, whatever characters the names hold
        f = [x if x in scanned else x.strip() for x in f if x.strip()]
        for x in f:
            if x in scanned and not CONTROL.search(x) and ".." not in x.split("/") and not x.startswith("/"):
                continue
            if not PATH_OK.fullmatch(x) or ".." in x.split("/") or x.startswith("/"):
                raise ValueError(f"'{x[:40]}' is not a path inside the project")
        missing = [x for x in _protect.prefixes() if x not in f]
        if missing:
            raise ValueError("these protected paths stay: " + ", ".join(missing[:5]))
        e["forbidden_paths"] = sorted(dict.fromkeys(f))
    if "guardrails" in edits:
        g = edits["guardrails"]
        if not isinstance(g, list) or any(x not in GUARDRAILS for x in g):
            raise ValueError("guardrails must be some of the standing rules")
        if not set(GUARDRAILS[:2]) <= set(g):
            raise ValueError("never merging and never pushing to the default branch cannot be turned off")
        e["guardrails"] = [x for x in GUARDRAILS if x in g]
    if "shipwright" in e["duties"] and not e["verify"]:
        raise ValueError("the Shipwright needs a verify command to prove its work")
    return out


AGENTS_MD = """# How Quarterdeck's crew works on this project

Quarterdeck (a local tool the owner runs) has a crew of agents that read this project and sometimes change it on their own branches. This note is so other coding agents know the same ground rules.

Duties switched on: {duties}.

How a change is proved: {verify}

Standing rules:
{rules}

Paths the crew does not change:
{paths}

The crew's set-up lives in the owner's data folder, not in this project. Delete this file whenever you like.
"""


def agents_md(prop):
    e = prop["entry"]
    return AGENTS_MD.format(duties=", ".join(e["duties"]), verify=e["verify"] or "no verify command is set yet",
                            rules="\n".join("- " + g for g in e["guardrails"]), paths="\n".join("- " + p for p in e["forbidden_paths"]) or "- none")


def write_agents_md(prop, root):
    """Add AGENTS.md to the project. Only after the owner confirmed; never replaces a file or link already there. Returns "written" or "exists".
    AGENTS.md is a protected path since round 8 (M4): that rule is about a MODEL changing it in a worktree. This is the owner's own confirmed write of
    a fixed text into their checkout, which no model or issue can trigger or steer, so it is not refused for that reason."""
    root = Path(root)
    target = root / "AGENTS.md"
    if target.exists() or target.is_symlink():
        return "exists"
    with open(target, "x") as f:
        f.write(agents_md(prop))
    return "written"


def registry_path():
    return _home.resolve() / "config" / "projects.json"


def load_registry(p):
    try:
        j = json.loads(Path(p).read_text())
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def apply(prop, prof, reg=None, proposed=None, by="owner, with --apply"):
    """Register the proposal and keep the profile and the record. Refuses a name already registered. Returns the registry path."""
    name = prop["name"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,60}", name):
        raise ValueError("the name may hold lowercase letters, digits, dot, dash and underscore")
    reg = Path(reg or registry_path())
    cur = load_registry(reg)
    if name in cur:
        raise ValueError(f"'{name}' is already registered")
    cur[name] = prop["entry"]
    reg.parent.mkdir(parents=True, exist_ok=True)
    tmp = reg.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, reg)
    _scan.save(prof, name)
    rec = _scan.profile_dir() / f"{name}.attach.json"
    rec.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "proposed": (proposed or prop)["entry"], "reasons": prop["reasons"], "approved": prop["entry"], "approved_by": by}, indent=2) + "\n")
    os.chmod(rec, 0o600)
    return reg


def set_repo(name, repo, reg=None):
    """Set the GitHub repo of a registered project. Only a plain owner/name: it ends up in gh -R and URLs."""
    reg = Path(reg or registry_path())
    cur = load_registry(reg)
    if name not in cur:
        raise ValueError(f"'{name}' is not registered (see: qtdeck projects)")
    if not REPO_OK.fullmatch(repo or "") or ".." in repo:
        raise ValueError(f"'{repo[:60]}' is not a GitHub owner/name, like octocat/hello-world")
    cur[name]["repo"] = repo
    tmp = reg.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, reg)
    return reg


def summary(prof, prop, path):
    """The short version: what was found, what would run, how a change is proved, and what to do next."""
    e, n = prop["entry"], prop["name"]
    langs = ", ".join(f"{l['name']} ({l['evidence'][0].split(' ', 1)[0]})" for l in prof["languages"][:4]) or "none recognised"
    print(f"  {n}  ({path})")
    print(f"    languages     {langs}")
    print(f"    duties        {', '.join(e['duties'])}")
    print(f"    verify        {e['verify'] + '   (' + prop['reasons']['verify'] + ')' if e['verify'] else 'none found; set it with --verify \"<command that runs the tests>\"'}")
    print(f"    repo          {e['repo'] or 'none (no GitHub remote); set it after --apply with: qtdeck repo ' + n + ' <owner/name>'}")
    print(f"    protected     {len(e['forbidden_paths'])} paths the crew may not change (--verbose lists them)")
    if prof["secret_files"]:
        print(f"    secret files  {len(prof['secret_files'])} found, never opened, on the protected list")
    print(f"  WARNING  {prop['warning']}")


def say(prop):
    e = prop["entry"]
    print(f"  proposal for '{prop['name']}'")
    print(f"  WARNING         {prop['warning']}")
    print(f"    repo            {e['repo'] or '(no GitHub remote found; set it by hand)'}")
    print(f"    default branch  {e['default_branch']}")
    print(f"    duties          {', '.join(e['duties'])}   ({prop['reasons']['duties']})")
    print(f"    verify          {e['verify'] or '(none)'}   ({prop['reasons']['verify']})")
    print(f"    forbidden       {', '.join(e['forbidden_paths']) or '(none)'}   ({prop['reasons']['forbidden_paths']})")
    print(f"    stack notes     {', '.join(e['packs']) or '(none)'}   ({prop['reasons']['packs']})")
    print(f"    guardrails      {len(e['guardrails'])} standing rules, including never merge and never push to the default branch")


def main(argv):
    if argv[:1] == ["set-repo"]:
        if len(argv) != 3:
            print("usage: qtdeck repo <project> <owner/name>")
            return 2
        try:
            set_repo(argv[1], argv[2])
        except ValueError as e:
            print(f"  {e}")
            return 2
        print(f"  {argv[1]}: GitHub repo set to {argv[2]}")
        print(f"  next: qtdeck run {argv[1]} surveyor --pr <number>")
        return 0
    args, path, name, do, verify, verbose = list(argv), None, None, False, None, False
    while args:
        a = args.pop(0)
        if a == "--name" and args:
            name = args.pop(0)
        elif a == "--verify" and args:
            verify = args.pop(0)
        elif a == "--verbose":
            verbose = True
        elif a == "--apply":
            do = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif path is None:
            path = a
        else:
            print(__doc__)
            return 2
    if not path:
        print(__doc__)
        return 2
    try:
        prof = _scan.scan(path)
        prop = propose(prof, name)
        if verify is not None:
            prop = edit(prop, {"verify": verify})
            prop["reasons"]["verify"] = "set with --verify"
        if verbose:
            _scan.say(prof)
            say(prop)
        else:
            summary(prof, prop, path)
        again = f"qtdeck attach {shlex.quote(path)}" + (f" --name {shlex.quote(name)}" if name else "") + (f" --verify {shlex.quote(verify)}" if verify else "")
        if do:
            reg = apply(prop, prof)
            print(f"  registered '{prop['name']}'" + (f" in {reg}; the profile and a record of this proposal are in {_scan.profile_dir()}" if verbose else " in your data folder"))
            print(f"  next: qtdeck repo {prop['name']} <owner/name>" if not prop["entry"]["repo"] else f"  next: qtdeck run {prop['name']} surveyor --pr <number>")
        else:
            print("  nothing was changed.")
            print(f"  next: {again} --apply")
    except ValueError as e:
        print(f"  {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
