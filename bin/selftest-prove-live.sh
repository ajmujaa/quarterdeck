#!/bin/bash
# The live view while "Run it once to prove it" runs, and the failure the owner sees afterwards. No model, no network, a temp data folder and a temp HOME.
#
# A fake project (a few committed files) is attached with a fake verify command that prints a line a second, then passes, fails or is stopped.
#   - the page polls GET /api/live?key=prove:<project>&since=N: lines arrive while the command runs (not only at the end), only the new ones after
#     `since`, with the elapsed seconds; text only (no escapes, no markup is ever made), and a credential in the output is redacted
#   - POST /api/ready/prove answers at once (the work is a detached process, never the request thread)
#   - the kept result holds the last 60 lines (redacted, 0600); a failed run names the line it stopped at, not its first (passing) line
#   - the Ready card says what to do next in one sentence; the sandbox's own refusals are named as such
#   - Stop ends the run, keeps nothing and leaves no copy, file or lock behind
#   - a project command is told it is in the sandbox (QUARTERDECK_IN_SANDBOX=1), and only that
#   - attach shows its stage lines in the same box
#   - a project whose tests are scripts is offered candidates found by name, one click each, never set or run silently
# Run it on its own: bash bin/selftest-prove-live.sh. QD_KEEP=1 keeps the throwaway folder.
ST_PROVIDER=fake
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init shipwright
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
TP="$T.proj"   # the projects live beside the data folder, not inside it
mkdir -p "$T/home" "$TP" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" QUARTERDECK_PROJECT_ROOTS="$TP"
export QUARTERDECK_HOME="$T" REAL PYTHONDONTWRITEBYTECODE=1; touch "$T/.quarterdeck-home"
QD="bash $T/bin/qtdeck"
DASH=""
X="$(cd "$(mktemp -d)" && pwd -P)"          # a second project folder outside the data folder: the dashboard's attach refuses one inside it
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T" "$X" "$TP"' EXIT

P="$TP/relay"
mkdir -p "$P/src"; printf 'hello\n' > "$P/README.txt"; printf 'x = 1\n' > "$P/src/app.py"
git init -q -b main "$P" 2>/dev/null || { git init -q "$P"; git -C "$P" checkout -q -b main; }
git -C "$P" add -A; git -C "$P" -c user.name=Test -c user.email=t@example.invalid commit -q -m "initial"
$QD attach "$P" --name relay --verify "true" --apply >/dev/null 2>&1
setverify() { jq --arg v "$1" '.relay.verify = $v' "$T/config/projects.json" > "$T/c.t" && chmod 600 "$T/c.t" && mv "$T/c.t" "$T/config/projects.json"; }

export QUARTERDECK_PROJECT_ROOTS="$TP:$X" QD_OTHER="$X"
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
export QD_PORT="$PORT" T
denv=(); for k in $(compgen -e); do
  case "$k" in
    *KEY*|*TOKEN*) ;;
    QUARTERDECK_*|HOME|PATH|XDG_CONFIG_HOME|LANG|LC_*|TMPDIR|TZ|TERM|USER|PYTHONDONTWRITEBYTECODE|CLAUDE_BIN|GIT_AUTHOR_*|GIT_COMMITTER_*|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM) denv+=("$k=${!k}") ;;
  esac
done
env -i "${denv[@]}" QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then ck "the dashboard started on a free port" 'false'; st_done; fi

