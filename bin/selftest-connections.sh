#!/bin/bash
# Connections: the instructions on every card are right and fit, and (below) several accounts of one service. Fake services only: no network,
# no credential, a temp data folder with the .quarterdeck-home marker and a temp secrets folder, never the real home.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/data" "$T/secrets"; : > "$T/data/.quarterdeck-home"
export QUARTERDECK_HOME="$T/data" QUARTERDECK_SECRETS_DIR="$T/secrets" HOME="$T/home"; mkdir -p "$HOME"
unset QUARTERDECK_DIR
fails=0
ck() { local label=$1 cond=$2; if eval "$cond"; then printf '  ok    %s\n' "$label"; else printf '  FAIL  %s\n' "$label"; fails=$((fails+1)); fi; }
py() { python3 -I -c "import sys; sys.path.insert(0, '$HERE'); $1" 2>&1; }

echo "connections: instructions"
ck "no manifest step is longer than the 240 characters the page keeps (a longer one would be cut short)" \
   '[ "$(python3 - "$HERE/integrations/services" <<PY
import json, sys, pathlib
bad = [f"{f.stem}: {len(s)}" for f in pathlib.Path(sys.argv[1]).glob("*.json") for s in json.loads(f.read_text()).get("steps", []) if len(s) > 240]
print(len(bad))
PY
)" = 0 ]'
ck "Gmail says the token expires after 7 days while the app is in Testing, and tells you to publish it to production first" \
   'py "from integrations import manifest; s = [x for x in manifest.load_services() if x[\"id\"] == \"gmail\"][0][\"steps\"]; t = \" \".join(s); assert \"7 days\" in t and \"In production\" in t and \"Testing\" in t; assert [i for i, x in enumerate(s) if \"In production\" in x][0] < [i for i, x in enumerate(s) if \"google_oauth.py\" in x][0]" >/dev/null'
ck "Site analytics has a property id field, and its steps name the exact data folder path of integrations.json" \
   'py "from integrations import manifest, common; r = [x for x in manifest.status(have=set(), cfg=common.load_config(), recorded={}) if x[\"id\"] == \"ga4\"][0]; assert \"GA4_PROPERTY_ID\" in [c[\"key\"] for c in r[\"credentials\"]]; assert any(str(common.HOME) + \"/config/integrations.json\" in s for s in r[\"steps\"]), r[\"steps\"]" >/dev/null'
ck "Site analytics reads the property id from the page field first, then from the config file" \
   'py "from integrations import ga4, common; import inspect; src = inspect.getsource(ga4.fetch); assert src.index(\"GA4_PROPERTY_ID\") < src.index(\"property_id\")" >/dev/null'
ck "Slack asks for the eight narrowest scopes (no channel or private channel history) and the steps agree" \
   'py "from integrations import manifest; m = [x for x in manifest.load_services() if x[\"id\"] == \"slack\"][0]; assert sorted(m[\"scopes\"]) == sorted([\"im:read\",\"im:history\",\"mpim:read\",\"mpim:history\",\"channels:read\",\"groups:read\",\"users:read\",\"search:read\"]); t = \" \".join(m[\"steps\"]); assert \"eight\" in t and \"channels:history\" in t" >/dev/null'
ck "Slack, run against a fake workspace, reads history only of direct messages and never of a channel where you were mentioned" \
   'py "
