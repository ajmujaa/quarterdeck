#!/bin/bash
# Tickets on the dashboard: the New ticket box, the drafts, filing, the ways forward for a project with no GitHub repo, and a mission started from a ticket.
# A real dashboard runs on a free port in a throwaway Quarterdeck (the program tree is copied, the data folder is a temp folder with the
# .quarterdeck-home marker, HOME is a temp folder), paired through its one-time link. The model is the fake provider (providers/fake.sh), gh is a
# stand-in that records every call, git is a real throwaway repository with a bare "origin". No network, no real model, no GitHub account.
#
#   1  GET /api/tickets: the shapes, with and without a repo; unpaired reads are refused
#   2  the writes are refused unpaired, from another origin, with a wrong token, and without confirm
#   3  POST /api/ticket/draft: the request is on standard input and in no process argument; the model has no gh and no write tool; why nothing came
#   4  POST /api/ticket/file and /discard: GitHub issues through the stand-in (one gh call each), local tickets, the credential scan, nothing posted
#   5  POST /api/repo: set; create (not signed in, signed in, the push is its own flag); no token in any answer
#   6  POST /api/cycle/start with a ticket: the opt-in, the confirm, the budget, the detached run; the mission list and the mission view
#   7  Demo mode: every new action answers with a plain message and does nothing; the made-up tickets read through the same shapes
#   8  the page, in a headless browser (skipped, saying so, when this machine has none)
# QD_KEEP=1 keeps the throwaway folder; QD_KEEP_SHOTS=<folder> copies the pictures the page checks take (every state of the new cards) there.
ST_PROVIDER=fake
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init planner purser panel shipwright
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
mkdir -p "$T/home" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
export QUARTERDECK_HOME="$T" REAL; touch "$T/.quarterdeck-home"
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT

mkgit() { # mkgit <dir>: a git checkout with one commit on main, an app.py and no remote
  mkdir -p "$1"; git init -q -b main "$1" 2>/dev/null || { git init -q "$1"; git -C "$1" checkout -q -b main; }
  printf 'def counter_reset(n):\n    return n\n' > "$1/app.py"; git -C "$1" add -A; git -C "$1" commit -q -m init
}
st_repo
git -C "$T/work" checkout -q main
for n in norepo norepo2 nocycle; do mkgit "$T/$n"; done
jq -n --arg w "$T/work" --arg t "$T" '
  def p($path; $repo; $cycle): {repo:$repo, path:$path, summary:"a fixture", default_branch:"main", duties:["planner","purser","panel","shipwright"], guardrails:[], verify:"PYTHONPATH=. python3 -c \"import app\"", forbidden_paths:["secrets/"]} + (if $cycle then {cycle:true} else {} end);
  {tp: p($w; "x/tp"; true), norepo: p($t + "/norepo"; ""; true), norepo2: p($t + "/norepo2"; ""; true), nocycle: p($t + "/nocycle"; ""; false)}' > "$T/config/projects.json"

# the gh stand-in: the lib's one, plus what `qtdeck repo create` asks of gh (sign-in, the user, a new repo)
cat > "$T/path/gh2" <<'GH'
#!/bin/bash
D="$QUARTERDECK_DIR"
case "$1 $2" in
  "auth status") echo "gh $*" >> "$D/gh-calls"; [ -f "$D/gh-signedout" ] && { echo "You are not logged into any GitHub hosts." >&2; exit 1; }; echo "Logged in"; exit 0 ;;
  "api user")    echo "gh $*" >> "$D/gh-calls"; printf '%s\n' "${GH_LOGIN-octo-cat}"; exit 0 ;;
  "repo create") echo "gh $*" >> "$D/gh-calls"
                 src=""; prev=""; for a in "$@"; do [ "$prev" = --source ] && src="$a"; prev="$a"; done
                 git init -q --bare -b main "$D/created-origin.git" 2>/dev/null; git -C "$src" remote add origin "$D/created-origin.git"; exit 0 ;;
esac
exec "$D/path/gh" "$@"
GH
chmod +x "$T/path/gh2"; export QUARTERDECK_GH="$T/path/gh2"
echo '[]' > "$T/ghdata/issue-list.json"

# the fake provider answers from a script the tests rewrite; the hook plays the builder that edits the worktree
export QUARTERDECK_FAKE_SCRIPT="$T/fake-script.json"
echo '[]' > "$QUARTERDECK_FAKE_SCRIPT"
cat > "$T/claude-hook" <<'HOOK'
#!/bin/bash
case "$1" in *"Build this one ticket"*) sed 's/return n/return 0  # TICKET-MARKER/' app.py > app.py.t && mv app.py.t app.py ;; esac
HOOK
chmod +x "$T/claude-hook"
export QUARTERDECK_DAILY_BUDGET=100 QUARTERDECK_CALL_BUDGET=0.01 QUARTERDECK_CYCLE_BUDGET=15

PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
export QD_PORT="$PORT" T
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi

# a small client: pairs like a browser (the one-time link, a cookie and this tab's token) and speaks as it
cat > "$T/qc.py" <<'PY'
import http.client, json, os, re, subprocess, sys, time
PORT, T = int(os.environ["QD_PORT"]), os.environ["T"]
ORIGIN = "http://127.0.0.1:%d" % PORT
def chk(label, cond): print(("ok " if cond else "FAIL ") + label)
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
    nonce = link.split("#pair=")[1]
    st, j, ck = req("POST", "/api/pair", {"nonce": nonce})
    return {"cookie": ck.split(";")[0], "token": j["token"]}