cat > "$T/qc.py" <<'PY'
import http.client, json, os, re, subprocess, sys, time
PORT, T = int(os.environ["QD_PORT"]), os.environ["T"]
ORIGIN = "http://127.0.0.1:%d" % PORT
def chk(label, cond, extra=None): print(("ok " if cond else "FAIL ") + label + ("" if cond or extra is None else "  | " + str(extra)[:400]))
def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None: h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
    c.request(method, path, body=data, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    try: j = json.loads(raw)
    except ValueError: j = {"raw": raw.decode("replace")}
    return r.status, j, r.getheader("Set-Cookie") or ""
def pair():
    link = subprocess.run([sys.executable, T + "/bin/dashboard.py", "link"], capture_output=True, text=True).stdout.strip()
    st, j, ck = req("POST", "/api/pair", {"nonce": link.split("#pair=")[1]})
    return {"cookie": ck.split(";")[0], "token": j["token"]}
S = pair()
def get(path): return req("GET", path, headers={"Cookie": S["cookie"]})[:2]
def post(path, body): return req("POST", path, body, {"Cookie": S["cookie"], "X-Quarterdeck-Token": S["token"], "Origin": ORIGIN})[:2]
P = "relay"
VJ = T + "/state/projects/relay/verify.json"
def live(since=0): return get("/api/live?key=prove:relay&since=%d" % since)
def ready(): return get("/api/ready?project=relay")[1]
def start():
    t0 = time.time(); st, j = post("/api/ready/prove", {"project": P, "confirm": True}); return st, j, time.time() - t0
def wait_done(limit=90):
    end = time.time() + limit
    while time.time() < end:
        if not ready()["running"]["prove"]: return True
        time.sleep(0.3)
    return False
def wait_running(limit=30):
    end = time.time() + limit
    while time.time() < end:
        if ready()["running"]["prove"]: return True
        time.sleep(0.2)
    return False
PY

# ---- 1. a slow command that passes: lines arrive while it runs ----
setverify "for i in 1 2 3 4 5; do echo \"step \$i\"; sleep 1; done; printf '\\033[31mcolour\\033[0m <b>not markup</b> ghp_%s\\n' a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8; echo 'QD_SANDBOX_MARKER='\"\$QUARTERDECK_IN_SANDBOX\"; echo 'ok all done'"
cat > "$T/p1.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
st, j, took = start()
chk("POST /api/ready/prove answers at once with started (the work is a detached process, not the request)", st == 200 and j == {"started": True} and took < 5, (st, j, took))
seen_running, first_lines, since, got, ok_since = False, None, 0, [], True
end = time.time() + 60
while time.time() < end:
    st, r = live(since)
    if st != 200: break
    if r["state"] == "running":
        seen_running = True
        if r["lines"] and first_lines is None: first_lines = (list(r["lines"]), r["seconds"])
        got += r["lines"]
        if r["next"] < since: ok_since = False
        since = r["next"]
        time.sleep(0.4)
    else:
        final = r
        break
else:
    final = {"state": "timeout", "lines": []}
chk("while it runs /api/live says running, with the elapsed seconds and the first lines before the command has finished", seen_running and first_lines is not None and first_lines[0][0].startswith("step 1") and "step 5" not in " ".join(first_lines[0]), (first_lines, final.get("state")))
chk("  asking again with since=N returns only the lines after N (no line twice), and next only grows", ok_since and len(got) == len(set(got)) and got[:5] == ["step %d" % i for i in range(1, 6)], got)
chk("  when it ends the state is passed, replace is true and the lines are the kept tail", final["state"] == "passed" and final["replace"] is True and final["lines"][-1] == "ok all done", final)
ls = "\n".join(final["lines"])
chk("  the output is text only: terminal escapes are gone, markup is just characters, and the credential is redacted", "\x1b" not in ls and "colour <b>not markup</b>" in ls and "ghp_a1B2c3D4" not in ls and "[redacted]" in ls, ls)
v = json.load(open(VJ))
chk("verify.json keeps the last lines (at most 60) next to the old fields, redacted, and the file is private (0600)", v["exit"] == 0 and isinstance(v["tail"], list) and 0 < len(v["tail"]) <= 60 and v["tail"][-1] == "ok all done"
    and "ghp_a1B2c3D4" not in json.dumps(v) and oct(os.stat(VJ).st_mode & 0o777) == "0o600" and {"at", "command", "exit", "seconds", "sandbox", "first_line", "tail"} == set(v), v)
item = [i for i in ready()["items"] if i["key"] == "verify"][0]
chk("the Ready item carries the same tail for the card's Show the output, and is done", item["state"] == "done" and item["tail"] == v["tail"], item)
chk("nothing is left behind: no live file, no copy, no lock", not [f for f in os.listdir(T + "/workspace") if f.startswith(("prove-live", "prove-tail", "wt-relay"))] and not os.path.exists(T + "/state/prove-relay.lock"))
print("marker " + ("1" if "QD_SANDBOX_MARKER=1" in ls else "0") + " " + v["sandbox"])
PY
if ! st_can_nest_sandbox; then
  st_skip "1 the live box over a slow passing command: Prove starts a sandboxed project command, and a sandbox cannot start inside the sandbox this suite is already in"
else
  OUT=$(python3 "$T/p1.py" 2>&1)
  while IFS= read -r line; do
    case "$line" in
      "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
      "marker "*) MARK=${line#marker } ;;
      *) [ -z "$line" ] || echo "        $line" ;;
    esac
  done <<<"$OUT"
  case "${MARK:-0 none}" in
    "1 "*) ck "a project command is told it is in the sandbox: QUARTERDECK_IN_SANDBOX=1" 'true' ;;
    "0 none") st_skip "no sandbox on this machine (neither sandbox-exec nor a usable bubblewrap): the marker is only set where a sandbox is applied" ;;
    *) ck "a project command is told it is in the sandbox: QUARTERDECK_IN_SANDBOX=1" 'false' ;;
  esac
fi

