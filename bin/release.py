#!/usr/bin/env python3
"""Prepare a release by hand, offline. It fills in COPIES of the Homebrew formula and the npm package under an output folder and prints what to do next.
It never publishes, never pushes, never runs npm and never touches the network. Standard library only.

    bin/release.py <version> --tarball <file> [--url <url>] [--npm] [--out <dir>]
        sha256 of the tarball, the placeholders filled into <out>/homebrew/qtdeck.rb (and, with --npm, <out>/npm/ with its app/ folder
        copied from the tracked files). The URL is https://github.com/ajmujaa/quarterdeck/archive/refs/tags/v<version>.tar.gz unless --url is given.
    bin/release.py --npm <version> [--out <dir>]
        only the npm folder.
    bin/release.py --make-tarball <version> [--out <dir>]
        a tarball of the tracked files (git archive) in <out>, for trying the steps locally.

The output folder defaults to dist/release/ (git-ignored).
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.]*)?")
URL_PATTERN = "https://github.com/ajmujaa/quarterdeck/archive/refs/tags/v{version}.tar.gz"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fill(text, **values):
    """The text with each @NAME@ placeholder replaced; a placeholder left over, or one that was not in the text, is an error."""
    for k, v in values.items():
        token = f"@{k.upper()}@"
        if text.count(token) != 1:
            raise ValueError(f"{token} should appear once in the template, not {text.count(token)} times")
        text = text.replace(token, v)
    left = re.findall(r"@[A-Z0-9_]+@", text)
    if left:
        raise ValueError("unfilled placeholder: " + left[0])
    return text


def tracked_files(root=ROOT):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [f for f in out.decode().split("\0") if f and (Path(root) / f).is_file()]


def make_tarball(version, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"quarterdeck-{version}.tar.gz"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", f"--prefix=quarterdeck-{version}/", "-o", str(dest), "HEAD"], check=True)
    return dest


def write_formula(version, tarball, url, out):
    sha = sha256_of(tarball)
    text = fill((ROOT / "packaging" / "homebrew" / "qtdeck.rb").read_text(), url=url, sha256=sha, version=version)
    dest = Path(out) / "homebrew" / "qtdeck.rb"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return dest, sha


def write_npm(version, out):
    src, dest = ROOT / "packaging" / "npm", Path(out) / "npm"
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "bin").mkdir(parents=True)
    (dest / "package.json").write_text(fill((src / "package.json").read_text(), version=version))
    for name in ("README.md", "bin/qtdeck.js"):
        shutil.copy2(src / name, dest / name)
    for f in tracked_files():
        if f.startswith(("packaging/", "dist/")):
            continue
        t = dest / "app" / f
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, t)
    return dest


def main(argv):
    ap = argparse.ArgumentParser(prog="release.py", description="Prepare a release by hand. Offline. Publishes nothing.")
    ap.add_argument("version", help="for example 1.2.3")
    ap.add_argument("--tarball", help="the release tarball to hash")
    ap.add_argument("--url", help="where the tarball will be")
    ap.add_argument("--npm", action="store_true", help="also fill the npm folder, with app/ copied from the tracked files")
    ap.add_argument("--make-tarball", action="store_true", help="build a tarball of the tracked files with git archive")
    ap.add_argument("--out", default=str(ROOT / "dist" / "release"), help="output folder (default dist/release)")
    a = ap.parse_args(argv)
    if not VERSION.fullmatch(a.version):
        print(f"release: '{a.version}' is not a version like 1.2.3", file=sys.stderr)
        return 2
    out = Path(a.out)
    if a.make_tarball:
        try:
            t = make_tarball(a.version, out)
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"release: could not make the tarball ({type(e).__name__})", file=sys.stderr)
            return 1
        print(f"made {t}\nnext: bin/release.py {a.version} --tarball {t} --npm")
        return 0
    if not a.tarball and not a.npm:
        print("release: give --tarball <file> (the formula needs its hash), or --npm for the npm folder only", file=sys.stderr)
        return 2
    made = []
    if a.tarball:
        if not Path(a.tarball).is_file():
            print(f"release: there is no tarball at {a.tarball}", file=sys.stderr)
            return 2
        url = a.url or URL_PATTERN.format(version=a.version)
        if not re.fullmatch(r"https://\S+", url):
            print("release: the URL must start with https://", file=sys.stderr)
            return 2
        f, sha = write_formula(a.version, a.tarball, url, out)
        made.append(f"formula   {f}\n            sha256 {sha}\n            url    {url}")
    if a.npm:
        made.append(f"npm       {write_npm(a.version, out)}")
    print("Prepared (nothing was published, pushed or uploaded):\n  " + "\n  ".join(made))
    print(f"""
What to do next, by hand, when you are ready:
  1. Tag the release and push the tag: v{a.version}. GitHub then serves the tarball at the URL above; its hash must equal the sha256 here.
  2. Homebrew: copy the formula into your tap's Formula folder (ajmujaa/homebrew-quarterdeck), commit and push the tap.
  3. npm: in the npm folder, remove the line "private": true, run npm pack to look at what would go up, then publish it yourself.
  Steps in full: packaging/README.md.""")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
