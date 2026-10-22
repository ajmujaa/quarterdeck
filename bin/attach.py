#!/usr/bin/env python3
"""attach: scan a project folder, propose how the crew should work on it, and register it only when you say so.

    bin/attach.py PATH [--name NAME] [--verify "CMD"] [--build "CMD"] [--lint "CMD"] [--verbose]   a short summary of the proposal; changes nothing
    bin/attach.py PATH [--name NAME] [--verify "CMD"] [--build "CMD"] [--lint "CMD"] --apply       register it in your registry and keep the profile and a record of what was proposed
    bin/attach.py set-repo NAME OWNER/REPO                         set the GitHub repo of a registered project

Attaching is onboarding: the scan is followed by a survey (bin/survey.py: layout, entry points, scripts, dependencies of note, documents present and
missing, size, git), the duties are chosen with reasons, and the ready checklist (bin/ready.py) says what is done and the one thing to do next. The dry run
shows all of that and changes nothing. --apply registers, keeps the survey in state/projects/<name>/ and ends with the real checklist. For a project that
is ALREADY registered, `attach DIR` surveys again and refreshes that profile (your data folder only) and says what changed since the last survey.

    bin/attach.py enable PROJECT DUTY... | cycle        turn duties on (cycle also allows full cycles and turns on the purser and the panel)
    bin/attach.py disable PROJECT DUTY... | cycle       turn duties off

--verify sets the command that proves a change works when the scan found none (or found the wrong one); --build and --lint do the same for the build and
lint commands, which are proposed next to it. --verbose shows the whole scan (every fact with its file), the reason each duty is on or off, and every
protected path.

The scan names the stack (for example "React 18 with Vite, tests by Vitest, lint by ESLint, package manager npm"). Duties that fit that stack are
offered as suggestions, switched off: nothing is on unless it was on before (the read-only duties, and the Shipwright when a verify command exists)
or you tick it. The registry's "build" is the command the Shipwright's checks already run (bin/lib.sh run_checks); "lint" and "typecheck" are recorded
for your review and the crew's notes, and nothing runs them by itself.

The proposal is what the scan supports and no more: the read-only duties first, the verify command only if the project has one, the
paths the crew may not touch taken from the sensitive folders and secret files found. Nothing is written into the project itself.
The registry, the profile and the record all live in your data folder. Standard library only; reads files, never the network.
"""
import json
import os
import tempfile
import platform
import re
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home
from integrations import common as _common
import scan as _scan
import projectroots as _projroots
import packs as _packs
import protect as _protect
import safegit as _safegit
import survey as _survey
import ready as _ready

READ_ONLY_DUTIES = ["surveyor", "foreman", "inspector"]
GUARDRAILS = ["Never merge a pull request.", "Never push to the default branch; every change goes on its own branch.",
              "Never touch .env files or anything that holds a secret.", "Follow the repository's own AGENTS.md or CLAUDE.md where it has one."]
# The three standing rules no edit, page, command or API call can turn off, each with the plain reason shown next to it (bin/guardrails.py).
LOCKED = [(GUARDRAILS[0], "The crew prepares changes and only you merge them."),
          (GUARDRAILS[1], "A change on its own branch can be reviewed and undone; a push to the default branch cannot."),
          (GUARDRAILS[2], "A secret the crew reads or writes can end up in a prompt, a log or a commit.")]


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


def no_repo_sentence(name):
    """The one sentence every place that meets a project with no GitHub repo says (bin/repo.py prints the ways forward)."""
    return f"{name} has no GitHub repo, so the crew cannot open pull requests yet; local tickets still work."


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


SUGGESTABLE = ("joiner", "lookout", "pilot", "marshal", "assayer", "caulker", "quartermaster", "infra", "planner", "harbourmaster", "purser", "trials")
OFF_WHY = {"brief": "turns an idea into a one-page design brief when you ask; it is not tied to the stack",
           "mockup": "needs an approved design brief first",
           "panel": "convenes several crew members on a question you put to them; you start it",
           "bosun": "reports stale branches and drift; it needs the GitHub repo to compare against",
           "logkeeper": "writes a decision record from a panel's ruling; it needs one first",
           "scribe": "drafts a README or an architecture overview the survey found missing; you ask for it with qtdeck docs, so it needs no switch"}


