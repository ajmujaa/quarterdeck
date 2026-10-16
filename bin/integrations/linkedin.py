"""LinkedIn from the official data export. A file import, not a live feed.

Drop the export (Shares.csv, or the .zip) and any post-analytics CSV or XLSX into
~/Documents/quarterdeck-inbox/linkedin/ and run this again. Reads files only; makes no network call.
"""
import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from integrations import common

SNAPSHOTS = ("linkedin",)
INBOX = Path.home() / "Documents" / "quarterdeck-inbox" / "linkedin"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_xlsx(data):
    """Every sheet as a list of rows of strings. Stdlib only."""
    z = zipfile.ZipFile(io.BytesIO(data))
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si"):
            strings.append("".join(t.text or "" for t in si.iter(NS + "t")))
    sheets = []
    for n in sorted(x for x in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", x)):
        rows = []
        for r in ET.fromstring(z.read(n)).iter(NS + "row"):
            row = []
            for c in r.iter(NS + "c"):
                v = c.find(NS + "v")
                if c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(NS + "t"))
                elif v is None:
                    val = ""
                elif c.get("t") == "s":
                    val = strings[int(v.text)]
                else:
                    val = v.text or ""
                col = re.match(r"[A-Z]+", c.get("r", "")).group(0) if c.get("r") else ""
                idx = 0
                for ch in col:
                    idx = idx * 26 + ord(ch) - 64
                while idx and len(row) < idx - 1:
                    row.append("")
                row.append(val)
            rows.append(row)
        sheets.append(rows)
    return sheets


def _csv_rows(data):
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig", "replace"))))


def _tables(folder):
    """(name, rows) for every table found in the inbox, including inside zips."""
    out = []
    for f in sorted(folder.glob("*")) if folder.is_dir() else []:
        try:
            blobs = []
            if f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as z:
                    blobs = [(Path(n).name, z.read(n)) for n in z.namelist() if n.lower().endswith((".csv", ".xlsx"))]
            elif f.suffix.lower() in (".csv", ".xlsx"):
                blobs = [(f.name, f.read_bytes())]
            for name, data in blobs:
                if name.lower().endswith(".csv"):
                    out.append((name, _csv_rows(data)))
                else:
                    out.extend((name, s) for s in read_xlsx(data))
        except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError):
            continue
    return out


def _key(u):
    return re.sub(r"[?#].*$", "", (u or "").strip().lower()).rstrip("/")


def _metrics(tables):
    """{post url key: {impressions, reactions, comments}} from any table with a link and a metric."""
    out = {}
    for name, rows in tables:
        if name.lower().startswith("shares"):
            continue
        for i, hdr in enumerate(rows[:10]):
            low = [h.strip().lower() for h in hdr]
            link = next((j for j, h in enumerate(low) if "url" in h or "link" in h), None)
            cols = {m: next((j for j, h in enumerate(low) if h.startswith(w)), None)
                    for m, w in (("impressions", "impressions"), ("reactions", "reactions"), ("comments", "comments"))}
            if link is None or not any(v is not None for v in cols.values()):
                continue
            for row in rows[i + 1:]:
                if link < len(row) and row[link]:
                    m = out.setdefault(_key(row[link]), {})
                    for k, j in cols.items():
                        if j is not None and j < len(row):
                            try:
                                m[k] = int(float(row[j].replace(",", "")))
                            except ValueError:
                                pass
            break
    return out


def fetch(env, cfg, folder=None):
    folder = folder or INBOX
    tables = _tables(folder)
    shares = next((r for n, r in tables if n.lower().startswith("shares")), None)
    if not shares:
        raise common.IntegrationError(f"needs a file: put Shares.csv (or the export .zip) in {folder}")
    hdr = [h.strip() for h in shares[0]]
    posts = [dict(zip(hdr, r)) for r in shares[1:] if r]
    posts.sort(key=lambda p: p.get("Date", ""), reverse=True)
    stats = _metrics(tables)
    items = []
    for p in posts[:8]:
        link = p.get("ShareLink", "")
        m = stats.get(_key(link), {})
        bits = [f"{common.fmt_int(m[k])} {k}" for k in ("impressions", "reactions", "comments") if k in m]
        date = p.get("Date", "").strip()
        items.append(common.make_item(p.get("ShareCommentary") or p.get("SharedUrl") or "(no text)",
                                      ", ".join(bits) or "no metrics in the export",
                                      date.replace(" ", "T") + "Z" if date else "", False, link))
    return {"linkedin": {"items": items}}
