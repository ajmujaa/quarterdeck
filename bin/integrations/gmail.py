"""Gmail: unread important mail, headers only (From, Subject, Date). Bodies are never requested."""
from email.utils import parseaddr, parsedate_to_datetime

from integrations import common, google_oauth

SNAPSHOTS = ("gmail",)
API = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
QUERY = "is:unread is:important -category:promotions -category:social newer_than:7d"


def _sender(raw):
    name, addr = parseaddr(raw or "")
    return name or addr or "unknown sender"


def _when(raw):
    try:
        return parsedate_to_datetime(raw).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        return ""


def fetch(env, cfg):
    auth = {"Authorization": "Bearer " + google_oauth.access_token(env, "gmail")}
    lst = common.request("GET", API, headers=auth, params={"q": QUERY, "maxResults": common.MAX_ITEMS})
    ids = [m.get("id") for m in lst.get("messages", []) if isinstance(m, dict) and m.get("id")]
    unread = lst.get("resultSizeEstimate", len(ids)) if lst.get("nextPageToken") else len(ids)
    items = []
    for mid in ids[:common.MAX_ITEMS]:
        m = common.request("GET", f"{API}/{mid}", headers=auth, params={
            "format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
        h = {x.get("name", "").lower(): x.get("value", "") for x in m.get("payload", {}).get("headers", [])}
        items.append(common.make_item(h.get("subject") or "(no subject)", _sender(h.get("from")),
                                      _when(h.get("date")), True, f"https://mail.google.com/mail/u/0/#inbox/{mid}"))
    return {"gmail": {"items": items, "unread": unread}}
