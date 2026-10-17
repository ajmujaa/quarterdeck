#!/usr/bin/env python3
"""outscan: refuse text that is about to leave this machine if it holds a credential.

    bin/outscan.py FILE      scan a file ("-" reads stdin); exit 1 and name the kind (never the value) on a hit, 0 when clean

lib.sh's gh_post runs this over every title, body and body file before a comment, issue or pull request is written on GitHub.
It uses the patterns bin/guard.py checks repositories with, plus a few that matter in prose a model wrote (a JWT, a password in a URL,
an AWS secret on a labelled line, a `key = long-random-value` assignment). Fail closed: an unreadable input is a hit.
Standard library only.
"""
import base64
import binascii
import math
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard as _guard

EXTRA = [
    ("a JSON web token", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("a password in a URL", r"\b[a-z][a-z0-9+.-]{1,12}://[^\s/:@]{1,64}:[^\s/@]{3,}@[^\s/]+"),
    ("an AWS secret access key", r"(?i)aws_?secret_?access_?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{30,}"),
    ("a labelled secret value", r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d|private[_-]?key|client[_-]?secret)[\"']?\s*[:=]\s*[\"']?(?=[A-Za-z0-9/+_=-]*\d)(?=[A-Za-z0-9/+_=-]*[A-Za-z])[A-Za-z0-9/+_=-]{24,}"),   # needs a digit and a letter: code like token = getTokenFromEnvironment() is not a secret
    ("an npm token", r"\bnpm_[A-Za-z0-9]{30,}"),
    ("a Twilio or SendGrid key", r"\b(?:SK[0-9a-f]{32}|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})"),
]
PATTERNS = _guard.SECRETS + EXTRA


_HYPHENS = {ord(c): "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d\u058a\u1806"}
_B64 = re.compile(r"[A-Za-z0-9+/_-]{24,}={0,2}")


def normalise(text):
    """What a reader sees, not what the bytes are: compatibility forms folded (fullwidth letters become plain), the other hyphens and dashes become "-",
    and every invisible format character (zero-width space and joiner, word joiner, soft hyphen, bidi marks) is dropped."""
    t = unicodedata.normalize("NFKC", text).translate(_HYPHENS)
    return "".join(c for c in t if unicodedata.category(c) != "Cf")


def _decoded(text):
    """The text of every base64 (or url-safe base64) run in `text` that decodes to something readable."""
    for m in _B64.finditer(text):
        s = m.group(0).rstrip("=").replace("-", "+").replace("_", "/")
        try:
            raw = base64.b64decode(s + "=" * (-len(s) % 4))
        except (binascii.Error, ValueError):
            continue
        if raw and sum(32 <= b < 127 or b in (9, 10, 13) for b in raw) >= 0.8 * len(raw):
            yield raw.decode("utf-8", "replace")


def scan_text(text):
    """[kind] for each credential pattern that matches somewhere in the text (the value is never returned). The text is scanned as written, then as read
    (normalise), then with every quote, plus, comma, bar and space taken out (a key split over lines or string pieces), and its base64 runs decoded."""
    seen = normalise(text)
    squashed = re.sub(r"[\s\"'`+,;|\\]+", "", seen)
    views = [(text, PATTERNS), (seen, PATTERNS), (squashed, _guard.SECRETS)] + [(d, PATTERNS) for d in _decoded(seen)]
    out = []
    for body, pats in views:
        for label, pat in pats:
            if label not in out and re.search(pat, body):
                out.append(label)
    return out


def _alnum(s):
    return re.sub(r"[^A-Za-z0-9]", "", s).lower()


def _env_values(path):
    """The values in a KEY=value file (an optional `export `, optional quotes). Never printed."""
    out = []
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            m = re.match(r"\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*(.*)$", line)
            if m:
                out.append(m.group(1).strip().strip("'\""))
    except OSError:
        pass
    return out


def known_values():
    """Every secret this machine is known to hold that could be pasted into a comment: the values in the harness env file (QUARTERDECK_SECRETS_DIR or
    ~/.config/quarterdeck), GH_TOKEN / GITHUB_TOKEN and the token the GitHub CLI holds. Only values of 12+ characters with a digit in them (a word like `sonnet`
    is not a secret). Read here, compared, never printed or logged."""
    d = Path(os.environ.get("QUARTERDECK_SECRETS_DIR") or Path.home() / ".config" / "quarterdeck")
    vals = []
    for f in [d / "env"] + sorted(d.glob("*.env")):
        vals += _env_values(f)
    vals += [os.environ.get(k, "") for k in ("GH_TOKEN", "GITHUB_TOKEN")]
    if not os.environ.get("QUARTERDECK_GH"):        # a stand-in gh (the tests) is not asked, and must not see a call it was not meant to see
        try:
            vals.append(subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return [v for v in dict.fromkeys(vals) if len(v) >= 12 and re.search(r"\d", v)]


def known_value_hit(text, values=None):
    """True when the text carries one of the machine's own secrets in any shape that survives stripping everything but letters and digits and ignoring case:
    as it is, reversed, hex-encoded, base64 or base32-encoded. Only a transformation that changes the letters themselves (rot13, a cipher) gets past,
    and that needs the model to have been shown the value at all."""
    flat = _alnum(text)
    for v in (known_values() if values is None else values):
        for form in (v, v[::-1], v.encode().hex(), base64.b64encode(v.encode()).decode(), base64.urlsafe_b64encode(v.encode()).decode(), base64.b32encode(v.encode()).decode()):
            f = _alnum(form)
            if len(f) >= 10 and f in flat:
                return True
    return False


def entropy_runs(text):
    """Runs of 24+ letters, digits, - _ + = with the look of random material (Shannon entropy above 4.2, letters and digits both): a WARNING class, not a
    credential pattern. A 40- or 64-digit hex hash is not reported."""
    out = []
    for m in re.finditer(r"[A-Za-z0-9_+=-]{24,}", text):
        r = m.group(0)
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", r, re.I) or not (re.search(r"\d", r) and re.search(r"[A-Za-z]", r)):
            continue
        h = -sum(c / len(r) * math.log2(c / len(r)) for c in (r.count(x) for x in set(r)))
        if h > 4.2:
            out.append(r[:4] + "...")
    return out


def redact(text):
    """The text with every credential-shaped run replaced by [redacted]. For text someone else wrote that the harness quotes in a comment (a pull
    request title): the quote is kept, the credential is not, and the comment is not refused for it. Text the model wrote is never passed through this."""
    for _label, pat in PATTERNS:
        text = re.sub(pat, "[redacted]", text)
    return text


def main(argv):
    if argv[:1] == ["--redact"]:
        sys.stdout.write(redact(sys.stdin.buffer.read().decode("utf-8", "replace")))
        return 0
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        text = sys.stdin.buffer.read().decode("utf-8", "replace") if argv[0] == "-" else Path(argv[0]).read_text(errors="replace")
    except OSError as e:
        print(f"outscan: cannot read {argv[0]} ({e}); refusing")
        return 1
    hits = scan_text(text)
    if known_value_hit(text):
        hits.append("a secret value this machine holds (the harness env file or a GitHub token), in some shape")
    warn = entropy_runs(text)
    if warn:
        print("outscan: warning: %d run(s) of random-looking characters (%s)" % (len(warn), ", ".join(warn[:3])), file=sys.stderr)
        if os.environ.get("QUARTERDECK_OUTSCAN_ENTROPY") == "block":
            hits.append("a long run of random-looking characters")
    for h in hits:
        print(f"outscan: the text holds {h}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
