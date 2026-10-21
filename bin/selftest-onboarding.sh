#!/bin/bash
# Smoother first run (round 2 brief, section 7): one path from a clean machine to "ready".
# Everything runs in throwaway folders: the program is copied to $T/prog, the data folder is $T/data (with the .quarterdeck-home marker), HOME is $T/home, and the
# tools the checklist looks for are stand-ins on a private PATH. No network, no GitHub (QUARTERDECK_GH is a stand-in), no model, no real ~/.quarterdeck, ~/.config,
# LaunchAgents, keychain or port 7878. Nothing is published, and no package manager is run.
#
#   1  packaging      the Homebrew formula (structure, placeholders, ruby -c when ruby is here), bin/release.py (fills copies, refuses bad input, no network, no
#                     publish), the npm package and its shim (a Python version gate with fake interpreters, the override, exit status, arguments with spaces and
#                     quotes, a missing Python or program, no network and no install script), tested offline with node
#   2  firstrun.py    the facts with fake tools on PATH: have, lack and unknown, the fix commands, and no secret in any output
#   3  the API        GET and POST /api/firstrun on a real paired dashboard with a fresh data folder
#   4  privacy scan   the narrow clipboard allowance: one write-only call in one named function, and every read form still fails
#   5  the page       in a headless browser (skipped, saying so, when none starts here): the first-run panel, Copy, Look around in Demo, then the guided attach panel
# QD_KEEP=1 keeps the throwaway folder; QD_KEEP_SHOTS=<folder> copies the pictures the page checks take there.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
P="$T/prog"; D="$T/data"; H="$T/home"; S="$T/shim"
mkdir -p "$P" "$D"/{config,state,logs,workspace} "$H" "$T/stub" "$T/secrets"
for d in bin dashboard packs duties crew config providers; do [ -d "$REAL/$d" ] && cp -R "$REAL/$d" "$P/"; done
rm -rf "$P/config/projects.json" "$P/bin/__pycache__" "$P/bin/integrations/__pycache__"
touch "$D/.quarterdeck-home"; chmod 700 "$T/secrets"
export HOME="$H" XDG_CONFIG_HOME="$H/.config" QUARTERDECK_HOME="$D" QUARTERDECK_SECRETS_DIR="$T/secrets" PYTHONDONTWRITEBYTECODE=1 REAL T P D H
unset QUARTERDECK_DIR CLAUDE_BIN QUARTERDECK_GH QUARTERDECK_PROJECT_ROOTS
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT

pyck() { # pyck <file.py>: each "ok ..." / "FAIL ..." line of its output is one check; a block that crashes is one failed check
  local line out
  out=$(python3 "$1" 2>&1); local rc=$?
  while IFS= read -r line; do
    case "$line" in
      "ok "*) printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
      "skip "*) printf '  skip  %s\n' "${line#skip }" ;;
      *) [ -z "$line" ] || [ "$rc" = 0 ] || { printf '  FAIL  crashed: %s\n' "$line"; fails=$((fails + 1)); } ;;
    esac
  done <<<"$out"
}

# ============================== 1. packaging ==============================
echo "-- packaging --"
cat > "$T/formula-check.py" <<'PY'
import os, re
R = os.environ["REAL"]
t = open(R + "/packaging/homebrew/qtdeck.rb").read()
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:300]))
body = re.sub(r"<<~(\w+)\n.*?\n\s*\1\n", "<<~HEREDOC\n", t, flags=re.S)         # a heredoc's text is not code
openers = len(re.findall(r"^\s*(?:class|def)\b|\bdo(?:\s*\|[^|]*\|)?\s*$", body, flags=re.M))
ends = len(re.findall(r"^\s*end\s*$", body, flags=re.M))
chk("the formula is class Qtdeck with desc, homepage, license Apache-2.0 and a url, sha256 and version", bool(re.search(r"^class Qtdeck < Formula$", t, re.M)) and all(re.search(r'^\s*%s "' % k, t, re.M) for k in ("desc", "homepage", "url", "sha256", "version")) and 'license "Apache-2.0"' in t)
chk("  do/def/class and end are balanced", openers == ends and openers >= 4, (openers, ends))
chk("  each placeholder (@URL@, @SHA256@, @VERSION@) is present exactly once, and there are no others", all(t.count(x) == 1 for x in ("@URL@", "@SHA256@", "@VERSION@")) and sorted(set(re.findall(r"@[A-Z0-9_]+@", t))) == ["@SHA256@", "@URL@", "@VERSION@"])
chk("  it depends on python@3.12, jq, gh and git", all(('depends_on "%s"' % d) in t for d in ("python@3.12", "jq", "gh", "git")))
inst = re.search(r"def install\n(.*?)\n  end\n", t, re.S)
chk("  the install block installs the tree into libexec and writes a bin/qtdeck shim, with no network call and no secret", bool(inst) and "libexec.install" in inst.group(1) and 'bin/"qtdeck"' in inst.group(1) and not re.search(r"curl|wget|http|system|ENV\[|token|secret|password|key", inst.group(1), re.I), inst and inst.group(1))
chk("  the shim leaves QUARTERDECK_DIR to the program (it sets no such variable) and runs libexec/bin/qtdeck", "QUARTERDECK_DIR" not in t and '#{libexec}/bin/qtdeck" "$@"' in t)
chk("  the test block runs qtdeck help and checks a line; the caveats point at qtdeck setup", re.search(r'test do\n.*shell_output\("#\{bin\}/qtdeck help"\)', t, re.S) is not None and "Usage: qtdeck" in t and "qtdeck setup" in t.split("def caveats")[1])
chk("  no em or en dash in it", "\u2014" not in t and "\u2013" not in t)
PY
pyck "$T/formula-check.py"
if command -v ruby >/dev/null 2>&1; then
  ck "ruby -c accepts the formula" 'ruby -c "$REAL/packaging/homebrew/qtdeck.rb" >/dev/null 2>&1'
