#!/usr/bin/env python3
"""Mock-up plumbing, kept out of the duty that uses it (duties/mockup.sh).

Harness code, not model code. The model returns static pages as one JSON contract. Nothing it wrote is trusted:
every page is PARSED here (html.parser) and refused whole if it holds anything outside a small allowlist of tags
and attributes, or anything that could run, load or send something: a script, an event handler, an external
address, a frame, a form that posts, a meta refresh. Pages that pass are saved under the data folder and are
only ever shown in a sandboxed frame with a strict Content-Security-Policy (see bin/dashboard.py).

  mockup.py check   <brief.json> [<design-notes-text-file>]   (the model's reply on stdin)  -> the checked pages JSON, or errors on stderr
  mockup.py save    <home> <brief-id> <pages.json> [<set-note>]   writes workspace/mockups/<brief-id>/*.html + manifest.json
  mockup.py fail    <home> <brief-id> <reason>
  mockup.py start   <home> <brief-id>                             marks the brief's mock-ups "working" (refuses an unapproved brief)
  mockup.py act     <home> <brief-id> approve|changes [note]
  mockup.py need    <home> <brief-id>                             -> the approved brief and the owner's notes as JSON (refuses an unapproved brief)
  mockup.py rules                                                 -> the allowlist, as the sentences the prompt gives the model
  mockup.py page    <home> <brief-id> <name>                      -> the page, re-checked, or exit 1
"""
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brief as B

MAX_PAGES = 8
MAX_BYTES = 61440
MIN_CONTRAST = 4.5
STRICT_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; "
              "frame-ancestors 'self'; sandbox")

TAGS = set("""html head meta title style body header footer main nav section article aside h1 h2 h3 h4 h5 h6 p a ul ol li dl dt dd
div span button input label select option textarea form fieldset legend table thead tbody tfoot tr th td caption img strong em small b i
u s br hr details summary figure figcaption time abbr blockquote code pre mark sub sup""".split())
VOID = {"meta", "input", "img", "br", "hr"}
GLOBAL = {"class", "id", "lang", "title", "role", "tabindex", "hidden", "dir"}
PER_TAG = {
    "meta": {"charset", "name", "content"}, "a": {"href"}, "label": {"for"}, "button": {"type", "disabled", "name", "value"},
    "input": {"type", "name", "placeholder", "value", "checked", "disabled", "required", "min", "max", "step", "maxlength", "readonly", "autocomplete"},
    "select": {"name", "disabled", "required"}, "option": {"value", "selected", "disabled"}, "textarea": {"name", "rows", "cols", "placeholder", "disabled", "required", "maxlength", "readonly"},
    "form": {"action", "autocomplete"}, "td": {"colspan", "rowspan", "headers"}, "th": {"colspan", "rowspan", "scope"},
    "ol": {"start", "type", "reversed"}, "img": {"src", "alt", "width", "height"}, "time": {"datetime"}, "details": {"open"},
    "option": {"value", "selected", "disabled"}, "html": set(), "style": set(),
}
INPUT_TYPES = {"text", "search", "email", "number", "tel", "url", "password", "checkbox", "radio", "date", "time", "range", "submit", "button", "reset"}
INTERACTIVE = {"a", "button", "input", "select", "textarea", "summary"}
DATA_IMG = re.compile(r"^data:image/(?:png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=\s]+$")
NAME_RE = B.SLUG_RE


class MockupError(Exception):
    pass


# ---- colour ------------------------------------------------------------------------------------------
def _hex(v):
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", (v or "").strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _decls(css, selector_re):
    """All declarations of every rule whose selector list contains a selector matching selector_re (a plain scan, not a CSS engine)."""
    out = {}
    for sel, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        if any(re.fullmatch(selector_re, s.strip()) for s in sel.split(",")):
            for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
                out[k.lower()] = v.strip()
    return out


