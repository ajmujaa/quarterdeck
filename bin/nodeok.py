"""Node is optional and only runs the page-logic tests. Those tests need Node 20 or newer; an older one is treated as absent."""
import shutil
import subprocess

MIN_MAJOR = 20


def path():
    """The node executable if it is version 20 or newer, otherwise None."""
    exe = shutil.which("node")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout.strip().lstrip("v")
        return exe if int(out.split(".")[0]) >= MIN_MAJOR else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