else
  st_skip "ruby is not on this machine: the formula was checked by structure only"
fi

cat > "$T/release-check.py" <<'PY'
import hashlib, json, os, re, subprocess, sys, tarfile
R, T = os.environ["REAL"], os.environ["T"]
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:400]))
rel = [sys.executable, R + "/bin/release.py"]
tb = T + "/v9.tar.gz"
with tarfile.open(tb, "w:gz") as t:
    info = tarfile.TarInfo("quarterdeck-9.9.9/README.md"); data = b"hello\n"; info.size = len(data)
    import io; t.addfile(info, io.BytesIO(data))
sha = hashlib.sha256(open(tb, "rb").read()).hexdigest()
log = T + "/netlog"
os.makedirs(T + "/spy", exist_ok=True)
for tool in ("npm", "brew", "curl", "wget"):
    open(T + "/spy/" + tool, "w").write('#!/bin/bash\necho "%s $*" >> "%s"\nexit 0\n' % (tool, log)); os.chmod(T + "/spy/" + tool, 0o755)
real_git = subprocess.run("command -v git", shell=True, capture_output=True, text=True).stdout.strip()
open(T + "/spy/git", "w").write('#!/bin/bash\necho "git $*" >> "%s"\nexec "%s" "$@"\n' % (log, real_git)); os.chmod(T + "/spy/git", 0o755)
env = dict(os.environ, PATH=T + "/spy:" + os.environ["PATH"])
out = T + "/rel1"
r = subprocess.run(rel + ["9.9.9", "--tarball", tb, "--out", out], capture_output=True, text=True, env=env)
f = open(out + "/homebrew/qtdeck.rb").read() if r.returncode == 0 else ""
chk("release.py fills a COPY of the formula: the default URL pattern, the sha256 of the given tarball and the version, no placeholder left", r.returncode == 0 and "https://github.com/ajmujaa/quarterdeck/archive/refs/tags/v9.9.9.tar.gz" in f and sha in f and 'version "9.9.9"' in f and not re.search(r"@[A-Z0-9_]+@", f), r.stdout + r.stderr)
chk("  the source formula is untouched", open(R + "/packaging/homebrew/qtdeck.rb").read().count("@URL@") == 1)
r2 = subprocess.run(rel + ["9.9.9", "--tarball", tb, "--url", "https://example.invalid/x.tgz", "--out", T + "/rel2"], capture_output=True, text=True, env=env)
chk("  --url is used instead of the pattern", r2.returncode == 0 and 'url "https://example.invalid/x.tgz"' in open(T + "/rel2/homebrew/qtdeck.rb").read())
chk("  it prints what to do next in plain words, and says nothing was published", "nothing was published" in r.stdout.lower() and "what to do next" in r.stdout.lower() and "\u2014" not in r.stdout and "\u2013" not in r.stdout, r.stdout)
r3 = subprocess.run(rel + ["9.9.9", "--npm", "--out", T + "/rel3"], capture_output=True, text=True, env=env)
pj = json.load(open(T + "/rel3/npm/package.json")) if r3.returncode == 0 else {}
chk("  --npm fills a copy of package.json (version set, bin, private still true) and the shim and README", pj.get("version") == "9.9.9" and pj.get("private") is True and pj.get("bin") == {"qtdeck": "bin/qtdeck.js"} and os.path.isfile(T + "/rel3/npm/bin/qtdeck.js") and os.path.isfile(T + "/rel3/npm/README.md"), r3.stdout + r3.stderr)
inrepo = subprocess.run(["git", "-C", R, "rev-parse", "--git-dir"], capture_output=True).returncode == 0
if inrepo:
    chk("  --npm copies the tracked files into app/ (the program, not packaging/ and not dist/)", os.path.isfile(T + "/rel3/npm/app/bin/qtdeck") and os.path.isfile(T + "/rel3/npm/app/dashboard/index.html") and not os.path.exists(T + "/rel3/npm/app/packaging"), r3.stdout + r3.stderr)
else:
    print("skip this copy is not a git checkout: the app/ copy was not checked")
bad = [("1.2", ["1.2", "--tarball", tb]), ("v1.2.3", ["v1.2.3", "--tarball", tb]), ("1.2.3; rm -rf x", ["1.2.3; rm -rf x", "--tarball", tb]), ("empty", ["", "--tarball", tb])]
for label, a in bad:
    rb = subprocess.run(rel + a + ["--out", T + "/relbad"], capture_output=True, text=True, env=env)
    chk(f"  a malformed version ({label!r}) is refused, with a plain message and nothing written", rb.returncode != 0 and "version" in rb.stderr and not os.path.exists(T + "/relbad"), rb.stderr)
