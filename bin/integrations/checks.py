"""Checks for the direct feeds, called from bin/selftest.py as run(check). Fake transport only:
no network, no credentials, invented data."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import common, ga4, gmail, google_oauth, linkedin, loop, macmail, manifest, meta, run, slack, threads, x  # noqa: E402


class Fake:
    """Routes by (method, url substring); records every call so secrets-in-URL can be checked."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers, data, timeout):
        self.calls.append((method, url, headers, data))
        for sub, resp in self.routes:
            if sub in url:
                r = resp(url, data) if callable(resp) else resp
                if isinstance(r, tuple):
                    return r
                return 200, json.dumps(r).encode()
        return 404, b""


def run_checks(check):
    tmp = Path(tempfile.mkdtemp())
    saved = (common.STATE, common.CONFIG_DIR, common.TRANSPORT, common.SLEEP, linkedin.INBOX)
    common.STATE, common.CONFIG_DIR, common.SLEEP = tmp / "state", tmp / "cfg", lambda s: None
    common.CONFIG_DIR.mkdir()
    try:
        _all(check, tmp)
    finally:
        common.STATE, common.CONFIG_DIR, common.TRANSPORT, common.SLEEP, linkedin.INBOX = saved
        shutil.rmtree(tmp, ignore_errors=True)


def _env(**kv):
    p = common.env_path()
    p.write_text("# c\n" + "\n".join(f"{k}={v}" for k, v in kv.items()) + "\n")
    os.chmod(p, 0o600)


