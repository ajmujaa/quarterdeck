"""Google OAuth for an installed app: loopback redirect on 127.0.0.1, PKCE, one scope per source.

The dashboard runs this for you when you press Save on the last credential (it passes --no-browser and shows you the address as a button).
By hand:  python3 bin/integrations/google_oauth.py gmail [--account <label>] [--no-browser]
The refresh token (one per account) is kept beside the env file, mode 0600. Nothing here prints a secret.
"""
import base64
import hashlib
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import accounts, common  # noqa: E402

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = {"gmail": "https://www.googleapis.com/auth/gmail.readonly"}


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token_file(name, label="default"):
    """google-<name>-token.json for the default account, google-<name>-<label>-token.json for another."""
    label = accounts.norm(label)
    return common.CONFIG_DIR / (f"google-{name}-token.json" if label == accounts.DEFAULT else f"google-{name}-{label}-token.json")


def build_auth_url(client_id, redirect, scope, verifier, state):
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": scope,
        "code_challenge": b64u(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256", "state": state, "access_type": "offline", "prompt": "select_account consent"})


def exchange_code(env, code, redirect, verifier):
    return common.request("POST", TOKEN_URL, form={
        "code": code, "client_id": common.need(env, "GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": common.need(env, "GOOGLE_OAUTH_CLIENT_SECRET"),
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})


def access_token(env, name, label="default"):
    """A fresh access token from the stored refresh token of one account."""
    import json
    p = token_file(name, label)
    if not p.is_file():
        raise IntegrationNeedsAuth(name, label=label)
    try:
        refresh = json.loads(p.read_text()).get("refresh_token", "")
    except ValueError:
        refresh = ""
    if not refresh:
        raise IntegrationNeedsAuth(name, label=label)
    try:
        d = common.request("POST", TOKEN_URL, form={
            "client_id": common.need(env, "GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": common.need(env, "GOOGLE_OAUTH_CLIENT_SECRET"),
            "refresh_token": refresh, "grant_type": "refresh_token"})
    except common.IntegrationError as e:
        if e.status in (400, 401):
            raise IntegrationNeedsAuth(name, expired=True, label=label)
        raise
    tok = d.get("access_token")
    if not tok:
        raise common.IntegrationError("Google did not return an access token")
    return tok


def IntegrationNeedsAuth(name, expired=False, label="default"):
    what = "token expired or revoked" if expired else "needs credentials: not signed in yet"
    more = "" if accounts.norm(label) == accounts.DEFAULT else f" --account {label}"
    return common.IntegrationError(f"{what}: run python3 bin/integrations/google_oauth.py {name}{more}")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if "code" in q or "error" in q:
            self.server.result = q
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Quarterdeck is connected. You can close this tab.")

    def log_message(self, *a):
        pass


def authorize(env, name, label="default", open_browser=True, timeout=240):
    label = accounts.norm(label)
    scope = SCOPES[name]
    verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(16)
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.result, srv.timeout = None, 1
    redirect = f"http://127.0.0.1:{srv.server_port}/"
    url = build_auth_url(common.need(env, "GOOGLE_OAUTH_CLIENT_ID"), redirect, scope, verifier, state)
    print("Open this address to sign in (it asks for read-only access to " + name + "):\n" + url, flush=True)
    if open_browser:
        webbrowser.open(url)
    waited = 0
    while srv.result is None and waited < timeout:
        srv.handle_request()
        waited += 1
    srv.server_close()
    q = srv.result or {}
    if q.get("state") != state or "code" not in q:
        raise common.IntegrationError("sign-in was cancelled or timed out: run it again")
    d = exchange_code(env, q["code"], redirect, verifier)
    if not d.get("refresh_token"):
        raise common.IntegrationError("Google gave no refresh token: remove Quarterdeck at myaccount.google.com/permissions and retry")
    import json
    common.write_private(token_file(name, label), json.dumps({"refresh_token": d["refresh_token"], "scope": scope}))
    more = "" if label == accounts.DEFAULT else f" --account {label}"
    print("Saved. Test it with: python3 bin/integrations/run.py " + name + more, flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    label = "default"
    open_browser = "--no-browser" not in args
    args = [a for a in args if a != "--no-browser"]
    if "--account" in args:
        i = args.index("--account")
        try:
            label = accounts.norm(args[i + 1] if i + 1 < len(args) else "")
        except ValueError as e:
            sys.exit(str(e))
        del args[i:i + 2]
    which = args[0] if args else ""
    if which not in SCOPES:
        sys.exit("usage: google_oauth.py gmail [--account <label>]")
    try:
        authorize(common.load_env(label), which, label, open_browser=open_browser)
    except common.IntegrationError as e:
        sys.exit(e.short)
