#!/usr/bin/env python3
"""docs: the harness side of the scribe (duties/scribe.sh): which documents may be drafted, the facts the model gets, and the checks on what it wrote.

    bin/docs.py wanted PROJECT [readme|architecture]...   the documents that are missing (survey) and still not in the working tree; one key per line
    bin/docs.py facts PROJECT                             the survey as the model is shown it (names from the project's files stay data)
    bin/docs.py parse PROJECT [which]...                  the model's DOC_JSON (stdin) checked and cleaned; prints {"files": [...], "notes": [...]}
    bin/docs.py save PROJECT [which]...                   keep a cleaned draft (stdin) as state/projects/<project>/docs-draft.json (0600)
    bin/docs.py show PROJECT [which]...                   the kept draft, to read
    bin/docs.py paths PROJECT [which]...                  the paths of the kept draft, one per line
    bin/docs.py write PROJECT WORKTREE [which]...         write the kept draft into a worktree: new files only, never over one, never through a link
    bin/docs.py record PROJECT BRANCH [URL]               remember the branch (and pull request) that holds the docs; the draft is used up

The HARNESS decides what may be written: exactly README.md and docs/ARCHITECTURE.md, and each only when the survey says it is missing and it is not
in the working tree now. A path the model invents is dropped with a note. Content is at most 20 KB per file, plain text (no control or invisible
characters), and is scanned for credentials (bin/outscan.py) before it is shown or kept: a hit refuses the whole reply. Standard library only.
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import survey as _survey

ALLOWED = {"readme": "README.md", "architecture": "docs/ARCHITECTURE.md"}
MAX_BYTES = 20_000
MIN_CHARS = 40


class DocsError(ValueError):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def _registry_path(project):
    import attach as _attach
    e = _attach.load_registry(_attach.registry_path()).get(project)
    if not isinstance(e, dict) or not e.get("path"):
        raise DocsError(f"'{project}' is not registered (see: qtdeck projects)")
    return Path(os.path.expanduser(e["path"]))


def _present(root, rel):
    p = Path(root) / rel
    return p.exists() or p.is_symlink()


def wanted(project, which=()):
    """The keys that may be drafted now: missing in the survey, and no file (or link) of that name in the working tree."""
    sv = _survey.load(project)
    if sv is None:
        raise DocsError(f"{project} has not been surveyed yet: run qtdeck attach <its folder> first")
    root = _registry_path(project)
    keys = [k for k in ("readme", "architecture") if k in sv["docs"]["missing"] and (not which or k in which) and not _present(root, ALLOWED[k])]
    return keys


def _keys(which):
    bad = [w for w in which if w not in ALLOWED]
    if bad:
        raise DocsError("which document? readme or architecture (not: " + ", ".join(w[:20] for w in bad) + ")")
    return list(which)


def facts(project):
    sv = _survey.load(project)
    if sv is None:
        raise DocsError(f"{project} has not been surveyed yet")
    return _survey.markdown(sv, timed=False)


def _plain(text, label):
    if not isinstance(text, str):
        raise DocsError(f"{label}: the content must be text")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise DocsError(f"{label}: more than {MAX_BYTES // 1000} KB; nothing was kept")
    for ch in text:
        cat = unicodedata.category(ch)
        if (cat == "Cc" and ch not in "\n\t") or cat in ("Cf", "Zl", "Zp") or ch == "\x85":
            raise DocsError(f"{label}: holds a control or invisible character; nothing was kept")
    if len(text.strip()) < MIN_CHARS:
        raise DocsError(f"{label}: almost empty; nothing was kept")
    return text if text.endswith("\n") else text + "\n"


def _credential(text):
    import outscan as _os
    hits = _os.scan_text(text)
    if _os.known_value_hit(text):
        hits.append("a secret value this machine holds")
    return hits


def parse(project, raw, which=()):
    """The model's DOC_JSON checked. Returns {"files": [{"path", "content"}], "notes": [...]}. DocsError(code 3) for a credential, 1 for anything else wrong,
    4 when nothing is left to write."""
    allowed = {ALLOWED[k] for k in wanted(project, _keys(which))}
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        raise DocsError("the reply's DOC_JSON is not JSON")
    files = obj.get("files") if isinstance(obj, dict) else None
    if not isinstance(files, list) or not files:
        raise DocsError("the reply's DOC_JSON has no files")
    out, notes, seen = [], [], set()
    for f in files[:12]:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str):
            raise DocsError("a file in the reply has no path")
        path = f["path"].strip()
        if path not in allowed:
            notes.append(f"dropped {path[:60]!r}: only " + ", ".join(sorted(allowed)) + " may be written here")
            continue
        if path in seen:
            raise DocsError(f"{path} appears twice in the reply")
        seen.add(path)
        text = _plain(f.get("content"), path)
        hits = _credential(text)
        if hits:
            raise DocsError(f"{path}: the text holds {hits[0]}; nothing was shown or kept", 3)
        out.append({"path": path, "content": text})
    if not out:
        raise DocsError("nothing left to write: " + "; ".join(notes) if notes else "nothing left to write", 4)
    return {"files": out, "notes": notes}


def _draft_path(project):
    return _survey.folder(project) / "docs-draft.json"


def save(project, cleaned, which=()):
    d = _survey.folder(project)
    d.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(d.parent, 0o700)
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    rec = {"project": project, "at": _survey.now_iso(), "which": list(which), "files": cleaned["files"], "notes": cleaned.get("notes", [])}
    _survey._atomic(_draft_path(project), json.dumps(rec, indent=2) + "\n")
    return rec


def load_draft(project):
    try:
        j = json.loads(_draft_path(project).read_text())
    except (OSError, ValueError):
        return None
    return j if isinstance(j, dict) and isinstance(j.get("files"), list) else None


def _files(project, which):
    dr = load_draft(project)
    if not dr:
        raise DocsError(f"there is no draft for {project} yet: qtdeck docs {project}")
    want = {ALLOWED[k] for k in _keys(which)} if which else set(ALLOWED.values())
    out = []
    for f in dr["files"]:
        if isinstance(f, dict) and f.get("path") in ALLOWED.values() and f["path"] in want:
            text = _plain(f.get("content"), f["path"])               # checked again: the file on disk may have been edited since
            hits = _credential(text)
            if hits:
                raise DocsError(f"{f['path']}: the kept draft holds {hits[0]}; nothing was written", 3)
            out.append({"path": f["path"], "content": text})
    if not out:
        raise DocsError("the kept draft has none of those documents")
    return out


def write(project, worktree, which=()):
    """Write the kept draft into a worktree. A file is made with O_EXCL (never over one), no folder on the way may be a link, and the result must stay
    inside the worktree. Returns the paths written."""
    root = Path(worktree).resolve()
    done = []
    for f in _files(project, which):
        target = root / f["path"]
        parent = target.parent
        cur = root
        for part in Path(f["path"]).parent.parts:
            cur = cur / part
            if cur.is_symlink() or (cur.exists() and not cur.is_dir()):
                raise DocsError(f"{cur.relative_to(root)} is a link or a file, so {f['path']} cannot be written there")
        parent.mkdir(parents=True, exist_ok=True)
        if root not in parent.resolve().parents and parent.resolve() != root:
            raise DocsError(f"{f['path']} would leave the project")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)       # raises FileExistsError: never overwrites
        with os.fdopen(fd, "w") as fh:
            fh.write(f["content"])
        done.append(f["path"])
    return done


def record(project, branch, url=""):
    dr = load_draft(project)
    d = _survey.folder(project)
    _survey._atomic(d / "docs-branch.json", json.dumps({"project": project, "at": _survey.now_iso(), "branch": branch, "url": url,
                                                          "files": [f.get("path") for f in (dr or {}).get("files", []) if isinstance(f, dict)]}, indent=2) + "\n")
    try:
        _draft_path(project).unlink()
    except OSError:
        pass


def main(argv):
    a = list(argv)
    try:
        if a[:1] == ["wanted"] and len(a) >= 2:
            ks = wanted(a[1], _keys(a[2:]))
            print("\n".join(ks))
            return 0 if ks else 4
        if a[:1] == ["facts"] and len(a) == 2:
            sys.stdout.write(facts(a[1]))
            return 0
        if a[:1] == ["parse"] and len(a) >= 2:
            print(json.dumps(parse(a[1], sys.stdin.read(400000), _keys(a[2:]))))
            return 0
        if a[:1] == ["save"] and len(a) >= 2:
            save(a[1], json.loads(sys.stdin.read(400000)), _keys(a[2:]))
            return 0
        if a[:1] == ["show"] and len(a) >= 2:
            for f in _files(a[1], _keys(a[2:])):
                print(f"  {f['path']}  ({len(f['content'])} characters)\n")
                print("\n".join("    " + ln for ln in f["content"].splitlines()))
                print()
            return 0
        if a[:1] == ["paths"] and len(a) >= 2:
            print("\n".join(f["path"] for f in _files(a[1], _keys(a[2:]))))
            return 0
        if a[:1] == ["write"] and len(a) >= 3:
            print("\n".join(write(a[1], a[2], _keys(a[3:]))))
            return 0
        if a[:1] == ["record"] and len(a) in (3, 4):
            record(a[1], a[2], a[3] if len(a) == 4 else "")
            return 0
    except DocsError as e:
        print(f"docs: {e}", file=sys.stderr)
        return e.code
    except FileExistsError as e:
        print(f"docs: {Path(e.filename).name} exists already, so it was not written over", file=sys.stderr)
        return 5
    except ValueError as e:
        print(f"docs: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        from integrations import common as _common
        print("docs: " + _common.why_not_saved(e), file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
