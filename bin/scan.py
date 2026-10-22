#!/usr/bin/env python3
"""scan: what is in a project folder, found by plain code. Read-only, local, no model.

    bin/scan.py PATH [--save NAME]     print the profile; --save keeps it in your data folder (state/profiles/NAME.json)
    bin/scan.py --infra-files PATH     read changed paths on stdin; print which are infrastructure files (kind, tab, path); used by the infra duty

Rules it keeps, and the tests check:
  - only the folder you name is read, and nothing in it is changed or written (the profile goes to your data folder, never into the project);
  - every claim carries its evidence: the file that proves it. No evidence, no claim;
  - files that hold secrets (.env, keys, credentials) are noted by NAME ONLY and their contents are never opened;
  - infrastructure and deploy targets are read from files in the folder, never from a live account or the network.
Only small manifests (package.json, pyproject.toml, requirements, go.mod, Makefile and similar) are opened, to name the dependencies and commands.
Standard library only.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".terraform", "target", "vendor", ".gradle", ".idea", ".cache", "fixtures"}
MAX_DEPTH = 4
MAX_FILES = 20000
MAX_MANIFEST = 400_000          # bytes: a manifest bigger than this is not read

LANG_EXT = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
            ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift", ".sh": "Shell", ".tf": "Terraform"}
SECRET_NAME = re.compile(r"^(\.env(\..+)?|\.dev\.vars(\..+)?|.*\.pem|.*\.p12|.*\.pfx|id_(rsa|ed25519|ecdsa)|credentials(\.json)?|.*\.keystore|secrets?\.(json|ya?ml|toml))$", re.I)
SECRET_EXAMPLE = re.compile(r"(example|sample|template|dist)", re.I)
SENSITIVE_DIRS = {"migrations": "database migrations", "migration": "database migrations", "secrets": "secrets", "crypto": "encryption", "encryption": "encryption", "auth": "authentication", "payments": "payments", "billing": "payments"}


def walk(root):
    """[(relative posix path, is_dir)] for the folder, shallow-bounded, skipping dependency and build folders. Never follows links."""
    out, n = [], 0
    root = str(root)
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))
                         and os.path.normpath(os.path.join(rel, d)).replace(os.sep, "/") != ".claude/worktrees")     # other checkouts of this same project
        if depth >= MAX_DEPTH:
            dirs[:] = []
        for d in dirs:
            out.append((os.path.normpath(os.path.join(rel, d)).replace(os.sep, "/"), True))
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            if os.path.islink(p):
                continue
            out.append((os.path.normpath(os.path.join(rel, f)).replace(os.sep, "/"), False))
            n += 1
            if n >= MAX_FILES:
                return out
    return out


def read_small(root, rel):
    p = Path(root) / rel
    try:
        if p.stat().st_size > MAX_MANIFEST:
            return ""
        return p.read_text(errors="replace")
    except OSError:
        return ""


def add(profile, key, value, evidence):
    """One claim with its proof. The same claim from a second file adds evidence rather than a second claim."""
    for item in profile[key]:
        if item["name"] == value:
            if evidence not in item["evidence"]:
                item["evidence"].append(evidence)
            return
    profile[key].append({"name": value, "evidence": [evidence]})


def json_of(text):
    try:
        j = json.loads(text)
        return j if isinstance(j, dict) else {}
    except (ValueError, RecursionError):           # deeply nested text is not a manifest; it must not stop the scan
        return {}


# ---- the stack: which framework and tools a project uses, from its files only ----
# Nothing here runs project code, opens the network or reads more than the manifests the rest of the scan reads. Every name that reaches a
# command comes from the fixed tables below, never from the project; a script NAME is checked against SCRIPT_OK before it is used.
SCRIPT_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,39}")           # a package.json script name; no leading dash, space, quote or shell character
CMD_OK = re.compile(r"[A-Za-z0-9_./:=@+ -]{1,200}")                  # the same limits as attach.VERIFY_OK: one plain command line
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x85  ]")
RUN_KEYS = ("dev", "start", "build", "lint", "typecheck", "test")
MAX_PKG_FILES = 20                                                   # package.json files merged for a monorepo
NPM_LOCKS = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"), ("bun.lockb", "bun"), ("bun.lock", "bun"))
JS_MAIN = (("next", "Next.js"), ("nuxt", "Nuxt"), ("@sveltejs/kit", "SvelteKit"), ("astro", "Astro"), ("@angular/core", "Angular"), ("expo", "Expo"),
           ("react-native", "React Native"), ("vue", "Vue"), ("svelte", "Svelte"), ("react", "React"), ("@nestjs/core", "NestJS"), ("fastify", "Fastify"), ("express", "Express"))
JS_UI = {"Next.js", "Nuxt", "SvelteKit", "Astro", "Angular", "Vue", "Svelte", "React"}
JS_MOBILE = {"Expo", "React Native"}
JS_SERVER = {"NestJS", "Fastify", "Express"}
# (label, kind, dependency names, config file prefixes)
JS_TOOLS = (("Vite", "build", ("vite",), ("vite.config.",)), ("webpack", "build", ("webpack",), ("webpack.config.",)), ("esbuild", "build", ("esbuild",), ()),
            ("tsup", "build", ("tsup",), ("tsup.config.",)),
            ("Vitest", "test", ("vitest",), ("vitest.config.", "vitest.workspace")), ("Jest", "test", ("jest",), ("jest.config.",)),
            ("Mocha", "test", ("mocha",), (".mocharc",)), ("Playwright", "test", ("@playwright/test", "playwright"), ("playwright.config.",)),
            ("Cypress", "test", ("cypress",), ("cypress.config.",)),
            ("ESLint", "lint", ("eslint", "eslint-config-next"), ("eslint.config.", ".eslintrc")), ("Biome", "lint", ("@biomejs/biome",), ("biome.json",)),
            ("Prettier", "tool", ("prettier",), (".prettierrc", "prettier.config.")), ("Tailwind", "tool", ("tailwindcss",), ("tailwind.config.",)),
            ("TypeScript", "language", ("typescript",), ("tsconfig.json",)))
JS_MAIN_CONFIG = {"Next.js": "next.config.", "Nuxt": "nuxt.config.", "SvelteKit": "svelte.config.", "Astro": "astro.config.", "Angular": "angular.json", "Svelte": "svelte.config."}
SCRIPT_ALIASES = {"dev": ("dev", "develop"), "start": ("start",), "build": ("build",), "lint": ("lint",), "typecheck": ("typecheck", "type-check"), "test": ("test",)}
PY_FRAMEWORKS = (("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"))
GO_FRAMEWORKS = (("github.com/gin-gonic/gin", "Gin"), ("github.com/labstack/echo", "Echo"), ("github.com/gofiber/fiber", "Fiber"), ("github.com/go-chi/chi", "Chi"))
RUST_FRAMEWORKS = (("axum", "Axum", "framework"), ("actix-web", "Actix", "framework"), ("rocket", "Rocket", "framework"), ("tokio", "Tokio", "runtime"), ("clap", "clap", "framework"))
LOCK_FILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "pdm.lock", "Cargo.lock", "go.sum")


def clip(s, n=120):
    """Untrusted text made safe to print or store: no control characters or line breaks, at most n characters."""
    return CONTROL_RE.sub(" ", str(s))[:n]


def major(rng):
    """The major version from a version range ('^18.2.0', '~14', '>=3.1 <4'); '' when the range does not start with a number (a tag, a path, a workspace link)."""
    m = re.match(r"[\^~<>=v\s]*(\d{1,4})", rng) if isinstance(rng, str) else None
    return m.group(1) if m else ""


def runner(pm, script):
    """The command that runs a package.json script with this package manager, or '' when the script name is not a plain one."""
    if pm not in ("npm", "pnpm", "yarn", "bun") or not isinstance(script, str) or not SCRIPT_OK.fullmatch(script):
        return ""
    if script == "test":
        return {"npm": "npm test", "pnpm": "pnpm test", "yarn": "yarn test", "bun": "bun run test"}[pm]
    return {"npm": "npm run ", "pnpm": "pnpm run ", "yarn": "yarn ", "bun": "bun run "}[pm] + script


def join_words(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def fact(kind, name, version, evidence):
    return {"kind": kind, "name": name, "version": version, "evidence": clip(evidence)}


def _any_name(names, prefixes):
    for n in names:
        if n.startswith(prefixes):
            return n
    return ""


def _js_stack(root, names, first, prof, notes):
    """The Node side: package.json files (the nearest to the root wins, nested ones fill the gaps), lockfiles, config files. Returns an ecosystem dict or None."""
    if "package.json" not in names:
        return None
    paths = sorted(names["package.json"], key=lambda f: (f.count("/"), f))[:MAX_PKG_FILES]
    pjs = []
    for f in paths:
        text = read_small(root, f)
        if not text and (Path(root) / f).is_file():
            try:
                big = (Path(root) / f).stat().st_size > MAX_MANIFEST
            except OSError:
                big = False
            if big:
                notes.append(f"{clip(f)} is larger than {MAX_MANIFEST // 1000} KB and was not read")
        pjs.append((f, json_of(text)))
    ev = paths[0]
    deps, scripts_from, scripts = {}, "", {}
    engines = ""
    pm_field, pm_ev = "", ""
    dev_scripts_text = ""
    for f, pj in pjs:
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            d = pj.get(key)
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(k, str) and k not in deps:
                        deps[k] = (v if isinstance(v, str) else "", f)
        sc = pj.get("scripts")
        if isinstance(sc, dict) and sc and not scripts:
            scripts = {k: v for k, v in sc.items() if isinstance(k, str) and isinstance(v, str)}
            scripts_from = f
        if not pm_field and isinstance(pj.get("packageManager"), str):
            m = re.match(r"(npm|pnpm|yarn|bun)@(\d{1,4})", pj["packageManager"])
            if m:
                pm_field, pm_ver, pm_ev = m.group(1), m.group(2), f
        eng = pj.get("engines")
        if not engines and isinstance(eng, dict) and isinstance(eng.get("node"), str):
            engines = major(eng["node"])
    # the package manager: the packageManager field is the owner's own statement; else the lockfile nearest the root; else npm
    pm, pm_version, pm_evidence, lock = "", "", "", ""
    for lockname, mgr in NPM_LOCKS:
        if lockname in names:
            add(prof, "package_managers", mgr, first(lockname))
            if not lock:
                lock = mgr
                lock_ev = "lockfile " + first(lockname)
    if pm_field:
        add(prof, "package_managers", pm_field, f"{pm_ev} packageManager")
        pm, pm_version, pm_evidence = pm_field, pm_ver, f"{pm_ev} packageManager field"
    elif lock:
        pm, pm_evidence = lock, lock_ev
    else:
        pm, pm_evidence = "npm", f"{ev} (no lockfile, npm assumed)"
        add(prof, "package_managers", "npm", ev)
    facts = []
    facts.append(fact("package_manager", pm, pm_version, pm_evidence))
    if lock and lock != pm:
        facts.append(fact("package_manager", lock, "", lock_ev))
    # scripts -> commands (fixed script names only)
    run = {k: "" for k in RUN_KEYS}
    for key, aliases in SCRIPT_ALIASES.items():
        for a in aliases:
            if a in scripts and SCRIPT_OK.fullmatch(a):
                if key == "test" and "no test specified" in scripts[a]:
                    continue                                     # npm's own placeholder is not a test command
                cmd = runner(pm, a)
                if cmd and CMD_OK.fullmatch(cmd):
                    run[key] = cmd
                    add(prof, "commands", f"{key}: {cmd}", f"{scripts_from} scripts.{a}")
                break
    # frameworks
    main = None
    present = {}
    for dep, label in JS_MAIN:
        cfg = JS_MAIN_CONFIG.get(label)
        if dep in deps:
            present[label] = (major(deps[dep][0]), f"{deps[dep][1]} dependency {dep}")
        elif cfg and _any_name(names, (cfg,)):
            present[label] = ("", first(_any_name(names, (cfg,))))
    for dep, label in JS_MAIN:
        if label in present:
            main = (label, present[label][0])
            break
    for label, (ver, evd) in present.items():
        facts.append(fact("framework", label, ver, evd))
    tools = {"build": [], "test": [], "lint": []}
    for label, kind, depnames, cfgs in JS_TOOLS:
        hit = next((d for d in depnames if d in deps), "")
        evd, ver = "", ""
        if hit:
            evd, ver = f"{deps[hit][1]} dependency {hit}", major(deps[hit][0])
        elif cfgs and _any_name(names, cfgs):
            evd = first(_any_name(names, cfgs))
        elif label == "ESLint" and any("next lint" in v or v.startswith("eslint") for v in scripts.values()):
            evd = f"{scripts_from} scripts"
        if not evd:
            continue
        facts.append(fact(kind, label, ver, evd))
        if kind in tools:
            tools[kind].append(label)
    if any("--turbo" in v or "turbopack" in v.lower() for k, v in scripts.items() if k in ("dev", "build")) and main and main[0] == "Next.js":
        facts.append(fact("build", "Turbopack", "", f"{scripts_from} scripts use --turbo"))
        tools["build"].insert(0, "Turbopack")
    if any(k.startswith("@testing-library/") for k in deps):
        k = next(k for k in deps if k.startswith("@testing-library/"))
        facts.append(fact("test", "Testing Library", major(deps[k][0]), f"{deps[k][1]} dependency {k}"))
    facts.append(fact("runtime", "Node", engines, f"{ev} engines.node" if engines else ev))
    labels = {f["name"] for f in facts}
    # what kind of application
    app = "unknown"
    if main and main[0] in JS_MOBILE:
        app = "mobile"
    elif main and main[0] in JS_UI:
        app = "web-ui"
    elif main and main[0] in JS_SERVER:
        app = "web-api"
    else:
        first_pj = pjs[0][1] if pjs else {}
        if isinstance(first_pj.get("bin"), (str, dict)):
            app = "cli"
        elif any(k in first_pj for k in ("main", "module", "exports", "types")) or "tsup" in labels:
            app = "library"
    # the sentence pieces
    if main and main[0] in JS_SERVER:
        head, withs = "Node", [main[0]]
    elif main:
        head, withs = (main[0] + (" " + main[1] if main[1] else "")), []
    else:
        head, withs = "Node", []
    builds = [t for t in tools["build"] if t in ("Turbopack", "Vite", "webpack", "esbuild", "tsup")]
    withs += builds
    withs += [x for x in ("TypeScript", "Tailwind") if x in labels]
    unit = [t for t in tools["test"] if t in ("Vitest", "Jest", "Mocha")]
    e2e = [t for t in tools["test"] if t in ("Playwright", "Cypress")]
    tests = unit[:1] + e2e[:1]
    return {"eco": "js", "facts": facts, "run": run, "app": app, "head": head, "with": withs, "tests": tests, "lints": tools["lint"][:1], "pm": pm,
            "recognised": bool(main or tools["build"] or tools["test"] or tools["lint"]), "main": main[0] if main else "", "ui": bool(main and main[0] in JS_UI | JS_MOBILE),
            "lock": bool(lock), "deps": bool(deps), "_deps": deps}


def _py_stack(root, names, first, files, dirs, prof):
    manifests = [m for m in ("pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "setup.cfg", "tox.ini") if m in names]
    cfgfiles = [n for n in ("pytest.ini", "conftest.py", "ruff.toml", ".ruff.toml", "mypy.ini", ".flake8") if n in names]
    pytest_cmd = next((c["evidence"][0] for c in prof["commands"] if c["name"] == "test: python -m pytest"), "")
    if not manifests and not cfgfiles and not pytest_cmd:
        return None
    anchor = first(manifests[0]) if manifests else first(cfgfiles[0]) if cfgfiles else pytest_cmd
    texts = {m: read_small(root, first(m)).lower() for m in manifests}
    allt = "\n".join(texts.values())
    dep = lambda d: re.search(r"(^|[\s\"'\[,])" + re.escape(d) + r"([\s=<>~!\]\"',;\[]|$)", allt, re.M)
    facts = []
    where = lambda needle, d: next((f"{first(m)} lists {d}" for m in manifests if needle in texts[m]), f"{anchor} lists {d}")
    pm, pm_ev = "pip", ""
    if "[tool.poetry" in allt or "poetry.lock" in names:
        pm, pm_ev = "poetry", first("poetry.lock") if "poetry.lock" in names else where("[tool.poetry", "poetry")
    elif "[tool.uv" in allt or "uv.lock" in names:
        pm, pm_ev = "uv", first("uv.lock") if "uv.lock" in names else where("[tool.uv", "uv")
    elif "[tool.pdm" in allt or "pdm.lock" in names:
        pm, pm_ev = "pdm", first("pdm.lock") if "pdm.lock" in names else where("[tool.pdm", "pdm")
    elif "Pipfile" in names:
        pm, pm_ev = "pipenv", first("Pipfile")
    else:
        pm_ev = anchor
    if pm in ("uv", "pdm"):
        add(prof, "package_managers", pm, pm_ev)
    facts.append(fact("package_manager", pm, "", ("lockfile " if pm_ev.endswith(".lock") else "") + pm_ev))
    if "hatch" in allt:
        facts.append(fact("tool", "Hatch", "", where("hatch", "hatch")))
    elif "setuptools" in allt:
        facts.append(fact("tool", "setuptools", "", where("setuptools", "setuptools")))
    main = ""
    for d, label in PY_FRAMEWORKS:
        if dep(d):
            facts.append(fact("framework", label, "", where(d, d)))
            main = main or label
    tests, lints = [], []
    pyt_ev = next((first(n) for n in ("pytest.ini", "conftest.py") if n in names), "")
    if dep("pytest") or "[tool.pytest" in allt or pyt_ev or pytest_cmd:
        evd = where("pytest", "pytest") if dep("pytest") or "[tool.pytest" in allt else pyt_ev or pytest_cmd
        facts.append(fact("test", "pytest", "", evd))
        tests.append("pytest")
    if "tox.ini" in names:
        facts.append(fact("tool", "tox", "", first("tox.ini")))
    run = {k: "" for k in RUN_KEYS}
    if tests:
        run["test"] = "python -m pytest"
    ruff = dep("ruff") or "[tool.ruff" in allt or "ruff.toml" in names or ".ruff.toml" in names
    black = dep("black") or "[tool.black" in allt
    mypy = dep("mypy") or "[tool.mypy" in allt or "mypy.ini" in names
    if ruff:
        facts.append(fact("lint", "ruff", "", where("ruff", "ruff") if dep("ruff") or "[tool.ruff" in allt else first("ruff.toml") if "ruff.toml" in names else first(".ruff.toml")))
        lints.append("ruff")
        run["lint"] = "ruff check ."
    if black:
        facts.append(fact("tool", "black", "", where("black", "black")))
        if not ruff:
            lints.append("black")
            run["lint"] = "black --check ."
    if mypy:
        facts.append(fact("tool", "mypy", "", where("mypy", "mypy") if dep("mypy") or "[tool.mypy" in allt else first("mypy.ini")))
        run["typecheck"] = "mypy ."
    facts.append(fact("language", "Python", "", anchor))
    app = "web-api" if main else "unknown"
    return {"eco": "python", "facts": facts, "run": run, "app": app, "head": main or "Python", "with": tests, "tests": [], "lints": lints, "pm": pm,
            "recognised": bool(main or tests or lints), "main": main, "ui": False, "lock": pm_ev.endswith(".lock"), "deps": bool(manifests)}


def _go_stack(root, names, first, files):
    if "go.mod" not in names:
        return None
    ev = first("go.mod")
    text = read_small(root, ev)
    facts, run = [], {k: "" for k in RUN_KEYS}
    m = re.search(r"(?m)^go\s+(\d{1,2}\.\d{1,3})", text)
    ver = m.group(1) if m else ""
    mod = re.search(r"(?m)^module\s+([A-Za-z0-9._/~-]{1,100})\s*$", text)
    facts.append(fact("language", "Go", ver, f"{ev}" + (f" (module {mod.group(1)})" if mod else "")))
    main = ""
    for needle, label in GO_FRAMEWORKS:
        if needle in text:
            facts.append(fact("framework", label, "", f"{ev} requires {needle}"))
            main = main or label
    facts.append(fact("package_manager", "go modules", "", ev))
    facts.append(fact("test", "go test", "", ev))
    run["test"], run["build"] = "go test ./...", "go build ./..."
    lints = []
    gl = _any_name(names, (".golangci.",))
    if gl:
        facts.append(fact("lint", "golangci-lint", "", first(gl)))
        lints.append("golangci-lint")
        run["lint"] = "golangci-lint run"
    else:
        run["lint"] = "go vet ./..."
    if "main.go" in names and "main.go" in files:
        run["start"] = "go run ."
    app = "web-api" if main else ("cli" if "main.go" in files or any(f.startswith("cmd/") for f in files) else "library")
    return {"eco": "go", "facts": facts, "run": run, "app": app, "head": "Go" + (" " + ver if ver else ""), "with": [main] if main else [], "tests": ["go test"], "lints": lints,
            "pm": "", "recognised": True, "main": main, "ui": False, "lock": "go.sum" in names, "deps": "go.sum" in names or "require" in text}


def _rust_stack(root, names, first, files):
    if "Cargo.toml" not in names:
        return None
    ev = first("Cargo.toml")
    text = read_small(root, ev)
    facts, run = [], {k: "" for k in RUN_KEYS}
    m = re.search(r'(?m)^\s*edition\s*=\s*"(\d{4})"', text)
    ed = m.group(1) if m else ""
    facts.append(fact("language", "Rust", ed, ev + (" (edition)" if ed else "")))
    main, kinds = "", set()
    for dep, label, kind in RUST_FRAMEWORKS:
        if re.search(r"(?m)^\s*(?:\[(?:dev-|build-)?dependencies\.)?" + re.escape(dep) + r"\s*[=\]\.]", text):
            facts.append(fact(kind, label, "", f"{ev} lists {dep}"))
            kinds.add(label)
            if label in ("Axum", "Actix", "Rocket") and not main:
                main = label
    facts.append(fact("package_manager", "cargo", "", ev))
    facts.append(fact("test", "cargo test", "", ev))
    cl = _any_name(names, ("clippy.toml", ".clippy.toml"))
    facts.append(fact("lint", "Clippy", "", first(cl) if cl else ev + " (cargo clippy ships with the Rust toolchain)"))
    rf = _any_name(names, ("rustfmt.toml", ".rustfmt.toml"))
    if rf:
        facts.append(fact("tool", "rustfmt", "", first(rf)))
    run["test"], run["build"], run["lint"] = "cargo test", "cargo build", "cargo clippy"
    run["start"] = "cargo run"
    app = "web-api" if main else "cli" if "clap" in kinds or "src/main.rs" in files else "library" if "src/lib.rs" in files else "unknown"
    return {"eco": "rust", "facts": facts, "run": run, "app": app, "head": "Rust" + (f" ({ed} edition)" if ed else ""), "with": [main] if main else [], "tests": ["cargo test"],
            "lints": ["Clippy"], "pm": "", "recognised": True, "main": main, "ui": False, "lock": "Cargo.lock" in names, "deps": True}


def stack_of(root, names, first, files, dirs, prof, js):
    """The `stack` object of the profile: {summary, facts, app, runnable}, plus what the duty suggestions read (ui, lockfile, dependencies)."""
    notes = prof["notes"]
    ecos = [e for e in (js, _py_stack(root, names, first, files, dirs, prof), _go_stack(root, names, first, files),
                        _rust_stack(root, names, first, files)) if e]
    for e in ecos:
        if e["eco"] in ("go", "rust"):
            for f in e["facts"]:
                if f["kind"] == "framework":
                    add(prof, "frameworks", f["name"], f["evidence"])
    out = {"summary": "", "facts": [], "app": "unknown", "runnable": {k: "" for k in RUN_KEYS}, "ui": False, "lockfile": False, "dependencies": False}
    langs = ", ".join(f"{l['name']} ({l['evidence'][0].split(' ', 1)[0]})" for l in prof["languages"][:4])
    if not ecos:
        out["summary"] = langs or "no language recognised"
        return out
    count = lambda *ls: sum(int(i["evidence"][0].split(" ", 1)[0]) for i in prof["languages"] if i["name"] in ls)
    weight = {"js": count("JavaScript", "TypeScript"), "python": count("Python"), "go": count("Go"), "rust": count("Rust")}
    ecos.sort(key=lambda e: (not e["recognised"], -weight[e["eco"]]))
    p = ecos[0]
    for e in ecos:
        out["facts"] += e["facts"]
    out["app"] = p["app"]
    for k in RUN_KEYS:
        v = p["run"].get(k, "")
        out["runnable"][k] = v if CMD_OK.fullmatch(v or "") else ""
    out["ui"], out["lockfile"], out["dependencies"] = p["ui"], any(e["lock"] for e in ecos), any(e["deps"] for e in ecos)
    if not p["recognised"]:
        out["summary"] = langs or "no language recognised"
        return out
    s = p["head"] + (" with " + join_words(p["with"]) if p["with"] else "")
    if p["tests"]:
        s += ", tests by " + join_words(p["tests"])
    if p["lints"]:
        s += ", lint by " + join_words(p["lints"])
    if p["pm"]:
        s += ", package manager " + p["pm"]
    out["summary"] = s
    return out


# What marks a folder as a project of its own (a folder holding any of these is one project, whatever it contains).
PROJECT_MARKERS = {"package.json", "pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
                   "build.gradle.kts", "Gemfile", "composer.json", "Package.swift", "mix.exs", "pubspec.yaml", "deno.json", "CMakeLists.txt", "Makefile", "makefile"}


def _is_project(folder):
    """True when the folder is a repository (.git, a folder or a worktree's file) or holds one of PROJECT_MARKERS."""
    try:
        return os.path.lexists(os.path.join(folder, ".git")) or any(os.path.isfile(os.path.join(folder, m)) for m in PROJECT_MARKERS)
    except OSError:
        return False


def projects_inside(root):
    """Names of the immediate, visible subfolders of `root` that are projects, in name order; [] when `root` is itself a project."""
    if _is_project(root):
        return []
    try:
        subs = sorted(e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and e.name not in SKIP_DIRS)
    except OSError:
        return []
    return [n for n in subs if _is_project(os.path.join(root, n))]


def scan(path):
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"{path} is not a folder")
    inside = projects_inside(root)
    if len(inside) >= 2:                       # no project marker of its own, two or more projects below: a folder of projects, as the home folder is
        raise ValueError(f"{path} is a whole folder of projects, not one project. Choose the project's own folder inside it (for example {', '.join(inside[:3])})")
    entries = walk(root)
    files = [p for p, d in entries if not d]
    dirs = [p for p, d in entries if d]
    base = lambda p: p.rsplit("/", 1)[-1]
    prof = {"path": str(root), "name": root.name, "languages": [], "frameworks": [], "package_managers": [], "commands": [], "ci": [], "containers": [],
            "infrastructure": [], "deploy_targets": [], "sensitive": [], "secret_files": [], "agent_config": [], "git": {}, "notes": [], "stack": {}}

    # languages: by file extension, evidence is how many files
    counts = {}
    for f in files:
        lang = LANG_EXT.get(os.path.splitext(f)[1].lower())
        if lang:
            counts.setdefault(lang, []).append(f)
    for lang, fs in sorted(counts.items(), key=lambda kv: -len(kv[1])):
        prof["languages"].append({"name": lang, "evidence": [f"{len(fs)} file(s), e.g. {fs[0]}"]})

    names = {}
    for f in files:
        names.setdefault(base(f), []).append(f)
    first = lambda n: names[n][0]

    # package managers, commands, frameworks from manifests. The Node side is read once, with the stack (nearest package.json first, nested ones fill the gaps)
    js = _js_stack(root, names, first, prof, prof["notes"])
    if js:
        deps = js["_deps"]
        for dep, label in (("react", "React"), ("next", "Next.js"), ("vue", "Vue"), ("svelte", "Svelte"), ("express", "Express"), ("fastify", "Fastify"),
                           ("serverless", "Serverless Framework"), ("aws-cdk-lib", "AWS CDK"), ("vite", "Vite"), ("react-native", "React Native"), ("expo", "Expo"),
                           ("jest", "Jest"), ("vitest", "Vitest"), ("playwright", "Playwright"), ("@playwright/test", "Playwright"), ("nuxt", "Nuxt"),
                           ("@sveltejs/kit", "SvelteKit"), ("astro", "Astro"), ("@angular/core", "Angular"), ("@nestjs/core", "NestJS"), ("cypress", "Cypress"),
                           ("mocha", "Mocha"), ("webpack", "webpack")):
            if dep in deps:
                add(prof, "frameworks", label, f"{deps[dep][1]} dependency {dep}")
    for req in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py"):
        if req in names:
            ev = first(req)
            text = read_small(root, ev).lower()
            add(prof, "package_managers", "poetry" if "[tool.poetry" in text else "pipenv" if req == "Pipfile" else "pip", ev)
            for dep, label in (("django", "Django"), ("flask", "Flask"), ("fastapi", "FastAPI"), ("pytest", "pytest"), ("sqlalchemy", "SQLAlchemy")):
                if re.search(r"(^|[\s\"'\[,])" + dep + r"([\s=<>~!\]\"',;]|$)", text, re.M):
                    add(prof, "frameworks", label, f"{ev} lists {dep}")
            if "pytest" in text or "tests" in dirs or "test" in dirs:
                add(prof, "commands", "test: python -m pytest", ev)
    # pytest without a manifest that names it: its own config files, or test files laid out the way it finds them
    pyt = [f for f in files if base(f) in ("pytest.ini", "conftest.py", "tox.ini")] + \
          [f for f in files if f.endswith(".py") and (base(f).startswith("test_") or base(f).endswith("_test.py"))]
    if pyt and not any(c["name"].startswith("test:") for c in prof["commands"]):
        add(prof, "commands", "test: python -m pytest", pyt[0])
    for manifest, mgr in (("go.mod", "go modules"), ("Cargo.toml", "cargo"), ("pom.xml", "maven"), ("build.gradle", "gradle"), ("build.gradle.kts", "gradle"),
                          ("Gemfile", "bundler"), ("composer.json", "composer"), ("Package.swift", "swift package manager")):
        if manifest in names:
            add(prof, "package_managers", mgr, first(manifest))
    if "go.mod" in names:
        add(prof, "commands", "test: go test ./...", first("go.mod"))
    if "Cargo.toml" in names:
        add(prof, "commands", "test: cargo test", first("Cargo.toml"))
    for mk in ("Makefile", "makefile"):
        if mk in names:
            text = read_small(root, first(mk))
            for target in ("test", "lint", "build", "check"):
                if re.search(r"^" + target + r"\s*:", text, re.M):
                    add(prof, "commands", f"{target}: make {target}", f"{first(mk)} target {target}")

    prof["stack"] = stack_of(root, names, first, files, dirs, prof, js)

    # CI
    for f in files:
        if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")):
            add(prof, "ci", "GitHub Actions", f)
    for f, label in ((".gitlab-ci.yml", "GitLab CI"), ("Jenkinsfile", "Jenkins"), ("azure-pipelines.yml", "Azure Pipelines"), ("bitbucket-pipelines.yml", "Bitbucket Pipelines"), (".circleci/config.yml", "CircleCI")):
        if f in files:
            add(prof, "ci", label, f)

    # containers
    for f in files:
        b = base(f)
        if b == "Dockerfile" or b.startswith("Dockerfile."):
            add(prof, "containers", "Docker", f)
        if b in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            add(prof, "containers", "Docker Compose", f)
        if b in ("Chart.yaml",) or f.startswith(("k8s/", "kubernetes/")):
            add(prof, "containers", "Kubernetes", f)

    # infrastructure and deploy targets, from files only
    for f in files:
        b = base(f)
        if f.endswith(".tf"):
            add(prof, "infrastructure", "Terraform", f)
        if b in ("cdk.json",):
            add(prof, "infrastructure", "AWS CDK", f)
        if b in ("serverless.yml", "serverless.yaml", "serverless.ts"):
            add(prof, "infrastructure", "Serverless Framework", f)
        if b in ("template.yaml", "template.yml") and "AWSTemplateFormatVersion" in read_small(root, f)[:4000]:
            add(prof, "infrastructure", "AWS CloudFormation / SAM", f)
        if b in ("Pulumi.yaml",):
            add(prof, "infrastructure", "Pulumi", f)
        if b in ("vercel.json",) or f == ".vercel/project.json":
            add(prof, "deploy_targets", "Vercel", f)
        if b in ("netlify.toml",):
            add(prof, "deploy_targets", "Netlify", f)
        if b in ("fly.toml",):
            add(prof, "deploy_targets", "Fly.io", f)
        if b in ("app.yaml",) and "runtime:" in read_small(root, f)[:2000]:
            add(prof, "deploy_targets", "Google Cloud App Engine", f)
        if b in ("firebase.json",):
            add(prof, "deploy_targets", "Firebase", f)
        if b in ("wrangler.toml", "wrangler.json", "wrangler.jsonc"):
            add(prof, "deploy_targets", "Cloudflare", f)
        if f.endswith(".bicep"):
            add(prof, "infrastructure", "Azure Bicep", f)
            add(prof, "deploy_targets", "Azure", f)
        if b in ("azure.yaml", "azure.yml"):
            add(prof, "infrastructure", "Azure Developer CLI", f)
            add(prof, "deploy_targets", "Azure", f)
        if b == "host.json" and '"version"' in read_small(root, f)[:2000]:
            add(prof, "deploy_targets", "Azure", f)
        if b in ("cloudbuild.yaml", "cloudbuild.yml", "cloudbuild.json"):
            add(prof, "deploy_targets", "Google Cloud Build", f)
        if b in ("render.yaml",):
            add(prof, "deploy_targets", "Render", f)
        if b in ("Procfile",):
            add(prof, "deploy_targets", "Heroku-style Procfile", f)
    for item in prof["infrastructure"]:
        if item["name"] in ("AWS CDK", "AWS CloudFormation / SAM", "Serverless Framework"):
            add(prof, "deploy_targets", "AWS", item["evidence"][0])
    if "supabase" in dirs or any(f.startswith("supabase/") for f in files):
        add(prof, "deploy_targets", "Supabase", "supabase/")

    # sensitive folders and secret files: names only
    for d in dirs:
        label = SENSITIVE_DIRS.get(base(d).lower())
        if label:
            add(prof, "sensitive", label, d + "/")
    for f in files:
        b = base(f)
        if SECRET_NAME.match(b) and not SECRET_EXAMPLE.search(b):
            add(prof, "secret_files", b, f)

    # agent configuration already in the project
    for f in files:
        b = base(f)
        if b == ".mcp.json":
            add(prof, "agent_config", "MCP servers (.mcp.json)", f)
        elif b in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules", "copilot-instructions.md") or f.startswith((".claude/", ".cursor/rules/")):
            if f.startswith(".claude/agents/"):
                add(prof, "agent_config", "Claude Code agents", f)
            elif f.startswith(".claude/commands/") or f.startswith(".claude/skills/"):
                add(prof, "agent_config", "Claude Code commands and skills", f)
            elif f.startswith(".claude/"):
                add(prof, "agent_config", "Claude Code settings", f)
            else:
                add(prof, "agent_config", b, f)

    # git facts, read from the repository's own files
    gitdir = root / ".git"
    if gitdir.is_dir():
        head = read_small(root, ".git/HEAD").strip()
        prof["git"]["branch"] = head.split("refs/heads/", 1)[-1] if head.startswith("ref:") else "(detached)"
        cfg = read_small(root, ".git/config")
        m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', cfg)
        if m:
            prof["git"]["origin"] = re.sub(r"//[^/@]*@", "//", m.group(1))     # never keep a credential that might sit in the address
    else:
        prof["notes"].append("not a git repository")
    if prof["secret_files"]:
        prof["notes"].append("secret files exist; they were noted by name and never opened")
    if not prof["commands"]:
        prof["notes"].append("no test, lint or build command was found; the verify command must be set by hand")
    return prof