S = pair()
def get(path): return req("GET", path, headers={"Cookie": S["cookie"]})[:2]
def post(path, body, **over):
    h = {"Cookie": S["cookie"], "X-Quarterdeck-Token": S["token"], "Origin": ORIGIN}
    h.update(over)
    return req("POST", path, body, {k: v for k, v in h.items() if v is not None})[:2]
def script(*replies):
    json.dump(list(replies), open(os.environ["QUARTERDECK_FAKE_SCRIPT"], "w"))
def tickets(p): return get("/api/tickets?project=" + p)[1]
def wait_idle(p, limit=90):
    end = time.time() + limit
    while time.time() < end:
        j = tickets(p)
        if not j.get("running"): return j
        time.sleep(0.3)
    return tickets(p)
def calls(): return [json.loads(l) for l in open(T + "/claude-calls") if l.strip()] if os.path.exists(T + "/claude-calls") else []
def ghcalls(): return open(T + "/gh-calls").read().splitlines() if os.path.exists(T + "/gh-calls") else []
def creates(): return len([l for l in ghcalls() if l.startswith("gh issue create")])
def registry(): return json.load(open(T + "/config/projects.json"))
def seen_in_args(token):
    hits = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try: hits.append(token in open("/proc/%s/cmdline" % pid, "rb").read().decode("replace"))
            except OSError: pass
    return any(hits)
GOOD = 'TICKETS_JSON: {"tickets":[{"title":"Add a reset button","body":"A button that sets the counter back to zero.","acceptance":["Press Reset and the counter shows 0"]},{"title":"Remember the count after a reload","body":"Keep the count in the browser.","acceptance":["Press + three times, reload the page, the counter still shows 3"]}]}\nRESULT: DRAFTED 2 tickets'
PY

pyck() { # pyck <file.py>: each "ok ..." / "FAIL ..." line of its output is one check; a block that crashes is one failed check
  local line n=0
  python3 "$1" > "$T/py.out" 2> "$T/py.err"; local prc=$?
  while IFS= read -r line; do
    case "$line" in
      ok\ *)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)); n=$((n + 1)) ;;
      FAIL\ *) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)); n=$((n + 1)) ;;
      DBG*) echo "$line" ;;
    esac
  done < "$T/py.out"
  if [ "$prc" != 0 ] || [ "$n" = 0 ]; then printf '  FAIL  a python block crashed (exit %s): %s\n' "$prc" "$(tail -3 "$T/py.err" | tr '\n' ' ')"; fails=$((fails + 1)); fi
}

# ---- 1 and 2. the reads, and who may write -------------------------------------------------------------------------------------------------
cat > "$T/t12.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
S1 = "norepo has no GitHub repo, so the crew cannot open pull requests yet; local tickets still work."
st, j = get("/api/tickets?project=norepo")
chk("GET /api/tickets, a project with no repo: project, repo, has_repo, the one sentence, tickets, drafts, running", st == 200 and j["project"] == "norepo" and j["repo"] == "" and j["has_repo"] is False
    and j["sentence"] == S1 and j["tickets"] == [] and j["drafts"] == [] and j["running"] is False and j["last_draft_error"] == "" and j["request_limit"] == 2000)
chk("  the four options in order a, b, c, d with their plain titles", [o["key"] for o in j["options"]] == list("abcd")
    and [o["title"] for o in j["options"]] == ["I already have a GitHub repo", "I have a GitHub account", "I have no GitHub account", "Not now"])
chk("  (c) holds the steps and says a person must do it; (b) names gh auth login", len(j["options"][2]["steps"]) >= 5 and "A person has to do this" in j["options"][2]["note"] and "gh auth login" in j["options"][1]["note"])
chk("  stack and cycle fields are there (the stack is a sentence or empty), and no secret key is in the answer", isinstance(j["stack"], str) and j["cycle"] is True
    and not re.search(r'ghp_|"token"|"secret"|"password"', json.dumps(j), re.I))
st, j = get("/api/tickets?project=tp")
chk("a project with a repo: has_repo, the repo, an empty sentence", st == 200 and j["has_repo"] is True and j["repo"] == "x/tp" and j["sentence"] == "")
chk("an unregistered project is a 400, and so is a missing or odd name", get("/api/tickets?project=nosuch")[0] == 400 and get("/api/tickets")[0] == 400 and get("/api/tickets?project=../x")[0] == 400)
chk("unpaired, the read is 401", req("GET", "/api/tickets?project=tp")[0] == 401)
WRITES = [("/api/ticket/draft", {"project": "tp", "request": "x", "confirm": True}), ("/api/ticket/file", {"project": "tp", "draft": "d1", "confirm": True}),
          ("/api/ticket/discard", {"project": "tp", "draft": "d1", "confirm": True}), ("/api/repo", {"project": "norepo", "action": "set", "repo": "a/b", "confirm": True}),
          ("/api/cycle/start", {"project": "tp", "issue": 5, "confirm": True})]
