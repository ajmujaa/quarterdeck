"""Slack: direct messages and mentions newer than your last-read marker, with a short preview.

User token (xoxp-), read scopes only, the narrowest set the calls below need: im:read im:history mpim:read
mpim:history (direct messages), channels:read groups:read (conversations.info on a channel where you were
mentioned), users:read, search:read. No channels:history or groups:history: no channel history is ever read. Written from Slack's method
docs as remembered, not tested against a live workspace; a wrong field shows up as a short error.
"""
import re
from datetime import datetime, timezone

from integrations import common

SNAPSHOTS = ("slack",)
API = "https://slack.com/api/"
MAX_DMS = 20
BAD_AUTH = {"invalid_auth", "token_revoked", "token_expired", "account_inactive", "not_authed"}


def call(token, method, **params):
    d = common.request("GET", API + method, headers={"Authorization": "Bearer " + token}, params=params)
    if not d.get("ok"):
        err = str(d.get("error", "unknown"))[:40]
        if err in BAD_AUTH:
            raise common.IntegrationError("token expired or revoked: create the Slack token again")
        if err == "missing_scope":
            raise common.IntegrationError("missing scope: " + common.clip(str(d.get("needed", "")), 40) + " (see the README)")
        raise common.IntegrationError("Slack said: " + err)
    return d


def _preview(text):
    t = re.sub(r"<@[A-Z0-9]+>", "@someone", text or "")
    t = re.sub(r"<(?:https?:[^|>]*\|)?([^>]*)>", r"\1", t)
    return common.clip(t, 100)


def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return ""


def fetch(env, cfg):
    token = common.need(env, "SLACK_USER_TOKEN")
    me = call(token, "auth.test").get("user_id", "")
    names, last_read = {}, {}

    def who(uid):
        if uid not in names:
            u = call(token, "users.info", user=uid).get("user", {})
            p = u.get("profile", {})
            names[uid] = p.get("display_name") or p.get("real_name") or u.get("name") or "someone"
        return names[uid]

    def read_marker(cid):
        """The last-read time of a channel, or None when Slack will not say (then it is skipped, not counted unread)."""
        if cid not in last_read:
            try:
                got = call(token, "conversations.info", channel=cid).get("channel", {}).get("last_read")
            except common.IntegrationError:
                got = None
            last_read[cid] = str(got) if got else None
        return last_read[cid]

    def link(cid, ts):
        try:
            return call(token, "chat.getPermalink", channel=cid, message_ts=ts).get("permalink")
        except common.IntegrationError:
            return None

    items, count = [], 0
    chans = call(token, "conversations.list", types="im,mpim", exclude_archived="true", limit=100).get("channels", [])
    for ch in chans[:MAX_DMS]:
        cid = ch.get("id")
        if not cid:
            continue
        marker = read_marker(cid)
        if marker is None:
            continue
        try:
            msgs = call(token, "conversations.history", channel=cid, oldest=marker, limit=5).get("messages", [])
        except common.IntegrationError:
            continue
        msgs = [m for m in msgs if m.get("user") and m.get("user") != me and not m.get("subtype")]
        if not msgs:
            continue
        count += len(msgs)
        m = msgs[0]
        where = "DM" if ch.get("is_im") else "group DM"
        items.append(common.make_item(f"{who(m['user'])} ({where})", _preview(m.get("text")),
                                      _iso(m.get("ts")), True, link(cid, m.get("ts"))))

    found = call(token, "search.messages", query=f"<@{me}>", sort="timestamp", sort_dir="desc", count=20)
    seen = set()
    for m in found.get("messages", {}).get("matches", []):
        c = m.get("channel") or {}
        cid = c.get("id")
        marker = None if not cid or c.get("is_im") or cid in seen else read_marker(cid)
        if marker is None or float(m.get("ts") or 0) <= float(marker):
            continue
        seen.add(cid)
        count += 1
        items.append(common.make_item(f"#{c.get('name', 'channel')}: mention", _preview(m.get("text")),
                                      _iso(m.get("ts")), True, m.get("permalink")))
    return {"slack": {"items": items, "unread": count}}
