#!/bin/bash
# Guardrails you can edit: bin/guardrails.py, `qtdeck guardrail`, the dashboard's /api/guardrails and /api/project/guardrails, and the card on a project's page.
# Everything runs in a throwaway Quarterdeck (the program tree is copied, the data folder is a temp folder with the .quarterdeck-home marker, HOME is a temp folder)
# against the fake provider and a real dashboard on a free port, paired through its one-time link. No network, no real model, no GitHub.
#
#   1  the library and the command line: listing, add, remove, move, the limits, what is refused, the locked rules, 0600, the log
#   2  the text the crew receives: the same bytes as a recorded prompt of a real duty and as lib.sh's own function
#   3  the API against a paired dashboard: shapes, the round trip, locked rules, who may write, Demo mode
#   4  the page, in a headless browser (skipped, saying so, when this machine has none)
ST_PROVIDER=fake
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init marshal
cp -R "$REAL"/bin/. "$T/bin/"; rm -rf "$T/bin/__pycache__" "$T/bin/integrations/__pycache__"
cp -R "$REAL/dashboard" "$T/dashboard"; cp -R "$REAL/packs" "$T/packs"
mkdir -p "$T/home" && export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
export QUARTERDECK_HOME="$T" REAL; touch "$T/.quarterdeck-home"
DASH=""
trap '[ -z "$DASH" ] || kill "$DASH" 2>/dev/null; [ -n "${QD_KEEP:-}" ] || rm -rf "$T"' EXIT
st_repo
st_pr 1 feat-ok src/ui/Button.tsx 'export const b = 1'
REG="$T/config/projects.json"
D4='["Never merge a pull request.","Never push to the default branch; every change goes on its own branch.","Never touch .env files or anything that holds a secret.","Follow the repository'"'"'s own AGENTS.md or CLAUDE.md where it has one."]'
jq -n --arg w "$T/work" --argjson g "$D4" '
  def p($g): {repo:"x/tp", path:$w, summary:"a fixture", default_branch:"main", duties:["marshal"], guardrails:$g, verify:""};
  {tp: p($g),
   odd: p($g[0:3] + ["Odd \"quote\" \\ back $x `tick` é ünï", "- dash first", "100% sure {braces} [brackets] *star*"]),
   legacy: p(["Never merge a pull request."]),
   other: p(["Keep it small."])}' > "$REG"
chmod 600 "$REG"
QD="bash $T/bin/qtdeck"
export PYTHONPATH="$T/bin"

# ---- 1. the library and the command line ----------------------------------------------------------------------------------------------------
cat > "$T/t1.py" <<'PY'
import json, os, stat, sys
sys.path.insert(0, os.environ["T"] + "/bin")
import attach, guardrails as g
T = os.environ["T"]; REG = T + "/config/projects.json"
def chk(label, cond): print(("ok " if cond else "FAIL ") + label)
def reg(): return json.load(open(REG))
def refused(fn, *a, word=""):
    try: fn(*a)
    except ValueError as e: return word in str(e)
    return False
L = g.listing("tp")
chk("listing: three locked rules with a reason each, the fourth built-in as an ordinary rule, the effective text and the limit",
    [x["text"] for x in L["locked"]] == attach.GUARDRAILS[:3] and all(len(x["reason"]) > 20 for x in L["locked"]) and L["custom"] == [attach.GUARDRAILS[3]]
    and L["effective"] == "\n".join("- " + x for x in attach.GUARDRAILS) and L["limit"] == 20 and L["missing_locked"] == [])
other_before = json.dumps(reg()["other"], sort_keys=True); odd_before = json.dumps(reg()["odd"], sort_keys=True)
g.add("tp", "  Keep each change small  ")
chk("add trims the text and appends it", g.listing("tp")["custom"][-1] == "Keep each change small")
g.add("tp", "Write a test first")
g.move("tp", "3", "up")
chk("move 3 up swaps it with the one above", g.listing("tp")["custom"] == [attach.GUARDRAILS[3], "Write a test first", "Keep each change small"])
g.move("tp", "Write a test first", "up")
chk("move by exact text works", g.listing("tp")["custom"][0] == "Write a test first")
chk("moving the first up and the last down is refused", refused(g.move, "tp", "1", "up", word="first") and refused(g.move, "tp", "3", "down", word="last") and refused(g.move, "tp", "1", "sideways"))
g.remove("tp", "1")
chk("remove by number", g.listing("tp")["custom"] == [attach.GUARDRAILS[3], "Keep each change small"])
g.remove("tp", "Keep each change small")
chk("remove by exact text", g.listing("tp")["custom"] == [attach.GUARDRAILS[3]])
chk("remove with no such number or text is refused", refused(g.remove, "tp", "9", word="no guardrail number") and refused(g.remove, "tp", "nonesuch", word="no guardrail says"))
for x in g.LOCKED:
    chk("locked: removing, moving and editing '" + x["text"][:24] + "' is refused with its reason",
        refused(g.remove, "tp", x["text"], word=x["reason"]) and refused(g.move, "tp", x["text"], "down", word=x["reason"])
        and refused(g.replace, "tp", [y["text"] if y is not x else x["text"] + " mostly" for y in g.LOCKED] + g.listing("tp")["custom"], word=x["reason"])
        and refused(g.replace, "tp", [y["text"] for y in g.LOCKED if y is not x] + g.listing("tp")["custom"], word=x["reason"]))