chk("unpaired, every write is 401", all(req("POST", p, b)[0] == 401 for p, b in WRITES))
chk("a cookie without this tab's token is 403", all(post(p, b, **{"X-Quarterdeck-Token": None})[0] == 403 for p, b in WRITES))
chk("a wrong token is 403", all(post(p, b, **{"X-Quarterdeck-Token": "nope"})[0] == 403 for p, b in WRITES))
chk("a foreign origin, and another port on localhost, are 403", all(post(p, b, Origin="http://evil.example")[0] == 403 and post(p, b, Origin="http://127.0.0.1:%d" % (PORT + 1))[0] == 403 for p, b in WRITES))
chk("nothing was written by any of those: no tickets file, no run, no draft", not os.path.exists(T + "/state/tickets") and not os.path.exists(T + "/logs/tickets.log"))
bad = []
for p, b in WRITES:
    body = dict(b); body.pop("confirm")
    st, j = post(p, body)
    if st != 400 or "confirm" not in json.dumps(j): bad.append((p, st, j))
chk("without confirm: true, draft, file, discard, repo set and cycle start are each a 400 that says confirm", not bad)
st, j = post("/api/repo", {"project": "norepo", "action": "create"})
chk("  and repo create without confirm is a 400, with nothing created", st == 400 and "confirm" in j["error"] and not any("repo create" in l for l in ghcalls()))
st, j = post("/api/cycle/start", {"project": "tp", "issue": 5})
chk("  and an issue cycle without confirm is a 400 too (unchanged)", st == 400 and "confirm" in j["error"])
chk("  cycle start with both an issue and a ticket, or with neither, is a 400", post("/api/cycle/start", {"project": "tp", "issue": 5, "ticket": 1, "confirm": True})[0] == 400
    and post("/api/cycle/start", {"project": "tp", "confirm": True})[0] == 400)
PY
pyck "$T/t12.py"

# ---- 3. drafting --------------------------------------------------------------------------------------------------------------------------
cat > "$T/t3.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
import threading
TOKEN = "ZEBRA-REQUEST-7"
script({"text": GOOD, "sleep": 2.5, "cost_usd": 0.05})
open(T + "/claude-calls", "w").close()
hit = {"seen": False}
def watch():
    end = time.time() + 40
    while time.time() < end:
        if seen_in_args(TOKEN): hit["seen"] = True
        time.sleep(0.05)
        if hit.get("stop"): return
th = threading.Thread(target=watch, daemon=True); th.start()
st, j = post("/api/ticket/draft", {"project": "tp", "request": TOKEN + " build me a page with a counter", "confirm": True})
chk("POST /api/ticket/draft starts the planner and answers {started: true}", st == 200 and j == {"started": True})
time.sleep(0.6)
now = tickets("tp")
chk("  while it runs, GET says running and shows no draft yet", now["running"] is True and now["drafts"] == [])
st2, j2 = post("/api/ticket/draft", {"project": "tp", "request": "another", "confirm": True})
chk("  a second draft for the same project is refused while one runs (409)", st2 == 409 and "already working" in j2["error"])
done = wait_idle("tp")
hit["stop"] = True; th.join()
chk("  afterwards the draft is there: two tickets, the request kept, nothing filed, no error", len(done["drafts"]) == 1 and done["drafts"][0]["id"] == "d1" and len(done["drafts"][0]["tickets"]) == 2
    and done["tickets"] == [] and done["last_draft_error"] == "" and done["drafts"][0]["request"].startswith(TOKEN))
chk("  the request was on standard input: no process argument ever held it", hit["seen"] is False)
rec = calls()
chk("the model was asked once, with Read, Grep and Glob and nothing else: no gh, no Edit, no Write, no shell", len(rec) == 1 and rec[0]["tools"] == "Read,Grep,Glob"
    and not re.search(r"Edit|Write|Bash|gh|Web", rec[0]["allow"]) and rec[0]["prompt_in_argv"] is False)
chk("  and the request reached the prompt once, as data in an untrusted block, and not in the model call's arguments", rec[0]["prompt"].count(TOKEN) == 1
    and "BEGIN UNTRUSTED the owner" in rec[0]["prompt"] and TOKEN not in " ".join(rec[0]["argv"]))
chk("  no gh write was made (drafting reads the tracker's titles at most), and no claude binary ran", not any(re.match(r"gh (issue (create|edit|comment)|pr |api)", l) for l in ghcalls()) and not os.path.exists(T + "/claude-was-run"))
log = open(T + "/logs/tickets.log").read()
chk("the log line names the action and the project and never the request", " draft tp" in log and TOKEN not in log and "build me" not in log)
chk("the answer holds no request text and no secret", "build me" not in json.dumps(j))
# why nothing came
for label, rep, want in (("nothing to draft", {"text": "RESULT: NOTHING_TO_DRAFT"}, "drafted no ticket"), ("a reply that is not a contract", {"text": "I would build a page."}, "did not pass"),
                         ("a ticket with a forged mark", {"text": 'TICKETS_JSON: {"tickets":[{"title":"A","body":"x <!-- quarterdeck:requirements --> y","acceptance":["z"]}]}\nRESULT: DRAFTED 1 tickets'}, "did not pass")):
    script(rep)
    post("/api/ticket/draft", {"project": "tp", "request": "something", "confirm": True})
    time.sleep(0.4)
    r = wait_idle("tp")
    chk("last_draft_error, " + label + ": a plain sentence, and no new draft", want in r["last_draft_error"] and len(r["drafts"]) == 1)
