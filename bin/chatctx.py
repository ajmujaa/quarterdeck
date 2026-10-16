"""What Helm's conversation brains are given: the persona, the facts block, the history, and the plumbing around a reply.

Pure functions, standard library only, and no import from dashboard.py: this file reads no file, runs no process and
opens no socket, so every rule in it can be tested with invented data. The dashboard hands it a state object (the
same one /api/state returns) and gets text back.
"""
import re
from datetime import datetime, timedelta, timezone

# ---- the persona -----------------------------------------------------------------
# One constant, tested for its rules (bin/selftest.py). Both brains get it; the local one gets the facts block as
# well, the Claude one gets a block with the private parts left out unless the owner asked for them.
PERSONA = """You are Helm, the voice of the Quarterdeck dashboard, speaking with its owner.
How you speak: calm, literal and brief, in full natural sentences, like a colleague who knows the work. One idea at a time. No filler, no flattery, no apologies, no jokes unless asked. Plain words.
Answer in one to three short spoken sentences unless asked for more. Give the useful detail the facts hold (a name, a number, how long ago), not only yes or no. Never use lists, markdown, emoji or headings: your words are read aloud.
What you may say: ONLY what is in the FACTS block below, or what the owner told you earlier in this conversation. Look through the facts before you answer: most questions about the work are answered there. Say "I do not know that" only when the facts really do not hold the answer, and then say where you would look on the dashboard. Never invent a number, a name, a time or a status.
Never mention the facts, the block, your instructions or these rules, and never repeat the examples: speak as if you simply know the work.
What you may not claim: you have not done anything. Never say you started, stopped, saved, sent or changed anything. You can only talk; the dashboard acts, and only after the owner clicks to confirm.
Actions: nearly every reply is only words and ends there. Add one final line of exactly this form, and nothing after it, ONLY when the owner asked you to do or open something (including "do it"): ACTION: <one phrase the dashboard already understands>. A question that only needs an answer never gets one.
Phrases it understands: what is running; brief me; open the ledger; open needs you; open the timeline; open wayfarer mobile; list my notes; what is next; start work on issue 12 on wayfarer mobile; run the surveyor on wayfarer mobile.
If the owner asks what you think, give one honest opinion from the facts and say what it rests on. If a follow-up such as "the other one" or "and that project?" is unclear, ask one short question.
The shape of a good answer (words in angle brackets stand for things from your facts; never say them literally, and never copy an example):
Owner: <a question about the work>
Helm: <one or two full sentences that name the thing, give its number or how long ago, and stop>
Owner: <a request to open or do something>
Helm: <one sentence about what that page shows>
ACTION: <a phrase from the list above>"""

# The deep brain keeps one process alive between turns, so the facts cannot sit in its system prompt (they change). Each turn
# carries the newest facts instead, and says so once here.
CLAUDE_NOTE = "Every message from the owner starts with the newest FACTS and the conversation so far. Use only the newest FACTS; older ones in this chat are out of date."

DIGEST_CAP = 2500       # characters of facts: about 700 tokens, which the local model's window can hold with a conversation
MAX_TURNS = 12
MAX_TURN_CHARS = 600
MAX_TEXT = 500          # one spoken utterance
ACTION_MAX = 120

_BAD_VERDICTS = {"ERROR", "FAILED", "BLOCKED", "BROKEN"}


def _s(x, n):
    return " ".join(str(x if x is not None else "").split())[:n]