from integrations import slack, common
import json
calls = []
def fake(method, url, headers, data, timeout):
    from urllib.parse import urlparse, parse_qs
    u = urlparse(url); m = u.path.rsplit(\"/\", 1)[-1]; q = {k: v[0] for k, v in parse_qs(u.query).items()}
    calls.append((m, q.get(\"channel\", \"\")))
    out = {\"auth.test\": {\"ok\": True, \"user_id\": \"U1\"},
           \"conversations.list\": {\"ok\": True, \"channels\": [{\"id\": \"D1\", \"is_im\": True}]},
           \"conversations.info\": {\"ok\": True, \"channel\": {\"last_read\": \"100.0\"}},
           \"conversations.history\": {\"ok\": True, \"messages\": [{\"user\": \"U2\", \"text\": \"hi\", \"ts\": \"200.0\"}]},
           \"users.info\": {\"ok\": True, \"user\": {\"name\": \"sam\"}},
           \"chat.getPermalink\": {\"ok\": True, \"permalink\": \"https://example.slack.com/x\"},
           \"search.messages\": {\"ok\": True, \"messages\": {\"matches\": [{\"channel\": {\"id\": \"C9\", \"name\": \"general\"}, \"ts\": \"300.0\", \"text\": \"ping\", \"permalink\": \"https://example.slack.com/y\"}]}}}[m]
    return 200, json.dumps(out).encode()
common.TRANSPORT = fake; common.SLEEP = lambda s: None
r = slack.fetch({\"SLACK_USER_TOKEN\": \"xoxp-fake\"}, common.load_config())
hist = [c for m, c in calls if m == \"conversations.history\"]
assert hist == [\"D1\"], hist
assert r[\"slack\"][\"unread\"] == 2
" >/dev/null'
ck "the calendar helper is named QuarterdeckAgenda.app and built with bash tools/agenda/build.sh" \
   'py "from integrations import manifest; t = \" \".join([x for x in manifest.load_services() if x[\"id\"] == \"calendar\"][0][\"steps\"]); assert \"QuarterdeckAgenda.app\" in t and \"bash tools/agenda/build.sh\" in t" >/dev/null && grep -q "QuarterdeckAgenda.app" "$HERE/../tools/agenda/build.sh"'

# ---- several accounts of one service. Every check below runs in its own fresh temp world (data folder with the marker, secrets folder,
# home), with a fake transport and a stub `security`: no network, no credential, never the real home or the real keychain.
PRELUDE=$(cat <<EOF
import os, sys, json, tempfile, stat, shutil
sys.path.insert(0, "$HERE")
W = tempfile.mkdtemp(prefix="qd-acct-")
for sub in ("data", "sec", "home"):
    os.makedirs(W + "/" + sub)
open(W + "/data/.quarterdeck-home", "w").close()
os.environ.update(QUARTERDECK_HOME=W + "/data", QUARTERDECK_SECRETS_DIR=W + "/sec", HOME=W + "/home")
os.environ.pop("QUARTERDECK_DIR", None)
from integrations import common, manifest, accounts, run, loop, google_oauth, keychain
common.SLEEP = lambda s: None
assert str(common.HOME).startswith(W) and str(common.CONFIG_DIR).startswith(W), (common.HOME, common.CONFIG_DIR)
def env_text():
    return common.env_path().read_text() if common.env_path().is_file() else ""
def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)
def tree():
    return sorted((str(p.relative_to(W)), p.stat().st_mtime_ns) for p in __import__("pathlib").Path(W).rglob("*") if p.is_file())
# a fake Google and Gmail: the sign-in token decides which mailbox answers
from urllib.parse import parse_qs
def fake(method, url, headers, data, timeout):
    if "oauth2.googleapis.com/token" in url:
        rt = parse_qs(data.decode())["refresh_token"][0]
        return (401, b"") if rt == "RT-bad" else (200, json.dumps({"access_token": "AT-" + rt}).encode())
    who = headers["Authorization"].split("AT-RT-")[1]
    if "/messages/" in url:
        return 200, json.dumps({"payload": {"headers": [{"name": "Subject", "value": "Hello from " + who}, {"name": "From", "value": who + "@example.test"},
                                                          {"name": "Date", "value": "Mon, 05 Oct 2026 09:30:00 +0000"}]}}).encode()
    return 200, json.dumps({"messages": [{"id": "m1"}], "resultSizeEstimate": 1}).encode()
common.TRANSPORT = fake
def sign_in(label, rt):
    common.write_private(google_oauth.token_file("gmail", label), json.dumps({"refresh_token": rt}))
def creds(label, cid, sec):
    manifest.set_credential("GOOGLE_OAUTH_CLIENT_ID", cid, label=label)
    manifest.set_credential("GOOGLE_OAUTH_CLIENT_SECRET", sec, label=label)
EOF
)
pyk() { local label=$1 out; out=$(python3 -I -c "$PRELUDE
$(cat)" 2>&1) && printf '  ok    %s\n' "$label" || { printf '  FAIL  %s\n' "$label"; printf '%s\n' "$out" | tail -6 | sed 's/^/        /'; fails=$((fails+1)); }; }

echo
echo "connections: several accounts"
pyk "an account label is lowercase letters, digits and dashes, at most 24, and starts with a letter or a digit" <<'PY'
for good in ("work", "personal", "a1-b2", "x" * 24, "9lives"):
    assert accounts.norm(good) == good, good
assert accounts.norm(None) == "default" and accounts.norm("") == "default"
for bad in ("Work", "x" * 25, "a b", "../x", "-x", "a@b", "a_b", "a.b", "é", " work", "work\n", 5):
    try:
        accounts.norm(bad)
    except ValueError as e:
        assert "lowercase letters, digits and dashes, at most 24" in str(e)
    else:
        raise AssertionError("accepted " + repr(bad))
try:
    manifest.add_account("gmail", "default")
except ValueError:
    pass
else:
    raise AssertionError("add_account took default")
for bad in ("", "Work", "x" * 25, "../x"):
    try:
        manifest.add_account("gmail", bad) if bad else manifest.add_account("gmail", None)
    except ValueError:
        pass
    else:
        raise AssertionError("add_account took " + repr(bad))
assert accounts.cred_key("K") == "K" and accounts.cred_key("K", "work") == "K@work"
PY
pyk "a service that holds no credential, or is read by a helper app, takes one account; a service with credentials takes several" <<'PY'
many = {m["id"]: m["accounts"] for m in manifest.load_services()}
assert many["gmail"] and many["slack"] and many["meta"] and many["ga4"], many
assert not many["calendar"] and not many["linkedin"] and not many["macmail"], many
for sid in ("calendar", "linkedin", "macmail"):
    try:
        manifest.add_account(sid, "work")
    except ValueError as e:
        assert "one account" in str(e)
    else:
        raise AssertionError(sid)
c = manifest._clean({"id": "mine", "credentials": [{"key": "MINE_TOKEN"}], "accounts": False})
assert c["accounts"] is False and manifest._clean({"id": "mine", "credentials": [{"key": "MINE_TOKEN"}]})["accounts"] is True
assert manifest._clean({"id": "bare"})["accounts"] is False
PY
pyk "two Gmail accounts keep separate credentials in the private file: KEY and KEY@work side by side, mode 0600, never returned" <<'PY'
creds("default", "cid-default-111", "sec-default-222")
manifest.add_account("gmail", "work")
creds("work", "cid-work-333", "sec-work-444")
t = env_text()
assert "GOOGLE_OAUTH_CLIENT_ID=" in t and "GOOGLE_OAUTH_CLIENT_ID@work=" in t and "GOOGLE_OAUTH_CLIENT_SECRET@work=" in t, t
assert mode(common.env_path()) == 0o600 and mode(common.CONFIG_DIR) == 0o700, (oct(mode(common.env_path())), oct(mode(common.CONFIG_DIR)))
assert common.load_env() == {"GOOGLE_OAUTH_CLIENT_ID": "cid-default-111", "GOOGLE_OAUTH_CLIENT_SECRET": "sec-default-222"}, "default sees only its own"
assert common.load_env("work") == {"GOOGLE_OAUTH_CLIENT_ID": "cid-work-333", "GOOGLE_OAUTH_CLIENT_SECRET": "sec-work-444"}, "work sees only its own"
assert manifest.env_keys() == {"GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"} == manifest.env_keys("work")
out = json.dumps(manifest.status()) + json.dumps(manifest.store_info())
for v in ("cid-default-111", "sec-default-222", "cid-work-333", "sec-work-444"):
    assert v not in out, "a value came back"
row = [r for r in manifest.status() if r["id"] == "gmail"][0]
assert [a["label"] for a in row["accounts"]] == ["default", "work"] and row["multi"] is True
assert all(c["present"] for a in row["accounts"] for c in a["credentials"])
manifest.set_credential("GOOGLE_OAUTH_CLIENT_ID", "", label="work")
assert "GOOGLE_OAUTH_CLIENT_ID@work" not in env_text() and "GOOGLE_OAUTH_CLIENT_ID=" in env_text() and "GOOGLE_OAUTH_CLIENT_SECRET@work=" in env_text()
PY
pyk "a labelled account with no keys of its own is missing them: it never falls back to the default account" <<'PY'
creds("default", "cid-default-111", "sec-default-222")
manifest.add_account("gmail", "personal")
manifest.set_enabled("gmail", True, label="personal")
assert common.load_env("personal") == {}
row = [r for r in manifest.status() if r["id"] == "gmail"][0]
d, p = row["accounts"]
assert d["label"] == "default" and p["label"] == "personal"
assert p["missing"] == ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"] and p["state"] == "needs set-up" and not any(c["present"] for c in p["credentials"]), p
assert d["missing"] == [] and all(c["present"] for c in d["credentials"])
sign_in("personal", "RT-personal")
ok, msg = run.run_source("gmail", "personal")
assert not ok and "GOOGLE_OAUTH_CLIENT_ID@personal" in msg, msg
assert not (common.STATE / "connectors" / "gmail" / "personal").exists()
PY
pyk "a missing sign-in says to run the sign-in command with --account for a labelled account, and without it for the default" <<'PY'
creds("default", "c", "s"); manifest.add_account("gmail", "work"); creds("work", "c2", "s2")
ok, msg = run.run_source("gmail", "work")
assert not ok and "google_oauth.py gmail --account work" in msg, msg
ok, msg = run.run_source("gmail")
assert not ok and msg.endswith("google_oauth.py gmail") and "--account" not in msg, msg
sign_in("work", "RT-bad"); ok, msg = run.run_source("gmail", "work")
assert not ok and "token expired" in msg and "--account work" in msg, msg
assert google_oauth.token_file("gmail").name == "google-gmail-token.json" and google_oauth.token_file("gmail", "work").name == "google-gmail-work-token.json"
PY
pyk "the keychain keeps KEY@label items too, and move_store carries every account both ways and back (stub security, never the real keychain)" <<'PY'
stub = W + "/security"
open(stub, "w").write("""#!/usr/bin/env python3
import binascii, json, os, sys
db = os.environ["QD_STUB_DB"]; items = json.load(open(db)) if os.path.exists(db) else {}
def opt(a, n): return a[a.index(n) + 1]
def run(a):
    if a[0] == "find-generic-password":
        k = opt(a, "-a")
        if k not in items: return 44
        print(items[k] if "-w" in a else 'attributes: "acct"<blob>="' + k + '"'); return 0
    if a[0] == "delete-generic-password":
        return 0 if items.pop(opt(a, "-a"), None) is not None else 44
    if a[0] == "add-generic-password":
        items[opt(a, "-a")] = binascii.unhexlify(opt(a, "-X")).decode(); return 0
    return 1
if sys.argv[1] == "-i":
    import shlex
    for l in [l for l in sys.stdin.read().splitlines() if l.strip()]: run(shlex.split(l))
    json.dump(items, open(db, "w")); sys.exit(0)
rc = run(sys.argv[1:]); json.dump(items, open(db, "w")); sys.exit(rc)
""")
os.chmod(stub, 0o755)
os.environ["QD_STUB_DB"] = W + "/kc.json"
keychain.SECURITY, keychain.PLATFORM = stub, "darwin"
assert keychain.SECURITY != "/usr/bin/security"
creds("default", "cid-d", "sec-d"); manifest.add_account("gmail", "work"); creds("work", "cid-w", "sec-w")
manifest.set_credential("SLACK_USER_TOKEN", "xoxp-d")
assert manifest.move_store("keychain") >= 5
assert not env_text().strip(), "the file still holds credentials"
assert json.load(open(W + "/kc.json")).keys() >= {"GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_ID@work", "GOOGLE_OAUTH_CLIENT_SECRET@work", "SLACK_USER_TOKEN"}
assert common.store_kind() == "keychain"
assert common.load_env("work") == {"GOOGLE_OAUTH_CLIENT_ID": "cid-w", "GOOGLE_OAUTH_CLIENT_SECRET": "sec-w"}
assert common.load_env()["GOOGLE_OAUTH_CLIENT_ID"] == "cid-d"
assert manifest.env_keys("work") == {"GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"} and manifest.env_keys("nope") == set()
manifest.set_credential("GOOGLE_OAUTH_CLIENT_ID", "cid-w2", label="work")
assert common.load_env("work")["GOOGLE_OAUTH_CLIENT_ID"] == "cid-w2" and common.load_env()["GOOGLE_OAUTH_CLIENT_ID"] == "cid-d"
manifest.set_credential("GOOGLE_OAUTH_CLIENT_ID", "", label="work")
assert "GOOGLE_OAUTH_CLIENT_ID@work" not in json.load(open(W + "/kc.json")) and "GOOGLE_OAUTH_CLIENT_ID" in json.load(open(W + "/kc.json"))
manifest.set_credential("GOOGLE_OAUTH_CLIENT_ID", "cid-w3", label="work")
assert manifest.move_store("file") >= 5
t = env_text()
assert "GOOGLE_OAUTH_CLIENT_ID@work=" in t and "GOOGLE_OAUTH_CLIENT_SECRET@work=" in t and "SLACK_USER_TOKEN=" in t, t
assert json.load(open(W + "/kc.json")) == {}, "the keychain still holds items"
assert common.load_env("work")["GOOGLE_OAUTH_CLIENT_ID"] == "cid-w3" and mode(common.env_path()) == 0o600
assert manifest.move_store("keychain") >= 5 and common.load_env("work")["GOOGLE_OAUTH_CLIENT_SECRET"] == "sec-w"
try:
    keychain._line("KEY@work\nadd-generic-password -s x", "v")
except keychain.KeychainError:
    pass
else:
    raise AssertionError("a name with a line break was taken")
l = keychain._line("GOOGLE_OAUTH_CLIENT_ID@work", "v")
assert l.count("\n") == 1 and l.endswith("\n") and "-a GOOGLE_OAUTH_CLIENT_ID@work " in l
PY
pyk "two accounts refresh into separate folders; the default account also keeps the flat file; one failing account does not stop or mark the other" <<'PY'
creds("default", "cid-d", "sec-d"); sign_in("default", "RT-default")
for lab, rt in (("work", "RT-work"), ("personal", "RT-bad")):
    manifest.add_account("gmail", lab); manifest.set_enabled("gmail", True, label=lab)
    creds(lab, "cid-" + lab, "sec-" + lab); sign_in(lab, rt)
manifest.set_enabled("gmail", True)
res = run.run_all()
assert set(res) >= {"gmail", "gmail@work", "gmail@personal"}, res
assert res["gmail"][0] and res["gmail@work"][0] and not res["gmail@personal"][0], res
S = common.STATE / "connectors"
f = lambda *p: json.loads(S.joinpath(*p).read_text())
assert f("gmail.json")["items"][0]["title"] == "Hello from default"
assert f("gmail", "default", "gmail.json")["items"][0]["title"] == "Hello from default"
assert f("gmail", "work", "gmail.json")["items"][0]["title"] == "Hello from work"
assert not (S / "gmail" / "personal" / "gmail.json").exists(), "a failed refresh wrote a snapshot"
assert not (S / "gmail" / "work.json").exists() and not (S / "work.json").exists()
assert mode(S / "gmail" / "work" / "gmail.json") == 0o600 and mode(S / "gmail" / "work") == 0o700 and mode(S / "gmail") == 0o700 and mode(S / "gmail.json") == 0o600
st = common.read_status()
assert st["gmail"]["ok"] and st["gmail@work"]["ok"] and st["gmail@personal"]["ok"] is False, st
assert "--account personal" in st["gmail@personal"]["error_short"]
row = [r for r in manifest.status() if r["id"] == "gmail"][0]
by = {a["label"]: a for a in row["accounts"]}
assert by["default"]["state"] == "ok" and by["work"]["state"] == "ok" and by["personal"]["state"] == "failing", {k: v["state"] for k, v in by.items()}
assert row["state"] == "ok" and row["error"] == "" and "token expired" in by["personal"]["error"]
assert not any("AT-" in json.dumps(v) or "RT-" in json.dumps(v) for v in (st, row))
PY
pyk "meta writes facebook and instagram under state/connectors/meta/<label>/ for each account" <<'PY'
from integrations import meta
common.write_snapshot("facebook", [{"title": "p"}], service="meta", label="work")
common.write_snapshot("instagram", [{"title": "q"}], service="meta", label="work")
S = common.STATE / "connectors"
assert (S / "meta" / "work" / "facebook.json").is_file() and (S / "meta" / "work" / "instagram.json").is_file()
assert not (S / "facebook.json").exists(), "a labelled account wrote the flat file"
assert common.read_snapshot("facebook", "meta", "work")["items"][0]["title"] == "p" and common.read_snapshot("facebook", "meta", "default") is None
common.record_status("facebook", True, "", 1.0, "work")
assert "facebook@work" in common.read_status() and "facebook" not in common.read_status()
PY
pyk "the loop yields gmail and gmail@work by their own flags, one interval per service, and runs a labelled one with --account" <<'PY'
cfg = {"sources": {"gmail": {"enabled": True, "minutes": 10, "accounts": {"work": {"enabled": True}, "off": {"enabled": False}}},
                   "slack": {"enabled": False, "minutes": 5, "accounts": {"team": {"enabled": True}}}}}
assert loop.due_sources(cfg, {}, 1000.0) == ["gmail", "gmail@work", "slack@team"], loop.due_sources(cfg, {}, 1000.0)
assert loop.due_sources(cfg, {"gmail": 900.0, "gmail@work": 0, "slack@team": 900.0}, 1000.0) == ["gmail@work"]
called, last = [], {}
loop.run_due(cfg, last, 1000.0, runner=called.append); loop.run_due(cfg, last, 1100.0, runner=called.append); loop.run_due(cfg, last, 1700.0, runner=called.append)
assert called == ["gmail", "gmail@work", "slack@team", "gmail", "gmail@work", "slack@team"], called
argvs = []
loop.subprocess.run = lambda argv, **k: argvs.append(argv)
loop.run_subprocess("gmail@work"); loop.run_subprocess("gmail")
assert argvs[0][2:] == ["gmail", "--account", "work"] and argvs[1][2:] == ["gmail"], argvs
def boom(*a, **k): raise OSError("x")
loop.subprocess.run = boom
loop.run_subprocess("gmail@work")
assert "gmail@work" in common.read_status() and common.read_status()["gmail@work"]["ok"] is False
PY
pyk "run.py takes --account, refuses a bad label, and the default account keeps its plain name" <<'PY'
import subprocess
runpy = os.path.abspath(run.__file__)
r = subprocess.run([sys.executable, runpy, "gmail", "--account", "Bad Label"], env=dict(os.environ), capture_output=True, text=True, cwd=W)
assert r.returncode != 0 and "lowercase letters, digits and dashes, at most 24" in (r.stderr + r.stdout), (r.stdout, r.stderr)
r = subprocess.run([sys.executable, runpy, "gmail", "--account", "work"], env=dict(os.environ), capture_output=True, text=True, cwd=W)
assert r.returncode == 1 and r.stdout.startswith("gmail@work: failed"), (r.returncode, r.stdout, r.stderr)
r = subprocess.run([sys.executable, runpy, "gmail"], env=dict(os.environ), capture_output=True, text=True, cwd=W)
assert r.returncode == 1 and r.stdout.startswith("gmail: failed"), (r.returncode, r.stdout, r.stderr)
PY
pyk "an install written by the previous version still shows as the working default account, and reading it writes nothing" <<'PY'
import pathlib
(common.HOME / "config").mkdir(parents=True, exist_ok=True)
(common.HOME / "config" / "integrations.json").write_text(json.dumps({"sources": {"gmail": {"enabled": True, "minutes": 10}}}))
common.env_path().write_text('GOOGLE_OAUTH_CLIENT_ID="old-id"\nGOOGLE_OAUTH_CLIENT_SECRET="old-secret"\n'); os.chmod(common.env_path(), 0o600)
common.write_private(google_oauth.token_file("gmail"), json.dumps({"refresh_token": "RT-old"}))
(common.STATE / "connectors").mkdir(parents=True)
old = {"updated": "2026-10-05T09:30:00Z", "items": [{"title": "Old mail", "sub": "a@b.test", "at": "", "new": True, "url": None}], "unread": 1}
(common.STATE / "connectors" / "gmail.json").write_text(json.dumps(old))
common.write_private(common.status_path(), json.dumps({"gmail": {"ok": True, "at": "2026-10-05T09:31:00Z", "error_short": "", "seconds": 1.0}}))
before = tree()
row = [r for r in manifest.status() if r["id"] == "gmail"][0]
assert row["state"] == "ok" and row["enabled"] is True and row["last_at"] == "2026-10-05T09:31:00Z" and row["missing"] == []
assert [a["label"] for a in row["accounts"]] == ["default"] and row["accounts"][0]["state"] == "ok"
assert common.load_env()["GOOGLE_OAUTH_CLIENT_ID"] == "old-id" and common.read_snapshot("gmail") == old
assert loop.due_sources(common.load_config(), {}, 1e9)[:1] == ["gmail"]
assert common.load_config()["sources"]["gmail"].get("accounts") is None
assert tree() == before, "reading wrote or changed a file"
common.TRANSPORT = lambda m, u, h, d, t: ((200, json.dumps({"access_token": "AT-RT-old"}).encode()) if "token" in u and "oauth" in u else
    (200, json.dumps({"payload": {"headers": [{"name": "Subject", "value": "New"}, {"name": "From", "value": "x@y.test"}, {"name": "Date", "value": ""}]}}).encode()) if "/messages/" in u
    else (200, json.dumps({"messages": [{"id": "m1"}]}).encode()))
ok, msg = run.run_source("gmail")
assert ok, msg
assert (common.STATE / "connectors" / "gmail" / "default" / "gmail.json").is_file() and json.loads((common.STATE / "connectors" / "gmail.json").read_text())["items"][0]["title"] == "New"
assert common.read_snapshot("gmail")["items"][0]["title"] == "New", "the account folder is preferred once it exists"
PY
pyk "remove_account deletes that account's credentials, sign-in, config entry, snapshots and status, and nothing of the default account" <<'PY'
creds("default", "cid-d", "sec-d"); sign_in("default", "RT-default"); manifest.set_enabled("gmail", True)
manifest.add_account("gmail", "work"); creds("work", "cid-w", "sec-w"); sign_in("work", "RT-work"); manifest.set_enabled("gmail", True, label="work")
manifest.add_account("gmail", "keep"); creds("keep", "cid-k", "sec-k")
run.run_source("gmail"); run.run_source("gmail", "work")
S = common.STATE / "connectors"
assert (S / "gmail" / "work" / "gmail.json").is_file() and "gmail@work" in common.read_status()
manifest.remove_account("gmail", "work")
t = env_text()
assert "@work" not in t and "GOOGLE_OAUTH_CLIENT_ID=" in t and "GOOGLE_OAUTH_CLIENT_ID@keep=" in t, t
assert not google_oauth.token_file("gmail", "work").exists() and google_oauth.token_file("gmail").exists()
assert not (S / "gmail" / "work").exists() and (S / "gmail" / "default" / "gmail.json").is_file() and (S / "gmail.json").is_file()
assert "gmail@work" not in common.read_status() and "gmail" in common.read_status()
assert "work" not in common.load_config()["sources"]["gmail"]["accounts"] and "keep" in common.load_config()["sources"]["gmail"]["accounts"]
manifest.remove_account("gmail", "default")
assert common.load_env() == {} and not google_oauth.token_file("gmail").exists() and not (S / "gmail.json").exists() and not (S / "gmail" / "default").exists()
row = [r for r in manifest.status() if r["id"] == "gmail"][0]
assert row["enabled"] is False and row["state"] == "off" and [a["label"] for a in row["accounts"]] == ["default", "keep"], row["accounts"]
assert common.load_env("keep")["GOOGLE_OAUTH_CLIENT_ID"] == "cid-k"
PY
pyk "brain_connectors: one account is exactly the entry it always was; two accounts are two entries that say which account each is" <<'PY'
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("dash", "$HERE/dashboard.py".replace("$HERE", sys.path[0]))
d = importlib.util.module_from_spec(spec); sys.modules["dash"] = d; spec.loader.exec_module(d)
assert str(d.CONNECTORS).startswith(W), d.CONNECTORS
S = d.CONNECTORS; S.mkdir(parents=True, exist_ok=True)
snap = lambda title: {"updated": "2026-10-05T09:30:00Z", "unread": 2, "items": [{"title": title, "sub": "s", "at": "2026-10-05T09:00:00Z", "new": True, "url": "https://x.test/1"}]}
(S / "gmail.json").write_text(json.dumps(snap("Only mail")))
one = [c for c in d.brain_connectors() if c["name"] == "gmail"]
expect = {"name": "gmail", "label": "Gmail", "connected": True, "updated": "2026-10-05T09:30:00Z", "unread": 2,
          "items": [{"title": "Only mail", "sub": "s", "at": "2026-10-05T09:00:00Z", "new": True, "url": "https://x.test/1"}]}
assert len(one) == 1 and json.dumps(one[0]) == json.dumps(expect), one
assert [c["name"] for c in d.brain_connectors()][:3] == ["gmail", "calendar", "reminders"]
# a second account that is only a folder with a snapshot makes two entries
(S / "gmail" / "work").mkdir(parents=True); (S / "gmail" / "work" / "gmail.json").write_text(json.dumps(snap("Work mail")))
two = [c for c in d.brain_connectors() if c["name"] == "gmail"]
assert [(c["account"], c["key"], c["label"]) for c in two] == [("default", "gmail", "Gmail (default)"), ("work", "gmail@work", "Gmail (work)")], two
assert two[0]["items"][0]["title"] == "Only mail" and two[1]["items"][0]["title"] == "Work mail"
# the default account prefers its own folder once it has one, and the two files of one account are never read together
(S / "gmail" / "default").mkdir(); (S / "gmail" / "default" / "gmail.json").write_text(json.dumps(snap("Default folder mail")))
assert [c for c in d.brain_connectors() if c["name"] == "gmail"][0]["items"][0]["title"] == "Default folder mail"
# an account that is switched on but has not refreshed yet is still an entry, not connected
manifest.add_account("gmail", "later"); manifest.set_enabled("gmail", True, label="later")
three = [c for c in d.brain_connectors() if c["name"] == "gmail"]
assert [c["account"] for c in three] == ["default", "later", "work"] and three[1]["connected"] is False and three[1]["key"] == "gmail@later", three
assert len({c["key"] for c in three}) == 3
# meta: facebook and instagram live in the meta folder
(S / "meta" / "work").mkdir(parents=True); (S / "meta" / "work" / "facebook.json").write_text(json.dumps(snap("Post")))
fb = [c for c in d.brain_connectors() if c["name"] == "facebook"]
assert [c["key"] for c in fb] == ["facebook", "facebook@work"], fb
import chatctx
dg = chatctx.chat_digest({"connectors": two}, {})
assert "2 gmail (default)" in dg and "2 gmail (work)" in dg, dg
solo = chatctx.chat_digest({"connectors": one}, {})
assert "2 gmail" in solo and "gmail (" not in solo, solo
PY
pyk "the connections API: a bad label is 400, a credential for a label lands under KEY@label, enable creates, remove removes, test is refused in demo mode, and the log never holds a value" <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("dash", sys.path[0] + "/dashboard.py")
d = importlib.util.module_from_spec(spec); sys.modules["dash"] = d; spec.loader.exec_module(d)
api = lambda **b: d.connections_api({"confirm": True, **b})
for bad in ("Work", "x" * 25, "a b", "../x", "-x", "a@b", 7):
    code, body = api(action="enable", id="gmail", label=bad, on=True)
    assert code == 400 and "lowercase letters, digits and dashes, at most 24" in body["error"], (bad, code, body)
    assert api(action="credential", id="gmail", key="GOOGLE_OAUTH_CLIENT_ID", label=bad, value="v")[0] == 400
assert api(action="enable", id="gmail", label="default", on=True)[0] == 200
assert api(action="enable", id="calendar", label="work", on=True)[0] == 400
code, body = api(action="credential", id="gmail", key="GOOGLE_OAUTH_CLIENT_ID", label="work", value="log-me-not-1234")
assert code == 200 and body["present"] is True and "log-me-not-1234" not in json.dumps(body)
assert "GOOGLE_OAUTH_CLIENT_ID@work=" in env_text() and "GOOGLE_OAUTH_CLIENT_ID=" not in env_text().replace("GOOGLE_OAUTH_CLIENT_ID@work", "")
assert common.load_config()["sources"]["gmail"]["accounts"]["work"] == {"enabled": False}, "a credential for a new label makes the account, switched off"
code, body = api(action="enable", id="gmail", label="personal", on=True)
assert code == 200 and common.load_config()["sources"]["gmail"]["accounts"]["personal"] == {"enabled": True}
code, body = api(action="enable", id="gmail", label="third", on=False, add=True)
assert code == 200 and common.load_config()["sources"]["gmail"]["accounts"]["third"] == {"enabled": False}
assert api(action="enable", id="gmail", label="ghost", on=False)[0] == 400, "switching off an account that does not exist"
code, body = api(action="credential", id="gmail", key="GOOGLE_OAUTH_CLIENT_ID", label="work", value="")
assert code == 200 and body["present"] is False and "GOOGLE_OAUTH_CLIENT_ID@work" not in env_text()
api(action="credential", id="gmail", key="GOOGLE_OAUTH_CLIENT_SECRET", label="work", value="log-me-not-5678")
common.write_private(google_oauth.token_file("gmail", "work"), "{}")
common.write_snapshot("gmail", [{"title": "x"}], service="gmail", label="work"); common.record_status("gmail", True, "", 1.0, "work")
code, body = api(action="enable", id="gmail", label="work", on=False, remove=True)
assert code == 200 and body["removed"] is True, (code, body)
assert "@work" not in env_text() and not google_oauth.token_file("gmail", "work").exists() and not (common.STATE / "connectors" / "gmail" / "work").exists()
assert "gmail@work" not in common.read_status() and "work" not in common.load_config()["sources"]["gmail"]["accounts"]
# the status shape
rows = {r["id"]: r for r in json.loads(json.dumps(manifest.status()))}
assert rows["gmail"]["multi"] is True and rows["calendar"]["multi"] is False and rows["calendar"]["accounts"][0]["label"] == "default"
assert set(rows["gmail"]["accounts"][0]) == {"label", "enabled", "state", "missing", "last_at", "error", "credentials"}
assert set(rows["gmail"]["accounts"][0]["credentials"][0]) == {"key", "label", "secret", "help", "looks", "optional", "present", "stored"}
assert rows["gmail"]["accounts"][1]["credentials"][0]["key"] == "GOOGLE_OAUTH_CLIENT_ID", "the base key name, the page sends the label separately"
# test: refused in demo mode, and never calls a real service
d.demo_set(True)
code, body = api(action="enable", id="gmail", label="personal", on=True, test=True)
assert code == 400 and "Demo mode" in body["error"], (code, body)
d.demo_set(False)
ran = []
d.subprocess.run = lambda argv, **k: (ran.append(argv), type("R", (), {"returncode": 1, "stdout": "gmail@personal: failed: needs credentials: x\n", "stderr": ""})())[1]
code, body = api(action="enable", id="gmail", label="personal", on=True, test=True)
assert code == 200 and body["ok"] is False and "needs credentials" in body["message"], body
assert ran[0][-3:] == ["gmail", "--account", "personal"] and ran[0][-4].endswith("run.py"), ran
code, body = api(action="enable", id="gmail", label="nobody", on=True, test=True)
assert body["ok"] is False and "no such account" in body["message"]
log = (d.LOGS / "connections.log").read_text()
assert "log-me-not" not in log and " credential gmail work" in log and " test gmail personal" in log and " remove gmail work" in log, log
# the DEMO world answers /api/connections with accounts, and refuses writes
w = d.demo.World()
mail = [s for s in w.connections()["services"] if s["id"] == "mail"][0]
assert mail["multi"] is True and [a["label"] for a in mail["accounts"]] == ["default", "work", "personal"]
assert w.post("/api/connections", {"action": "enable", "test": True, "confirm": True})[0] == 400
gm = [c for c in w.connectors(0) if c["name"] == "gmail"]
assert [c["account"] for c in gm] == ["work", "personal"] and len({c["key"] for c in gm}) == 2 and gm[0]["items"] != gm[1]["items"]
PY
pyk "qtdeck connect: list, enter (piped), remove, a secret as an argument is refused, a bad label exits non-zero, and nothing leaves the temp folders" <<'PY'
import subprocess
qt = [sys.executable, sys.path[0] + "/connect.py"]
env = {k: v for k, v in os.environ.items()}
go = lambda *a, inp="": subprocess.run(qt + list(a), env=env, input=inp, capture_output=True, text=True, cwd=W)
r = go("gmail", "--account", "work", inp="cid-piped-1\nsec-piped-2\n")
assert r.returncode == 0 and "work account" in r.stdout and "--account work" in r.stdout and "cid-piped-1" not in r.stdout + r.stderr, (r.stdout, r.stderr)
assert "GOOGLE_OAUTH_CLIENT_ID@work=" in env_text() and mode(common.env_path()) == 0o600
r = go("gmail", "--account", "work", inp="\n\n")
assert r.returncode == 0 and "Saved 0 credentials" in r.stdout and "cid-piped-1" in env_text(), "a blank line keeps the saved value"
r = go("list")
assert r.returncode == 0 and "gmail" in r.stdout and "work" in r.stdout and "cid-piped-1" not in r.stdout, r.stdout
for args in (("gmail", "--token", "abc"), ("gmail", "abc"), ("gmail", "--client-secret=abc"), ("gmail", "GOOGLE_OAUTH_CLIENT_SECRET=abc")):
    r = go(*args)
    assert r.returncode == 2 and "never given as an argument" in r.stderr and "abc" not in r.stdout, (args, r.returncode, r.stderr)
r = go("gmail", "--account", "Bad Label")
assert r.returncode == 2 and "lowercase letters, digits and dashes, at most 24" in r.stderr
r = go("nosuchservice")
assert r.returncode == 2 and "no service called" in r.stderr
r = go("calendar", "--account", "work")
assert r.returncode == 0 and "needs nothing entered here" in r.stdout
r = go("remove", "gmail", "--account", "work")
assert r.returncode == 2 and "--yes" in r.stderr and "cid-piped-1" in env_text(), "no terminal and no --yes: nothing removed"
r = go("remove", "gmail", "--account", "work", "--yes")
assert r.returncode == 0 and "@work" not in env_text() and "work" not in common.load_config()["sources"]["gmail"]["accounts"], (r.stdout, r.stderr)
r = go("remove", "gmail", "--account", "../x", "--yes")
assert r.returncode == 2
# through the qtdeck command itself
q = subprocess.run(["bash", sys.path[0] + "/qtdeck", "connect", "list"], env={**env, "QUARTERDECK_DIR": ""} if False else env, capture_output=True, text=True, cwd=W)
assert q.returncode == 0 and "SERVICE" in q.stdout, (q.returncode, q.stdout[-300:], q.stderr[-300:])
q = subprocess.run(["bash", sys.path[0] + "/qtdeck", "connect", "gmail", "--account", "BAD"], env=env, capture_output=True, text=True, cwd=W)
assert q.returncode == 2, q.returncode
assert "connect" in subprocess.run(["bash", sys.path[0] + "/qtdeck", "help", "more"], env=env, capture_output=True, text=True).stdout
PY
ck "the page offers Add another account, a per-account switch, test and remove, escapes what the server sends, and the new actions exist" \
   'py "
h = open(\"$HERE/../dashboard/index.html\").read()
for w in (\"Add another account\", \"Remove account\", \"connTest\", \"connAddSave\", \"connRemoveAccount\", \"connAddOpen\", \"conn-acct\", \"lowercase letters, digits and dashes, at most 24\"):
    assert w in h, w
i = h.index(\"function connAcct\"); blk = h[i:h.index(\"function connRow\")]
assert \"esc(a.label)\" in blk and \"esc(who)\" in blk and \"confirmDlg\" not in blk
assert \"confirmDlg\" in h[h.index(\"async function connRemoveAccount\"):h.index(\"/* ---- settings\")]
assert \"c.key || c.name\" in h and \"S.integrations || {})[ck]\" in h
s = open(\"$HERE/../dashboard/assets/suggest.js\").read()
assert \"conns(S, name)\" in s and \"connKey(c)\" in s
" >/dev/null'
ck "the new files and the new page copy hold no em dash and no en dash" \
   'py "
import pathlib
h = pathlib.Path(\"$HERE\")
text = [(h / \"connect.py\").read_text(), (h / \"integrations\" / \"accounts.py\").read_text(), (h / \"integrations\" / \"services\" / \"gmail.json\").read_text()]
page = (h.parent / \"dashboard\" / \"index.html\").read_text()
text.append(page[page.index(\"const connLab\"):page.index(\"/* ---- settings\")])
assert not [t for t in text if \"\\u2014\" in t or \"\\u2013\" in t]
" >/dev/null'

echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