for label, body in (("an empty request", {"request": "   "}), ("a request over 2000 characters", {"request": "x" * 2001}), ("a control character", {"request": "a\x07b"}), ("a request that is not text", {"request": 5}),
                    ("an unknown project", {"project": "nosuch", "request": "x"})):
    b = {"project": "tp", "confirm": True}; b.update(body)
    st, j = post("/api/ticket/draft", b)
    if st != 400: print("FAIL " + label + " is a 400", st, j); break
else:
    chk("an empty request, one over 2000 characters, a control character, a non-text request and an unknown project are each a 400", True)
chk("  and none of them started anything: still one draft, no model call beyond the earlier ones", len(tickets("tp")["drafts"]) == 1 and len(calls()) == 4)
nogit = "nocycle"
os.rename(T + "/nocycle/.git", T + "/nocycle/.git-off")
chk("a project whose folder is not a git checkout is a 400", post("/api/ticket/draft", {"project": nogit, "request": "x", "confirm": True})[0] == 400)
os.rename(T + "/nocycle/.git-off", T + "/nocycle/.git")
n_calls = len(calls())
DEC3 = "ghp_" + "b" * 36
st, j = post("/api/ticket/draft", {"project": "tp", "request": "log in with the token " + DEC3 + " and show the todos", "confirm": True})
time.sleep(0.4)
r = wait_idle("tp")
chk("a request that holds a credential shape starts, is refused by the planner before any model call, and the page is told in a plain sentence that never repeats it", st == 200 and len(calls()) == n_calls
    and r["last_draft_error"].startswith("Your request looks like it holds a password or a key") and DEC3 not in json.dumps(r) and DEC3 not in open(T + "/state/tickets/tp.json").read())
PY
pyck "$T/t3.py"

# ---- 4. filing, discarding -----------------------------------------------------------------------------------------------------------
cat > "$T/t4.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
DEC = "ghp_" + "a" * 36
rm = lambda: open(T + "/gh-calls", "w").close()
d1 = tickets("tp")["drafts"][0]["id"]
before = creates()
st, j = post("/api/ticket/file", {"project": "tp", "draft": d1, "local": False, "confirm": True})
chk("file with a repo and local false starts the GitHub filing (through the planner and gh_post): {started: true}", st == 200 and j.get("started") is True and j.get("count") == 2 and j.get("repo") == "x/tp")
r = wait_idle("tp")
chk("  gh issue create ran once per ticket, two in all, in x/tp", creates() - before == 2 and all("-R x/tp" in l for l in ghcalls() if l.startswith("gh issue create")))
chk("  the tickets are remembered as GitHub issues, with their numbers, and the draft is used up", [t["source"] for t in r["tickets"]] == ["github", "github"] and all(t["issue"] for t in r["tickets"]) and r["drafts"] == [] and r["last_file_error"] == "")
body = open(T + "/gh-calls").read()
chk("  the issue body holds the body and the acceptance checks as a list", "Keep the count in the browser" in body and "- [ ] Press + three times" in body)
# local true on a project with a repo
script({"text": GOOD, "cost_usd": 0.05})
post("/api/ticket/draft", {"project": "tp", "request": "again", "confirm": True}); time.sleep(0.4); r = wait_idle("tp")
d2 = r["drafts"][0]["id"]
c0, n0 = creates(), len(r["tickets"])
st, j = post("/api/ticket/file", {"project": "tp", "draft": d2, "local": True, "confirm": True})
r = tickets("tp")
chk("file with local true saves local tickets at once, calls gh issue create never, and removes the draft", st == 200 and j.get("local") is True and len(j["tickets"]) == 2 and creates() == c0
    and r["drafts"] == [] and [t["source"] for t in r["tickets"]][-2:] == ["local", "local"] and len(r["tickets"]) == n0 + 2 and all(t["issue"] is None for t in r["tickets"][-2:]))
# a project with no repo: local whatever the flag says; gh is never touched
open(T + "/gh-calls", "w").close()
script({"text": GOOD, "cost_usd": 0.05})
post("/api/ticket/draft", {"project": "norepo", "request": "a page", "confirm": True}); time.sleep(0.4); r = wait_idle("norepo")
chk("drafting on a project with no repo needs neither a repo nor gh", len(r["drafts"]) == 1 and r["last_draft_error"] == "" and not any(l.startswith("gh issue") or l.startswith("gh api") for l in ghcalls()))
d3 = r["drafts"][0]["id"]
st, j = post("/api/ticket/file", {"project": "norepo", "draft": d3, "local": False, "confirm": True})
r = tickets("norepo")
chk("file on a project with no repo saves local tickets (whatever local says), and the gh stand-in has no write", st == 200 and j["local"] is True and len(r["tickets"]) == 2 and r["drafts"] == []
    and not any(re.match(r"gh (pr|issue (create|edit|comment)|api|repo create)", l) for l in ghcalls()))