# ---- 2. a command that fails: the line it stopped at, and what to do next ----
setverify "echo 'ok first thing'; echo 'ok second thing'; echo 'FAIL the real problem is here'; echo '3 passed, 1 failed'; exit 1"
cat > "$T/p2.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
start(); wait_done()
v = json.load(open(VJ)); item = [i for i in ready()["items"] if i["key"] == "verify"][0]
chk("a failed run is described by the line it stopped at, not its first (passing) line", v["exit"] == 1 and v["first_line"] == "FAIL the real problem is here" and "It stopped at: FAIL the real problem is here" in item["detail"], (v, item["detail"]))
chk("  the card says what to do next in one sentence, and the tail is there to open", item["state"] == "blocked" and item["next_step"].startswith("Open Show the output") and item["next_step"].count(". ") == 0 and item["tail"][0] == "ok first thing", item)
st, r = live(0)
chk("  the live box ends as failed with the tail", r["state"] == "failed" and r["lines"][-2] == "FAIL the real problem is here", r)
PY
OUT=$(python3 "$T/p2.py" 2>&1)
while IFS= read -r line; do
  case "$line" in
    "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
    "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    *) [ -z "$line" ] || echo "        $line" ;;
  esac
done <<<"$OUT"

# ---- 3. a command the sandbox forbids on purpose is named as that ----
setverify "echo 'ok start'; echo 'touch: cannot touch x: Operation not permitted'; exit 1"
cat > "$T/p3.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
start(); wait_done()
item = [i for i in ready()["items"] if i["key"] == "verify"][0]
chk("a refusal by the sandbox says so: this command needs more than the sandbox allows, and what to set instead", "needs more than the sandbox allows" in item["next_step"] and item["next_step"] in item["detail"], item)
PY
OUT=$(python3 "$T/p3.py" 2>&1)
while IFS= read -r line; do
  case "$line" in
    "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
    "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    *) [ -z "$line" ] || echo "        $line" ;;
  esac
done <<<"$OUT"

# ---- 4. Stop ends the run and keeps nothing ----
setverify "echo 'ok begun'; sleep 57"
AT_BEFORE=$(jq -r .at "$T/state/projects/relay/verify.json")
sleep 1
cat > "$T/p4.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
before = json.load(open(VJ))["at"]
start(); up = wait_running()
end = time.time() + 30
st, r = live(0)
while time.time() < end and not r.get("lines"):
    time.sleep(0.3); st, r = live(0)
chk("a long run shows running and its first line", up and r["state"] == "running" and r["lines"][:1] == ["ok begun"], r)
bad = post("/api/ready/prove-stop", {"project": P})
chk("Stop without confirm is a 400, and for a project with nothing running a 409", bad[0] == 400 and post("/api/ready/prove-stop", {"project": "nosuch", "confirm": True})[0] == 400, bad)
st, j = post("/api/ready/prove-stop", {"project": P, "confirm": True})
chk("Stop answers stopped", st == 200 and j == {"stopped": True}, (st, j))
gone = wait_done(20)
st, r = live(0)
rd = ready()
chk("  the run ends within seconds, the state is stopped, nothing new is kept, and the card says it was stopped (not failed)", gone and r["state"] == "stopped" and json.load(open(VJ))["at"] == before
    and "You stopped it" in rd["last_error"]["prove"], (gone, r, rd["last_error"]))
chk("  a second Stop is a 409", post("/api/ready/prove-stop", {"project": P, "confirm": True})[0] == 409)
PY
OUT=$(python3 "$T/p4.py" 2>&1)
while IFS= read -r line; do
  case "$line" in
    "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
    "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    *) [ -z "$line" ] || echo "        $line" ;;
  esac
done <<<"$OUT"
ck "  the command, its copy, the file and the lock are all gone (no sleep 57 left, no worktree, no live file)" 'st_gone "sleep 57" && [ ! -e "$T/state/prove-relay.lock" ] && [ -z "$(find "$T/workspace" -maxdepth 1 \( -name "wt-relay-prove*" -o -name "prove-live*" -o -name "exec.*" \) 2>/dev/null)" ] && [ "$(git -C "$P" worktree list | wc -l | tr -d " ")" = 1 ]'

# ---- 5. attach shows its stages in the same box; the keys and the pairing are checked ----
cat > "$T/p5.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
mk = os.environ["QD_OTHER"] + "/other"
os.makedirs(mk + "/src", exist_ok=True); open(mk + "/README.txt", "w").write("hi\n")
subprocess.run(["git", "init", "-q", "-b", "main", mk], capture_output=True)
st, j = post("/api/attach", {"path": mk})
st2, r = get("/api/live?key=attach")
chk("attach leaves its stage lines for the live box: reading, the stack it found, surveying, done", st == 200 and st2 == 200 and r["state"] == "done" and len(r["lines"]) >= 4 and r["lines"][0].startswith("Reading") and r["lines"][-1] == "Survey done", (st, r))
chk("an unknown key is a 400, an unknown project is a 400, and an unpaired read is a 401", get("/api/live?key=nope")[0] == 400 and get("/api/live?key=prove:nosuch")[0] == 400 and req("GET", "/api/live?key=attach")[0] == 401)
chk("a since that is not a number is read as 0", get("/api/live?key=attach&since=abc")[0] == 200 and get("/api/live?key=attach&since=-5")[0] == 200)
PY
OUT=$(python3 "$T/p5.py" 2>&1)
while IFS= read -r line; do
  case "$line" in
    "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
    "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    *) [ -z "$line" ] || echo "        $line" ;;
  esac
