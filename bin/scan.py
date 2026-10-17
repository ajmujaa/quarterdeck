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
    except ValueError:
        return {}


def scan(path):
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"{path} is not a folder")
    entries = walk(root)
    files = [p for p, d in entries if not d]
    dirs = [p for p, d in entries if d]
    base = lambda p: p.rsplit("/", 1)[-1]
    prof = {"path": str(root), "name": root.name, "languages": [], "frameworks": [], "package_managers": [], "commands": [], "ci": [], "containers": [],
            "infrastructure": [], "deploy_targets": [], "sensitive": [], "secret_files": [], "agent_config": [], "git": {}, "notes": []}

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

    # package managers, commands, frameworks from manifests
    if "package.json" in names:
        pj = json_of(read_small(root, first("package.json")))
        ev = first("package.json")
        for lock, mgr in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"), ("bun.lockb", "bun")):
            if lock in names:
                add(prof, "package_managers", mgr, first(lock))
        if not any(m["name"] in ("pnpm", "yarn", "npm", "bun") for m in prof["package_managers"]):
            add(prof, "package_managers", "npm", ev)
        for script in ("test", "lint", "build", "dev", "start", "typecheck"):
            if isinstance(pj.get("scripts"), dict) and script in pj["scripts"]:
                add(prof, "commands", f"{script}: npm run {script}" if script != "test" else "test: npm test", f"{ev} scripts.{script}")
        deps = {**(pj.get("dependencies") or {}), **(pj.get("devDependencies") or {})}
        for dep, label in (("react", "React"), ("next", "Next.js"), ("vue", "Vue"), ("svelte", "Svelte"), ("express", "Express"), ("fastify", "Fastify"),
                           ("serverless", "Serverless Framework"), ("aws-cdk-lib", "AWS CDK"), ("vite", "Vite"), ("react-native", "React Native"), ("expo", "Expo"),
                           ("jest", "Jest"), ("vitest", "Vitest"), ("playwright", "Playwright"), ("@playwright/test", "Playwright")):
            if dep in deps:
                add(prof, "frameworks", label, f"{ev} dependency {dep}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