chk("  the same draft again is a 400 (it is used up), and a bad draft id is a 400", post("/api/ticket/file", {"project": "norepo", "draft": d3, "confirm": True})[0] == 400
    and post("/api/ticket/file", {"project": "norepo", "draft": "../x", "confirm": True})[0] == 400 and post("/api/ticket/file", {"project": "norepo", "draft": "d1", "local": "yes", "confirm": True})[0] == 400)
# the credential scan
script({"text": 'TICKETS_JSON: {"tickets":[{"title":"First good one","body":"fine","acceptance":["ok"]},{"title":"Second with a secret","body":"the key is %s","acceptance":["ok"]}]}\nRESULT: DRAFTED 2 tickets' % DEC, "cost_usd": 0.05})
post("/api/ticket/draft", {"project": "tp", "request": "leaky", "confirm": True}); time.sleep(0.4); r = wait_idle("tp")
dl = r["drafts"][0]["id"]
c0, n0 = creates(), len(r["tickets"])
st, j = post("/api/ticket/file", {"project": "tp", "draft": dl, "local": False, "confirm": True}); r = wait_idle("tp")
chk("a draft holding a credential shape is refused by the scan: nothing is posted, not even the good ticket, and the page is told why", creates() == c0 and len(r["tickets"]) == n0 and len(r["drafts"]) == 1
    and "password or a key" in r["last_file_error"] and DEC not in json.dumps(r) and DEC not in open(T + "/gh-calls").read())
chk("  and the draft the page reads shows no credential: the scan blanks it in the answer (the draft stays on disk, to be discarded)", DEC not in json.dumps(tickets("tp")) and "[redacted]" in json.dumps(tickets("tp")["drafts"]))
# discard
st, j = post("/api/ticket/discard", {"project": "tp", "draft": dl, "confirm": True})
chk("POST /api/ticket/discard removes a draft; the same again, a bad id and an unknown project are each a 400", st == 200 and j == {"discarded": True} and tickets("tp")["drafts"] == []
    and post("/api/ticket/discard", {"project": "tp", "draft": dl, "confirm": True})[0] == 400 and post("/api/ticket/discard", {"project": "tp", "draft": "x1", "confirm": True})[0] == 400
    and post("/api/ticket/discard", {"project": "nosuch", "draft": "d1", "confirm": True})[0] == 400)
log = open(T + "/logs/tickets.log").read()
chk("every write is logged by action and project only", "file-github tp" in log and "file-local tp" in log and "file-local norepo" in log and "discard tp" in log and DEC not in log and "leaky" not in log)
PY
pyck "$T/t4.py"

# ---- 5. the repo ---------------------------------------------------------------------------------------------------------------------------
cat > "$T/t5.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
open(T + "/gh-calls", "w").close()
st, j = post("/api/repo", {"project": "norepo2", "action": "set", "repo": "octo/norepo2", "confirm": True})
chk("repo set connects a repo the owner already has: the registry is updated, nothing else is called", st == 200 and j["ok"] is True and registry()["norepo2"]["repo"] == "octo/norepo2" and ghcalls() == [])
chk("  and the page's data now says has_repo", tickets("norepo2")["has_repo"] is True and tickets("norepo2")["sentence"] == "")
for bad in ("x; rm -rf /", "a/b/c", "-x/y", "no-slash", "a/b c", "", "../../x", "o/..", 5, None):
    st, j = post("/api/repo", {"project": "norepo2", "action": "set", "repo": bad, "confirm": True})
    if st != 400: print("FAIL a repo %r was accepted" % (bad,), st, j); break
else:
    chk("a repo that is not a plain owner/name is a 400 (a shell character, three parts, a leading dash, nothing, a number)", True)
chk("  an unknown project and an unknown action are a 400", post("/api/repo", {"project": "nosuch", "action": "set", "repo": "a/b", "confirm": True})[0] == 400
    and post("/api/repo", {"project": "norepo", "action": "delete", "confirm": True})[0] == 400 and registry()["norepo"]["repo"] == "")
# create
open(T + "/gh-signedout", "w").close()
st, j = post("/api/repo", {"project": "norepo", "action": "create", "push": False, "confirm": True})
chk("repo create, gh not signed in: the plain message with gh auth login, code 3, nothing created or recorded", st == 200 and j["ok"] is False and j["code"] == 3
    and j["message"] == "GitHub CLI is not signed in: run gh auth login in a terminal, then try again." and not any(l.startswith("gh repo create") for l in ghcalls()) and registry()["norepo"]["repo"] == ""
    and subprocess.run(["git", "-C", T + "/norepo", "remote"], capture_output=True, text=True).stdout.strip() == "")
os.unlink(T + "/gh-signedout"); open(T + "/gh-calls", "w").close()
st, j = post("/api/repo", {"project": "norepo", "action": "create", "push": False, "confirm": True})
refs = subprocess.run(["git", "--git-dir", T + "/created-origin.git", "for-each-ref"], capture_output=True, text=True).stdout.strip()
chk("signed in, the first yes only: a PRIVATE repo is made and recorded, and nothing is pushed", st == 200 and j["ok"] is True and j["repo"] == "octo-cat/norepo" and j["private"] is True and j["pushed"] is False
    and any(l.startswith("gh repo create octo-cat/norepo --private") for l in ghcalls()) and registry()["norepo"]["repo"] == "octo-cat/norepo" and refs == "")