def _cmd_reason(prof, key, cmd):
    """Where a proposed command came from, in a few words."""
    if not cmd:
        return "none found"
    for c in prof["commands"]:
        if c["name"] == f"{key}: {cmd}":
            return c["evidence"][0]
    for f in prof.get("stack", {}).get("facts", []):
        n = cmd.split(" ", 1)[0]
        if f["name"].lower().startswith(n.lower()) or f["name"].lower() in cmd.lower():
            return f["evidence"]
    return "from the stack scan"


def duty_plan(prof, entry, verify):
    """For every duty: {on, suggested, why}. On is the old rule, untouched; suggested duties stay off until the owner ticks them."""
    st = prof.get("stack") or {}
    run = st.get("runnable") or {}
    ui, app = bool(st.get("ui")), st.get("app", "unknown")
    names = [f["name"] for f in st.get("facts", []) if f["kind"] == "framework"]
    uiname = next((n for n in names if n in ("Next.js", "Nuxt", "SvelteKit", "Astro", "Angular", "Vue", "Svelte", "React", "Expo", "React Native")), "")
    served = run.get("dev") or run.get("start")
    test = verify or run.get("test")
    repo = bool(entry["repo"])
    infra = [i["name"] for i in prof["infrastructure"]] + [d["name"] for d in prof["deploy_targets"] if d["name"] in ("Vercel", "Supabase")]
    sens = {d["name"] for d in prof["sensitive"]}
    out = {}

    def put(duty, on, suggested, why):
        out[duty] = {"on": bool(on), "suggested": bool(suggested) and not on, "why": why}

    put("surveyor", True, False, "reads a pull request and posts findings; it changes nothing")
    put("foreman", True, False, "turns a findings report into well-formed issues, and files none unless you run it")
    put("inspector", True, False, "checks that a pull request does what it says; it only reads")
    put("shipwright", bool(verify), False, f"a verify command exists ({verify}) to prove its work" if verify else "off until a verify command is set: it needs one to prove its work")
    put("joiner", False, ui, f"{uiname or 'a UI framework'} is a UI framework, and the joiner reviews the interface for accessibility, states and small screens" if ui else "no UI framework was found, and it reviews interface code")
    pilot_ok = ui and app == "web-ui" and served
    qa = "; it needs qa settings you must give in the registry (how to start the app and when it is ready)"
    put("lookout", False, pilot_ok, f"the app can be run ({served}), so it can take screenshots of each screen{qa}" if pilot_ok else "needs a web app with a dev or start script to take screenshots of")
    put("pilot", False, pilot_ok, f"the app can be run ({served}), so a crew can sail it in a headless browser{qa}" if pilot_ok else "needs a web app with a dev or start script to drive")
    sec = app in ("web-api", "web-ui") or sens & {"authentication", "payments", "encryption", "secrets"} or st.get("dependencies")
    why_sec = ("it has a server" if app == "web-api" else "it serves pages and may hold sign-in or data" if app == "web-ui" else
               "the folder has " + "/".join(sorted(sens & {"authentication", "payments", "encryption", "secrets"})) if sens & {"authentication", "payments", "encryption", "secrets"} else "it pulls dependencies from the network")
    put("marshal", False, sec, f"{why_sec}, and the marshal reads a pull request for security" if sec else "no server, sign-in or dependencies were found")
    put("assayer", False, test, f"a test command exists ({test}); it writes tests from an issue's acceptance checks and needs the purser's requirements" if test else "needs a test command to keep a test")
    put("caulker", False, test, f"a test command exists ({test}) to prove a fix; it fixes exactly what reviewers found on a pull request" if test else "needs a test command to prove a fix")
    put("quartermaster", False, st.get("dependencies") and st.get("lockfile"), "a dependency manifest and a lockfile exist, so it can judge version bumps" if st.get("dependencies") and st.get("lockfile") else "needs a dependency manifest and a lockfile, and one was not found")
    put("infra", False, infra, f"infrastructure or deploy files found ({', '.join(dict.fromkeys(infra[:4]))}); it reads changes to them" if infra else "no Terraform, CDK, CloudFormation, Serverless, Vercel or Supabase files were found")
    put("planner", False, repo, "it plans a GitHub project board's backlog; it needs the repo and a board, which the scan cannot see" if repo else "needs a GitHub repo and a project board, and no GitHub remote was found")
    put("harbourmaster", False, repo, "it keeps a GitHub project board honest; it needs the repo and a board, which the scan cannot see" if repo else "needs a GitHub repo and a project board, and no GitHub remote was found")
    put("purser", False, repo, "it turns a GitHub issue into requirements a stranger could start from" if repo else "needs a GitHub repo to read issues from, and no GitHub remote was found")
    put("trials", False, test, f"a test command exists ({test}); it writes a failing test for a bug issue and needs GitHub issues to work from" if test else "needs a test command to run a new test with")
    for d, why in OFF_WHY.items():
        put(d, False, False, why)
    for d in sorted(known_duties() - set(out)):                 # a duty added later still gets a line
        put(d, False, False, "not tied to the stack; start it yourself when you want it")
    return out