done <<<"$OUT"

# ---- 5b. a script-driven project: verify candidates found by name, offered, never set or run silently ----
SP="$TP/scripty"; mkdir -p "$SP/bin" "$SP/scripts"
printf 'print("ok")\n' > "$SP/bin/selftest.py"; printf 'true\n' > "$SP/bin/selftest-flow.sh"; printf 'true\n' > "$SP/bin/selftest-lib.sh"; printf 'true\n' > "$SP/scripts/build.sh"
printf 'check:\n\ttrue\n' > "$SP/Makefile"
git init -q -b main "$SP" 2>/dev/null || { git init -q "$SP"; git -C "$SP" checkout -q -b main; }
git -C "$SP" add -A; git -C "$SP" -c user.name=Test -c user.email=t@example.invalid commit -q -m "initial"
$QD attach "$SP" --name scripty --apply >/dev/null 2>&1
cat > "$T/p5b.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
def item(): return [i for i in get("/api/ready?project=scripty")[1]["items"] if i["key"] == "verify"][0]
def registry(): return json.load(open(T + "/config/projects.json"))["scripty"]
it = item()
cmds = [c["command"] for c in it.get("candidates", [])]
chk("a project with no manifest: the Ready card offers what is named like a test, best first, and not a library or a build script", cmds == ["python3 bin/selftest.py", "bash bin/selftest-flow.sh", "make check"], cmds)
chk("  each is marked not run yet and says why it was picked; nothing was set or run on its own", all(c["run"] is False and c["why"] for c in it["candidates"]) and registry().get("verify", "") == "" and not os.path.exists(T + "/state/projects/scripty/verify.json") and it["state"] == "blocked", registry())
chk("  setting needs confirm, and only a command from the list is taken (a typed one is a 400)", post("/api/project/verify", {"project": "scripty", "command": cmds[0]})[0] == 400
    and post("/api/project/verify", {"project": "scripty", "command": "rm -rf x", "confirm": True})[0] == 400 and registry().get("verify", "") == "")
st, j = post("/api/project/verify", {"project": "scripty", "command": cmds[0], "confirm": True})
it = item()
chk("  one click sets it and runs nothing: the item now says it has not been run yet, and a second set is a 409", st == 200 and j == {"verify": cmds[0], "run": False} and registry()["verify"] == cmds[0]
    and it["state"] == "todo" and "has not been run yet" in it["detail"] and not os.path.exists(T + "/state/projects/scripty/verify.json")
    and post("/api/project/verify", {"project": "scripty", "command": cmds[1], "confirm": True})[0] == 409, (st, j, it))
PY
OUT=$(python3 "$T/p5b.py" 2>&1)
while IFS= read -r line; do
  case "$line" in
    "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
    "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    *) [ -z "$line" ] || echo "        $line" ;;
  esac
done <<<"$OUT"

# ---- 6. the page: the box is one piece, polite, and the card uses it ----
ck "the page has one reusable live box (assets/livebox.js) used by Prove and attach, with a polite log, a progress strip that is not a percentage, and a Stop button" \
  'f="$REAL/dashboard/assets/livebox.js"; [ -s "$f" ] && grep -q "export function liveBoxHtml" "$f" && grep -q "role=\"progressbar\"" "$f" && ! grep -q "aria-valuenow" "$f" && grep -q "textContent" "$f" && ! grep -q "innerHTML *= *.*lines" "$f" && grep -q "livebox.js" "$REAL/dashboard/index.html" && grep -q "liveBoxHtml(\"prove\"" "$REAL/dashboard/index.html" && grep -q "liveBoxHtml(\"attach\"" "$REAL/dashboard/index.html" && grep -q "Show the output" "$REAL/dashboard/index.html"'
if command -v node >/dev/null 2>&1; then
  OUT=$(node --no-warnings "$REAL/bin/selftest-livebox.mjs" 2>&1); RC=$?
  while IFS= read -r line; do
    case "$line" in
      "ok "*)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)) ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)) ;;
    esac
  done <<<"$OUT"
  [ "$RC" = 0 ] || { printf '  FAIL  the live box under node exited %s\n' "$RC"; fails=$((fails + 1)); }
else st_skip "the live box under node: node is not installed"; fi

kill "$DASH" 2>/dev/null; wait "$DASH" 2>/dev/null; DASH=""
st_done