chk("  the message says what happened in a sentence", "Created the private repository octo-cat/norepo" in j["message"] and "Nothing was pushed" in j["message"])
chk("  the program asks gh only for auth status, api user and repo create (no token read, no account made)", sorted({" ".join(l.split()[1:3]) for l in ghcalls()}) == ["api user", "auth status", "repo create"]
    and not re.search(r"ghp_|token", json.dumps(j), re.I))
os.system("rm -rf %s/created-origin.git" % T); open(T + "/gh-calls", "w").close()
st, j = post("/api/repo", {"project": "nocycle", "action": "create", "push": True, "confirm": True})
refs = subprocess.run(["git", "--git-dir", T + "/created-origin.git", "for-each-ref"], capture_output=True, text=True).stdout.strip()
chk("the push is its own flag: with push true the default branch goes once", st == 200 and j["ok"] is True and j["pushed"] is True and "refs/heads/main" in refs and refs.count("\n") == 0)
chk("  a project that already has a repo is a 400 and creates nothing; push must be true or false", post("/api/repo", {"project": "norepo", "action": "create", "confirm": True})[0] == 400
    and post("/api/repo", {"project": "norepo2", "action": "create", "push": "yes", "confirm": True})[0] == 400)
log = open(T + "/logs/tickets.log").read()
chk("both are logged by action and project", "repo-set norepo2" in log and "repo-create norepo" in log and "repo-create-push nocycle" in log)
# restore the registry for the rest: norepo is a no-repo project again
reg = registry(); reg["norepo"]["repo"] = ""; json.dump(reg, open(T + "/config/projects.json", "w"))
os.system("git -C %s remote remove origin" % (T + "/norepo"))
chk("(the registry for the rest of the suite is put back)", tickets("norepo")["has_repo"] is False)
PY
pyck "$T/t5.py"

# ---- 6. a mission from a ticket ------------------------------------------------------------------------------------------------------------
cat > "$T/t6.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
sys.path.insert(0, T + "/bin")
import tickets as K
PLAN = 'REQUIREMENTS_JSON'
script({"match": "REQUIREMENTS_JSON", "text": 'REQUIREMENTS_JSON: {"summary":"Let the counter be reset","requirements":[{"what":"Reset sets the counter to zero","accept":"Call counter_reset(5) and check the result equals 0"}],"out_of_scope":["styling"]}\nRESULT: READY 1 requirement(s)', "cost_usd": 0.05},
       {"match": "RULING_JSON", "text": 'HEADLINE: one change\nRULING_JSON: [{"kind":"change","tier":"routine","area":"app","severity":"major","title":"Make counter_reset return zero","claim":"it returns its argument","where":"app.py","why":"the ticket asks for zero","action":"return 0","support":["shipwright"],"overruled":[],"note":""}]\nRESULT: RULED 1', "cost_usd": 0.05},
       {"match": "STANCES_JSON", "text": 'STANCES_JSON: [{"id":"shipwright-1","stance":"agree","note":"n"}]\nRESULT: STANCES 1', "cost_usd": 0.05},
       {"match": "Build this one ticket", "text": "RESULT: FIXED the counter resets to zero", "cost_usd": 0.05},
       {"text": 'ITEMS_JSON: [{"area":"app","severity":"major","title":"Make counter_reset return zero","claim":"it returns its argument","where":"app.py","why":"the ticket asks for zero","action":"return 0"}]\nRESULT: ITEMS 1', "cost_usd": 0.05})
K.local_add("nocycle", [{"title": "Cycle me where I may not", "body": "b", "acceptance": ["c"]}])
st, j = post("/api/cycle/start", {"project": "nocycle", "ticket": 1, "confirm": True})
chk("a ticket cycle on a project without cycle: true is refused with the registry hint, and starts nothing", st == 400 and '"cycle": true' in j["error"] and not os.path.exists(T + "/state/cycles"))
local = [t for t in tickets("norepo")["tickets"] if t["source"] == "local" and t["status"] == "open"]
tid = local[0]["id"]
chk("a ticket that is not there, a bad number and a GitHub-filed ticket are each a 400",
    post("/api/cycle/start", {"project": "norepo", "ticket": 99, "confirm": True})[0] == 400 and post("/api/cycle/start", {"project": "norepo", "ticket": -1, "confirm": True})[0] == 400
    and post("/api/cycle/start", {"project": "norepo", "ticket": "1", "confirm": True})[0] == 400 and post("/api/cycle/start", {"project": "norepo", "ticket": True, "confirm": True})[0] == 400
    and "GitHub issue" in post("/api/cycle/start", {"project": "tp", "ticket": [t for t in tickets("tp")["tickets"] if t["source"] == "github"][0]["id"], "confirm": True})[1].get("error", ""))