chk("replace puts the locked rules first whatever the order sent", g.replace("tp", ["Z last"] + attach.GUARDRAILS[2::-1])["effective"].startswith("- " + attach.GUARDRAILS[0]))
chk("  and a rule listed twice or already a locked rule in other letters is refused",
    refused(g.replace, "tp", attach.GUARDRAILS[:3] + ["a", "A "], word="already") and refused(g.add, "tp", "NEVER merge a  pull request.", word="already") and refused(g.add, "tp", "Z last", word="already"))
bad = {"empty": "   ", "a line break": "one\ntwo", "a control character": "a\x07b", "a comment marker": "x <!-- y", "a prompt marker": "see BEGIN UNTRUSTED issue 1234", "an end marker": "end  untrusted body",
       "a credential": "use ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "a private key": "-----BEGIN RSA PRIVATE KEY-----", "301 characters": "x" * 301}
for k, v in bad.items(): chk("refused: " + k, refused(g.add, "tp", v))
chk("  and the credential-shaped text is not in the answer", (lambda r: "a1B2c3D4" not in r.stdout + r.stderr and r.returncode != 0)(__import__("subprocess").run([sys.executable, T + "/bin/guardrails.py", "tp", "add", bad["a credential"]], capture_output=True, text=True)))
g.add("tp", "y" * 300)
chk("exactly 300 characters is allowed", len(g.listing("tp")["custom"][-1]) == 300)
g.remove("tp", "y" * 300)
for i in range(19): g.add("tp", "rule number %d" % i)
n = len(g.listing("tp")["custom"])
chk("20 rules of its own are allowed, the 21st is refused", n == 20 and refused(g.add, "tp", "one too many", word="at most 20"))
for i in range(19): g.remove("tp", "rule number %d" % i)
chk("the registry stays 0600, no temp file is left, and every other project is byte for byte as it was",
    stat.S_IMODE(os.stat(REG).st_mode) == 0o600 and not os.path.exists(REG + ".tmp") and json.dumps(reg()["other"], sort_keys=True) == other_before and json.dumps(reg()["odd"], sort_keys=True) == odd_before)
chk("an unknown project is refused", refused(g.listing, "nosuch", word="not registered") and refused(g.add, "nosuch", "x", word="not registered"))
leg = g.listing("legacy")
chk("a project whose list lacks locked rules says so, and the first save puts them back in front", len(leg["missing_locked"]) == 2 and g.add("legacy", "Mine")["effective"].startswith("- " + attach.GUARDRAILS[0] + "\n- " + attach.GUARDRAILS[1]) and g.listing("legacy")["missing_locked"] == [])
lines = open(T + "/logs/guardrails.log").read().splitlines()
chk("the log has one line per change: time, project, action, new count, clipped text", all(l.split(" ")[1] == "tp" or l.split(" ")[1] == "legacy" for l in lines) and any(" add 2 Keep each change small" in l for l in lines)
    and any(" remove " in l for l in lines) and any(" move " in l for l in lines) and all(l[:4] == "2026" or l[:2] == "20" for l in lines) and not any("a1B2c3D4" in l for l in lines))
g.add("tp", "z" * 200)
chk("  and a long rule is clipped to 120 characters in the log", open(T + "/logs/guardrails.log").read().splitlines()[-1].endswith(" " + "z" * 120))
g.remove("tp", "z" * 200)
chk("attach.edit still refuses an empty list and a list without the secrets rule, naming it, and accepts the full standing list",
    refused(attach.edit, {"entry": {"duties": ["marshal"], "verify": "", "guardrails": []}}, {"guardrails": []}, word="locked")
    and refused(attach.edit, {"entry": {"duties": [], "verify": "", "guardrails": []}}, {"guardrails": attach.GUARDRAILS[:2]}, word="secret")
    and attach.edit({"entry": {"duties": [], "verify": "", "guardrails": []}}, {"guardrails": attach.GUARDRAILS})["entry"]["guardrails"] == attach.GUARDRAILS)
PY
pyck() { # pyck <file.py>: each "ok ..." / "FAIL ..." line is one check; a block that crashes is one failed check
  local line n=0 prc
  python3 "$1" > "$T/py.out" 2> "$T/py.err"; prc=$?
  while IFS= read -r line; do
    case "$line" in
      ok\ *)   printf '  ok    %s\n' "${line#ok }"; passed=$((passed + 1)); n=$((n + 1)) ;;
      FAIL\ *) printf '  FAIL  %s\n' "${line#FAIL }"; fails=$((fails + 1)); n=$((n + 1)) ;;
    esac
  done < "$T/py.out"
  if [ "$prc" != 0 ] || [ "$n" = 0 ]; then printf '  FAIL  a python block crashed (exit %s): %s\n' "$prc" "$(tail -3 "$T/py.err" | tr '\n' ' ')"; fails=$((fails + 1)); fi
}
export T
pyck "$T/t1.py"