rm = subprocess.run(rel + ["1.2.3", "--tarball", T + "/nope.tgz", "--out", T + "/relbad"], capture_output=True, text=True, env=env)
chk("  a missing tarball is refused and nothing is written", rm.returncode != 0 and "no tarball" in rm.stderr and not os.path.exists(T + "/relbad"), rm.stderr)
rn = subprocess.run(rel + ["1.2.3", "--out", T + "/relbad"], capture_output=True, text=True, env=env)
chk("  with neither --tarball nor --npm it asks for one", rn.returncode != 0 and "--tarball" in rn.stderr)
if inrepo:
    rt = subprocess.run(rel + ["--make-tarball", "9.9.9", "--out", T + "/rel4"], capture_output=True, text=True, env=env)
    names = tarfile.open(T + "/rel4/quarterdeck-9.9.9.tar.gz").getnames() if rt.returncode == 0 else []
    chk("  --make-tarball builds a tarball of the tracked files with git archive", "quarterdeck-9.9.9/bin/qtdeck" in names and "quarterdeck-9.9.9/dashboard/index.html" in names, rt.stdout + rt.stderr)
calls = open(log).read().splitlines() if os.path.exists(log) else []
chk("  across all of that: npm, brew, curl and wget were never started, and git was only asked to list or archive the tracked files", not any(c.split()[0] in ("npm", "brew", "curl", "wget") for c in calls) and all(re.match(r"git (-C \S+ )?(ls-files|archive|rev-parse)", c) for c in calls if c.startswith("git")), calls)
src = open(R + "/bin/release.py").read()
chk("  release.py imports nothing that reaches the network and has no push, publish or upload call", not re.search(r"^\s*(?:import|from)\s+(?:socket|urllib|http|requests|ssl|ftplib|smtplib)", src, re.M) and not re.search(r'"(?:push|publish|upload|remote|fetch|clone)"', src))
chk("  .gitignore keeps dist/release/ out of git", "dist/release/" in open(R + "/.gitignore").read())
PY
pyck "$T/release-check.py"

cat > "$T/npm-check.py" <<'PY'
import json, os, re
R = os.environ["REAL"]
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:300]))
pj = json.load(open(R + "/packaging/npm/package.json"))
chk("the npm package is qtdeck with a bin shim, node 20 or newer, Apache-2.0 and a version placeholder", pj["name"] == "qtdeck" and pj["bin"] == {"qtdeck": "bin/qtdeck.js"} and pj["engines"]["node"] == ">=20" and pj["license"] == "Apache-2.0" and pj["version"] == "@VERSION@")
chk("  it is private until the owner flips it, has no dependencies and no scripts (so no install script)", pj.get("private") is True and not any(k in pj for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies", "scripts", "bundledDependencies")), list(pj))
js = open(R + "/packaging/npm/bin/qtdeck.js").read()
mods = sorted(set(re.findall(r'require\("([^"]+)"\)', js)))
chk("  the shim requires only child_process, fs, os and path, and has no network call", mods == ["node:child_process", "node:fs", "node:os", "node:path"] and not re.search(r"https?://|fetch\(|\.connect\(|XMLHttp|WebSocket|dns|net\b", js), mods)
chk("  the shim uses no shell (it spawns bash with the arguments as a list)", "shell:" not in js and not re.search(r"(?<![.\w])exec\(|execSync|execFile", js) and "spawnSync(\"bash\", [" in js)
txt = js + open(R + "/packaging/npm/README.md").read() + json.dumps(pj)
chk("  no em or en dash in the package text", "\u2014" not in txt and "\u2013" not in txt)
PY
pyck "$T/npm-check.py"

if command -v node >/dev/null 2>&1; then
  mkdir -p "$S/bin"; ln -s "$(command -v bash)" "$S/bin/bash"
  mkfake_py() { # mkfake_py <dir> <name> <major> <minor>: a stand-in interpreter that answers the version question (and where it is), nothing else
    mkdir -p "$1"
    cat > "$1/$2" <<EOF
#!/bin/bash
case "\$*" in
  *version_info*) echo "$3 $4" ;;
  *sys.executable*) echo "$1/$2" ;;
  *) echo "fake python got: \$*" ;;
esac
EOF
    chmod +x "$1/$2"
  }
  mkfake_py "$S/p39" python3 3 9; mkfake_py "$S/p312" python 3 12; mkfake_py "$S/q312" python3 3 12; mkfake_py "$S/q39" python 3 9
  mkdir -p "$S/app/bin" "$S/pkg/bin" "$S/pkg/app/bin" "$S/clone/packaging/npm/bin" "$S/clone/bin" "$S/bare/bin"
  cat > "$S/app/bin/qtdeck" <<'EOF'
