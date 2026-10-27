#!/usr/bin/env python3
"""Build the docs pages of the website from the repository's own markdown files.

The .md files stay the only source. This runs in the Pages workflow before the upload and writes
site/docs/<name>/index.html in the same template (nav, footer, styles) as the home page. Nothing it writes is committed.
Needs the `markdown` package at build time only; the pages it writes load nothing from other sites.
"""
import html
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
GITHUB = "https://github.com/ajmujaa/quarterdeck/blob/main/"
# file, folder under /docs/, what the index page says about it
DOCS = [
    ("SETUP.md", "setup", "Step by step, from nothing installed to a reviewed pull request."),
    ("GUIDE.md", "guide", "The full guide: what each part does and how to use it."),
    ("SECURITY.md", "security", "What is protected, what is not, and how to report a problem."),
    ("THREAT-MODEL.md", "threat-model", "What was considered, what is mitigated and what is left open."),
]
SLUG = {name: slug for name, slug, _ in DOCS}
# repository images the docs show, and the copy of each that the site ships
IMAGES = {"images/home.png": "/assets/home.jpg", "images/fleet.png": "/assets/fleet.jpg", "images/connections.png": "/assets/connections.jpg", "images/brain.png": "/assets/brain-wide.jpg"}

CSS = """
.doc{max-width:760px;margin:0 auto;padding:56px var(--gut) 72px;color:#c9d4ec;line-height:1.7;font-size:17px}
.doc p,.doc li,.doc td,.doc th,.doc blockquote,.doc h1,.doc h2,.doc h3{overflow-wrap:anywhere}
.doc h1,.doc h2,.doc h3{font-family:'Space Grotesk',sans-serif;color:#e8eefc;line-height:1.2;text-wrap:balance}
.doc h1{font-size:clamp(30px,6vw,44px);margin:0 0 24px}
.doc h2{font-size:28px;margin:48px 0 12px;padding-top:12px;border-top:1px solid #1f2c46}
.doc h3{font-size:21px;margin:32px 0 8px}
.doc p,.doc ul,.doc ol{margin:0 0 16px}
.doc li{margin:4px 0}
.doc a{color:#3dd6c6}
.doc code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:#111a2e;border:1px solid #1f2c46;border-radius:5px;padding:1px 5px}
.doc pre{background:#111a2e;border:1px solid #1f2c46;border-radius:10px;padding:14px 16px;overflow-x:auto;margin:0 0 20px}
.doc pre code{background:none;border:0;padding:0;font-size:14px;line-height:1.6}
.doc blockquote{margin:0 0 20px;padding:4px 18px;border-left:3px solid #3dd6c6;color:#93a1c0}
.doc table{border-collapse:collapse;width:100%;font-size:15px}
.doc .scroll{overflow-x:auto;margin:0 0 20px}
.doc th,.doc td{border:1px solid #1f2c46;padding:8px 12px;text-align:left;vertical-align:top}
.doc th{background:#111a2e;color:#e8eefc}
.doc img{max-width:100%;height:auto;border:1px solid #1f2c46;border-radius:10px}
.doc hr{border:0;border-top:1px solid #1f2c46;margin:32px 0}
.doc .edit{margin-top:48px;font-size:14px;color:#93a1c0}
.doclist{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;margin-top:32px}
.doclist a{display:block;background:#111a2e;border:1px solid #1f2c46;border-radius:12px;padding:22px;text-decoration:none;color:#93a1c0}
.doclist a:hover{border-color:#3dd6c6}
.doclist b{display:block;color:#e8eefc;font-family:'Space Grotesk',sans-serif;font-size:20px;margin-bottom:6px}
"""


def fail(msg):
    sys.exit("build_docs: " + msg)


def parts():
    """The shared pieces of the home page: the head, the opening of the page, the nav and the footer."""
    s = (SITE / "index.html").read_text()
    style = re.search(r"<style>\n(.*?)\n</style>", s, re.S).group(1)
    nav_at = s.index('<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between;padding:20px var(--gut)')
    nav_end = s.index("</div>\n</div>\n", nav_at) + len("</div>\n</div>")
    foot_at = s.index('<div style="border-top:1px solid #1f2c46;padding:32px')
    foot_end = s.index("\n\n</div>\n\n</body>", foot_at)
    opening = s[s.index("<body>") + len("<body>"):nav_at].strip("\n") + "\n"
    nav, foot = s[nav_at:nav_end], s[foot_at:foot_end]
    nav = nav.replace('<a href="/" style="color:#e8eefc">Home</a>', '<a href="/" style="color:#93a1c0">Home</a>')
    nav = re.sub(r'(<a href="/docs/" style=")color:#93a1c0(">Docs</a>)', r"\1color:#e8eefc\2", nav)
    return style, opening, nav, foot


def fix_link(url, here):
    if url.startswith(("http://", "https://", "mailto:", "#")):
        return url
    path, _, frag = url.partition("#")
    frag = "#" + frag if frag else ""
    name = path.removeprefix("./")
    if name in SLUG:
        return f"/docs/{SLUG[name]}/{frag}"
    if name in IMAGES:
        return IMAGES[name]
    if name.startswith("images/"):
        fail(f"{here}: the image {name} has no copy in site/assets (add it to IMAGES)")
    return GITHUB + name + frag


def page(style, opening, nav, foot, title, description, canonical, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="https://quarterdeckhq.com{canonical}">
<link rel="icon" href="/assets/favicon.png">
<meta name="theme-color" content="#0b1220">
<style>
{style}
{CSS}
</style>
</head>
<body>
{opening}{nav}
{body}
{foot}

</div>

</body>
</html>
"""


def main():
    style, opening, nav, foot = parts()
    out = SITE / "docs"
    cards = []
    for name, slug, blurb in DOCS:
        src = ROOT / name
        md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
        body = md.convert(src.read_text())
        body = re.sub(r'(<(?:a|img)\b[^>]*?\b(?:href|src)=")([^"]*)(")', lambda m: m.group(1) + fix_link(html.unescape(m.group(2)), name) + m.group(3), body)
        body = re.sub(r"(<table>.*?</table>)", r'<div class="scroll">\1</div>', body, flags=re.S)
        title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
        title = re.sub(r"<[^>]+>", "", title.group(1)) if title else name
        article = f'<article class="doc">\n{body}\n<p class="edit">This page is built from <a href="{GITHUB}{name}">{name}</a> in the repository.</p>\n</article>'
        if re.search(r"<script|<iframe|\bon\w+=|(?:src|href)=\"//", article) or re.search(r'src="https?:', article):
            fail(f"{name}: the page would load something from another site or run a script")
        d = out / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page(style, opening, nav, foot, f"{title} | Quarterdeck", blurb, f"/docs/{slug}/", article))
        cards.append(f'<a href="/docs/{slug}/"><b>{html.escape(title)}</b>{html.escape(blurb)}</a>')
    index = f'<article class="doc"><h1>Docs</h1><p>The same files that are in the repository, shown in the site\'s template.</p><div class="doclist">{"".join(cards)}</div></article>'
    (out / "index.html").write_text(page(style, opening, nav, foot, "Docs | Quarterdeck", "Setup, the guide, security and the threat model.", "/docs/", index))
    print(f"built {len(DOCS) + 1} pages in {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
