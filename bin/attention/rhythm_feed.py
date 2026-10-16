"""The small adapter that gives dashboard/assets/rhythm.js the same shape the demo world gives it, from the hour buckets in
state/attention.json. It reads nothing but that file's counts: no commit message, file, note text or calendar title has ever been
stored there, so none can appear here.

Only the HOUR of each event is kept, so the minutes are an estimate: the events of an hour are spread evenly across it, one
project after another, which is why everything built from them is labelled estimated."""
BADGE = "Estimated from your commits, branches, notes and calendar. It cannot see reading, thinking or other work."
KINDS = {"commits": "commit", "prs": "pr", "notes": "note", "runs": "run"}
RULES = {"gap": 44, "minBlock": 20, "tail": 5, "switchKinds": ["commit"], "minEvents": 15, "minDays": 3}
BACK_DAYS = 100                    # the screen reaches nine weeks back plus a five week heatmap
MAX_PER_BUCKET = 20


def _spread(n, lo, hi):
    """n minutes, evenly across [lo, hi] (a single one in the middle)."""
    n = max(0, min(int(n), MAX_PER_BUCKET))
    if n == 1:
        return [round((lo + hi) / 2)]
    return [round(lo + i * (hi - lo) / (n - 1)) for i in range(n)]


def _days_back(today, n):
    from datetime import date, timedelta
    d = date.fromisoformat(today)
    return {(d - timedelta(days=i)).isoformat() for i in range(n)}


def build(store, today, updated=None):
    """{concept: False, estimated: True, badge, today, rules, events: [{t, kind, project}], meetings: [{day, from, to: None}]}."""
    store = store if isinstance(store, dict) else {}
    hours = store.get("hours") if isinstance(store.get("hours"), dict) else {}
    keep = _days_back(today, BACK_DAYS)
    events, meetings, slots = [], [], {}
    for project, per_day in hours.items():
        if not isinstance(per_day, dict):
            continue
        for day, per_hour in per_day.items():
            if day not in keep or not isinstance(per_hour, dict):
                continue
            for hh, counts in per_hour.items():
                if isinstance(counts, dict) and isinstance(hh, str) and hh.isdigit() and 0 <= int(hh) <= 23:
                    slots.setdefault((day, int(hh)), []).append((project, counts))
    for (day, h), items in sorted(slots.items()):
        items.sort(key=lambda x: x[0])
        share = 50 / len(items)
        for i, (project, counts) in enumerate(items):
            lo, hi = 5 + i * share, 5 + (i + 1) * share - (1 if len(items) > 1 else 0)
            for field, kind in KINDS.items():
                n = counts.get(field)
                if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                    for m in _spread(n, lo, hi):
                        events.append({"t": "%sT%02d:%02d" % (day, h, min(59, max(0, m))), "kind": kind, "project": project if project not in ("other",) else ""})
            n = counts.get("meetings")
            if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                for m in _spread(n, 5, 55):
                    meetings.append({"day": day, "from": "%d:%02d" % (h, m), "to": None})
    events.sort(key=lambda e: e["t"])
    return {"concept": False, "on": True, "estimated": True, "badge": BADGE, "today": today, "updated": updated or store.get("updated"), "rules": RULES,
            "events": events, "meetings": sorted(meetings, key=lambda m: (m["day"], m["from"]))}


TASK_FIELDS = ("t", "kind", "project", "label", "branch")


def task_view(store, today, on=True):
    """The task events for the screen: only the allowed fields, cleaned again, the last BACK_DAYS days. Nothing else in the store is passed on."""
    from attention import tasks
    if not on:
        return {"on": False, "events": [], "file": "state/" + tasks.FILE}
    keep = _days_back(today, BACK_DAYS)
    out = []
    for e in (store.get("events") if isinstance(store, dict) else None) or []:
        if isinstance(e, dict) and e.get("kind") in tasks.KINDS and isinstance(e.get("t"), str) and e["t"][:10] in keep and isinstance(e.get("label"), str):
            row = {k: tasks.clean(e[k], tasks.MAX_LABEL) for k in TASK_FIELDS if isinstance(e.get(k), str)}
            if row.get("label"):
                out.append(row)
    return {"on": True, "events": out, "file": "state/" + tasks.FILE}