def _all(check, tmp):
    cfg = {"ga4": {"property_id": "123456", "site_url": "https://example.com"}, "sources": {}}

    # --- common
    check("integrations: titles clip to 140, urls must be https, items cap at 12",
          len(common.make_item("x" * 300)["title"]) == 140 and common.make_item("a", url="http://x.test")["url"] is None
          and common.make_item("a", url="javascript:alert(1)")["url"] is None
          and common.make_item("a", url="https://x.test/p")["url"] == "https://x.test/p")
    common.write_snapshot("t1", [{"title": f"n{i}", "url": "http://bad"} for i in range(30)], unread=3)
    f = common.STATE / "connectors" / "t1.json"
    d = json.loads(f.read_text())
    check("integrations: snapshot is atomic-written, mode 0600, capped, in the connector shape",
          oct(f.stat().st_mode & 0o777) == "0o600" and len(d["items"]) == 12 and d["unread"] == 3
          and all(i["url"] is None for i in d["items"]) and not list(f.parent.glob("*.tmp")))

    p = common.env_path()
    check("integrations: a missing env file says it needs credentials", _fails(common.load_env, "needs credentials"))
    p.write_text("A=1\n")
    os.chmod(p, 0o644)
    check("integrations: an env file that is not mode 0600 is refused", _fails(common.load_env, "chmod 600"))
    os.chmod(p, 0o600)
    check("integrations: a 0600 env file loads KEY=value lines", common.load_env() == {"A": "1"})
    check("integrations: a missing key is reported by name, not by value",
          _fails(lambda: common.need({}, "SLACK_USER_TOKEN"), "SLACK_USER_TOKEN"))

    fk = Fake([("/ok", {"a": 1}), ("/flaky", _seq([(503, b""), (429, b""), (200, b'{"b": 2}')])), ("/down", (500, b"secret-body"))])
    common.TRANSPORT = fk
    check("integrations: http helper returns JSON, retries 429 and 5xx, then succeeds",
          common.request("GET", "https://x.test/ok") == {"a": 1} and common.request("GET", "https://x.test/flaky") == {"b": 2})
    msg = _msg(lambda: common.request("GET", "https://x.test/down", headers={"Authorization": "Bearer SEKRET"}))
    check("integrations: a failing call gives a short error with no body, header or token", "SEKRET" not in msg and "secret-body" not in msg and "500" in msg, msg)
    check("integrations: a secret in a URL or a non-https address is refused",
          _fails(lambda: common.request("GET", "https://x.test/ok", params={"access_token": "z"}), "secret")
          and _fails(lambda: common.request("GET", "http://x.test/ok"), "non-https"))

    # --- ga4
    sa = tmp / "sa.json"
    sa.write_text(json.dumps({"client_email": "svc@proj.iam.gserviceaccount.test", "private_key": "PEM"}))
    _env(GA4_SERVICE_ACCOUNT_FILE=sa)
    ga4.sign_rs256 = lambda pem, data: b"sig"
    ga4.make_jwt.__defaults__ = (lambda pem, data: b"sig", None)

    def report(url, data):
        b = json.loads(data)
        dims = [x["name"] for x in b.get("dimensions", [])]
        mv = lambda *v: {"metricValues": [{"value": str(x)} for x in v]}
        if dims == ["pagePath", "pageTitle"]:
            return {"rows": [{"dimensionValues": [{"value": "/a/"}, {"value": "Post A"}, {"value": "this"}], **mv(124)},
                             {"dimensionValues": [{"value": "/a/"}, {"value": "Post A"}, {"value": "prior"}], **mv(100)},
                             {"dimensionValues": [{"value": "/b/"}, {"value": "Post B"}, {"value": "this"}], **mv(10)}]}
        if dims:
            return {"rows": [{"dimensionValues": [{"value": "Organic Search"}], **mv(300)}]}
        return {"rows": [{"dimensionValues": [{"value": "this"}], **mv(1240, 420, 610)},
                         {"dimensionValues": [{"value": "prior"}], **mv(940, 400, 500)}]}
    fk = Fake([("oauth2.googleapis.com/token", {"access_token": "AT-ga"}), ("runReport", report)])
    common.TRANSPORT = fk
    out = ga4.fetch(common.load_env(), cfg)["ga4"]["items"]
    check("integrations: ga4 totals, top pages with change vs last week, and top source",
          out[0]["title"] == "Last 7 days: 1,240 views" and "+32%" in out[0]["sub"]
          and out[1]["title"] == "Post A" and out[1]["sub"] == "124 views, +24% vs last week"
          and out[1]["url"] == "https://example.com/a/" and out[3]["title"] == "Source: Organic Search", out[:2])
    nosite = ga4.fetch(common.load_env(), {"ga4": {"property_id": "123456", "site_url": ""}, "sources": {}})["ga4"]["items"]
    check("integrations: ga4 with no site address set gives items with no link, never a relative one that would point at the dashboard",
          nosite and all(i["url"] is None for i in nosite))
    check("integrations: ga4 sends its token in a header, never in the URL",
          all("AT-ga" not in c[1] for c in fk.calls) and any(c[2].get("Authorization") == "Bearer AT-ga" for c in fk.calls))
    check("integrations: ga4 without a property id says what to set",
          _fails(lambda: ga4.fetch(common.load_env(), {"ga4": {}}), "GA4 property id"))
    if shutil.which("openssl"):
        k = tmp / "k.pem"
        subprocess.run(["openssl", "genrsa", "-out", str(k), "2048"], capture_output=True)
        pub = tmp / "pub.pem"
        subprocess.run(["openssl", "rsa", "-in", str(k), "-pubout", "-out", str(pub)], capture_output=True)
        sig = tmp / "s.bin"
        sig.write_bytes(subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(k)], input=b"hello", capture_output=True).stdout)
        real = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sig)], input=b"hello", capture_output=True)
        import importlib
        importlib.reload(ga4)
        s2 = ga4.sign_rs256(k.read_text(), b"hello")
        sig.write_bytes(s2)
        ok = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sig)], input=b"hello", capture_output=True)
        check("integrations: ga4 RS256 signing through openssl verifies against the public key", real.returncode == 0 and ok.returncode == 0)
    else:
        print("  skipped: the ga4 openssl signing check (openssl not on PATH)")

    # --- google oauth + gmail
    url = google_oauth.build_auth_url("cid", "http://127.0.0.1:5/", google_oauth.SCOPES["gmail"], "v" * 64, "st")
    check("integrations: oauth uses PKCE S256, a loopback redirect and only gmail.readonly",
          "code_challenge_method=S256" in url and "127.0.0.1" in url and url.count("scope=") == 1
          and "gmail.readonly" in url and "client_secret" not in url)
    srv = google_oauth.HTTPServer(("127.0.0.1", 0), google_oauth._Handler)
    srv.result, srv.timeout = None, 5
    t = threading.Thread(target=srv.handle_request)
    t.start()
    urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/?code=abc&state=s1", timeout=5).read()
    t.join()
    srv.server_close()
    check("integrations: the loopback listener catches the code and state", srv.result == {"code": "abc", "state": "s1"})
    _env(GOOGLE_OAUTH_CLIENT_ID="cid", GOOGLE_OAUTH_CLIENT_SECRET="csec")
    check("integrations: gmail not signed in says to run the sign-in", _fails(lambda: gmail.fetch(common.load_env(), cfg), "google_oauth.py gmail"))
    common.write_private(google_oauth.token_file("gmail"), json.dumps({"refresh_token": "RT"}))
    check("integrations: the stored refresh token is mode 0600", oct(google_oauth.token_file("gmail").stat().st_mode & 0o777) == "0o600")
    hdr = lambda s, f, d: {"payload": {"headers": [{"name": "From", "value": f}, {"name": "Subject", "value": s}, {"name": "Date", "value": d}]}}
    fk = Fake([("oauth2.googleapis.com/token", {"access_token": "AT-gm"}),
               ("messages/m1", hdr("Invoice due", "Ada Example <ada@example.test>", "Mon, 05 Oct 2026 09:30:00 +0000")),
               ("messages/m2", hdr("Lunch?", "bob@example.test", "Mon, 05 Oct 2026 10:00:00 +0000")),
               ("messages?", {"messages": [{"id": "m1"}, {"id": "m2"}], "resultSizeEstimate": 2})])
    common.TRANSPORT = fk
    g = gmail.fetch(common.load_env(), cfg)["gmail"]
    gets = [c[1] for c in fk.calls if "/messages/" in c[1]]
    check("integrations: gmail lists unread important mail with headers only, no bodies",
          g["unread"] == 2 and g["items"][0]["title"] == "Invoice due" and g["items"][0]["sub"] == "Ada Example"
          and g["items"][1]["sub"] == "bob@example.test" and all("format=metadata" in u and "format=full" not in u for u in gets)
          and "is%3Aunread" in fk.calls[1][1] and "AT-gm" not in "".join(c[1] for c in fk.calls), g)
    common.TRANSPORT = Fake([("oauth2.googleapis.com/token", (400, b""))])
    check("integrations: a revoked Google token says token expired and how to sign in again",
          _fails(lambda: gmail.fetch(common.load_env(), cfg), "token expired"))

    # --- slack
    _env(SLACK_USER_TOKEN="xoxp-fake")

    def hist(url, data):
        return {"ok": True, "messages": [{"user": "U2", "text": "Can you look at <@U1> the build? " + "x" * 200, "ts": "1760000000.1"},
                                          {"user": "U1", "text": "mine", "ts": "1760000001.1"}]}
    S = lambda **kv: {"ok": True, **kv}
    fk = Fake([("auth.test", S(user_id="U1")), ("conversations.list", S(channels=[{"id": "D1", "is_im": True, "user": "U2"}])),
               ("conversations.info", S(channel={"last_read": "1759999000.0"})), ("conversations.history", hist),
               ("users.info", S(user={"name": "grace", "profile": {"display_name": "Grace"}})),
               ("chat.getPermalink", S(permalink="https://example.slack.com/archives/D1/p1")),
               ("search.messages", S(messages={"matches": [
                   {"text": "hi <@U1>", "ts": "1760000500.0", "permalink": "https://example.slack.com/archives/C9/p2", "channel": {"id": "C9", "name": "build"}},
                   {"text": "old", "ts": "1700000000.0", "channel": {"id": "C8", "name": "old"}}]}))])
    # conversations.info returns the same marker for C9 and C8; the old mention is before it
    common.TRANSPORT = fk
    sl = slack.fetch(common.load_env(), cfg)["slack"]
    check("integrations: slack lists unread DMs and channel mentions with a 100 char preview and permalink",
          sl["unread"] == 2 and sl["items"][0]["title"] == "Grace (DM)" and len(sl["items"][0]["sub"]) == 100
          and sl["items"][0]["url"].startswith("https://") and sl["items"][1]["title"] == "#build: mention"
          and all("xoxp" not in c[1] for c in fk.calls), sl)
    common.TRANSPORT = Fake([("auth.test", {"ok": False, "error": "token_revoked"})])
    check("integrations: slack with a revoked token says token expired", _fails(lambda: slack.fetch(common.load_env(), cfg), "token expired"))
    common.TRANSPORT = Fake([("auth.test", {"ok": False, "error": "missing_scope", "needed": "im:history"})])
    check("integrations: slack missing scope names the scope", _fails(lambda: slack.fetch(common.load_env(), cfg), "im:history"))

    # a channel Slack will not describe is skipped; it must not take the whole feed down or count everything unread
    common.TRANSPORT = Fake([("auth.test", S(user_id="U1")), ("conversations.list", S(channels=[{"id": "D1", "is_im": True, "user": "U2"}])),
                             ("conversations.info", {"ok": False, "error": "channel_not_found"}), ("conversations.history", hist),
                             ("search.messages", S(messages={"matches": []}))])
    sl = slack.fetch(common.load_env(), cfg)["slack"]
    check("integrations: slack skips a channel it cannot read instead of failing the feed", sl["items"] == [] and sl["unread"] == 0, sl)
    common.TRANSPORT = Fake([("auth.test", S(user_id="U1")), ("conversations.list", S(channels=[{"id": "D1", "is_im": True, "user": "U2"}])),
                             ("conversations.info", S(channel={})), ("conversations.history", hist), ("search.messages", S(messages={"matches": []}))])
    sl = slack.fetch(common.load_env(), cfg)["slack"]
    check("integrations: slack with no last-read marker does not count every message unread", sl["items"] == [] and sl["unread"] == 0, sl)
    check("integrations: a redirect is never followed, so the token cannot be sent to another host",
          common._NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.example/") is None)
    check("integrations: meta names both of its snapshots for status", common.snapshots_of("meta") == ("facebook", "instagram")
          and common.snapshots_of("ga4") == ("ga4",))

    # --- linkedin
    inbox = tmp / "li"
    inbox.mkdir()
    linkedin.INBOX = inbox
    check("integrations: linkedin with no export says which file to drop where", _fails(lambda: linkedin.fetch({}, cfg, inbox), "Shares.csv"))
    shares = ("Date,ShareLink,ShareCommentary,SharedUrl,Visibility\n"
              + "".join(f'2026-0{m}-01 10:00:00,https://www.linkedin.example/feed/update/urn:li:share:{m},"Post {m}, with comma",,MEMBER_NETWORK\n' for m in range(1, 10)))
    (inbox / "Shares.csv").write_text(shares)
    (inbox / "stats.csv").write_text("Post URL,Impressions,Reactions,Comments\nhttps://www.linkedin.example/feed/update/urn:li:share:9?x=1,\"1,200\",30,4\n")
    li = linkedin.fetch({}, cfg, inbox)["linkedin"]["items"]
    check("integrations: linkedin reads Shares.csv, newest 8, and joins CSV metrics by post link",
          len(li) == 8 and li[0]["title"] == "Post 9, with comma" and li[0]["sub"] == "1,200 impressions, 30 reactions, 4 comments"
          and li[1]["sub"] == "no metrics in the export" and li[0]["url"].startswith("https://"), li[0])
    _xlsx(inbox / "posts.xlsx", [["Post URL", "Impressions", "Reactions", "Comments"], ["https://www.linkedin.example/feed/update/urn:li:share:8", "540", "12", "2"]])
    li = linkedin.fetch({}, cfg, inbox)["linkedin"]["items"]
    check("integrations: linkedin reads post metrics from an XLSX with zipfile and xml", li[1]["sub"] == "540 impressions, 12 reactions, 2 comments", li[1])
    (inbox / "stats.csv").unlink()
    (inbox / "posts.xlsx").unlink()
    with zipfile.ZipFile(inbox / "export.zip", "w") as z:
        z.writestr("Shares.csv", "Date,ShareLink,ShareCommentary,SharedUrl,Visibility\n2026-01-01 08:00:00,http://insecure.example/x,Zipped,,PUBLIC\n")
    (inbox / "Shares.csv").unlink()
    li = linkedin.fetch({}, cfg, inbox)["linkedin"]["items"]
    check("integrations: linkedin reads a zip export and drops non-https links", li[0]["title"] == "Zipped" and li[0]["url"] is None)

    # --- meta
    _env(META_PAGE_TOKEN="EAAfake", META_PAGE_ID="111", META_IG_USER_ID="222")
    cnt = lambda n: {"summary": {"total_count": n}}
    fk = Fake([("111/posts", {"data": [{"id": "111_1", "message": "Hello page", "created_time": "2026-10-01T08:00:00+0000",
                                        "permalink_url": "https://www.facebook.example/111/posts/1", "shares": {"count": 3},
                                        "reactions": cnt(9), "comments": cnt(2)}]}),
               ("111_1/insights", {"data": [{"values": [{"value": 450}]}]}),
               ("222/media", {"data": [{"id": "9", "caption": "Pic", "media_type": "IMAGE", "permalink": "https://www.instagram.example/p/9/",
                                        "timestamp": "2026-10-02T08:00:00+0000", "like_count": 40, "comments_count": 5}]}),
               ("9/insights", (403, b""))])
    common.TRANSPORT = fk
    mm = meta.fetch(common.load_env(), cfg)
    check("integrations: meta gives facebook posts with counts and insights, instagram with insights skipped when not permitted",
          mm["facebook"]["items"][0]["sub"] == "9 reactions, 2 comments, 3 shares, 450 impressions"
          and mm["instagram"]["items"][0]["sub"] == "40 likes, 5 comments" and mm["instagram"]["items"][0]["url"].startswith("https://")
          and all("EAAfake" not in c[1] for c in fk.calls) and any(c[2].get("Authorization") == "Bearer EAAfake" for c in fk.calls), mm)
    common.TRANSPORT = Fake([("111/posts", (400, b""))])
    check("integrations: meta with a bad token says token expired", _fails(lambda: meta.fetch(common.load_env(), cfg), "token expired"))

    # --- runner and loop
    _env(META_PAGE_TOKEN="EAAfake", META_PAGE_ID="111", META_IG_USER_ID="222", GOOGLE_OAUTH_CLIENT_ID="cid",
         GOOGLE_OAUTH_CLIENT_SECRET="csec", GA4_SERVICE_ACCOUNT_FILE=sa)
    common.TRANSPORT = Fake([("oauth2.googleapis.com/token", (400, b""))])
    ok_g, msg_g = run.run_source("gmail")
    common.TRANSPORT = Fake([("111/posts", {"data": []}), ("222/media", {"data": []})])
    ok_m, _ = run.run_source("meta")
    st = common.read_status()
    check("integrations: one failing source is recorded and does not stop the next",
          not ok_g and ok_m and st["gmail"]["ok"] is False and "token expired" in st["gmail"]["error_short"]
          and st["facebook"]["ok"] and st["instagram"]["ok"] and (common.STATE / "connectors" / "facebook.json").is_file())
    p = common.env_path()
    os.chmod(p, 0o666)
    check("integrations: the runner records a readable-by-others env file as an error, with no secrets",
          not run.run_source("slack")[0] and "chmod 600" in common.read_status()["slack"]["error_short"])
    os.chmod(p, 0o600)
    common.TRANSPORT = lambda *a: (_ for _ in ()).throw(KeyError("SEKRET-VALUE"))
    ga4.make_jwt = lambda *a, **k: "jwt"
    real_load = common.load_config
    common.load_config = lambda: cfg
    ok_u, msg_u = run.run_source("ga4")
    check("integrations: an unexpected exception is recorded by type only", not ok_u and "SEKRET-VALUE" not in json.dumps(common.read_status()) and "KeyError" in msg_u)

    called = []
    c2 = {"sources": {"a": {"enabled": True, "minutes": 5}, "b": {"enabled": False}, "c": {"enabled": True, "minutes": 1}}}
    last = {}
    loop.run_due(c2, last, 1000.0, runner=called.append)
    loop.run_due(c2, last, 1100.0, runner=called.append)
    loop.run_due(c2, last, 1400.0, runner=called.append)
    check("integrations: the loop runs only enabled sources, each on its own interval (minimum 5 minutes)", called == ["a", "c", "a", "c"], called)
    env = loop.minimal_env()
    check("integrations: sources run with a minimal environment", set(env) == {"PATH", "HOME", "LANG"})
    common.load_config = real_load
    check("integrations: the default config enables nothing", not any(s["enabled"] for s in common.load_config()["sources"].values()))
    _new_feeds(check, tmp)


def _seq(items):
    it = iter(items)
    return lambda url, data: next(it)


def _msg(fn):
    try:
        fn()
    except common.IntegrationError as e:
        return e.short
    return ""


def _fails(fn, needle):
    return needle in _msg(fn)


def _xlsx(path, rows):
    sst = [c for r in rows for c in r]
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    body = "".join(f'<row r="{i + 1}">' + "".join(f'<c r="{chr(65 + j)}{i + 1}" t="s"><v>{sst.index(c)}</v></c>' for j, c in enumerate(r)) + "</row>" for i, r in enumerate(rows))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join(f"<si><t>{esc(s)}</t></si>" for s in sst) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>')


# ---- Mac Mail, Threads and X, and the help in every manifest. Fake osascript, fake transport, invented data: nothing real is called. ----
def _fake_osascript(tmp, body):
    d = Path(tmp) / "fakebin"
    d.mkdir(exist_ok=True)
    f = d / "osascript"
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)
    return str(d)