#!/bin/bash
if [ "${1:-}" = "--status" ]; then exit "${2:-0}"; fi
printf 'argc=%s\n' "$#"
for a in "$@"; do printf '[%s]\n' "$a"; done
printf 'foo=%s\n' "${FOO:-}"
printf 'path=%s\n' "$PATH"
printf 'py=%s\n' "$(command -v python3)"
EOF
  chmod +x "$S/app/bin/qtdeck"
  cp "$S/app/bin/qtdeck" "$S/pkg/app/bin/qtdeck"; cp "$S/app/bin/qtdeck" "$S/clone/bin/qtdeck"
  for dest in "$S/pkg/bin" "$S/clone/packaging/npm/bin" "$S/bare/bin"; do cp "$REAL/packaging/npm/bin/qtdeck.js" "$dest/qtdeck.js"; done
  cat > "$T/shim-check.mjs" <<'JS'
import {spawnSync} from "node:child_process";
import fs from "node:fs";
const S = process.env.S, SHIM = S + "/bare/bin/qtdeck.js";
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra !== undefined ? " | " + String(extra).slice(0, 400) : "")); } };
const run = (args, env, shim = SHIM) => { const r = spawnSync(process.execPath, [shim, ...args], {env: {FOO: "bar", ...env}, encoding: "utf8"}); return {code: r.status, out: r.stdout || "", err: r.stderr || ""}; };
const B = S + "/bin", APP = {QUARTERDECK_APP: S + "/app"};
let r = run([], {PATH: S + "/p39:" + B, ...APP});
ok("the shim: Python 3.9 is refused (nothing runs), with a plain two-line message naming 3.10 and how to install, exit 127", r.code === 127 && r.out === "" && r.err.trim().split("\n").length === 2 && /3\.10/.test(r.err) && /install/i.test(r.err), JSON.stringify(r));
r = run(["a"], {PATH: S + "/q312:" + B, ...APP});
ok("  Python 3.12 as python3 runs the program, with PATH and the other variables passed through unchanged", r.code === 0 && r.out.includes("path=" + S + "/q312:" + B + "\n") && r.out.includes("foo=bar") && r.out.includes("py=" + S + "/q312/python3"), JSON.stringify(r));
r = run([], {PATH: S + "/p39:" + S + "/p312:" + B, ...APP});
ok("  python3 too old but python new enough: python is used, and the program's python3 means it", r.code === 0 && /py=.*qtdeck-py-.*\/python3/.test(r.out) && /path=.*qtdeck-py-/.test(r.out), JSON.stringify(r));
r = run([], {PATH: S + "/p39:" + B, QUARTERDECK_PYTHON: S + "/p312/python", ...APP});
ok("  QUARTERDECK_PYTHON names the interpreter to use", r.code === 0, JSON.stringify(r));
r = run([], {PATH: S + "/q312:" + B, QUARTERDECK_PYTHON: S + "/q39/python", ...APP});
ok("  an override that is too old is not trusted: the next candidate is tried", r.code === 0, JSON.stringify(r));
r = run([], {PATH: B, ...APP});
ok("  no Python at all: the same two-line message, exit 127", r.code === 127 && r.err.trim().split("\n").length === 2, JSON.stringify(r));
r = run(["--status", "7"], {PATH: S + "/q312:" + B, ...APP});
ok("  the program's exit status is the shim's", r.code === 7, JSON.stringify(r));
const odd = ["a b", "it's", 'say "hi"', "$HOME", "*", ";echo pwned", "`id`", "", "--flag=x y", "\\n"];
r = run(odd, {PATH: S + "/q312:" + B, ...APP});
const want = ["argc=" + odd.length, ...odd.map(a => "[" + a + "]")].join("\n");
ok("  arguments with spaces, quotes, a dollar sign, a star, a semicolon, backticks, an empty one and a backslash reach the program exactly as typed (no shell)", r.out.startsWith(want + "\n") && !r.out.includes("pwned\n[") , JSON.stringify(r.out.slice(0, 300)));
r = run([], {PATH: S + "/q312:" + B});
ok("  no program anywhere: a two-line message saying how to fix it, exit 127", r.code === 127 && r.err.trim().split("\n").length === 2 && /QUARTERDECK_APP/.test(r.err), JSON.stringify(r));
r = run(["x"], {PATH: S + "/q312:" + B}, S + "/pkg/bin/qtdeck.js");
ok("  the package's own app/ folder is used when there is no override", r.code === 0 && r.out.includes("[x]"), JSON.stringify(r));
r = run(["y"], {PATH: S + "/q312:" + B}, S + "/clone/packaging/npm/bin/qtdeck.js");
ok("  run from a clone, the clone's own bin/qtdeck is used", r.code === 0 && r.out.includes("[y]"), JSON.stringify(r));
ok("  nothing is left behind in the temp folder by the python3 stand-in", fs.readdirSync(process.env.TMPDIR || "/tmp").filter(n => n.startsWith("qtdeck-py-")).length === 0);
process.exit(bad ? 1 : 0);
JS
  SHIMOUT=$(S="$S" node "$T/shim-check.mjs" 2>&1)
  while IFS= read -r line; do
    case "$line" in
      "ok "*) printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
      *) [ -z "$line" ] || { printf '  FAIL  the shim check crashed: %s\n' "$line"; fails=$((fails + 1)); } ;;
    esac
  done <<<"$SHIMOUT"
else
  st_skip "node is not here: the npm shim checks are not run"
fi

