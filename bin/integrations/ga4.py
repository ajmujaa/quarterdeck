"""Google Analytics 4 for the blog: last 7 days against the 7 before. Data API v1beta, read only.

Auth is a service-account key file; the RS256 JWT is signed with the openssl command line.
"""
import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from integrations import common

SNAPSHOTS = ("ga4",)
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
API = "https://analyticsdata.googleapis.com/v1beta/properties/{}:runReport"
RANGES = [{"startDate": "6daysAgo", "endDate": "today", "name": "this"},
          {"startDate": "13daysAgo", "endDate": "7daysAgo", "name": "prior"}]


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign_rs256(pem, data):
    fd, path = tempfile.mkstemp()                # mode 0600; removed straight after signing
    try:
        os.write(fd, pem.encode())
        os.close(fd)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", path], input=data,
                           capture_output=True, timeout=15)
    except FileNotFoundError:
        raise common.IntegrationError("openssl was not found on PATH")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if r.returncode != 0 or not r.stdout:
        raise common.IntegrationError("could not sign with the service-account key: is the key file intact?")
    return r.stdout


def make_jwt(email, pem, signer=sign_rs256, now=None):
    now = int(now or time.time())
    head = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = _b64u(json.dumps({"iss": email, "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3000}).encode())
    return f"{head}.{claim}.{_b64u(signer(pem, f'{head}.{claim}'.encode()))}"


def access_token(env):
    p = Path(common.need(env, "GA4_SERVICE_ACCOUNT_FILE")).expanduser()
    try:
        key = json.loads(p.read_text())
        jwt = make_jwt(key["client_email"], key["private_key"])
    except (OSError, ValueError, KeyError):
        raise common.IntegrationError("needs credentials: GA4_SERVICE_ACCOUNT_FILE is missing or not a service-account key")
    d = common.request("POST", TOKEN_URL, form={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt})
    if not d.get("access_token"):
        raise common.IntegrationError("Google did not return an access token")
    return d["access_token"]


def _num(row, i):
    try:
        return int(float(row["metricValues"][i]["value"]))
    except (KeyError, IndexError, ValueError, TypeError):
        return 0


def _dims(row):
    return [x.get("value", "") for x in row.get("dimensionValues", [])]


def fetch(env, cfg):
    prop = str(env.get("GA4_PROPERTY_ID") or cfg["ga4"].get("property_id", "")).strip()      # the field on the Connections page wins over the config file
    if not prop.isdigit():
        raise common.IntegrationError("needs the GA4 property id: enter it on the Connections page (digits only)")
    site = str(cfg["ga4"].get("site_url") or "").rstrip("/")             # no site address set: the items carry no link at all
    auth = {"Authorization": "Bearer " + access_token(env)}
    url = API.format(prop)
    metrics = [{"name": "screenPageViews"}, {"name": "activeUsers"}, {"name": "sessions"}]

    tot = common.request("POST", url, headers=auth, json_body={"dateRanges": RANGES, "metrics": metrics})
    sums = {"this": [0, 0, 0], "prior": [0, 0, 0]}
    for r in tot.get("rows", []):
        which = _dims(r)[-1:] or [""]
        if which[0] in sums:
            sums[which[0]] = [_num(r, 0), _num(r, 1), _num(r, 2)]

    pg = common.request("POST", url, headers=auth, json_body={
        "dateRanges": RANGES, "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
        "metrics": [{"name": "screenPageViews"}], "limit": 200})
    pages = {}
    for r in pg.get("rows", []):
        d = _dims(r)
        if len(d) < 3:
            continue
        p = pages.setdefault(d[0], {"title": d[1], "this": 0, "prior": 0})
        if d[2] in ("this", "prior"):
            p[d[2]] += _num(r, 0)
    top = sorted(pages.items(), key=lambda kv: -kv[1]["this"])[:8]

    src = common.request("POST", url, headers=auth, json_body={
        "dateRanges": [RANGES[0]], "dimensions": [{"name": "sessionDefaultChannelGroup"}],
        "metrics": [{"name": "sessions"}], "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 3})

    t, p = sums["this"], sums["prior"]
    items = [common.make_item(f"Last 7 days: {common.fmt_int(t[0])} views",
                              f"{common.fmt_int(t[1])} users, {common.fmt_int(t[2])} sessions, "
                              f"views {common.pct_change(t[0], p[0])} vs last week", "", False, site + "/" if site else None)]
    for path, v in top:
        items.append(common.make_item(v["title"] or path,
                                      f"{common.fmt_int(v['this'])} views, {common.pct_change(v['this'], v['prior'])} vs last week",
                                      "", False, site + path if site and path.startswith("/") else None))
    for r in src.get("rows", [])[:3]:
        items.append(common.make_item("Source: " + (_dims(r)[0] or "unknown"),
                                      f"{common.fmt_int(_num(r, 0))} sessions", "", False, None))
    return {"ga4": {"items": items}}