def propose(prof, name=None):
    """The registry entry the scan supports, with a reason for each part. A dict: entry, reasons, duty_reasons (per duty), suggested (duties that fit, off)."""
    root = Path(prof["path"])
    tests = [c for c in prof["commands"] if c["name"].startswith("test:")]
    verify = tests[0]["name"].split(": ", 1)[1] if tests else ""
    run = (prof.get("stack") or {}).get("runnable") or {}
    cmds = {k: (run.get(k) or "") for k in ("build", "lint", "typecheck")}
    cmds = {k: (v if VERIFY_OK.fullmatch(v) else "") for k, v in cmds.items()}
    forbidden = [d["evidence"][0] for d in prof["sensitive"] if d["name"] in ("database migrations", "secrets", "encryption", "payments")]
    forbidden += _protect.prefixes()          # CI, manifests, lockfiles, tool configs, scripts: the harness also refuses these on any model-made change
    forbidden += [s["evidence"][0] for s in prof["secret_files"]] + [i["evidence"][0].rsplit("/", 1)[0] + "/" for i in prof["infrastructure"] if "/" in i["evidence"][0] and "prod" in i["evidence"][0].lower()]
    odd = [x for x in forbidden if CONTROL.search(x)]             # a file name may hold a line break; it must not become a line of AGENTS.md or the registry
    forbidden = [x for x in forbidden if x not in odd]
    duties = list(READ_ONLY_DUTIES) + (["shipwright"] if verify else [])
    why = {"duties": "read-only duties first" + ("; the Shipwright too, since there is a command to prove its work" if verify else "; no Shipwright until a verify command is set"),
           "verify": tests[0]["evidence"][0] if tests else "no test command was found",
           "build": _cmd_reason(prof, "build", cmds["build"]) if cmds["build"] else "no build command was found",
           "lint": _cmd_reason(prof, "lint", cmds["lint"]) if cmds["lint"] else "no lint command was found",
           "forbidden_paths": "sensitive folders and secret files found by the scan, and the build, CI and dependency files no model-made change may touch (bin/protect.py)"}
    if cmds["typecheck"]:
        why["typecheck"] = _cmd_reason(prof, "typecheck", cmds["typecheck"])
    fit = _packs.select(prof)
    why["packs"] = ("stack notes for " + ", ".join(p["label"] for p, _ in fit) + ": " + "; ".join(h[0] for _, h in fit)) if fit else "no stack pack fits this project"
    entry = {"repo": repo_of(prof), "path": tilde(root), "summary": "", "default_branch": default_branch(root, prof),
             "duties": duties, "guardrails": list(GUARDRAILS), "verify": verify, "build": cmds["build"], "lint": cmds["lint"], "forbidden_paths": sorted(dict.fromkeys(forbidden)),
             "packs": [p["id"] for p, _ in fit]}
    if cmds["typecheck"]:
        entry["typecheck"] = cmds["typecheck"]
    plan = duty_plan(prof, entry, verify)
    agent = [f"{c['name']}: {', '.join(c['evidence'][:3])}" for c in prof.get("agent_config", [])]
    return {"name": (name or prof["name"]).lower(), "entry": entry, "reasons": why, "duty_reasons": plan, "suggested": [d for d, v in plan.items() if v["suggested"]],
            "stack": (prof.get("stack") or {}).get("summary", ""), "agent_config": agent,
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
    """A copy of the proposal with the owner's changes, or ValueError saying what is wrong. Only duties, verify, build, lint, typecheck, forbidden_paths
    and guardrails can change. The Shipwright needs a verify command; the harness's own protected paths and the three locked rules (merging, pushing, secrets) stay."""
    if not isinstance(edits, dict):
        raise ValueError("edits must be an object")
    out = json.loads(json.dumps(prop))
    e = out["entry"]
    unknown = set(edits) - {"duties", "verify", "build", "lint", "typecheck", "forbidden_paths", "guardrails"}
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
    for key in ("build", "lint", "typecheck"):
        if key in edits:
            v = edits[key]
            if not isinstance(v, str) or (v.strip() and not VERIFY_OK.fullmatch(v.strip())):
                raise ValueError(f"the {key} command may be one plain command of up to 200 characters, without ; & | $ ` < > ( ) or quotes")
            if v.strip() or key in e:
                e[key] = v.strip()
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
        if not isinstance(g, list) or not all(isinstance(x, str) for x in g):
            raise ValueError("guardrails must be a list of rules")
        import guardrails as _gr                     # the rules for a rule (length, characters, credentials) live with the editor; the three locked ones lead
        e["guardrails"] = _gr.normalise(g)
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


def _put_registry(reg, cur):
    """Write the registry through a temp file of its own (two writers at once must not share one), 0600, then swap it in."""
    fd, tmp = tempfile.mkstemp(dir=str(reg.parent), prefix=reg.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(cur, indent=2) + "\n")
        os.replace(tmp, reg)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_registry(cur, reg=None):
    """The registry, atomically, 0600."""
    reg = Path(reg or registry_path())
    reg.parent.mkdir(parents=True, exist_ok=True)
    _put_registry(reg, cur)
    return reg


def apply(prop, prof, reg=None, proposed=None, by="owner, with --apply", sv=None):
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
    _put_registry(reg, cur)
    _scan.save(prof, name)           # state/profiles/<name>.json: the older record, still read by existing code; the survey below is the one new code reads
    if sv is not None:
        _survey.save(name, dict(sv, name=name))
    rec = _scan.profile_dir() / f"{name}.attach.json"
    rec.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "proposed": (proposed or prop)["entry"], "reasons": prop["reasons"], "stack": prop.get("stack", ""), "suggested": prop.get("suggested", []), "duty_reasons": prop.get("duty_reasons", {}), "approved": prop["entry"], "approved_by": by}, indent=2) + "\n")
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
    _put_registry(reg, cur)
    return reg