st, j = post("/api/cycle/start", {"project": "norepo", "ticket": tid})
chk("a ticket cycle without confirm: true is a 400 that says confirm, and starts nothing", st == 400 and "confirm" in j["error"] and not os.path.exists(T + "/state/cycles"))
st, j = post("/api/cycle/start", {"project": "norepo", "ticket": tid, "confirm": True})
chk("a ticket cycle on an opted-in project starts, detached: {started: 'cycle norepo --ticket n', id}", st == 200 and j["started"] == "cycle norepo --ticket %d" % tid and isinstance(j["id"], str) and j["id"].startswith("cyc-norepo-t%d-" % tid))
cid = j["id"]
st2, j2 = post("/api/cycle/start", {"project": "norepo", "ticket": tid, "confirm": True})
rec = None
end = time.time() + 180
while time.time() < end:
    rec = json.load(open(T + "/state/cycles/%s.json" % cid))
    if rec["status"] != "running": break
    time.sleep(0.5)
chk("  the same ticket again, while it runs or after, is refused (409 running, or 400 once it is in review)", st2 in (409, 400))
chk("  the cycle ended awaiting-review on a local branch, with the ticket, no pull request and no gh issue or pr call", rec["status"] == "awaiting-review" and rec["ticket"] == tid and rec["issue"] is None and rec["pr"] is None
    and (rec.get("branch") or "").startswith("ticket/%d-" % tid) and not any(re.match(r"gh (pr|issue)", l) for l in ghcalls()[-4:]))
lst = get("/api/state")[1]["cycles"]
mine = [c for c in lst if c["id"] == cid]
chk("the mission list shows it: the state's cycles hold the ticket and the branch", len(mine) == 1 and mine[0]["ticket"] == tid and mine[0]["branch"] == rec["branch"] and mine[0]["issue"] is None)
st, m = get("/api/mission?id=" + "cycle:" + cid)
nodes = {n["id"]: n for n in m["pipeline"]}
chk("/api/mission renders it: a title with ticket #n, the pipeline with the pull-request groups skipped (never blocked), human awaiting", st == 200 and "ticket #%d" % tid in m["title"] and m["state"] == "awaiting"
    and nodes["brief"]["state"] == "done" and nodes["build"]["state"] == "done" and nodes["review"]["state"] == "skipped" and nodes["seal"]["state"] == "skipped" and nodes["human"]["state"] == "awaiting"
    and not any(n["state"] in ("blocked", "failed") for n in m["pipeline"]))
chk("  the skipped stages carry their reason in the history, as skipped", [h for h in m["history"] if h["verdict"] == "SKIPPED"] and all("pull request" in h["detail"] for h in m["history"] if h["verdict"] == "SKIPPED"))
chk("  the ticket block: number, branch, the review command and one line of what is next", m["ticket"]["n"] == tid and m["ticket"]["branch"] == rec["branch"] and "diff" in m["ticket"]["review"] and "merge it yourself" in m["ticket"]["next"])
r = tickets("norepo")
t = [x for x in r["tickets"] if x["id"] == tid][0]
chk("the ticket list shows it in review with its branch and the review command", t["status"] == "review" and t["branch"] == rec["branch"] and t["review"] == rec["review"] and t["cycle"] == cid)
chk("  and it cannot be started again from the page's data (the server refuses a ticket in review)", "review" in post("/api/cycle/start", {"project": "norepo", "ticket": tid, "confirm": True})[1].get("error", ""))
# an issue cycle is as it was
st, j = post("/api/cycle/start", {"project": "tp", "issue": 5, "confirm": True})
chk("an issue cycle still starts as before (the opt-in and confirm rules are the same)", st == 200 and j["started"] == "cycle tp --issue 5")
time.sleep(1)
# the budget: today's spend is over the daily budget
with open(T + "/state/spend.jsonl", "a") as f:
    f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "project": "tp", "duty": "x", "cost": 500}) + "\n")
other = K.local_add("norepo", [{"title": "Too late today", "body": "b", "acceptance": ["c"]}])[0]["id"]
st, j = post("/api/cycle/start", {"project": "norepo", "ticket": other, "confirm": True})
chk("with today's budget spent a ticket cycle is refused (409) and starts nothing", st == 409 and "budget" in j["error"])
st, j = post("/api/ticket/draft", {"project": "norepo", "request": "late", "confirm": True})
chk("  and so is a draft", st == 409 and "budget" in j["error"])
rows = [l for l in open(T + "/state/spend.jsonl") if '"cost": 500' not in l]
open(T + "/state/spend.jsonl", "w").writelines(rows)          # the day's spend is put back for the rest of the suite
PY
PYTHONPATH="$T/bin" pyck "$T/t6.py"

# ---- 7. Demo mode --------------------------------------------------------------------------------------------------------------------------
cat > "$T/t7.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
sys.path.insert(0, T + "/bin")
import repo as R
calls0 = len(calls()); logs0 = open(T + "/logs/tickets.log").read(); reg0 = open(T + "/config/projects.json").read(); gh0 = ghcalls()
post("/api/demo", {"on": True})
MSG = "Demo mode: nothing is drafted, filed or created."
acts = [("/api/ticket/draft", {"project": "saltpan-blog", "request": "x", "confirm": True}), ("/api/ticket/file", {"project": "saltpan-blog", "draft": "d1", "confirm": True}),
        ("/api/ticket/discard", {"project": "saltpan-blog", "draft": "d1", "confirm": True}), ("/api/repo", {"project": "saltpan-blog", "action": "set", "repo": "a/b", "confirm": True}),
        ("/api/repo", {"project": "saltpan-blog", "action": "create", "confirm": True})]
