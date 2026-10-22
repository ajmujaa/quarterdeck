"""Facebook Page posts and Instagram professional-account media through the Meta Graph API.

Uses a long-lived Page access token, sent in an Authorization header (never in the URL).
Personal-profile posts are not reachable by any API. Insights are best effort: a metric Meta
does not allow for a post is skipped, not an error.
"""
from integrations import common

SNAPSHOTS = ("facebook", "instagram")
API = "https://graph.facebook.com/v21.0/"


def _get(token, path, **params):
    try:
        return common.request("GET", API + path, headers={"Authorization": "Bearer " + token}, params=params)
    except common.IntegrationError as e:
        if e.status in (400, 401):
            raise common.IntegrationError("token expired or invalid (Facebook rejected it: it ran out, its app was deleted, or it is not a Page token): press Connect with Facebook on this card, or run python3 bin/integrations/meta_oauth.py meta", e.status)
        raise


def _insight(token, oid, metric):
    try:
        for row in _get(token, f"{oid}/insights", metric=metric).get("data", []):
            vals = row.get("values") or [{}]
            if isinstance(vals[0].get("value"), int):
                return vals[0]["value"]
    except common.IntegrationError:
        pass
    return None


def _count(d, key):
    x = d.get(key)
    return x.get("summary", {}).get("total_count", 0) if isinstance(x, dict) else 0


def fetch(env, cfg):
    token, page = env.get("META_PAGE_TOKEN", ""), env.get("META_PAGE_ID", "")
    if not token or not page:
        raise common.IntegrationError("needs credentials: not signed in yet: run python3 bin/integrations/meta_oauth.py meta")
    posts = _get(token, f"{page}/posts", limit=8, fields=(
        "id,message,created_time,permalink_url,shares,"
        "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)")).get("data", [])
    fb = []
    for p in posts[:8]:
        bits = [f"{_count(p, 'reactions')} reactions", f"{_count(p, 'comments')} comments",
                f"{(p.get('shares') or {}).get('count', 0)} shares"]
        reach = _insight(token, p.get("id", ""), "post_impressions")
        if reach is not None:
            bits.append(f"{common.fmt_int(reach)} impressions")
        fb.append(common.make_item(p.get("message") or "(photo or link post)", ", ".join(bits),
                                   p.get("created_time", ""), False, p.get("permalink_url")))
    out = {"facebook": {"items": fb}}
    ig_id = env.get("META_IG_USER_ID", "")
    if ig_id:
        media = _get(token, f"{ig_id}/media", limit=8,
                     fields="id,caption,media_type,permalink,timestamp,like_count,comments_count").get("data", [])
        ig = []
        for m in media[:8]:
            bits = [f"{m.get('like_count', 0)} likes", f"{m.get('comments_count', 0)} comments"]
            reach = _insight(token, m.get("id", ""), "reach")
            if reach is not None:
                bits.append(f"{common.fmt_int(reach)} reached")
            ig.append(common.make_item(m.get("caption") or f"({str(m.get('media_type', 'post')).lower()})",
                                       ", ".join(bits), m.get("timestamp", ""), False, m.get("permalink")))
        out["instagram"] = {"items": ig}
    return out