# the command line (tp starts again from the four standing rules)
jq --argjson g "$D4" '.tp.guardrails = $g' "$REG" > "$T/reg.tmp" && cat "$T/reg.tmp" > "$REG"
OUT=$($QD guardrail tp list 2>&1); RC=$?
ck "qtdeck guardrail <p> list: the locked ones marked with their reason, then the custom ones numbered, then the line about the crew" \
   '[ $RC = 0 ] && [ "$(grep -c "^  locked  " <<<"$OUT")" = 3 ] && grep -q "^   1\. " <<<"$OUT" && grep -q "only you merge" <<<"$OUT" && grep -q "This is what the crew receives" <<<"$OUT" && grep -q -- "--effective" <<<"$OUT"'
OUT=$($QD guardrail tp add "Name every file you change" 2>&1); RC=$?
ck "add: a plain message, exit 0, and the rule is in the registry" '[ $RC = 0 ] && grep -q "^Added" <<<"$OUT" && jq -e ".tp.guardrails | index(\"Name every file you change\")" "$REG" >/dev/null'
OUT=$($QD guardrail tp move 2 up 2>&1); RC=$?
ck "move <number> up" '[ $RC = 0 ] && [ "$(jq -r ".tp.guardrails[3]" "$REG")" = "Name every file you change" ]'
OUT=$($QD guardrail tp remove 1 2>&1); RC=$?
ck "remove <number>" '[ $RC = 0 ] && [ "$(jq -r ".tp.guardrails | length" "$REG")" = 4 ]'
OUT=$($QD guardrail tp remove "Follow the repository's own AGENTS.md or CLAUDE.md where it has one." 2>&1); RC=$?
ck "remove <text>" '[ $RC = 0 ] && [ "$(jq -r ".tp.guardrails | length" "$REG")" = 3 ]'
BEFORE=$(cksum < "$REG")
for a in 'remove "Never merge a pull request."' 'move "Never merge a pull request." down' 'add "Never merge a pull request."' 'add "key ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"' 'remove 9' 'move 1 up' 'add ""' 'frobnicate'; do
  OUT=$(eval "$QD guardrail tp $a" 2>&1); RC=$?
  ck "refused change ($a): non-zero exit, a reason, no registry change" '[ $RC != 0 ] && [ -n "$OUT" ] && [ "$(cksum < "$REG")" = "$BEFORE" ] && ! grep -q a1B2c3D4 <<<"$OUT"'
done
OUT=$($QD guardrail nosuch list 2>&1); RC=$?
ck "an unknown project is a plain error" '[ $RC != 0 ] && grep -q "unknown project\|which project" <<<"$OUT"'
ck "the registry is 0600 after the command line too" '[ "$(stat -c %a "$REG" 2>/dev/null || stat -f %Lp "$REG")" = 600 ]'
ck "help more lists the command" '$QD help more | grep -q "guardrail <project>"'

# ---- 2. the text the crew receives -------------------------------------------------------------------------------------------------------
$QD guardrail tp add 'Say "why" in the commit, with a \ and a $HOME and a `tick`' >/dev/null
for P in tp odd; do
  jq --arg p "$P" '.[$p].duties = ["marshal"]' "$REG" > "$T/reg.tmp" && cat "$T/reg.tmp" > "$REG"
  jq 'with_entries(.value.path = "'"$T/work"'")' "$REG" > "$T/reg.tmp" && cat "$T/reg.tmp" > "$REG"
  rm -f "$T/claude-calls"; st_noreplies; st_reply default 'FINDINGS_JSON: []