# ============================== 2. firstrun.py ==============================
echo "-- the facts (bin/firstrun.py) --"
mkstub() { # mkstub <dir> <name> <body>
  mkdir -p "$1"; printf '#!/bin/bash\n%s\n' "$3" > "$1/$2"; chmod +x "$1/$2"
}
mkstub "$T/f-all" claude 'echo "token sk-ant-LEAKME-12345"; exit 0'
mkstub "$T/f-all" gh '[ "$1 $2" = "auth status" ] && { echo "Logged in as LEAKME-user"; exit 0; }; exit 0'
mkstub "$T/f-all" git 'exit 0'; mkstub "$T/f-all" node 'exit 0'
mkstub "$T/f-out" claude '[ "$1 $2" = "auth status" ] && exit 1; exit 0'
mkstub "$T/f-out" gh '[ "$1 $2" = "auth status" ] && exit 1; exit 0'
SLEEP=$(command -v sleep)
mkstub "$T/f-hang" claude "exec $SLEEP 30"
mkstub "$T/f-hang" gh "exec $SLEEP 30"
mkdir -p "$T/f-none"
mkdir -p "$T/secrets"
cat > "$T/facts-check.py" <<'PY'
import json, os, subprocess, sys
R, T = os.environ["REAL"], os.environ["T"]
sys.path.insert(0, R + "/bin")
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:400]))
def facts(path_dir, **kw):
    """firstrun.facts() in a child process whose PATH is only the stand-ins (and the basics bash needs), printed as JSON."""
    code = "import json,sys; sys.path.insert(0, %r); import firstrun; print(json.dumps(firstrun.facts(%s)))" % (R + "/bin", ", ".join(f"{k}={v!r}" for k, v in kw.items()))
    env = dict(os.environ, PATH=path_dir + os.pathsep + T + "/basics")
    for k in ("CLAUDE_BIN", "QUARTERDECK_GH"): env.pop(k, None)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr}