got = [post(p, b) for p, b in acts]
chk("Demo mode answers each new action with the plain message, a 400", all(st == 400 and j["error"] == MSG for st, j in got))
st, j = get("/api/tickets?project=saltpan-blog")
chk("the made-up GET has the real shape: no repo, the sentence, four options, local tickets (one in review with a branch), a draft", st == 200 and j["has_repo"] is False and j["sentence"].startswith("saltpan-blog has no GitHub repo")
    and [o["key"] for o in j["options"]] == list("abcd") and any(t["status"] == "review" and t["branch"] and t["review"] for t in j["tickets"]) and len(j["drafts"]) == 1 and set(j) >= {"project", "repo", "has_repo", "sentence", "options", "stack", "tickets", "drafts", "running", "last_draft_error", "request_limit"})
chk("  the made-up options say what the real ones say", j["options"] == R.options("saltpan-blog"))
st, j2 = get("/api/tickets?project=wayfarer-web")
chk("  a demo project with a repo has_repo, GitHub-filed and local tickets, and nosuch is a 400", j2["has_repo"] is True and {t["source"] for t in j2["tickets"]} == {"github", "local"} and get("/api/tickets?project=nosuch")[0] == 400)
sid = [c for c in get("/api/state")[1]["cycles"] if c.get("ticket")]
chk("the demo state lists a ticket cycle, and /api/mission renders it with the skipped stages", len(sid) == 1 and sid[0]["branch"] and get("/api/mission?id=cycle:" + sid[0]["id"])[1]["ticket"]["review"]
    and any(n["state"] == "skipped" for n in get("/api/mission?id=cycle:" + sid[0]["id"])[1]["pipeline"]))
st, j3 = post("/api/cycle/start", {"project": "wayfarer-web", "ticket": [t["id"] for t in j2["tickets"] if t["source"] == "local"][0], "confirm": True})
chk("a ticket cycle in Demo mode makes an invented record and runs nothing real", st == 200 and "--ticket" in j3["started"] and len(calls()) == calls0 and not os.path.exists(T + "/state/cycles/" + j3["id"] + ".json"))
chk("nothing real changed: no model call, no gh call, no log line, the registry untouched", len(calls()) == calls0 and ghcalls() == gh0 and open(T + "/logs/tickets.log").read() == logs0 and open(T + "/config/projects.json").read() == reg0)
post("/api/demo", {"on": False})
chk("(Demo mode is switched off again)", get("/api/tickets?project=norepo")[0] == 200)
PY
pyck "$T/t7.py"

# ---- 8. the page ---------------------------------------------------------------------------------------------------------------------------
# st_have_browser asks bin/browse.mjs, which keeps Chromium's renderer sandbox on and so cannot start as root in a container; the page driver here
# launches the way bin/a11y-check.mjs does, so it is asked as well. When neither can start a browser the page checks are skipped, saying so.
if st_have_browser || node "$REAL/bin/tickets-ui-page.mjs" probe >/dev/null 2>&1; then
  mkdir -p "$T/shots"
  : > "$T/gh-calls"
  # two fresh projects with nothing in them: the page test types a request, drafts through the fake provider and saves on this computer; and creates a repo
  jq '. + {pagetest: (.norepo + {path: ($t + "/pagetest")}), pagetest2: (.norepo + {path: ($t + "/pagetest2")})}' --arg t "$T" "$T/config/projects.json" > "$T/c.t" && mv "$T/c.t" "$T/config/projects.json"
  mkgit "$T/pagetest"; mkgit "$T/pagetest2"
  echo '[{"text": "TICKETS_JSON: {\"tickets\":[{\"title\":\"Add a reset button\",\"body\":\"A button that sets the counter back to zero.\",\"acceptance\":[\"Press Reset and the counter shows 0\"]},{\"title\":\"Remember the count after a reload\",\"body\":\"Keep the count in the browser.\",\"acceptance\":[\"Press + three times, reload the page, the counter still shows 3\"]}]}\nRESULT: DRAFTED 2 tickets", "sleep": 1.5, "cost_usd": 0.05}]' > "$QUARTERDECK_FAKE_SCRIPT"
  LINK=$(QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link)
  OUT=$(QD_LINK="$LINK" QD_SHOTS="$T/shots" QD_T="$T" node "$REAL/bin/tickets-ui-page.mjs" 2>&1); RC=$?
  printf '%s\n' "$OUT" | while IFS= read -r line; do
    case "$line" in
      "ok "*) printf '  ok    %s\n' "${line#ok }" ;;
      "FAIL "*) printf '  FAIL  %s\n' "${line#FAIL }" ;;
      "skip "*) printf '  skip  %s\n' "${line#skip }" ;;
    esac
  done
  passed=$((passed + $(printf '%s\n' "$OUT" | grep -c '^ok ')))
  nf=$(printf '%s\n' "$OUT" | grep -c '^FAIL '); fails=$((fails + nf))
  if [ "$RC" != 0 ] && [ "$nf" = 0 ]; then printf '  FAIL  the page test crashed (exit %s): %s\n' "$RC" "$(printf '%s\n' "$OUT" | tail -3 | tr '\n' ' ')"; fails=$((fails + 1)); fi
  [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
else
  st_skip_browser "the page checks (the Tickets card, the repo options, filing) are not run"
fi

st_done
