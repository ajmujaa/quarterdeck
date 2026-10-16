"""X: recent mentions of you and how your latest posts did, through the X API with a read-only bearer token.

Needs a bearer token and your numeric user id. It only reads: your latest posts with their counts, and posts that mention you.
It never posts, likes, follows or deletes. X's access tiers and prices change and may cost money: the owner checks the developer portal.
The shapes below follow X's documentation for the posts and mentions lists. Not tested against the real service, so every parser tolerates a missing field.
"""
from integrations import common

SNAPSHOTS = ("x",)
API = "https://api.x.com/2/users/"
COUNTS = (("impression_count", "impressions"), ("like_count", "likes"), ("reply_count", "replies"), ("repost_count", "reposts"), ("quote_count", "quotes"))


def _get(token, path, **params):
    try:
        return common.request("GET", API + path, headers={"Authorization": "Bearer " + token}, params=params)
    except common.IntegrationError as e:
        if e.status == 401:
            raise common.IntegrationError("bearer token rejected: create a new one in the X developer portal", e.status)
        if e.status in (402, 403):
            raise common.IntegrationError("X refused this: your plan may not include it, check the developer portal", e.status)
        raise


def _rows(doc):
    rows = doc.get("data") if isinstance(doc, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _bits(m):
    m = m if isinstance(m, dict) else {}
    return ", ".join(f"{common.fmt_int(m[k])} {w}" for k, w in COUNTS if isinstance(m.get(k), int) and not isinstance(m.get(k), bool))


def fetch(env, cfg):
    token = common.need(env, "X_BEARER_TOKEN")
    uid = common.need(env, "X_USER_ID")
    if not uid.isdigit():
        raise common.IntegrationError("X_USER_ID must be the numeric id of your account")
    mine = _get(token, f"{uid}/tweets", max_results=5, exclude="retweets,replies", **{"tweet.fields": "created_at,public_metrics"})
    ments = _get(token, f"{uid}/mentions", max_results=10, **{"tweet.fields": "created_at"})
    items = [common.make_item(r.get("text") or "(post)", "mentioned you", r.get("created_at", ""), True, f"https://x.com/i/web/status/{r['id']}" if str(r.get("id", "")).isdigit() else None)
             for r in _rows(ments)[:6]]
    items += [common.make_item(r.get("text") or "(post)", _bits(r.get("public_metrics")) or "counts not available", r.get("created_at", ""), False,
                               f"https://x.com/i/web/status/{r['id']}" if str(r.get("id", "")).isdigit() else None) for r in _rows(mine)[:6]]
    return {"x": {"items": items, "unread": len(_rows(ments))}}