STANDING = {"guardrails", "guardrail", "rules", "never-merge", "never-push", "never-merging", "never-pushing"}
CYCLE_DUTIES = ("purser", "panel")


def _log(line):
    try:
        d = _home.resolve() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "quarterdeck.log", "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except OSError:
        pass                                  # a note that could not be written never undoes the change


def set_duties(name, add=(), remove=(), cycle=None, reg=None):
    """Turn duties on or off for a registered project, through the same validation as the review (edit(), known_duties()), atomically, 0600. `cycle` True
    allows full cycles ("cycle": true, and the purser and the panel on); False takes the permission away and leaves the duties as they are. The standing
    rules (never merge, never push to the default branch) are not duties and cannot be touched. Returns {"duties": [...], "cycle": bool, "added", "removed", "notes"}.
    The log names the project and the duties, never a value."""
    reg = Path(reg or registry_path())
    cur = load_registry(reg)
    if name not in cur or not isinstance(cur[name], dict):
        raise ValueError(f"'{name}' is not registered (see: qtdeck projects)")
    add, remove = list(dict.fromkeys(add)), list(dict.fromkeys(remove))
    for d in add + remove:
        if d.lower() in STANDING:
            raise ValueError("the standing rules (never merge, never push to the default branch) are not duties and cannot be turned off")
    entry = cur[name]
    duties = list(entry.get("duties", []))
    notes = []
    if cycle is True:
        for d in CYCLE_DUTIES:
            if d not in add and d not in duties:
                add.append(d)
                notes.append(f"{d} turned on, since a cycle goes through it")
    want = [d for d in duties if d not in remove] + [d for d in add if d not in duties]
    if not want:
        raise ValueError("at least one duty has to stay on")
    out = edit({"entry": entry}, {"duties": want})["entry"]          # unknown duty names and "shipwright without a verify command" are refused here
    out["duties"] = want
    if cycle is True:
        out["cycle"] = True
        notes.append("full cycles are allowed (a cycle spends model money; it is never started by a schedule)")
    elif cycle is False:
        out.pop("cycle", None)
        notes.append("full cycles are no longer allowed")
    cur[name] = {**entry, "duties": out["duties"], **({"cycle": True} if out.get("cycle") else {})}
    if cycle is False:
        cur[name].pop("cycle", None)
    write_registry(cur, reg)
    added, removed = [d for d in want if d not in duties], [d for d in duties if d not in want]
    _log(f"duties {name}: on {','.join(added) or '-'} off {','.join(removed) or '-'}" + (f" cycle {'on' if cycle else 'off'}" if cycle is not None else ""))
    return {"duties": want, "cycle": cur[name].get("cycle") is True, "added": added, "removed": removed, "notes": notes}