os.makedirs(T + "/basics", exist_ok=True)
by = lambda rows: {x["key"]: x for x in rows}
a = by(facts(T + "/f-all", key=False))
chk("every item has exactly key, label, state, detail and fix; the state is have, lack or unknown", all(sorted(x) == ["detail", "fix", "key", "label", "state"] and x["state"] in ("have", "lack", "unknown") and isinstance(x["detail"], str) and (x["fix"] is None or sorted(x["fix"]) == ["command", "note"]) for x in a.values()) and list(a) == ["claude", "gh", "git", "node", "python3", "claude_auth", "gh_auth", "api_key"], list(a))
chk("  tools present and signed in: have, with nothing to fix", all(a[k]["state"] == "have" and a[k]["fix"] is None for k in ("claude", "gh", "git", "node", "python3", "claude_auth", "gh_auth")), a)
chk("  no API key stored is reported as a plain 'lack' with no fix while claude is signed in", a["api_key"]["state"] == "lack" and a["api_key"]["fix"] is None, a["api_key"])
b = by(facts(T + "/f-none", key=False))
chk("  with none of the tools: claude, gh, git and node are lacking, each with a fix command; the sign-ins are unknown (nothing to ask)", all(b[k]["state"] == "lack" and b[k]["fix"] and b[k]["fix"]["command"] for k in ("claude", "gh", "git", "node")) and b["claude_auth"]["state"] == "unknown" and b["gh_auth"]["state"] == "unknown", b)
chk("  the fix for gh, git and node names the tool, and the one for claude points at qtdeck setup and carries the setup note", all(k in b[k]["fix"]["command"] for k in ("gh", "git")) and "node" in b["node"]["fix"]["command"] and b["claude"]["fix"]["command"] == "qtdeck setup" and "claude" in b["claude"]["fix"]["note"].lower(), {k: b[k]["fix"] for k in ("claude", "gh", "git", "node")})
c = by(facts(T + "/f-out", key=False))
chk("  signed out: claude_auth is lacking with 'claude', gh_auth with 'gh auth login', and the API key then offers 'qtdeck keys set anthropic'", c["claude_auth"]["state"] == "lack" and c["claude_auth"]["fix"]["command"] == "claude" and c["gh_auth"]["state"] == "lack" and c["gh_auth"]["fix"]["command"] == "gh auth login" and c["api_key"]["fix"]["command"] == "qtdeck keys set anthropic", c)
d = by(facts(T + "/f-hang", key=False, timeout=1))
chk("  a tool that does not answer in time is 'unknown', not 'lack'", d["claude_auth"]["state"] == "unknown" and d["gh_auth"]["state"] == "unknown" and d["claude_auth"]["fix"] is None, d)
e = by(facts(T + "/f-all", key=True))
chk("  an API key that is stored is 'have' and says present, and never shows the key", e["api_key"]["state"] == "have" and "present" in e["api_key"]["detail"], e["api_key"])
old = by(facts(T + "/f-all", key=False, py=(3, 9)))
new = by(facts(T + "/f-all", key=False, py=(3, 10)))
chk("  Python 3.9 is lacking (with a fix, and '3.10 or newer' in the detail); 3.10 is fine", old["python3"]["state"] == "lack" and old["python3"]["fix"] and "3.10" in old["python3"]["detail"] and new["python3"]["state"] == "have", [old["python3"], new["python3"]])
# the real key file: its value must not appear anywhere in the facts, in the output of the tool, or on the command line
sys.path.insert(0, R + "/bin")
os.environ["QUARTERDECK_HOME"] = os.environ["D"]
import billing
name = billing.KEY_NAME
envf = T + "/secrets/" + os.path.basename(str(billing.common.env_path()))
open(envf, "w").write(f"{name}=sk-ant-SECRETVALUE-98765\n"); os.chmod(envf, 0o600)
g = facts(T + "/f-all")
dump = json.dumps(g)
chk("  with a real key file the key is reported present, and no secret (the key, or text a tool printed) is anywhere in the output", by(g)["api_key"]["state"] == "have" and "SECRETVALUE" not in dump and "LEAKME" not in dump and "sk-ant" not in dump, dump)
cli = subprocess.run([sys.executable, R + "/bin/firstrun.py", "--json"], capture_output=True, text=True, env=dict(os.environ, PATH=T + "/f-all" + os.pathsep + T + "/basics"))
chk("  python3 bin/firstrun.py --json prints the same facts and no secret", cli.returncode == 0 and "SECRETVALUE" not in cli.stdout + cli.stderr and "LEAKME" not in cli.stdout + cli.stderr and len(json.loads(cli.stdout)) == 8, cli.stdout + cli.stderr)
os.remove(envf)
txt = open(R + "/bin/firstrun.py").read()
chk("  firstrun.py reuses the install lines of setup.py and runs no installer", "_setup.install_cmd" in txt and "pip install" not in txt and "brew install" not in txt.replace('"brew install python@3.12"', ""))
PY
pyck "$T/facts-check.py"
rm -f "$T/secrets"/*

# ============================== 3. the API ==============================
echo "-- the API --"
mkstub "$T/stub" claude 'if [ "$1 $2" = "auth status" ]; then echo "{\"loggedIn\": true}"; exit 0; fi; exit 0'
mkstub "$T/stub" gh '[ "$1 $2" = "auth status" ] && exit 1; exit 0'
export CLAUDE_BIN="$T/stub/claude" QUARTERDECK_GH="$T/stub/gh"
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$P/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi
newlink() { QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$P/bin/dashboard.py" link; }
export PORT
cat > "$T/api-check.py" <<'PY'
import http.client, json, os, stat, subprocess, sys
PORT, T, D, P = int(os.environ["PORT"]), os.environ["T"], os.environ["D"], os.environ["P"]
def req(m, p, b=None, h=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    d = json.dumps(b).encode() if b is not None else None
    hh = dict(h or {})
    if d is not None: hh.update({"Content-Type": "application/json", "Content-Length": str(len(d))})
    c.request(m, p, body=d, headers=hh); r = c.getresponse(); raw = r.read(); c.close()
    try: body = json.loads(raw)
    except ValueError: body = raw
    return r.status, body, r.getheader("Set-Cookie") or ""
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:400]))
link = subprocess.run([sys.executable, P + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
st, body, ck = req("POST", "/api/pair", {"nonce": link.split("#pair=")[1]}, {"Origin": "http://127.0.0.1:%d" % PORT})
tok, cookie = body["token"], ck.split(";")[0]
good = {"Cookie": cookie, "X-Quarterdeck-Token": tok, "Origin": "http://127.0.0.1:%d" % PORT}
ff = D + "/state/first-run.json"
projects = D + "/config/projects.json"
st, body, _ = req("GET", "/api/firstrun")
chk("GET /api/firstrun without pairing is 401", st == 401, (st, body))
st, body, _ = req("POST", "/api/firstrun", {"action": "dismiss", "confirm": True})
chk("  POST without pairing is 401 and writes nothing", st == 401 and not os.path.exists(ff), (st, body))
st, body, _ = req("GET", "/api/firstrun", None, {"Cookie": cookie, "Origin": "http://127.0.0.1:%d" % PORT})
keys = [x["key"] for x in body["items"]] if st == 200 else []
chk("  paired, on a fresh data folder: first is true, done_at is null and the checklist is the doctor's eight facts, from the stand-ins on this machine's PATH", st == 200 and body["first"] is True and body["done_at"] is None and keys == ["claude", "gh", "git", "node", "python3", "claude_auth", "gh_auth", "api_key"], (st, body))
by = {x["key"]: x for x in body["items"]}
chk("  the stand-ins show: claude signed in, gh signed out with 'gh auth login' as its fix", by["claude_auth"]["state"] == "have" and by["gh_auth"]["state"] == "lack" and by["gh_auth"]["fix"]["command"] == "gh auth login", by)
st, S, _ = req("GET", "/api/state", None, {"Cookie": cookie})
chk("  the state carries first_run true, so the page knows to ask", st == 200 and S.get("first_run") is True, S.get("first_run"))
st, body, _ = req("POST", "/api/firstrun", {"action": "dismiss", "confirm": True}, {"Cookie": cookie, "Origin": "http://127.0.0.1:%d" % PORT})
chk("  a write with the cookie but without this tab's token is 403", st == 403 and not os.path.exists(ff), (st, body))
st, body, _ = req("POST", "/api/firstrun", {"action": "dismiss", "confirm": True}, dict(good, **{"X-Quarterdeck-Token": "wrong"}))
chk("  a wrong token is 403", st == 403 and not os.path.exists(ff), (st, body))
st, body, _ = req("POST", "/api/firstrun", {"action": "dismiss", "confirm": True}, dict(good, Origin="http://evil.example"))
chk("  a bad Origin is 403", st == 403 and not os.path.exists(ff), (st, body))
st, body, _ = req("POST", "/api/firstrun", {"action": "dismiss"}, good)
chk("  without confirm: 400, and nothing is written", st == 400 and "confirm" in body["error"] and not os.path.exists(ff), (st, body))
st, body, _ = req("POST", "/api/firstrun", {"action": "format-the-disk", "confirm": True}, good)
chk("  an action that is not demo or dismiss: 400", st == 400 and not os.path.exists(ff), (st, body))
st, body, _ = req("POST", "/api/firstrun", {"action": "demo", "confirm": True}, good)
mode = stat.S_IMODE(os.stat(ff).st_mode) if os.path.exists(ff) else None
rec = json.load(open(ff)) if os.path.exists(ff) else {}
st2, S, _ = req("GET", "/api/state", None, {"Cookie": cookie})
chk("  demo: 200, state/first-run.json is written (mode 0600, done_at and how) and Demo mode is on", st == 200 and mode == 0o600 and rec.get("how") == "demo" and rec.get("done_at") and body["first"] is False and (S.get("demo") or {}).get("on") is True, (st, body, oct(mode or 0), rec, (S.get("demo") if isinstance(S, dict) else S)))
chk("  no temp file is left behind", not any(n.endswith(".tmp") for n in os.listdir(D + "/state")), os.listdir(D + "/state"))
st, body, _ = req("GET", "/api/firstrun", None, {"Cookie": cookie})
chk("  GET /api/firstrun still answers (it is about the machine, not the made-up world) and first is false now", st == 200 and body["first"] is False and body["done_at"] == rec["done_at"], (st, body))
st, body, _ = req("POST", "/api/demo", {"on": False}, good)
os.remove(ff)
st, body, _ = req("GET", "/api/firstrun", None, {"Cookie": cookie})
chk("  deleting the file makes first true again (the file is the only memory)", body["first"] is True, body)
st, body, _ = req("POST", "/api/firstrun", {"action": "dismiss", "confirm": True}, good)
mode = stat.S_IMODE(os.stat(ff).st_mode)
st2, S, _ = req("GET", "/api/state", None, {"Cookie": cookie})
chk("  dismiss: 200, the file is 0600, Demo mode is NOT switched on", st == 200 and mode == 0o600 and json.load(open(ff))["how"] == "dismiss" and not (S.get("demo") or {}).get("on"), (st, body, S.get("demo")))
os.remove(ff)
os.makedirs(D + "/config", exist_ok=True)
json.dump({"alpha": {"repo": "", "path": D + "/alpha", "duties": []}}, open(projects, "w"))
st, body, _ = req("GET", "/api/firstrun", None, {"Cookie": cookie})
chk("  once a project is registered, first is false, with no file at all", st == 200 and body["first"] is False and not os.path.exists(ff), body)
os.remove(projects)
st, body, _ = req("GET", "/api/firstrun", None, {"Cookie": cookie})
chk("  and true again when the registry is empty again", body["first"] is True, body)
leaks = [k for k in json.dumps(body) if False]
chk("  nothing in the answer looks like a secret", "sk-" not in json.dumps(body) and "token" not in json.dumps(body).lower())
os.remove(ff) if os.path.exists(ff) else None
PY
pyck "$T/api-check.py"

# ============================== 4. the privacy scan ==============================
echo "-- the privacy scan --"
cat > "$T/scan-check.py" <<'PY'
import os, re, shutil, sys, tempfile
R, T = os.environ["REAL"], os.environ["T"]
sys.path.insert(0, R + "/bin")
import forbidden_signals as fs
chk = lambda label, cond, extra="": print(("ok " if cond else "FAIL ") + label + ("" if cond else " | " + str(extra)[:400]))
def scan_with(files):
    root = tempfile.mkdtemp(dir=T)
    for rel, text in files.items():
        p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)
    try: return fs.scan(root)
    finally: shutil.rmtree(root, ignore_errors=True)
page = open(R + "/dashboard/index.html").read()
FX = R + "/fixtures/privacy-scan"
sample = lambda name: open(f"{FX}/{name}.txt").read().split("\n", 1)[1]
OK_FN = sample("ok-copy")
chk("the real page passes the scan: its one Copy function is allowed", scan_with({"dashboard/index.html": page}) == [])
chk("  that function is one named function that writes one command and reads nothing", page.count("function copyCommand(") == 1 and page.count("writeText(") == 1 and not re.search(r"clipboard\W+read", page))
chk("  a small copyCommand with the one write call, in dashboard/index.html, is allowed", scan_with({"dashboard/index.html": "<script>" + OK_FN + "</script>"}) == [])
for name in sorted(n[:-4] for n in os.listdir(FX) if n.startswith("bad-")):
    label = open(f"{FX}/{name}.txt").readline()[2:].strip()
    hits = scan_with({"dashboard/index.html": "<script>\n" + OK_FN + sample(name) + "\n</script>"})
    chk(f"  fails: {label}", any(h[0] in ("clipboard", "built at run time") for h in hits), hits)
chk("  fails: the allowed function in any other file (a script, another page)", scan_with({"dashboard/assets/x.js": OK_FN}) != [] and scan_with({"bin/x.sh": "#!/bin/bash\n" + OK_FN}) != [] and scan_with({"dashboard/other.html": OK_FN}) != [])
chk("  fails: the allowed function when it has grown past a few lines (the allowance is for a small function)", scan_with({"dashboard/index.html": "function copyCommand(t){\n" + "  var a = 1;\n" * 200 + OK_FN.split("{", 1)[1]}) != [])
chk("  the other rules are untouched: the old built-from-pieces form still fails on its own", scan_with({"bin/a.py": sample("bad-old-rule")}) != [])
chk("  the allowance is documented in SECURITY.md", "copyCommand" in open(R + "/SECURITY.md").read() and "writes one command to the clipboard and reads nothing" in open(R + "/SECURITY.md").read())
PY
pyck "$T/scan-check.py"

# ============================== 5. the page ==============================
echo "-- the page --"
mkproj() { # mkproj <dir>: a copy of the sample app with its own git repository, one commit, no remote
  mkdir -p "$(dirname "$1")"; cp -R "$REAL/fixtures/sample-react" "$1"
  git init -q -b main "$1" 2>/dev/null || { git init -q "$1"; git -C "$1" checkout -q -b main; }
  git -C "$1" add -A; git -C "$1" -c user.name=Test -c user.email=test@example.invalid commit -q -m "initial todo app"
}
tree_sum() { (cd "$1" && find . -path ./.git -prune -o -print | LC_ALL=C sort | while IFS= read -r f; do if [ -f "$f" ]; then cksum "$f"; else echo "$f"; fi; done; git status --porcelain 2>/dev/null); }
if st_have_browser || node "$REAL/bin/onboarding-page.mjs" probe >/dev/null 2>&1; then
  # a new dashboard on a fresh data folder: nothing registered, first run not seen
  kill "$DASH" 2>/dev/null; st_gone "$P/bin/dashboard.py"; DASH=""
  rm -rf "$D/state" "$D/config" "$D/logs"; mkdir -p "$D"/{config,state,logs}
  mkproj "$H/projects/sample-react"; mkdir -p "$H/.hidden-proj" "$T/outside"; cp -R "$REAL/fixtures/sample-react" "$H/projects/my app"
  BEFORE=$(tree_sum "$H/projects/sample-react"); BEFORE2=$(tree_sum "$H/projects/my app")
  PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'); export PORT
  QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$P/bin/dashboard.py" > "$T/dash2.log" 2>&1 &
  DASH=$!
  if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the second dashboard did not start"; exit 1; fi
  mkdir -p "$T/shots"
  page_run() { # page_run <mode>
    local out rc nf
    out=$(QD_LINK="$(newlink)" QD_MODE="$1" QD_SHOTS="$T/shots" QD_T="$D" QD_HOME_DIR="$H" QD_OUTSIDE="$T/outside" node "$REAL/bin/onboarding-page.mjs" 2>&1 | tee -a "${QD_PAGE_LOG:-/dev/null}"); rc=${PIPESTATUS[0]}
    printf '%s\n' "$out" | while IFS= read -r line; do
      case "$line" in
        "ok "*) printf '  ok    %s\n' "${line#ok }" ;;
        "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }" ;;
        "skip "*) printf '  skip  %s\n' "${line#skip }" ;;
      esac
    done
    passed=$((passed + $(printf '%s\n' "$out" | grep -c '^ok ')))
    nf=$(printf '%s\n' "$out" | grep -c '^FAIL '); fails=$((fails + nf))
    if [ "$rc" != 0 ] && [ "$nf" = 0 ]; then printf '  FAIL  the page test crashed (exit %s): %s\n' "$rc" "$(printf '%s\n' "$out" | tail -3 | tr '\n' ' ')"; fails=$((fails + 1)); fi
  }
  page_run first
  ck "after 'Look around in Demo', state/first-run.json exists (0600) and says demo" '[ -f "$D/state/first-run.json" ] && [ "$(python3 -c "import os,stat,sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))" "$D/state/first-run.json")" = 0o600 ] && grep -q demo "$D/state/first-run.json"'
  page_run attach
  ck "the project folder the page scanned and attached is untouched (no file made, changed or removed, git clean)" '[ "$(tree_sum "$H/projects/sample-react")" = "$BEFORE" ]'
  ck "  and so is the folder with a space in its name" '[ "$(tree_sum "$H/projects/my app")" = "$BEFORE2" ]'
  ck "  only the one attached project is registered, in the data folder, and a profile exists only for it" '[ "$(jq -r "keys | join(\",\")" "$D/config/projects.json")" = "sample-react" ] && [ "$(ls "$D/state/profiles" 2>/dev/null | grep -vc "^sample-react\.")" = 0 ] && [ -f "$D/state/profiles/sample-react.json" ]'
  ck "  nothing was written under the fake HOME but the fixtures made here" '[ -z "$(find "$H" -newer "$T/shim-check.mjs" ! -path "$H/projects/*" ! -path "$H/.hidden-proj" -type f 2>/dev/null | head -1)" ]'
  [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
else
  st_skip_browser "the page checks (the first-run panel and its Copy buttons, Look around in Demo, the guided attach panel, the next action, Calm, a phone width) are not run"
fi
st_done