def _with_path(path, fn):
    old = os.environ.get("PATH", "")
    os.environ["PATH"] = path
    try:
        return fn()
    finally:
        os.environ["PATH"] = old


def _new_feeds(check, tmp):
    # --- Mac Mail
    ask = lambda: macmail.fetch({}, {})
    ok = _with_path(_fake_osascript(tmp, "printf '7|172800'"), ask)["macmail"]
    check("integrations: Mac Mail turns the unread count and the oldest age into one item, and asks for nothing else",
          ok["unread"] == 7 and len(ok["items"]) == 1 and "7 unread" in ok["items"][0]["title"] and "2 days" in ok["items"][0]["sub"]
          and not any(w in macmail.SCRIPT.lower() for w in ("subject", "sender", "content", "attachment")) and "date received" in macmail.SCRIPT)
    check("integrations: Mac Mail with nothing unread gives no item and a zero count",
          _with_path(_fake_osascript(tmp, "printf '0|0'"), ask)["macmail"] == {"items": [], "unread": 0})
    check("integrations: Mac Mail says in one sentence when macOS has not allowed it",
          _fails(lambda: _with_path(_fake_osascript(tmp, "echo 'execution error: Not authorized to send Apple events to Mail. (-1743)' >&2; exit 1"), ask), "macOS has not allowed"))
    check("integrations: Mac Mail says when Mail has no inbox to read",
          _fails(lambda: _with_path(_fake_osascript(tmp, "echo 'execution error: Mail got an error: Cannot get inbox. (-1728)' >&2; exit 1"), ask), "add an account"))
    check("integrations: Mac Mail says when osascript is missing and when the answer is not what it expects, and never crashes",
          _fails(lambda: _with_path(str(Path(tmp) / "nothing-here"), ask), "only works on a Mac")
          and _fails(lambda: _with_path(_fake_osascript(tmp, "printf 'banana'"), ask), "unexpected")
          and macmail.parse("3|x") is None and macmail.parse("-1|4") is None and macmail.parse("3|90") == (3, 90))
    _env()
    cfgd = {"sources": {}}
    real_cfg = common.load_config
    common.load_config = lambda: cfgd
    okm, _m = _with_path(_fake_osascript(tmp, "printf '2|4000'"), lambda: run.run_source("macmail"))
    check("integrations: Mac Mail runs through the runner without any credential file entry, writes its snapshot and its status",
          okm and json.loads((common.STATE / "connectors" / "macmail.json").read_text())["unread"] == 2 and common.read_status()["macmail"]["ok"])

    # --- Threads
    _env(THREADS_ACCESS_TOKEN="TH-SEKRET")
    posts = {"data": [{"id": "11", "text": "first post", "timestamp": "2026-10-01T10:00:00+0000", "permalink": "https://www.threads.net/@me/post/a", "media_type": "TEXT_POST"},
                      {"id": "12", "text": "", "timestamp": "2026-10-02T10:00:00+0000", "permalink": "http://insecure.test/x", "media_type": "IMAGE"}] + [{"id": str(20 + i), "text": "p"} for i in range(12)]}
    ins = {"data": [{"name": "views", "values": [{"value": 1200}]}, {"name": "likes", "values": [{"value": 9}]}, {"name": "replies", "total_value": {"value": 2}}, {"name": "weird", "values": [{"value": 5}]}]}
    fk = Fake([("/11/insights", ins), ("/insights", (403, b"")), ("me/threads", posts)])
    common.TRANSPORT = fk
    th = threads.fetch(common.load_env(), cfgd)["threads"]["items"]
    check("integrations: Threads lists the latest posts with the counts it can read, skips the ones Meta will not give, and caps at 8",
          len(th) == 8 and "1,200 views" in th[0]["sub"] and "9 likes" in th[0]["sub"] and "2 replies" in th[0]["sub"] and "weird" not in th[0]["sub"]
          and th[1]["sub"] == "counts not available" and th[1]["url"] is None and th[0]["url"].startswith("https://"))
    check("integrations: Threads sends the token in a header only, never in an address",
          all("TH-SEKRET" not in c[1] and c[2].get("Authorization") == "Bearer TH-SEKRET" for c in fk.calls))
    common.TRANSPORT = Fake([("me/threads", (401, b""))])
    check("integrations: Threads with a bad token says token expired", _fails(lambda: threads.fetch(common.load_env(), cfgd), "token expired"))
    common.TRANSPORT = Fake([("me/threads", {"data": "nope"})])
    check("integrations: Threads with an answer in an unexpected shape gives one sentence, not a crash", _fails(lambda: threads.fetch(common.load_env(), cfgd), "unexpected"))
    common.TRANSPORT = Fake([("me/threads", {"data": [{"id": "1", "text": "x"}, 5, None]}), ("insights", {"data": [{"name": "views", "values": []}]})])
    check("integrations: Threads tolerates missing fields and odd entries", len(threads.fetch(common.load_env(), cfgd)["threads"]["items"]) == 1)

    # --- X
    _env(X_BEARER_TOKEN="X-SEKRET", X_USER_ID="12345")
    mine = {"data": [{"id": "901", "text": "my post", "created_at": "2026-10-03T08:00:00.000Z", "public_metrics": {"like_count": 4, "reply_count": 1, "repost_count": 0, "quote_count": 0, "impression_count": 321}}]}
    ments = {"data": [{"id": "902", "text": "hello @me", "created_at": "2026-10-04T08:00:00.000Z"}, {"id": "x", "text": "odd id"}], "meta": {"result_count": 2}}
    fk = Fake([("/mentions", ments), ("/tweets", mine)])
    common.TRANSPORT = fk
    xo = x.fetch(common.load_env(), cfgd)["x"]
    check("integrations: X gives mentions first (marked new) and your latest posts with their counts, with a count of mentions",
          xo["unread"] == 2 and xo["items"][0]["sub"] == "mentioned you" and xo["items"][0]["new"] and xo["items"][0]["url"] == "https://x.com/i/web/status/902"
          and xo["items"][1]["url"] is None and "4 likes" in xo["items"][2]["sub"] and "321 impressions" in xo["items"][2]["sub"])
    check("integrations: X reads only (GET), sends the token in a header, and keeps it out of every address",
          all(c[0] == "GET" and "X-SEKRET" not in c[1] and c[2].get("Authorization") == "Bearer X-SEKRET" for c in fk.calls) and len(fk.calls) == 2)
    common.TRANSPORT = Fake([("/tweets", (403, b""))])
    check("integrations: X says the plan may not include it, and points to the developer portal", _fails(lambda: x.fetch(common.load_env(), cfgd), "developer portal"))
    common.TRANSPORT = Fake([("/tweets", (401, b""))])
    check("integrations: X with a rejected token says so", _fails(lambda: x.fetch(common.load_env(), cfgd), "bearer token rejected"))
    common.TRANSPORT = Fake([("/tweets", {}), ("/mentions", {"data": "oops"})])
    check("integrations: X with empty or odd answers shows nothing and does not crash", x.fetch(common.load_env(), cfgd)["x"] == {"items": [], "unread": 0})
    _env(X_BEARER_TOKEN="t", X_USER_ID="@name")
    check("integrations: X refuses a user id that is not numeric", _fails(lambda: x.fetch(common.load_env(), cfgd), "numeric"))

    # --- manifests and their help
    svc = {m["id"]: m for m in manifest.load_services()}
    want = {"gmail", "macmail", "calendar", "meta", "linkedin", "threads", "x", "slack", "ga4"}
    check("manifests: the default catalog is Gmail, Mac Mail, Calendar and Reminders, Facebook and Instagram, LinkedIn, Threads, X, Slack and site analytics", want <= set(svc))
    strings = []
    for m in svc.values():
        strings += [m["what"], m["revoke"], m["tested"]] + m["steps"] + m["reads"] + m["not_reads"] + m["scopes"] + [l["label"] for l in m["links"]] + [c["help"] + c["looks"] for c in m["credentials"]]
    check("manifests: every built-in service explains what it reads and does not read, has numbered steps, how to revoke, and what was tested; no em dashes",
          all(m["reads"] and m["not_reads"] and m["steps"] and m["revoke"] and m["scopes"] and m["tested"] for m in svc.values()) and not any("\u2014" in t or "\u2013" in t for t in strings))
    check("manifests: no built-in claims it was tested against the real service, and every link is https",
          not any(m["tested"].startswith(manifest.VERIFIED) for m in svc.values()) and all(l["url"].startswith("https://") for m in svc.values() for l in m["links"])
          and all("not tested against the real service" in m["tested"].lower() for m in svc.values()))
    check("manifests: X says plainly that access and prices change and may cost money, and that it never posts",
          any("may cost money" in t for t in svc["x"]["steps"]) and "never posts" in " ".join(svc["x"]["scopes"]))
    check("manifests: the Facebook and Instagram help names both, and the Instagram id is optional so it never blocks set-up",
          "Facebook" in svc["meta"]["label"] and "Instagram" in svc["meta"]["label"] and any(c["key"] == "META_IG_USER_ID" and c["optional"] for c in svc["meta"]["credentials"]))
    raw = {"id": "mine", "label": "Mine", "what": "w", "reads": ["a"] * 9, "links": [{"label": "ok", "url": "https://x.test"}, {"label": "bad", "url": "http://x.test"}, {"label": "worse", "url": "javascript:1"}, "no"],
           "credentials": [{"key": "MINE_TOKEN", "looks": "digits"}], "tested": ""}
    c = manifest._clean(raw)
    check("manifests: a service of your own can carry help; unknown or unsafe parts are dropped and the tested line defaults to not tested",
          c and len(c["reads"]) == 6 and [l["url"] for l in c["links"]] == ["https://x.test"] and c["tested"] == manifest.NOT_TESTED and c["credentials"][0]["looks"] == "digits"
          and manifest._clean({"id": "bare"})["not_reads"] == [])
    st = [r for r in manifest.status(services=[manifest._clean({**raw, "credentials": [{"key": "MINE_TOKEN", "optional": True}]})], cfg={"sources": {"mine": {"enabled": True}}}, have=set(), recorded={})]
    check("manifests: status carries the help and an optional credential does not count as missing", st[0]["state"] == "ready" and st[0]["missing"] == [] and st[0]["verified"] is False and st[0]["links"])
    common.load_config = real_cfg
