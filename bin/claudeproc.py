"""One long-lived `claude` process for the deep brain, so a turn does not pay for starting it again.

The command is started once with stream-json input and output and talks only: every tool is off, nothing is saved, the
transcript never appears on the command line (each turn is one JSON line on stdin), and the process has a hard dollar cap
for its whole life. The answer is read as it is written, so the first sentence is available while the rest is still being
generated. The process is started again on any error, when the settings change, after it has been idle, after a few turns
(so its context cannot grow), when a conversation starts over, and when something that was shared (agenda, notes) is no
longer shared. Standard library only; no import from dashboard.py, so it is tested with a stand-in command.
"""
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time

IDLE_SECONDS = 600          # a process nobody has used for ten minutes is stopped
MAX_PROC_TURNS = 6          # and replaced after this many turns
TURN_TIMEOUT = 45           # seconds for one reply
LOCK_WAIT = 2               # seconds a second reply waits for the first before it is refused as busy
START_TIMEOUT = 20          # seconds for the first sign of life from a process that was just started
MAX_REPLY_CHARS = 2500      # a reply longer than this is cut off (the persona asks for a few sentences)
THINKING_ENV = {"MAX_THINKING_TOKENS": "0"}     # a voice answer does not need a thinking pass before the first word


# What the process is given of the dashboard's environment: what claude needs to run and to sign in, nothing else (the same idea as _qd_claude_env in bin/lib.sh).
_ENV_KEEP = ("HOME", "PATH", "TMPDIR", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TZ", "CLAUDE_CONFIG_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
             "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "CLAUDE_BIN")
_ENV_PREFIX = ("LC_", "ANTHROPIC_", "CLAUDE_CODE_")
_ENV_CLOUD = ("AWS_", "GOOGLE_", "CLOUD_ML_REGION", "VERTEX_", "GCLOUD_")


def clean_env(environ=None):
    """The environment for a claude process the dashboard starts: no GH_TOKEN, no QUARTERDECK_*, no tokens from the owner's env file, no cloud keys unless a
    cloud provider is the one in use. CLAUDE_CODE_SUBPROCESS_ENV_SCRUB keeps the process's own children from inheriting even this."""
    environ = os.environ if environ is None else environ
    cloud = any(environ.get(k) for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"))
    out = {}
    for k, v in environ.items():
        if k in _ENV_KEEP or k.startswith(_ENV_PREFIX) or (cloud and k.startswith(_ENV_CLOUD)):
            out[k] = v
    out["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
    return out


class Busy(Exception):
    """Another reply is still being written."""


class Failed(Exception):
    """The turn did not produce an answer. The message is a short reason the page may show."""


class StartFailed(Failed):
    """The process could not be started or never spoke: the caller may use the one-shot path instead."""


def _num(x):
    try:
        v = float(x)
        return v if v == v and v >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def user_line(text):
    """One JSON line for stdin. json.dumps escapes newlines, so whatever the text holds it stays one line and is data."""
    return json.dumps({"type": "user", "message": {"role": "user", "content": str(text)}}) + "\n"


def delta_text(ev):
    """The text of a streamed delta event, or "" (thinking and everything else is ignored)."""
    if not isinstance(ev, dict) or ev.get("type") != "stream_event":
        return ""
    e = ev.get("event")
    d = e.get("delta") if isinstance(e, dict) and e.get("type") == "content_block_delta" else None
    return d["text"] if isinstance(d, dict) and d.get("type") == "text_delta" and isinstance(d.get("text"), str) else ""


class Session:
    def __init__(self, popen=subprocess.Popen, now=time.monotonic):
        self.popen, self.now = popen, now
        self.lock = threading.Lock()
        self.proc = self.q = self.work = None
        self.sig = None
        self._reset_counters()

    def _reset_counters(self):
        self.budget = 0.0           # the --max-budget-usd this process was started with
        self.total = 0.0            # total_cost_usd it last reported (cumulative for the process)
        self.turns = self.convo = 0     # turns served, and how many were real conversation (not the warm-up)
        self.inc = frozenset()      # what was shared with it: "agenda", "notes"
        self.used = self.now()

    # ---- the process --------------------------------------------------------------
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def kill(self):
        proc, work = self.proc, self.work
        self.proc = self.q = self.work = None
        self.sig = None
        self._reset_counters()
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
            for f in (proc.stdin, proc.stdout):
                try:
                    f.close()
                except (OSError, ValueError, AttributeError):
                    pass
            try:
                proc.wait(timeout=2)
            except (subprocess.SubprocessError, OSError):
                pass
        if work:
            shutil.rmtree(work, ignore_errors=True)

    def reap(self, idle=IDLE_SECONDS):
        """Stop a process that has been idle. Never waits for a reply in progress."""
        if self.proc is not None and self.lock.acquire(blocking=False):
            try:
                if self.proc is not None and (not self.alive() or self.now() - self.used > idle):
                    self.kill()
            finally:
                self.lock.release()

    def _spawn(self, argv, env):
        self.work = tempfile.mkdtemp(prefix="quarterdeck-helm-")        # an empty folder: it can see nothing of the project
        try:
            proc = self.popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
                              cwd=self.work, env={**clean_env(), **THINKING_ENV, **(env or {})})
        except OSError as e:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None
            raise StartFailed("the claude command could not be started") from e
        q = queue.Queue()

        def pump():
            try:
                for line in proc.stdout:
                    q.put(line)
            except (OSError, ValueError):
                pass
            q.put(None)

        threading.Thread(target=pump, daemon=True).start()
        self.proc, self.q = proc, q

    def _prepare(self, argv, env, sig, budget, allow, fresh, inc, warm):
        if self.proc is not None:
            if not self.alive() or self.now() - self.used > IDLE_SECONDS or sig != self.sig or self.turns >= MAX_PROC_TURNS:
                self.kill()
            elif not warm and ((fresh and self.convo > 0) or (self.inc - inc)):
                self.kill()                                          # a conversation started over, or sharing was withdrawn: nothing may carry over
            elif self.budget - self.total < allow:
                self.kill()                                          # not enough of this process's own cap left for another turn
        if self.proc is None:
            self._spawn(argv, env)
            self.sig, self.budget = sig, float(budget)

    # ---- one turn -----------------------------------------------------------------
    def turn(self, message, *, argv, sig, budget, allow, fresh, inc, book, env=None, warm=False):
        """Generator of ("s", text delta) and finally ("done", cost). Raises Busy or Failed (StartFailed when it never spoke).
        `book(cost, result, stopped)` is called exactly once for every turn that reached the model, failed or not, so the
        spend ledger and the daily cap see it. `allow` is the most this turn may cost; `budget` the process's own cap."""
        if not self.lock.acquire(timeout=LOCK_WAIT):
            raise Busy("another reply is still being written")
        finished = False
        st = {"heard": False, "booked": False}
        real_book = book

        def book(cost, result, stopped):
            st["booked"] = True
            real_book(cost, result, stopped)
        try:
            self._prepare(argv, env, sig, budget, allow, fresh, frozenset(inc), warm)
            q, proc = self.q, self.proc
            try:
                proc.stdin.write(user_line(message))
                proc.stdin.flush()
            except (OSError, ValueError) as e:
                raise StartFailed("the claude command stopped before it was asked") from e
            began, deadline, chars, spoke, heard = self.now(), self.now() + TURN_TIMEOUT, 0, False, False
            while True:
                left = deadline - self.now()
                if left <= 0 or (not heard and self.now() - began > START_TIMEOUT):
                    book(allow, {}, "timeout")                       # killed mid-turn: count the most it could have cost, so the daily cap still bites
                    raise (Failed("it took too long") if heard else StartFailed("it did not answer in time"))
                try:
                    line = q.get(timeout=min(left, 0.5))
                except queue.Empty:
                    continue
                if line is None:
                    if heard:
                        book(0.0, {}, "error")
                    raise (Failed("the call failed") if heard else StartFailed("the claude command stopped at once"))
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") in ("system", "stream_event", "assistant", "result"):
                    heard = st["heard"] = True                       # a sign that this turn is being worked on, not just the start-up chatter
                text = delta_text(ev)
                if text:
                    chars += len(text)
                    spoke = True
                    yield ("s", text)
                    if chars > MAX_REPLY_CHARS:
                        book(allow, {}, "long")                      # it ran on: stop it, and count the most the turn could have cost
                        yield ("done", float(allow))
                        return
                    continue
                if isinstance(ev, dict) and ev.get("type") == "result":
                    total = _num(ev.get("total_cost_usd"))
                    cost = total - self.total if total >= self.total else total      # cumulative for the process; a smaller number means it began again
                    self.total = total
                    stopped = "cap" if ev.get("subtype") == "error_max_budget_usd" else "error" if ev.get("is_error") or ev.get("subtype") != "success" else None
                    book(cost, ev, stopped)
                    if stopped == "cap":
                        raise Failed("it hit its limit for one turn")
                    if stopped:
                        raise Failed("the call failed")
                    if not spoke:
                        reply = ev.get("result")
                        if not isinstance(reply, str) or not reply.strip():
                            raise Failed("it returned nothing")
                        yield ("s", reply)
                    self.turns += 1
                    self.convo += 0 if warm else 1
                    self.inc = self.inc | frozenset(inc)
                    self.used = self.now()
                    finished = True
                    if cost > allow + 1e-9:                          # it cost more than a turn may: this process does not get another
                        finished = False
                    yield ("done", cost)
                    return
        finally:
            if not finished:
                if st["heard"] and not st["booked"]:
                    real_book(allow, {}, "aborted")                  # abandoned mid turn (the page left): it may have been billed, so count the most it could have cost
                    st["booked"] = True
                self.kill()                                          # any failure, a stopped listener, an odd turn: the next one starts clean
            self.lock.release()