def update_commands(name, edits, reg=None):
    """Set verify, build, lint or typecheck of a registered project (the same limits as the review). Returns the registry path."""
    reg = Path(reg or registry_path())
    cur = load_registry(reg)
    if name not in cur or not isinstance(cur[name], dict):
        raise ValueError(f"'{name}' is not registered (see: qtdeck projects)")
    out = edit({"entry": cur[name]}, edits)["entry"]
    cur[name] = {**cur[name], **{k: out[k] for k in edits if k in out}}
    write_registry(cur, reg)
    _log(f"commands {name}: set {','.join(sorted(edits))}")
    return reg


def registered_as(root, name=None, cur=None):
    """The registry name this folder is already attached under: the entry with the same path, else None. A different folder that happens to carry a
    registered name is not that project (attach --apply refuses its name)."""
    cur = load_registry(registry_path()) if cur is None else cur
    want = Path(root).resolve()
    for n, e in cur.items():
        try:
            if isinstance(e, dict) and e.get("path") and Path(os.path.expanduser(e["path"])).resolve() == want:
                return n
        except (OSError, RuntimeError):
            continue
    return None


SHORT_ON = {"surveyor": "reads pull requests", "foreman": "files issues from findings", "inspector": "checks a change does what it says", "shipwright": "a verify command exists"}


def cmd_line(e, prop, key, flag):
    v = e.get(key, "")
    return v + "   (" + prop["reasons"].get(key, "") + ")" if v else f'none found; set it with --{flag} "<command>"'


def docs_line(sv):
    """One line: the documents that are there and the ones that are not."""
    pr, ms = sv["docs"]["present"], sv["docs"]["missing"]
    have = [w for k, w in (("readme", "README"), ("architecture", "architecture overview"), ("contributing", "CONTRIBUTING"), ("license", "LICENSE"), ("changelog", "CHANGELOG")) if pr.get(k)]
    gone = [w for k, w in (("readme", "README"), ("architecture", "architecture overview")) if k in ms]
    return ("present: " + (", ".join(have) or "none")) + ("; missing: " + ", ".join(gone) + "  (qtdeck docs <name> drafts them; nothing is written until you say so)" if gone else "")


def preview_items(prop, sv, path):
    """The ready checklist as it would be right after attaching (nothing is saved or run)."""
    return _ready.build(prop["name"], prop["entry"], sv, {"duty_reasons": prop.get("duty_reasons", {})}, None, None, path=path, preview=True)


def _clip_line(s, n=96):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 3] + "..."