ADR: searched none
VERDICT: CLEAN'
  OUT=$(QUARTERDECK_PROJECT="$P" QUARTERDECK_WORKDIR="$T/work" bash "$T/duties/marshal.sh" --pr 1 2>&1); RC=$?
  python3 - "$P" > "$T/eff.sent" <<'PY'
import json, sys
calls = [json.loads(l) for l in open(__import__("os").environ["T"] + "/claude-calls") if l.strip()]
pr = calls[0]["prompt"]
sys.stdout.write(pr.split("Hard rules for this project:\n", 1)[1].split("\n\n", 1)[0])
PY
  python3 "$T/bin/guardrails.py" effective "$P" > "$T/eff.py"
  $QD guardrail "$P" list --effective > "$T/eff.cli"
  bash -c 'source "$1/bin/lib.sh"; project_guardrails "$2"' _ "$T" "$P" > "$T/eff.sh"
  ck "$P: the rules in a recorded fake-provider prompt of a real duty equal guardrails.effective_text byte for byte" '[ -s "$T/eff.sent" ] && [ "$(cat "$T/eff.sent")" = "$(cat "$T/eff.py")" ]'
  ck "$P: qtdeck guardrail list --effective and lib.sh project_guardrails print the same bytes" 'cmp -s "$T/eff.cli" "$T/eff.py" && [ "$(cat "$T/eff.sh")" = "$(cat "$T/eff.py")" ]'
done

# ---- 3. the API ----------------------------------------------------------------------------------------------------------------------------
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
export QD_PORT="$PORT"
QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" > "$T/dash.log" 2>&1 &
DASH=$!
if ! st_http_up "http://127.0.0.1:$PORT/api/health"; then echo "  FAIL  the dashboard did not start: $(tail -3 "$T/dash.log" | tr '\n' ' ')"; exit 1; fi
cat > "$T/qc.py" <<'PY'
import http.client, json, os, subprocess, sys
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
    st, j, ck = req("POST", "/api/pair", {"nonce": link.split("#pair=")[1]})
    return {"cookie": ck.split(";")[0], "token": j["token"]}
S = pair()
def get(path): return req("GET", path, headers={"Cookie": S["cookie"]})[:2]
def post(path, body, **over):
    h = {"Cookie": S["cookie"], "X-Quarterdeck-Token": S["token"], "Origin": ORIGIN}
    h.update(over)
    return req("POST", path, body, {k: v for k, v in h.items() if v is not None})[:2]
REGF = T + "/config/projects.json"
def raw(): return open(REGF, "rb").read()
LOCK = ["Never merge a pull request.", "Never push to the default branch; every change goes on its own branch.", "Never touch .env files or anything that holds a secret."]
U = "/api/project/guardrails"
PY
cat > "$T/t3.py" <<'PY'
exec(open(__import__("os").environ["T"] + "/qc.py").read())
st, j = get("/api/guardrails?project=other")
chk("GET /api/guardrails: locked (text and reason), custom, effective, limit", st == 200 and [x["text"] for x in j["locked"]] == LOCK and all(x["reason"] for x in j["locked"]) and j["custom"] == ["Keep it small."]
    and j["effective"] == "- Keep it small." and j["limit"] == 20 and j["missing_locked"] == LOCK)
chk("  a bad or missing project is a 400, and unpaired it is 401", get("/api/guardrails?project=nosuch")[0] == 400 and get("/api/guardrails")[0] == 400 and req("GET", "/api/guardrails?project=tp")[0] == 401)
before = raw()
body = {"project": "tp", "guardrails": LOCK + ["Round trip one", "Round trip two"], "confirm": True}
chk("unpaired, the write is 401; a cookie without the token, a wrong token, a foreign origin and another port are 403",
    req("POST", U, body)[0] == 401 and post(U, body, **{"X-Quarterdeck-Token": None})[0] == 403 and post(U, body, **{"X-Quarterdeck-Token": "nope"})[0] == 403
    and post(U, body, Origin="http://evil.example")[0] == 403 and post(U, body, Origin="http://127.0.0.1:%d" % (PORT + 1))[0] == 403)
