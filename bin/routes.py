#!/usr/bin/env python3
"""Which routes should the Pilot sail? A pure function of the checkout, the changed files and the home page.

  routes.py <checkout> <changed-files.txt> <home.html> <cap> [<explicit-routes.json>]   prints a JSON array of paths

Sources, in order: "/", the project's own list (qa.routes), routes the pull request touches, framework router files
(Next.js app/ and pages/), a sitemap, links on the home page. Every path is a same-origin path on the local dev server:
it starts with one "/", has no host, query or fragment, is not dynamic ([id], :id), and is not an api, logout or
delete-like route. External links are dropped, not followed. Routes are only ever opened (GET); forms are never submitted
by a derived route. The list is capped.
"""
import json, re, sys
from pathlib import Path
from urllib.parse import urlsplit

SKIP = re.compile(r"(^|/)(api|logout|log-out|signout|sign-out|delete|remove|destroy)(/|$)|[\[\]:*<>{}()\\]", re.I)
PAGE = re.compile(r"^(?:src/)?app/((?:[^/]+/)*)page\.(?:tsx|jsx|ts|js|mdx)$")
PAGES = re.compile(r"^(?:src/)?pages/((?:[^/]+/)*)([^/]+)\.(?:tsx|jsx|ts|js|mdx)$")


def clean(p, host=""):
    """One same-origin path, or None. host: the dev server's own host:port, the only absolute address accepted."""
    p = (p or "").strip()
    u = urlsplit(p)
    if u.scheme or u.netloc:
        if u.scheme not in ("http", "https") or not host or u.netloc != host:
            return None
    path = u.path
    if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
        return None
    path = path.rstrip("/") or "/"
    if SKIP.search(path) or not re.fullmatch(r"[A-Za-z0-9._~/%-]+", path) or re.search(r"\.[a-z0-9]{1,5}$", path, re.I) and not path.endswith(".html"):
        return None
    return path


def router_route(rel):
    """Route a router file serves, or None. Route groups (x) vanish; dynamic segments are left in and refused by clean()."""
    m = PAGE.match(rel)
    if m:
        segs = [s for s in m.group(1).split("/") if s and not (s.startswith("(") and s.endswith(")"))]
        return "/" + "/".join(segs)
    m = PAGES.match(rel)
    if m and not m.group(2).startswith("_"):
        segs = [s for s in m.group(1).split("/") if s] + ([] if m.group(2) == "index" else [m.group(2)])
        return "/" + "/".join(segs)
    return None


def touched(changed, routers):
    """Routes a changed file belongs to: the router file itself, or any file in a route's own folder."""
    out = []
    for f in changed:
        r = router_route(f)
        if r:
            out.append(r)
            continue
        d = f.rsplit("/", 1)[0] if "/" in f else ""
        while d:
            hit = routers.get(d)
            if hit:
                out.append(hit)
                break
            d = d.rsplit("/", 1)[0] if "/" in d else ""
    return out


def derive(checkout, changed, home_html="", cap=8, explicit=(), host="127.0.0.1"):
    root = Path(checkout)
    files = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not p.is_symlink() and "node_modules" not in p.parts and ".git" not in p.parts][:20000] if root.is_dir() else []
    router = {f: r for f in files if (r := router_route(f))}
    folders = {f.rsplit("/", 1)[0]: r for f, r in router.items() if PAGE.match(f)}
    sitemap = []
    for f in files:
        if f.rsplit("/", 1)[-1] in ("sitemap.xml", "sitemap.txt"):
            # a sitemap names the live site's address; only its path is used, on the local server
            sitemap += [urlsplit(u).path for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", (root / f).read_text(errors="ignore"))]
    links = re.findall(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"'#][^"']*)["']""", home_html or "", re.I)
    out = []
    for group, raw in (("home", ["/"]), ("config", list(explicit)), ("diff", touched(list(changed), folders)),
                       ("router", sorted(router.values())), ("sitemap", sitemap), ("links", links)):
        for r in raw:
            p = clean(r, host)
            if p and p not in out:
                out.append(p)
    return out[:max(1, cap)]


def _selfcheck():
    import tempfile
    t = Path(tempfile.mkdtemp())
    for f in ["app/page.tsx", "app/settings/page.tsx", "app/settings/Form.tsx", "app/(auth)/login/page.tsx", "app/users/[id]/page.tsx",
              "app/api/pay/route.ts", "app/logout/page.tsx", "pages/about.tsx", "pages/index.tsx", "pages/_app.tsx", "node_modules/x/page.tsx"]:
        (t / f).parent.mkdir(parents=True, exist_ok=True); (t / f).write_text("x")
    (t / "public").mkdir(); (t / "public/sitemap.xml").write_text("<urlset><loc>https://example.test/pricing</loc><loc>https://example.test/blog/?a=1#x</loc></urlset>")
    home = '<a href="/team">t</a><a href="//evil.test/x">e</a><a href="https://evil.test/y">e</a><a href="http://127.0.0.1:3000/docs/">d</a><a href="mailto:a@b.test">m</a><a href="#top">h</a><a href="/img.png">i</a><a href="javascript:1">j</a>'
    r = derive(t, ["app/settings/Form.tsx"], home, 50, ["/qa-listed", "http://evil.test/z"], "127.0.0.1:3000")
    assert r[0] == "/" and r[1] == "/qa-listed" and r[2] == "/settings", r
    assert set(r) == {"/", "/qa-listed", "/settings", "/login", "/about", "/pricing", "/blog", "/team", "/docs"}, r
    assert not any(x in r for x in ("/users/[id]", "/logout", "/api/pay", "/evil.test/x", "/img.png")), r
    assert len(derive(t, [], home, 3)) == 3 and derive(t, [], "", 1) == ["/"]
    assert derive(t / "missing", [], "", 5) == ["/"]
    # a sitemap that is a link out of the checkout is not read (round 5)
    o = Path(tempfile.mkdtemp()); (o / "s.xml").write_text("<loc>https://x.test/outside-secret</loc>")
    (t / "sitemap.xml").symlink_to(o / "s.xml")
    assert "/outside-secret" not in derive(t, [], "", 50), "a linked sitemap was read"
    assert clean("/a?x=1#y") == "/a" and clean("/a/") == "/a" and clean("//h/x") is None and clean("/../etc") is None and clean("ftp://h/x") is None
    print("routes.py: ok")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _selfcheck(); sys.exit()
    co, ch, home, cap = sys.argv[1:5]
    ex = json.loads(Path(sys.argv[5]).read_text()) if len(sys.argv) > 5 else []
    lines = Path(ch).read_text().split() if Path(ch).exists() else []
    print(json.dumps(derive(co, lines, Path(home).read_text(errors="ignore") if Path(home).exists() else "", int(cap) if cap.isdigit() else 8,
                            ex if isinstance(ex, list) else [], sys.argv[6] if len(sys.argv) > 6 else "127.0.0.1")))