def summary(prof, prop, path, sv=None):
    """The short version: what was found, what would run, how a change is proved, and what to do next."""
    e, n = prop["entry"], prop["name"]
    langs = ", ".join(f"{l['name']} ({l['evidence'][0].split(' ', 1)[0]})" for l in prof["languages"][:4]) or "none recognised"
    plan = prop.get("duty_reasons") or {}
    print(f"  {n}  ({path})")
    print(f"    languages     {langs}")
    print(f"    stack         {prop.get('stack') or langs}")
    if sv:
        print(f"    docs          {docs_line(sv).replace('<name>', n)}")
    print(f"    verify        {cmd_line(e, prop, 'verify', 'verify')}")
    hint = _ready.install_hint(path, e.get("verify", ""), sv)
    if hint:
        print(f"                  note: {hint}")
    print(f"    build         {cmd_line(e, prop, 'build', 'build')}")
    print(f"    lint          {cmd_line(e, prop, 'lint', 'lint')}")
    print(f"    duties        " + ", ".join(d + (f" ({SHORT_ON[d]})" if d in SHORT_ON else "") for d in e["duties"]))
    if prop.get("suggested"):
        print(f"    also fit this stack (off): {', '.join(prop['suggested'])}   (not on until you say so; --verbose says why)")
        for d in prop["suggested"][:6]:
            print(f"      {d:<14}{_clip_line(plan.get(d, {}).get('why', ''))}   [qtdeck enable {n} {d}]")
    print(f"    repo          {e['repo'] or 'none (no GitHub remote); set it after --apply with: qtdeck repo ' + n + ' <owner/name>'}")
    print(f"    protected     {len(e['forbidden_paths'])} paths the crew may not change (--verbose lists them)")
    if prof["secret_files"]:
        print(f"    secret files  {len(prof['secret_files'])} found, never opened, on the protected list")
    print(f"  WARNING  {prop['warning']}")
    if sv:
        print("\n  the checklist as it would be right after you attach:")
        print("\n".join(_ready.item_lines(preview_items(prop, sv, path))))


def say(prop):
    e = prop["entry"]
    print(f"  proposal for '{prop['name']}'")
    print(f"  WARNING         {prop['warning']}")
    print(f"    stack           {prop.get('stack') or '(not recognised)'}")
    print(f"    repo            {e['repo'] or '(no GitHub remote found; set it by hand)'}")
    print(f"    default branch  {e['default_branch']}")
    print(f"    duties          {', '.join(e['duties'])}   ({prop['reasons']['duties']})")
    print(f"    verify          {e['verify'] or '(none)'}   ({prop['reasons']['verify']})")
    print(f"    build           {e.get('build') or '(none)'}   ({prop['reasons'].get('build', '')})")
    print(f"    lint            {e.get('lint') or '(none)'}   ({prop['reasons'].get('lint', '')})")
    if e.get("typecheck"):
        print(f"    typecheck       {e['typecheck']}   ({prop['reasons'].get('typecheck', '')})")
    print(f"    forbidden       {', '.join(e['forbidden_paths']) or '(none)'}   ({prop['reasons']['forbidden_paths']})")
    print(f"    stack notes     {', '.join(e['packs']) or '(none)'}   ({prop['reasons']['packs']})")
    print(f"    guardrails      {len(e['guardrails'])} standing rules, including never merge and never push to the default branch")
    plan = prop.get("duty_reasons") or {}
    if plan:
        print("    every duty, and why it is on or off:")
        for d, v in plan.items():
            state = "on " if d in e["duties"] else "off"
            print(f"      {d:<14}{state}{' (suggested)' if v['suggested'] and d not in e['duties'] else ''}  {v['why']}")


def reattach(regname, path, prof, sv, edits, do):
    """A folder that is already registered: survey it again and refresh the profile (the data folder only), say what changed since the last survey.
    New verify, build or lint commands are written to the registry only with --apply."""
    old = _survey.load(regname)
    sv = dict(sv, name=regname)
    _survey.save(regname, sv)
    _scan.save(prof, regname)
    print(f"  {regname} is already registered. Its survey was refreshed in your data folder; nothing in the project or the registry was changed.")
    ch = _survey.changes(old, sv)
    if not old:
        print("  there was no survey of it before, so there is nothing to compare with.")
    elif ch:
        print("  changed since the last survey (" + str(old.get("surveyed_at", "?")) + "):")
        for c in ch:
            print(f"    - {c}")
    else:
        print(f"  nothing changed since the last survey ({old.get('surveyed_at', '?')}).")
    if edits:
        if do:
            update_commands(regname, edits)
            print("  registry updated: " + ", ".join(f"{k} = {v or '(none)'}" for k, v in edits.items()))
        else:
            print("  would set " + ", ".join(f"{k} = {v or '(none)'}" for k, v in edits.items()) + "; nothing was changed. Add --apply to do it.")
    return regname


def finish(name):
    """The real checklist of a registered project and the one next action."""
    print()
    v = _ready.view(name)
    print("\n".join(_ready.lines(v["items"], v["next"])))