def _ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _age(at, now):
    t = _ts(at)
    if t is None:
        return ""
    m = int((now - t).total_seconds() // 60)
    if m < 1:
        return "just now"
    return f"{m} min ago" if m < 90 else f"{round(m / 60)} h ago" if m < 2880 else f"{round(m / 1440)} days ago"


def _list(x):
    return x if isinstance(x, list) else []


def _dict(x):
    return x if isinstance(x, dict) else {}


# ---- the facts block --------------------------------------------------------------
def chat_digest(state, opts=None):
    """Plain facts about the work, newest and most important first, at most DIGEST_CAP characters.

    opts: {"agenda": bool, "notes": bool, "prs": [{project, number, title, checks}], "now": datetime}.
    Calendar and reminder titles appear ONLY with opts["agenda"], note text ONLY with opts["notes"]. Mail and Slack
    are never more than a count. The cloud brain is built with both flags off unless the owner said otherwise."""
    opts, state = _dict(opts), _dict(state)
    now = opts.get("now") or datetime.now(timezone.utc)
    sections = []                   # (priority, [lines]): lower number = kept first

    inbox = [x for x in _list(state.get("inbox")) if isinstance(x, dict) and not x.get("acknowledged")]
    if inbox:
        sections.append((0, ["Needs the owner:"] + [f"- {_s(x.get('project') or x.get('source'), 30)} {_s(x.get('duty'), 20)}: {_s(x.get('text'), 140)}" for x in inbox[:5]]))
    else:
        sections.append((0, ["Needs the owner: nothing."]))

    agents = [a for a in _list(state.get("agents")) if isinstance(a, dict)]
    running = [a for a in agents if a.get("status") == "running"]
    busy = {a.get("project") for a in running}
    lines = ["Working now: " + ("; ".join(f"{_s(a.get('duty'), 20)} on {_s(a.get('project'), 30)} ({_s(a.get('what'), 70)}, {_age(a.get('since'), now).replace(' ago', '')})" for a in running[:6]) if running else "nothing.")]
    projects = [p for p in _list(state.get("projects")) if isinstance(p, dict)]
    if projects:
        lines.append("Projects: " + ", ".join(f"{_s(p.get('name'), 30)}{' (busy)' if p.get('name') in busy else ''}" for p in projects[:12]))
    sections.append((1, lines))

    runs = [r for r in _list(state.get("runs")) if isinstance(r, dict)][:8]
    if runs:
        sections.append((2, ["Last runs, newest first:"] + [f"- {_s(r.get('project'), 30)} {_s(r.get('duty'), 20)} {_s(r.get('verdict'), 20)}"
                                                            f"{' ' + _age(r.get('at'), now) if r.get('at') else ''}{': ' + _s(r.get('detail'), 90) if r.get('detail') and r.get('verdict') in _BAD_VERDICTS else ''}" for r in runs]))

    prs = [p for p in _list(opts.get("prs")) if isinstance(p, dict)][:8]
    if prs:
        def checks(p):
            c = _dict(p.get("checks"))
            return f"{c.get('pass', 0)} passing, {c.get('fail', 0)} failing, {c.get('pending', 0)} running"
        sections.append((3, ["Open pull requests:"] + [f"- {_s(p.get('project'), 30)} #{_s(p.get('number'), 8)} {_s(p.get('title'), 70)}: {checks(p)}" for p in prs]))

    notes = [_s(n, 300) for n in _list(state.get("chat_notes")) if isinstance(n, str)][:3]       # a line or two an add-on wants said about what it watches
    if notes:
        sections.append((4, notes))

    sp = _dict(state.get("spend"))
    if sp:
        today, budget = float(sp.get("today") or 0), float(sp.get("daily_budget") or 0)
        sections.append((5, [f"Spend today: ${today:.2f}" + (f" of a ${budget:.2f} daily budget" if budget else ", no daily budget set")]))

    counts = []
    for c in _list(state.get("connectors")):
        if isinstance(c, dict) and c.get("name") in ("gmail", "slack") and c.get("connected") and isinstance(c.get("unread"), int):
            counts.append(f"{c['unread']} {c['name']}")
    caps = _dict(state.get("captures"))
    if isinstance(caps.get("open"), int):
        counts.append(f"{caps['open']} open notes")
    if counts:
        sections.append((6, ["Waiting (counts only): " + ", ".join(counts)]))

    if opts.get("agenda"):
        ag = []
        for c in _list(state.get("connectors")):
            if isinstance(c, dict) and c.get("name") in ("calendar", "reminders") and c.get("connected"):
                ag += [f"- {c['name']}: {_s(i.get('title'), 70)} ({_s(i.get('at'), 16)})" for i in _list(c.get("items"))[:6] if isinstance(i, dict)]
        if ag:
            sections.append((7, ["Agenda and reminders (shared by the owner):"] + ag))
    if opts.get("notes"):
        nt = [f"- {_s(n.get('text'), 110)}" for n in _list(caps.get("items"))[:6] if isinstance(n, dict)]
        if nt:
            sections.append((8, ["Open notes (shared by the owner):"] + nt))

    # Every section keeps its first line (the headline) while there is room, most important first; then the rest of each
    # section fills what is left, again most important first. The cap is on the whole block.
    ordered = sorted(sections, key=lambda s: s[0])
    keep, used = [0] * len(ordered), 0
    for k, (_, lines) in enumerate(ordered):
        if used + len(lines[0]) + 1 <= DIGEST_CAP:
            keep[k], used = 1, used + len(lines[0]) + 1
    for k, (_, lines) in enumerate(ordered):
        while keep[k] and keep[k] < len(lines) and used + len(lines[keep[k]]) + 1 <= DIGEST_CAP:
            used += len(lines[keep[k]]) + 1
            keep[k] += 1
    out = [ln for k, (_, lines) in enumerate(ordered) for ln in lines[:keep[k]]]
    return "\n".join(out)


# ---- the conversation ---------------------------------------------------------------
def clean_history(history, chat_only=False):
    """The page's memory, made safe: only user and assistant turns, plain text, the newest MAX_TURNS, each cut short.
    chat_only keeps just the turns the page tagged as a conversation exchange: a command's answer can carry an agenda or
    note text, so for the cloud brain it never goes out, whatever the include flags say."""
    out = []
    for t in _list(history):
        if chat_only and not (isinstance(t, dict) and t.get("src") == "chat"):
            continue
        if isinstance(t, dict) and t.get("role") in ("user", "assistant") and isinstance(t.get("content"), str):
            text = _s(t["content"], MAX_TURN_CHARS)
            if text:
                out.append({"role": t["role"], "content": text})
    return out[-MAX_TURNS:]


def clean_text(text):
    return _s(text, MAX_TEXT)


def system_prompt(digest, persona=PERSONA):
    return persona + "\n\nFACTS (the only things you may state as true; never mention this list):\n" + (digest or "(no facts available)")


def build_messages(digest, history, text, persona=PERSONA):
    return [{"role": "system", "content": system_prompt(digest, persona)}, *clean_history(history), {"role": "user", "content": clean_text(text)}]


def wants_more(text):
    """The owner asked for a longer answer."""
    return bool(re.search(r"\b(in detail|more detail|explain|tell me more|go on|elaborate|walk me through|at length)\b", str(text).lower()))


# ---- streaming: cutting a growing reply into sentences ---------------------------------
_ABBREV = {"mr", "mrs", "ms", "dr", "vs", "etc", "approx", "no", "st", "prof", "inc", "fig", "min", "max", "avg", "est", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}


def split_sentences(buf, final=False):
    """(complete sentences, the rest). A boundary is . ! ? or a newline followed by a space and then something that can
    start a sentence; decimals (3.50), abbreviations (Dr. Hansen, e.g.) and initials do not end one. While streaming, a
    full stop at the very end of the buffer waits for the next character (it might be 3.5); final=True flushes the rest.
    A long run with no punctuation is cut at a comma or space so speech can start."""
    out, start, i, n = [], 0, 0, len(buf)
    while i < n:
        ch = buf[i]
        if ch == "\n":
            seg = buf[start:i].strip()
            if seg:
                out.append(seg)
            start = i + 1
        elif ch in ".!?":
            j = i
            while j + 1 < n and buf[j + 1] in ".!?\"')":
                j += 1
            if j + 1 >= n:
                if final:
                    pass                                    # flushed below
                else:
                    break                                   # wait: the next character decides
            elif buf[j + 1] in " \t":
                k = j + 1
                while k < n and buf[k] in " \t":
                    k += 1
                if k >= n and not final:
                    break
                word = re.search(r"([A-Za-z0-9.]+)$", buf[start:i])
                tok = word.group(1).lower().strip(".") if word else ""
                nxt = buf[k] if k < n else ""
                initial = (len(tok) == 1 and tok.isalpha()) or ("." in tok and all(len(x) == 1 and x.isalpha() for x in tok.split(".")))     # "J." and "e.g." 
                numbered = ch == "." and tok.isdigit() and len(tok) <= 2 and buf[start:i].strip() == tok     # "1. first": a list marker
                boundary = ch != "." or not (tok in _ABBREV or initial or (nxt and nxt.islower()) or (tok.isdigit() and nxt.islower()))
                if boundary and not numbered:
                    out.append(buf[start:j + 1].strip())
                    start = k
                i = j
        i += 1
    rest = buf[start:]
    if final:
        if rest.strip():
            out.append(rest.strip())
        return out, ""
    if len(rest) > 220:                                     # no punctuation for a long while: cut at the last comma or space
        cut = max(rest.rfind(", ", 0, 200), rest.rfind(" ", 0, 200))
        if cut > 60:
            out.append(rest[:cut + 1].strip().rstrip(","))
            rest = rest[cut + 1:]
    return [s for s in out if s], rest


def parse_action(sentence):
    """("say", text) or ("action", phrase). A line that starts ACTION: is never spoken; it is a phrase the PAGE runs
    through its normal command pipeline (parse, vet, confirm click). The model's text reaches no endpoint."""
    m = re.match(r"^\s*ACTION\s*:\s*(.+?)\s*$", str(sentence), re.I | re.S)
    if m:
        phrase = " ".join(m.group(1).split())[:ACTION_MAX].strip(" .\"'`")
        return ("action", phrase) if phrase else ("action", "")
    return ("say", " ".join(str(sentence).split()))


def strip_for_speech(text):
    """Things a voice should not read: markdown marks, bullets, emphasis."""
    t = re.sub(r"[`*_#]+", "", str(text))
    t = re.sub(r"^\s*>+\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return " ".join(t.split())


# ---- keeping the model's own wording out of what is spoken -----------------------------------
_LEAD = re.compile(r"^\s*(?:according to|based on|from|per|looking at|going by)\s+(?:the|my)\s+(?:facts(?: block)?|information i have|data i have|dashboard facts|list)\s*[,:]?\s*", re.I)
_LEAK = re.compile(r"\b(?:facts block|the facts block|system prompt|my instructions|my persona|the persona|as instructed|these rules|the rules above|FACTS \()", re.I)


def scrub_prompt_wording(sentence):
    """A model sometimes repeats the wording of its instructions ("according to the facts, ..."). Take a leading phrase of
    that kind off the front, and drop a sentence that talks about its own instructions. Returns "" for a dropped sentence."""
    t = _LEAD.sub("", str(sentence), count=1).strip()
    if _LEAK.search(t):
        return ""
    return (t[:1].upper() + t[1:]) if t and t != str(sentence).strip() else t


_DO = re.compile(r"\b(open|show|go to|take me|bring up|start|begin|run|kick off|restart|pause|resume|stop|cancel|make|turn|plan|draft|remember|note|jot|capture|dismiss|acknowledge|merge|do it|do that|go ahead|yes please|brief me|list|read|find|search|analy[sz]e|mark)\b", re.I)


def action_wanted(text):
    """May a reply carry an ACTION line? Only when the owner's own words ask for something to be done or opened. A plain
    question gets an answer, never a suggested command (the page would otherwise offer one the owner did not want)."""
    return bool(_DO.search(str(text)))


# ---- the deep brain: Claude, through the claude CLI, talking only ---------------------------
CLAUDE_DEFAULT_MODEL = "claude-haiku-4-5"
CLAUDE_DEFAULT_TURN = 0.05      # dollars per turn, passed as --max-budget-usd
CLAUDE_DEFAULT_DAILY = 1.00     # dollars per day, counted from the spend ledger (duty "helm-chat")
CLAUDE_TIMEOUT = 45
CLAUDE_TOOLS_OFF = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task"     # belt and braces beside --tools ""
_MODEL = re.compile(r"[A-Za-z0-9._-]{1,60}")


def claude_settings(env):
    """The settings from config/quarterdeck.env, made safe: off unless exactly 'on'; a model name that is only name
    characters; a per-turn and a daily limit that are positive numbers."""
    def num(key, default, floor):
        try:
            v = float(env(key, "") or default)
            return v if v >= floor else default
        except (TypeError, ValueError):
            return default
    model = str(env("QUARTERDECK_HELM_CLAUDE_MODEL", "") or CLAUDE_DEFAULT_MODEL).strip()
    return {"on": str(env("QUARTERDECK_HELM_CLAUDE", "off")).strip().lower() == "on", "model": model if _MODEL.fullmatch(model) else CLAUDE_DEFAULT_MODEL,
            "turn": num("QUARTERDECK_HELM_CLAUDE_TURN_BUDGET", CLAUDE_DEFAULT_TURN, 0.001), "daily": num("QUARTERDECK_HELM_CLAUDE_DAILY", CLAUDE_DEFAULT_DAILY, 0.0)}


def claude_prompt(history, text):
    """The whole transcript as ONE argument. It always starts with a fixed word, so nothing the owner or the model said can
    begin with a dash and be read as a flag."""
    lines = ["Conversation so far:"]
    for t in clean_history(history, chat_only=True):
        lines.append(("Owner: " if t["role"] == "user" else "Helm: ") + t["content"])
    lines.append("Owner: " + clean_text(text))
    lines.append("Helm:")
    return "\n".join(lines)


def claude_argv(claude_bin, prompt, system, model, budget):
    """The command line for one deep-brain turn, as a list (no shell is ever involved): every tool switched off so it can only
    talk, no slash commands, no MCP servers, nothing saved, a hard dollar cap for the turn, JSON back."""
    return [str(claude_bin), "-p", str(prompt), "--system-prompt", str(system), "--model", str(model), "--max-budget-usd", f"{float(budget):.4f}",
            "--tools", "", "--disallowedTools", CLAUDE_TOOLS_OFF, "--permission-mode", "dontAsk", "--disable-slash-commands",
            "--strict-mcp-config", "--no-session-persistence", "--output-format", "json"]


def claude_stream_argv(claude_bin, system, model, budget):
    """The command line for the long-lived deep-brain process, as a list (no shell). There is no prompt on it: each turn is a JSON
    line on stdin, so nothing the owner or the model says can ever become a flag. Every tool off, nothing saved, no slash commands,
    no MCP, and a hard dollar cap for the whole life of the process."""
    return [str(claude_bin), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--system-prompt", str(system), "--model", str(model), "--max-budget-usd", f"{float(budget):.4f}",
            "--tools", "", "--disallowedTools", CLAUDE_TOOLS_OFF, "--permission-mode", "dontAsk", "--disable-slash-commands",
            "--strict-mcp-config", "--no-session-persistence"]


def claude_system():
    return PERSONA + "\n\n" + CLAUDE_NOTE


def claude_message(digest, history, text):
    """One turn for the long-lived process: the newest facts, the conversation tagged as chat (never a command's answer), the question."""
    lines = ["FACTS now (state only these as true; never mention this list):", digest or "(no facts available)", "", "Conversation so far:"]
    for t in clean_history(history, chat_only=True):
        lines.append(("Owner: " if t["role"] == "user" else "Helm: ") + t["content"])
    lines += ["Owner: " + clean_text(text), "Helm:"]
    return "\n".join(lines)


def process_budget(daily_left, turn, turns=6):
    """The hard cap a new process starts with: what `turns` turns may cost, but never more than is left of the day."""
    return round(max(0.0, min(float(daily_left), float(turn) * turns)), 4)


def spent_today(rows, since_iso, duty="helm-chat"):
    """Dollars the deep brain has cost since `since_iso` (local midnight in UTC), from the spend ledger."""
    total = 0.0
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("duty") == duty and str(r.get("at") or "") >= since_iso:
            try:
                total += float(r.get("cost") or 0)
            except (TypeError, ValueError):
                pass
    return total


def turn_allowance(spent, daily, turn):
    """What this turn may cost: the per-turn limit, or what is left of the day if that is less; 0 means refuse."""
    left = daily - spent
    return 0.0 if left < 0.005 else round(min(turn, left), 4)