SECRET_IAC = re.compile(r"(\.tfstate(\..+)?|\.tfvars(\.json)?|\.auto\.tfvars)$", re.I)       # Terraform state and variable files: names only, never opened
CODE_EXT = (".ts", ".js", ".mjs", ".py", ".java", ".cs", ".go")
CDK_MARKS = ("aws-cdk-lib", "@aws-cdk/", "aws_cdk", "software.amazon.awscdk", "Amazon.CDK")


def infra_changed(root, paths):
    """Which of these changed paths are infrastructure files, by the same names the scan uses: ([(path, kind)], [secret-looking paths left unopened]).
    Reads only the files named, small ones only, from the folder given; a deleted file is judged by its name alone."""
    out, skipped = [], []
    for rel in paths:
        b = rel.rsplit("/", 1)[-1]
        if SECRET_IAC.search(b) or (SECRET_NAME.match(b) and not SECRET_EXAMPLE.search(b)):
            skipped.append(rel)
            continue
        kind = None
        if rel.endswith((".tf", ".tf.json")):
            kind = "Terraform"
        elif b == "cdk.json":
            kind = "AWS CDK"
        elif b in ("serverless.yml", "serverless.yaml", "serverless.ts", "serverless.js", "serverless.json"):
            kind = "Serverless Framework"
        elif b == "vercel.json" or rel.endswith(".vercel/project.json"):
            kind = "Vercel"
        elif rel.startswith("supabase/"):
            kind = "Supabase"
        elif b in ("samconfig.toml", "samconfig.yaml"):
            kind = "AWS CloudFormation / SAM"
        elif rel.endswith((".bicep", ".bicepparam")):
            kind = "Azure Bicep"
        elif b == "host.json" and '"version"' in read_small(root, rel)[:2000]:
            kind = "Azure Functions"
        elif b in ("azure.yaml", "azure.yml"):
            kind = "Azure Developer CLI"
        elif b in ("wrangler.toml", "wrangler.json", "wrangler.jsonc"):
            kind = "Cloudflare"
        elif b == "fly.toml":
            kind = "Fly.io"
        elif b in ("cloudbuild.yaml", "cloudbuild.yml", "cloudbuild.json"):
            kind = "Google Cloud Build"
        elif b == "app.yaml" and "runtime:" in read_small(root, rel)[:2000]:
            kind = "Google Cloud App Engine"
        elif rel.endswith((".yml", ".yaml", ".json", ".template")):
            head = read_small(root, rel)[:20000]
            if "AWSTemplateFormatVersion" in head or "AWS::Serverless" in head:
                kind = "AWS CloudFormation / SAM"
            elif "schema.management.azure.com" in head and "deploymentTemplate" in head:
                kind = "Azure ARM template"
            elif "serving.knative.dev" in head:
                kind = "Google Cloud Run"
        elif rel.endswith(CODE_EXT):
            head = read_small(root, rel)[:20000]
            if any(m in head for m in CDK_MARKS):
                kind = "AWS CDK"
        if kind:
            out.append((rel, kind))
    return out, skipped