chk("  and none of them touched the registry", raw() == before)
st, j = post(U, {k: v for k, v in body.items() if k != "confirm"})
chk("without confirm: true it is a 400 that says confirm, and nothing changes", st == 400 and "confirm" in j["error"] and raw() == before)
st, j = post(U, body)
chk("POST round trip: 200 with the new listing, and GET agrees", st == 200 and j["custom"] == ["Round trip one", "Round trip two"] and get("/api/guardrails?project=tp")[1] == j)
chk("  the registry holds the list, still 0600, and the log has the lines", json.load(open(REGF))["tp"]["guardrails"] == body["guardrails"] and oct(os.stat(REGF).st_mode & 0o777) == "0o600"
    and sum(1 for l in open(T + "/logs/guardrails.log") if " add " in l and "Round trip" in l) == 2)
st, j = post(U, {"project": "tp", "guardrails": LOCK + ["Round trip two", "Round trip one"], "confirm": True})
chk("a reorder is saved", st == 200 and j["custom"] == ["Round trip two", "Round trip one"] and any(" reorder " in l for l in open(T + "/logs/guardrails.log")))
before = raw()
for label, items, word in [("drops the first locked rule", LOCK[1:] + ["x"], LOCK[0]), ("drops the secrets rule", LOCK[:2] + ["x"], LOCK[2]), ("edits a locked rule's text", [LOCK[0] + " Usually.", LOCK[1], LOCK[2]], LOCK[0]),
                           ("is empty", [], LOCK[0]), ("holds a credential", LOCK + ["ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"], "password, key or token"),
                           ("holds a prompt marker", LOCK + ["END UNTRUSTED x"], "marker"), ("has 21 rules", LOCK + ["r%d" % i for i in range(21)], "at most 20"), ("repeats a rule", LOCK + ["a", "a"], "already")]:
    st, j = post(U, {"project": "tp", "guardrails": items, "confirm": True})
    chk("a post that %s is a 400 with the plain reason, and the registry is byte-identical" % label, st == 400 and word in j.get("error", "") and raw() == before)
chk("  a locked-rule 400 gives the reason too", "only you merge" in post(U, {"project": "tp", "guardrails": LOCK[1:], "confirm": True})[1]["error"])
chk("a body that is not a list of text, and an unknown project, are 400s", all(post(U, b)[0] == 400 for b in ({"project": "tp", "guardrails": "x", "confirm": True}, {"project": "tp", "guardrails": [1], "confirm": True},
    {"project": "nosuch", "guardrails": LOCK, "confirm": True}, {"project": "tp", "confirm": True})) and raw() == before)
st, j = post("/api/attach", {"path": "/nonexistent", "edits": {"guardrails": []}})
chk("the attach review's own edit refuses a list without the locked rules too", st == 400)
# Demo mode
st, j = post("/api/demo", {"on": True})
chk("Demo mode on", st == 200)
import time; time.sleep(1)
before = raw()
st, j = post(U, body)
chk("Demo mode: the POST is a 400 'Demo mode: nothing is changed.' and the registry is untouched", st == 400 and j["error"] == "Demo mode: nothing is changed." and raw() == before)
names = [p["name"] for p in get("/api/state")[1]["projects"]]
st, j = get("/api/guardrails?project=" + names[0])
chk("Demo mode: GET serves invented data (the locked rules and made-up ones)", st == 200 and [x["text"] for x in j["locked"]] == LOCK and len(j["custom"]) >= 1 and j.get("demo") is True and "tp" not in json.dumps(j["custom"]))
post("/api/demo", {"on": False}); time.sleep(1)
chk("Demo mode off again: the real project reads again", get("/api/guardrails?project=tp")[1]["custom"] == ["Round trip two", "Round trip one"])
PY
pyck "$T/t3.py"

# ---- 4. the page -----------------------------------------------------------------------------------------------------------------------------
if st_have_browser || node "$REAL/bin/guardrails-page.mjs" probe >/dev/null 2>&1; then
  mkdir -p "$T/shots"
  jq '.tp.guardrails = '"$D4" "$REG" > "$T/reg.tmp" && cat "$T/reg.tmp" > "$REG"
  LINK=$(QUARTERDECK_DASHBOARD_PORT="$PORT" python3 "$T/bin/dashboard.py" link)
  out=$(QD_LINK="$LINK" QD_PROJECT=tp QD_SHOTS="$T/shots" QD_T="$T" node "$REAL/bin/guardrails-page.mjs" 2>&1 | tee -a "${QD_PAGE_LOG:-/dev/null}"); rc=${PIPESTATUS[0]}
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
  [ -z "${QD_KEEP_SHOTS:-}" ] || cp -R "$T/shots" "$QD_KEEP_SHOTS"
else
  st_skip "no browser can start here: the guardrails card checks (locked rules, add, move, edit, save, reload, remove, Calm, 390px) are not run"
fi

st_done
