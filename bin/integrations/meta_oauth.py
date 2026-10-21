"""Facebook sign-in for the Meta connection: one button instead of the Graph API Explorer and the token debugger.

The dashboard runs this when you press Connect with Facebook (it passes --no-browser and shows the address as a button).
By hand:  python3 bin/integrations/meta_oauth.py meta [--account <label>] [--no-browser]
It needs META_APP_ID and META_APP_SECRET saved first. It signs you in on facebook.com, trades the answer for a long-lived token, asks
me/accounts for your Page and saves the Page token, the Page id and the Instagram id the same way you would paste them. A Page token made from
a long-lived token does not expire. The user token is never saved. Nothing here prints a secret.
Meta wants the redirect address spelled out in the app, so the port is fixed: add  http://localhost:53172/  under Valid OAuth Redirect URIs.
"""
import secrets
import sys
import webbrowser
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import accounts, common, manifest  # noqa: E402
from integrations.google_oauth import _Handler  # noqa: E402  (the same one-shot loopback page)

GRAPH = "https://graph.facebook.com/v21.0/"
DIALOG = "https://www.facebook.com/v21.0/dialog/oauth"
PORT = 53172
REDIRECT = f"http://localhost:{PORT}/"
SCOPE = "pages_show_list,pages_read_engagement,read_insights,instagram_basic,instagram_manage_insights"


def build_auth_url(app_id, state):
    return DIALOG + "?" + urlencode({"client_id": app_id, "redirect_uri": REDIRECT, "state": state, "scope": SCOPE, "response_type": "code"})


def long_lived_user_token(env, code):
    """The code for a short token, the short token for a long-lived one. Secrets go in the request body, never in an address."""
    app_id, secret = common.need(env, "META_APP_ID"), common.need(env, "META_APP_SECRET")
    short = common.request("POST", GRAPH + "oauth/access_token", form={"client_id": app_id, "client_secret": secret, "redirect_uri": REDIRECT, "code": code}).get("access_token")
    if not short:
        raise common.IntegrationError("Facebook did not return a token: run the sign-in again")
    tok = common.request("POST", GRAPH + "oauth/access_token", form={"grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret, "fb_exchange_token": short}).get("access_token")
    if not tok:
        raise common.IntegrationError("Facebook did not return a long-lived token: run the sign-in again")
    return tok


def pick_page(user_token, want_id=""):
    """The Page the person shared: the one whose id is already saved, else the first. Returns the me/accounts entry."""
    pages = common.request("GET", GRAPH + "me/accounts", headers={"Authorization": "Bearer " + user_token},
                           params={"fields": "id,name,access_token,instagram_business_account{id}", "limit": 25}).get("data", [])
    pages = [p for p in pages if p.get("id") and p.get("access_token")]
    if not pages:
        raise common.IntegrationError("Facebook shared no Page: sign in again and tick your Page when it asks")
    return next((p for p in pages if p["id"] == want_id), pages[0])


def save_page(page, label):
    manifest.set_credential("META_PAGE_TOKEN", page["access_token"], label=label)
    manifest.set_credential("META_PAGE_ID", page["id"], label=label)
    manifest.set_credential("META_IG_USER_ID", ((page.get("instagram_business_account") or {}).get("id")) or "", label=label)


def authorize(env, label="default", open_browser=True, timeout=240):
    label = accounts.norm(label)
    state = secrets.token_urlsafe(16)
    try:
        srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    except OSError:
        raise common.IntegrationError(f"port {PORT} is busy: close what uses it and run the sign-in again")
    srv.result, srv.timeout = None, 1
    url = build_auth_url(common.need(env, "META_APP_ID"), state)
    print(url, flush=True)
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
    page = pick_page(long_lived_user_token(env, q["code"]), env.get("META_PAGE_ID", ""))
    save_page(page, label)
    print("Saved the Page " + str(page.get("name", ""))[:80] + (" and its Instagram account." if (page.get("instagram_business_account") or {}).get("id") else "."), flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    label, open_browser = "default", "--no-browser" not in args
    args = [a for a in args if a != "--no-browser"]
    if "--account" in args:
        i = args.index("--account")
        try:
            label = accounts.norm(args[i + 1] if i + 1 < len(args) else "")
        except ValueError as e:
            sys.exit(str(e))
        del args[i:i + 2]
    if args[:1] != ["meta"]:
        sys.exit("usage: meta_oauth.py meta [--account <label>]")
    try:
        authorize(common.load_env(label), label, open_browser=open_browser)
    except common.IntegrationError as e:
        sys.exit(e.short)