def profile_dir():
    import home as _home
    return _home.resolve() / "state" / "profiles"


def save(prof, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", name):
        raise ValueError("the name may hold letters, digits, dot, dash and underscore")
    d = profile_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    out = d / f"{name}.json"
    out.write_text(json.dumps(prof, indent=2) + "\n")
    os.chmod(out, 0o600)                                   # a map of a project's sensitive folders and secret file names: owner only
    return out


def say(prof):
    print(f"  {prof['name']}  ({prof['path']})")
    st = prof.get("stack") or {}
    if st.get("summary"):
        print(f"    stack: {st['summary']}" + (f" [{st['app']}]" if st.get("app") not in (None, "unknown") else ""))
        for f in st.get("facts", []):
            print(f"      {f['kind']}: {f['name']}{' ' + f['version'] if f['version'] else ''} [{f['evidence']}]")
    for key, title in (("languages", "languages"), ("frameworks", "frameworks"), ("package_managers", "package managers"), ("commands", "commands"), ("ci", "CI"),
                       ("containers", "containers"), ("infrastructure", "infrastructure"), ("deploy_targets", "deploy targets"), ("sensitive", "sensitive areas"),
                       ("secret_files", "secret files (names only)"), ("agent_config", "agent set-up already there")):
        if prof[key]:
            print(f"    {title}: " + "; ".join(f"{i['name']} [{i['evidence'][0]}]" for i in prof[key]))
    if prof["git"]:
        print("    git: " + ", ".join(f"{k} {v}" for k, v in prof["git"].items()))
    for n in prof["notes"]:
        print(f"    note: {n}")


def main(argv):
    args, path, name = list(argv), None, None
    if args[:1] == ["--infra-files"] and len(args) == 2:         # changed paths on stdin, one per line -> "kind<TAB>path" and "secret<TAB>path"
        got, skipped = infra_changed(args[1], [l for l in sys.stdin.read().splitlines() if l])
        print("\n".join([f"{k}\t{p}" for p, k in got] + [f"secret\t{p}" for p in skipped]))
        return 0
    while args:
        a = args.pop(0)
        if a == "--save" and args:
            name = args.pop(0)
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
        prof = scan(path)
        say(prof)
        if name:
            print(f"  saved {save(prof, name)}")
    except ValueError as e:
        print(f"  {e}")
        return 2
    except OSError as e:
        from integrations import common as _common
        print("  " + _common.why_not_saved(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