def contrast_of(css):
    """-> (ratio or None, note). The body text colour against the body background, when both are plain hex (directly or through one
    var() from :root). Everything else is not checked, and the note says so."""
    root = _decls(css, r"(:root|html)")
    body = _decls(css, r"(body|html|html\s*,\s*body)")
    body = {**_decls(css, r"html"), **body}

    def val(prop):
        v = body.get(prop)
        if v is None and prop == "background-color":
            v = body.get("background")
        if v is None:
            return None
        m = re.search(r"var\(\s*(--[\w-]+)", v)
        if m:
            v = root.get(m.group(1)) or v
        m = re.search(r"#[0-9a-fA-F]{3,6}\b", v)
        return _hex(m.group(0)) if m else None
    fg, bg = val("color"), val("background-color")
    if fg is None or bg is None:
        return None, "the body colours are not plain hex values, so contrast was not measured"
    return round(ratio(fg, bg), 2), ""


# ---- the page check -------------------------------------------------------------------------------------
class _Check(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors, self.css, self.tags, self.in_style = [], [], set(), False
        self.title_seen = self.body_seen = False
        self.out = []                     # the page as the parser understood it, written out again (see serialize)

    def bad(self, msg):
        if msg not in self.errors and len(self.errors) < 8:
            self.errors.append(msg)

    def _css(self, text, where):
        t = text.lower()
        if "\\" in t:
            self.bad(f"{where}: a backslash in CSS is not allowed")
        if re.search(r"@import|expression\s*\(|javascript:|vbscript:|behaviou?r\s*:|-moz-binding|@namespace", t):
            self.bad(f"{where}: CSS that loads or runs something")
        for u in re.findall(r"url\s*\(\s*([^)]*)\)", t):
            u = u.strip("'\" ")
            if not DATA_IMG.match(u):
                self.bad(f"{where}: url() may only hold a small inline image (data:image/...)")
        if "image-set(" in t or "-webkit-image-set" in t or "src(" in t:
            self.bad(f"{where}: image-set()/src() are not allowed")

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        if tag not in TAGS:
            self.bad(f"<{tag}> is not allowed")
            return
        self.out.append("<" + tag + "".join(f' {k.lower()}="{html.escape("" if v is None else v, quote=True)}"' if v is not None else f" {k.lower()}" for k, v in attrs) + ">")
        if tag == "style":
            self.in_style = True
        if tag == "title":
            self.title_seen = True
        if tag == "body":
            self.body_seen = True
        allowed = GLOBAL | PER_TAG.get(tag, set())
        for k, v in attrs:
            k = k.lower()
            v = "" if v is None else re.sub(r"[\x00-\x20]+", " ", v).strip()
            if k.startswith("on"):
                self.bad(f"event handler '{k}' on <{tag}>")
            elif k.startswith("aria-") or k.startswith("data-"):
                pass
            elif k == "style":
                self._css(v, f"style attribute on <{tag}>")
            elif k not in allowed:
                self.bad(f"attribute '{k}' on <{tag}> is not allowed")
            elif k == "href" and not re.fullmatch(r"#[\w-]*", v):
                self.bad("a link may only point to a place on the same page (#name): no address of any kind")
            elif k == "src" and not DATA_IMG.match(v):
                self.bad("an image may only be a small inline image (data:image/png|jpeg|gif|webp)")
            elif k == "action" and v not in ("", "#"):
                self.bad("a form may not send anywhere")
            elif tag == "input" and k == "type" and v.lower() not in INPUT_TYPES:
                self.bad(f"input type '{v}' is not allowed")
            elif tag == "button" and k == "type" and v.lower() not in ("button", "submit", "reset"):
                self.bad(f"button type '{v}' is not allowed")
            elif tag == "meta":
                pass
        if tag == "meta":
            d = {k.lower(): (v or "").lower() for k, v in attrs}
            if "http-equiv" in d or "refresh" in d.get("content", "") or d.get("name", "viewport") not in ("viewport", "description", "color-scheme", "theme-color", "") or "url=" in d.get("content", ""):
                self.bad("only a charset or viewport <meta> is allowed (no refresh)")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in TAGS and tag not in VOID:                  # "<div/>" opens a div in a browser; written out it is an empty one
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag in TAGS and tag not in VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.in_style:
            self.css.append(data)
            if "<" in data:
                self.bad("a < inside the <style> block is not allowed")
            self.out.append(data)
        else:
            self.out.append(html.escape(data, quote=False))

    def handle_decl(self, decl):
        if not re.fullmatch(r"(?i)doctype\s+html\s*", decl.strip()):
            self.bad("only <!doctype html> is allowed")
        else:
            self.out.append("<!doctype html>")

    def handle_comment(self, data):
        self.bad("a comment is not allowed")

    def handle_pi(self, data):
        self.bad("a processing instruction (<? ?>) is not allowed")

    def unknown_decl(self, data):
        self.bad("a CDATA section is not allowed")


def check_page(page_html):
    """-> {"errors": [...], "css": str, "tags": set}. No error means the page is acceptable."""
    if not isinstance(page_html, str) or not page_html.strip():
        return {"errors": ["the page is empty"], "css": "", "tags": set()}
    if len(page_html.encode()) > MAX_BYTES:
        return {"errors": [f"the page is {len(page_html.encode()) // 1024} KB; the limit is {MAX_BYTES // 1024} KB"], "css": "", "tags": set()}
    # What html.parser does not see the way a browser does: a comment ends at "--!>" in a browser and at "-->" here; a <style>, <title>, <textarea> or <script>
    # ends at "</style x>" in a browser and only at "</style>" here; a NUL byte is dropped or replaced differently. Each gap hid a <meta http-equiv=refresh> that the
    # check never saw and the browser obeyed. So none of these constructions is accepted at all (no comment, no odd end tag, no NUL), and the page that is
    # saved is the parser's own re-serialisation (serialize), not the model's text.
    if "\x00" in page_html:
        return {"errors": ["a NUL byte is not allowed"], "css": "", "tags": set(), "out": ""}
    if re.search(r"<!--|--!>|<![^dD]|<\?|<!\[", page_html):
        return {"errors": ["a comment, CDATA section or processing instruction is not allowed"], "css": "", "tags": set(), "out": ""}
    if re.search(r"(?i)</(style|title|textarea|script|xmp|iframe|noembed|noframes|noscript|plaintext)(?!>)", page_html):
        return {"errors": ["an end tag of <style>, <title> or <textarea> must be exactly </style>, </title>, </textarea>"], "css": "", "tags": set(), "out": ""}
    p = _Check()
    try:
        p.feed(page_html)
        p.close()
    except Exception as e:
        return {"errors": [f"the page could not be parsed: {type(e).__name__}"], "css": "", "tags": set()}
    css = "\n".join(p.css)
    p._css(css, "the <style> block")
    if not p.css:
        p.bad("the page needs its own <style> block")
    if not p.body_seen:
        p.bad("the page needs a <body>")
    if p.tags & INTERACTIVE and not re.search(r":focus(?:-visible)?\s*[,{]", css):
        p.bad("the page has links or controls but no :focus-visible style: a person using the keyboard must see where they are")
    elif p.tags & INTERACTIVE:
        fr = " ".join(b for s, b in re.findall(r"([^{}@]*:focus(?:-visible)?[^{}]*)\{([^{}]*)\}", css))
        if not re.search(r"outline\s*:\s*(?!none|0)[^;]+|box-shadow\s*:\s*(?!none)[^;]+|border[\w-]*\s*:|background[\w-]*\s*:|text-decoration", fr):
            p.bad("the :focus-visible style does not show anything (an outline, a shadow or a border)")
    r, _ = contrast_of(css)
    if r is not None and r < MIN_CONTRAST:
        p.bad(f"body text against its background is {r}:1; it must be at least {MIN_CONTRAST}:1")
    return {"errors": p.errors, "css": css, "tags": p.tags, "out": "".join(p.out)}


def serialize(page_html):
    """The page as the checker parsed it, written out again: lower-case tags, quoted escaped attributes, escaped text, no comment, no stray end tag.
    '' when the page does not pass. This is what is saved and served, so a browser reads what the checker read."""
    got = check_page(page_html)
    if got["errors"]:
        return ""
    out = got["out"]
    again = check_page(out)
    return out if not again["errors"] and again["out"] == out else ""


# ---- the contract ------------------------------------------------------------------------------------------
def check(raw, brief):
    """The model's MOCKUPS_JSON (text or parsed) and the approved brief -> the checked pages. Refuses the whole set on any violation."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw, strict=False)
        except ValueError as e:
            raise MockupError(f"the mock-ups are not JSON: {e}")
    if not isinstance(raw, list) or not raw:
        raise MockupError("MOCKUPS_JSON must be a non-empty list of pages")
    if len(raw) > MAX_PAGES:
        raise MockupError(f"{len(raw)} pages; the limit is {MAX_PAGES}")
    want = set(B.screen_slugs(brief))
    out, seen = [], set()
    for i, p in enumerate(raw, 1):
        if not isinstance(p, dict):
            raise MockupError(f"page {i} must be an object")
        name = p.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise MockupError(f"page {i}: name must be a short lowercase word with dashes, one of: {', '.join(sorted(want))}")
        if name not in want:
            raise MockupError(f"page {i}: '{name}' is not a screen of the brief (screens: {', '.join(sorted(want))})")
        if name in seen:
            raise MockupError(f"page '{name}' appears twice")
        seen.add(name)
        title = " ".join(str(p.get("title") or "").split())[:80]
        if not title:
            raise MockupError(f"page '{name}': title is empty")
        got = check_page(p.get("html"))
        if got["errors"]:
            raise MockupError(f"page '{name}' refused: " + "; ".join(got["errors"]))
        clean = serialize(p["html"])
        if not clean:
            raise MockupError(f"page '{name}' refused: it does not survive being written out again")
        r, note = contrast_of(got["css"])
        out.append({"name": name, "title": title, "html": clean, "contrast": r, "contrast_note": note})
    return out


# ---- state ---------------------------------------------------------------------------------------------------
def _dir(home, bid):
    if not B.id_ok(bid):
        raise MockupError("that is not a brief id")
    return Path(home) / "workspace" / "mockups" / bid


def _put(home, bid, **kw):
    rec = B.load(home, bid)
    m = rec.get("mockups") or {"state": "none"}
    m.update(kw)
    rec["mockups"], rec["updated"] = m, B.now()
    B._write(B._path(home, bid), rec)
    return rec


def _fresh(ts, secs=1200):
    """A run that began less than twenty minutes ago may still be going; an older "working" belongs to a run that died."""
    from datetime import datetime, timezone
    try:
        return (datetime.now(timezone.utc) - datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() < secs
    except (TypeError, ValueError):
        return False


def start(home, bid):
    with B.LOCK:
        rec = B.load(home, bid)
        if rec["status"] != "approved":
            raise MockupError(f"{bid} is {rec['status'].replace('_', ' ')}: mock-ups are made only from an approved brief")
        m = rec.get("mockups") or {}
        if m.get("state") == "working" and _fresh(m.get("started")):
            raise MockupError("mock-ups for this brief are already being made")
        _put(home, bid, state="working", started=B.now(), error="")


def fail(home, bid, reason):
    with B.LOCK:
        try:
            m = (B.load(home, bid).get("mockups") or {})
        except B.BriefError:
            return
        if m.get("state") == "working":
            _put(home, bid, state="failed", error=str(reason)[:300])


def save(home, bid, pages, note=""):
    d = _dir(home, bid)
    d.mkdir(parents=True, exist_ok=True)
    with B.LOCK:
        for old in d.glob("*.html"):
            old.unlink()
        names = []
        for p in pages:
            (d / f"{p['name']}.html").write_text(p["html"])
            names.append({"name": p["name"], "title": p["title"], "bytes": len(p["html"].encode()),
                          "contrast": p.get("contrast"), "contrast_note": p.get("contrast_note", "")})
        man = {"brief": bid, "created": B.now(), "pages": names, "note": note}
        B._write(d / "manifest.json", man)
        rec = B.load(home, bid)
        miss = [s["name"] for s in rec["brief"]["key_screens"] if B.slug(s["name"]) not in {n["name"] for n in names}]
        _put(home, bid, state="ready", pages=names, created=man["created"], missing=miss, error="")
    return d


def act(home, bid, action, note=""):
    with B.LOCK:
        rec = B.load(home, bid)
        m = rec.get("mockups") or {}
        if m.get("state") not in ("ready", "approved", "changes_requested") or not m.get("pages"):
            raise MockupError("there are no finished mock-ups to answer")
        text = " ".join(str(note or "").split())[:B.NOTE_MAX]
        if action == "approve":
            if m["state"] != "ready":
                raise MockupError(f"the mock-ups are {m['state'].replace('_', ' ')}; only a new set can be approved")
            state = "approved"
        elif action == "changes":
            if not text:
                raise MockupError("say what should change")
            state = "changes_requested"
        else:
            raise MockupError("unknown action")
        notes = list(m.get("notes") or []) + [{"at": B.now(), "action": state, "text": text}]
        return _put(home, bid, state=state, notes=notes)


def need(home, bid):
    """The approved brief, with the owner's notes on an earlier set of mock-ups. Refuses a brief that is not approved."""
    rec = B.load(home, bid)
    if rec["status"] != "approved":
        raise MockupError(f"{bid} is {rec['status'].replace('_', ' ')}: mock-ups are made only from an approved brief")
    m = rec.get("mockups") or {}
    notes = "\n".join(f"- {n['text']}" for n in m.get("notes", []) if n.get("action") == "changes_requested" and n.get("text")) if m.get("state") == "changes_requested" else ""
    return {"brief": rec["brief"], "project": rec.get("project", ""), "notes": notes, "slugs": B.screen_slugs(rec["brief"])}


def rules():
    """What the prompt tells the model it may write: the single source is the allowlist the check enforces."""
    per = "; ".join(f"{t}: {', '.join(sorted(a))}" for t, a in sorted(PER_TAG.items()) if a)
    return ("Allowed tags: " + " ".join(sorted(TAGS)) + ".\n"
            "Allowed on every tag: " + " ".join(sorted(GLOBAL)) + ", aria-*, data-*, and style (plain CSS, no url() except a data:image).\n"
            "Also allowed, per tag: " + per + ".\n"
            "A link (a href) may only be #name, a place on the same page. An img src may only be data:image/png|jpeg|gif|webp;base64,... "
            "A form may have no action or action=\"#\". Input types: " + " ".join(sorted(INPUT_TYPES)) + ".\n"
            f"Each page is at most {MAX_BYTES // 1024} KB, starts with <!doctype html>, has its own <style>, no backslash in CSS, "
            f"a :focus-visible style that shows (outline or box-shadow), and body text/background set as plain #hex colours at least {MIN_CONTRAST}:1.")


def page(home, bid, name):
    """The saved page, checked again on the way out. Raises MockupError when it is missing or no longer passes."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise MockupError("that is not a page name")
    f = _dir(home, bid) / f"{name}.html"
    try:
        man = json.loads((_dir(home, bid) / "manifest.json").read_text())
        html = f.read_text()
    except (OSError, ValueError):
        raise MockupError("no such mock-up")
    if name not in {p["name"] for p in man.get("pages", [])}:
        raise MockupError("no such mock-up")
    got = check_page(html)
    if got["errors"]:
        raise MockupError("this page no longer passes the check: " + "; ".join(got["errors"]))
    return html


def main(a):
    c = a[0] if a else ""
    try:
        if c == "check":
            rec = json.load(open(a[1]))
            print(json.dumps(check(sys.stdin.read(), rec["brief"] if isinstance(rec.get("brief"), dict) else rec)))
        elif c == "save":
            print(save(a[1], a[2], json.load(open(a[3])), a[4] if len(a) > 4 else ""))
        elif c == "fail":
            fail(a[1], a[2], a[3])
        elif c == "start":
            start(a[1], a[2])
        elif c == "act":
            rec = act(a[1], a[2], a[3], a[4] if len(a) > 4 else "")
            print(f"mock-ups for {rec['id']} are now {rec['mockups']['state'].replace('_', ' ')}.")
        elif c == "need":
            print(json.dumps(need(a[1], a[2])))
        elif c == "rules":
            print(rules())
        elif c == "page":
            sys.stdout.write(page(a[1], a[2], a[3]))
        else:
            sys.exit(__doc__)
    except (MockupError, B.BriefError) as e:
        sys.exit(f"mockup: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
