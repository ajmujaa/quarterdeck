"""Threads: your latest posts and how they did, through Meta's Threads API.

Uses a long-lived user access token, sent in an Authorization header (never in the URL). It reads your own posts (text, time, link)
and, where Meta allows it, the counts for each (views, likes, replies, reposts, quotes). It never posts, replies or deletes.
The response shapes below come from Meta's documentation for the posts list. The counts call is best effort: a post whose
counts Meta will not give is shown without them. Not tested against the real service, so every parser here tolerates a missing field.
"""
from integrations import common

SNAPSHOTS = ("threads",)
API = "https://graph.threads.net/v1.0/"
METRICS = ("views", "likes", "replies", "reposts", "quotes")


def _get(token, path, **params):
    try:
        return common.request("GET", API + path, headers={"Authorization": "Bearer " + token}, params=params)
    except common.IntegrationError as e:
        if e.status in (400, 401):
            raise common.IntegrationError("token expired or invalid: create a new long-lived Threads token", e.status)
        raise


def counts(doc):
    """{metric: int} from an insights answer. Handles a value list or a total_value, skips anything else."""
    out = {}
    rows = doc.get("data") if isinstance(doc, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("name") not in METRICS:
            continue
        v = None
        vals = row.get("values")
        if isinstance(vals, list) and vals and isinstance(vals[0], dict):
            v = vals[0].get("value")
        if v is None and isinstance(row.get("total_value"), dict):
            v = row["total_value"].get("value")
        if isinstance(v, int) and not isinstance(v, bool):
            out[row["name"]] = v
    return out


def _bits(c):
    return ", ".join(f"{common.fmt_int(c[m])} {m}" for m in METRICS if m in c)


def fetch(env, cfg):
    token = common.need(env, "THREADS_ACCESS_TOKEN")
    doc = _get(token, "me/threads", fields="id,text,timestamp,permalink,media_type", limit=8)
    posts = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(posts, list):
        raise common.IntegrationError("Threads answered with something unexpected: see the README")
    items = []
    for p in posts[:8]:
        if not isinstance(p, dict):
            continue
        c = {}
        if p.get("id"):
            try:
                c = counts(_get(token, f"{p['id']}/insights", metric=",".join(METRICS)))
            except common.IntegrationError:
                pass
        items.append(common.make_item(p.get("text") or f"({str(p.get('media_type', 'post')).lower()})", _bits(c) or "counts not available",
                                      p.get("timestamp", ""), False, p.get("permalink")))
    return {"threads": {"items": items}}