def main(argv):
    if argv[:1] in (["enable"], ["disable"]):
        on = argv[0] == "enable"
        names = argv[1:]
        if len(names) < 2:
            print(f"usage: qtdeck {argv[0]} <project> <duty>... | cycle")
            return 2
        project, rest = names[0], names[1:]
        cyc = "cycle" in rest
        duties = [d for d in rest if d != "cycle"]
        try:
            r = set_duties(project, add=duties if on else (), remove=() if on else duties, cycle=(on if cyc else None))
        except ValueError as e:
            print(f"  {e}")
            return 2
        except OSError as e:
            print("qtdeck: " + _common.why_not_saved(e), file=sys.stderr)
            return 1
        word = "turned on" if on else "turned off"
        if r["added"] or r["removed"] or cyc:
            print(f"  {project}: {word} {', '.join(duties + (['cycles'] if cyc else []))}.")
        else:
            print(f"  {project}: nothing to change; those duties were already {'on' if on else 'off'}.")
        for n in r["notes"]:
            print(f"  {n}")
        print(f"  duties now: {', '.join(r['duties'])}")
        return 0
    if argv[:1] == ["set-repo"]:
        if len(argv) != 3:
            print("usage: qtdeck repo <project> <owner/name>")
            return 2
        try:
            set_repo(argv[1], argv[2])
        except ValueError as e:
            print(f"  {e}")
            return 2
        except OSError as e:
            print("qtdeck: " + _common.why_not_saved(e), file=sys.stderr)
            return 1
        print(f"  {argv[1]}: GitHub repo set to {argv[2]}")
        print(f"  next: qtdeck run {argv[1]} surveyor --pr <number>")
        return 0
    args, path, name, do, verify, verbose = list(argv), None, None, False, None, False
    extra = {}
    while args:
        a = args.pop(0)
        if a == "--name" and args:
            name = args.pop(0)
        elif a == "--verify" and args:
            verify = args.pop(0)
        elif a in ("--build", "--lint") and args:
            extra[a[2:]] = args.pop(0)
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
        _projroots.check_project_folder(path)       # the same rule and message as the dashboard: under your home folder or QUARTERDECK_PROJECT_ROOTS, never hidden
        prof = _scan.scan(path)
        prop = propose(prof, name)
        if verify is not None:
            prop = edit(prop, {"verify": verify})
            prop["reasons"]["verify"] = "set with --verify"
        if extra:
            prop = edit(prop, extra)
            for k in extra:
                prop["reasons"][k] = f"set with --{k}"
        sv = _survey.survey(path, prop["name"])
        regname = registered_as(Path(path).resolve(), prop["name"])
        if regname:
            edits = ({"verify": verify} if verify is not None else {}) | extra
            reattach(regname, path, prof, sv, edits, do)
            finish(regname)
            return 0
        if verbose:
            _scan.say(prof)
            say(prop)
            print(f"    docs            {docs_line(sv).replace('<name>', prop['name'])}")
            print("\n  the checklist as it would be right after you attach:")
            print("\n".join(_ready.item_lines(preview_items(prop, sv, path))))
        else:
            summary(prof, prop, path, sv)
        again = f"qtdeck attach {shlex.quote(path)}" + (f" --name {shlex.quote(name)}" if name else "") + (f" --verify {shlex.quote(verify)}" if verify else "") + "".join(f" --{k} {shlex.quote(v)}" for k, v in extra.items())
        if do:
            reg = apply(prop, prof, sv=sv)
            print(f"\n  registered '{prop['name']}'" + (f" in {reg}; the profile and a record of this proposal are in {_scan.profile_dir()}" if verbose else " in your data folder"))
            print(f"  the survey is kept in {_survey.folder(prop['name'])} (profile.md is the readable one)")
            if not prop["entry"]["repo"]:
                print(f"  {no_repo_sentence(prop['name'])}")
                print(f"  see your options: qtdeck repo {prop['name']}")
                print(f"  to connect a repo you already have: qtdeck repo {prop['name']} <owner/name>")
                print(f"  or keep it on this computer: qtdeck ticket new {prop['name']} \"<what you want built>\"")
            finish(prop["name"])
        else:
            print("\n  nothing was changed.")
            print(f"  next: {again} --apply")
    except ValueError as e:
        print(f"  {e}")
        return 2
    except OSError as e:
        print("qtdeck: " + _common.why_not_saved(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
