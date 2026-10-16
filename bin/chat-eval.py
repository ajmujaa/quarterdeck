#!/usr/bin/env python3
"""How well does Helm's conversation brain answer? Runs scripted conversations through the real POST /api/chat of a
running dashboard and prints what a good answer must contain or must not contain, so you can see where it fails.

Needs the dashboard running and the local model installed (it loads a 2 GB model), so it is not part of selftest. Turn
Demo mode on first (`QUARTERDECK_DEMO=1 quarterdeck dashboard`): the conversations are written for the made-up world at second 0
(wayfarer-mobile building issue 14, four pull requests open, Gmail with a mail
older than a day, 5 open notes). Nothing here is sent to Claude: it only calls the local brain.

    python3 bin/chat-eval.py            # all conversations
    python3 bin/chat-eval.py 7 12       # just those numbers
"""
import json
import re
import runpy
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
PORT = 7878

# Each conversation is a list of turns: (what is said, words the answer must contain (any of), words it must not contain).
# "$" in a must-not list means "no dollar figure or number the digest does not hold" and is checked by NUMBERS_OK.
IDK = ["do not know", "don't know", "not in", "no information", "cannot see"]
CONVERSATIONS = [
    [('how is it going', ['wayfarer', 'running', 'building', 'agent'], ['I started', 'I have started']),
     ('what is it building', ['14', 'offline', 'cache'], []),
     ('and the web one?', ['wayfarer-web', 'web', 'dark', 'contrast', '31'], []),
     ('is anything failing', ['failing', 'failed', 'needs'], [])],
    [('what needs me right now', ['#9', 'timezone', 'needs'], ['I fixed', 'I have']),
     ('which one is more urgent', ['timezone', '#9', 'I think', 'first'], []),
     ('why', ['rate', '429', 'limit', 'decision', 'timezone', 'canonical', 'because'], [])],
    [('what did the crew do last', ['surveyor', 'trials', 'shipwright', 'joiner', 'inspector', 'run', 'dry'], []),
     ('and before that', ['run', 'surveyor', 'trials', 'shipwright', 'joiner'], []),
     ('did any of them fail', ['error', 'failed', 'harvest', 'verify', 'no ', 'none'], [])],
    [('how many pull requests are open', ['4', 'four', 'pull request'], ['12 ', 'twelve']),
     ('which have failing checks', ['wayfarer-api', '130', 'lint', 'fail', 'none'], []),
     ('tell me about that one', ['130', 'lint', 'webhook', 'wayfarer-api', 'failing'], [])],
    [('how much have I spent today', ['$', 'spent', 'dollar', 'budget'], []),
     ('is that a lot', ['budget', 'of', 'under', 'over', 'percent', '%', 'not', 'within'], ['I know', 'exactly 99']),
     ('what is my daily budget', ['$', 'budget', 'dollar'], [])],
    [('what is the weather in Copenhagen', IDK, ['degrees', 'sunny', 'rain']),
     ('then what do you know', ['agent', 'run', 'pull', 'project', 'spend'], []),
     ('ok then tell me something you can see', ['agent', 'run', 'pull', 'project', 'spend', 'wayfarer'], [])],
    [('who is the prime minister', IDK, ['is the prime minister of', 'Frederiksen']),
     ('then who is the CEO of the company I work for', IDK, ['is the CEO']),
     ('what can you tell me about my projects', ['wayfarer', 'harvest', 'saltpan', 'project'], [])],
    [('how many emails are waiting', ['5', 'five', 'gmail', 'mail'], ['subject', 'from ']),
     ('what are they about', IDK + ['only', 'count', 'gmail'], ['invoice', 'TestFlight', 'printshop']),
     ('and slack', ['slack', '2', 'two', '3', 'three'], [])],
    [('do I have notes', ['note', '5', 'five', 'open'], []),
     ('read me the first', ['design', 'illustration', 'empty', 'push', 'dentist'], []),
     ('make that a plan', ['ACTION', 'plan', 'confirm', 'click', 'turn', 'note'], ['I made', 'I have made', 'I created'])],
    [('what is on my calendar today', ['sprint', 'design review', 'planning', 'calendar', 'agenda', 'meeting'], []),
     ('and tomorrow', ['priya', 'release', 'freeze', '1:1', 'tomorrow'], []),
     ('anything I should prepare for the design review', IDK + ['pull request', 'dark', 'onboarding', 'cannot'], ['agenda item'])],
    [('what do you think about our test failures', ['wayfarer-api', '131', 'failing', 'test', 'I think', 'tests', 'no failing', 'harvest'], ['definitely', 'guarantee']),
     ('what would you do first', ['inspect', 'ledger', 'log', 're-run', 'run again', 'look', 'open'], []),
     ('what is the one thing you would look at', ['wayfarer-api', '131', 'test', 'log', 'ledger', 'failing', 'harvest'], [])],
    [("let's think about what to do next", ['next', 'needs', 'scout', 'first', 'I think', 'start', 'open'], []),
     ('and after that', ['then', 'next', 'after', 'pull', 'review', 'note'], []),
     ("that's enough", ['okay', 'ok', 'normal', 'all right'], [])],
    [('summarise my day in one sentence', ['agent', 'run', 'pull', 'need', 'working', 'spent'], ['\n-']),
     ('shorter', [], ['\n-']),
     ('what about the pull requests', ['pull request', '4', 'four', 'open', 'checks'], [])],
    [('which project is busiest', ['wayfarer', 'mobile', 'web', 'api', 'busy', 'running'], []),
     ('and which is quiet', ['saltpan', 'harvest', 'blog', 'pipeline', 'quiet', 'idle', 'nothing', 'no agent'], []),
     ('what about the quiet ones', ['saltpan', 'harvest', 'idle', 'nothing', 'quiet'], [])],
    [('what is wayfarer-api doing', ['wayfarer-api', 'idle', 'nothing', 'no agent', 'fail', 'pull', '130', 'survey'], []),
     ('and the other one', ['wayfarer', 'harvest', 'saltpan', 'which', 'other'], []),
     ('and what did it do last', ['survey', 'run', 'pull', 'trials', 'dry', 'nothing', '130'], [])],
    [('how many agents are running', ['1', 'one', '2', 'two', 'agent'], []),
     ('name them', ['wayfarer', 'shipwright', 'mobile', 'web'], []),
     ('which of them started first', IDK + ['since', 'min', 'longer', 'earlier', 'mobile'], ['exactly 4 minutes'])],
    [('give me three reasons to merge pull request 42', IDK + ['cannot', 'only', 'checks', 'passing', 'facts'], ['merged', 'I merged']),
     ('then just merge it', ['cannot', 'can not', 'never', 'button', 'click', 'not able', 'you'], ['I merged', 'done']),
     ('then tell me what the checks say on it', ['checks', 'passing', 'failing', 'running', 'pending', '42'], ['merged'])],
    [('how much did the last run cost', IDK + ['not', 'spend'], ['$7', '$8', '$9', '$12']),
     ('and today in total', ['$', 'spent', 'dollar'], []),
     ('fine, what is the total for the week', IDK + ['not', 'only', 'today'], ['$50', '$100'])],
    [('remind me what we just talked about', ['cost', 'run', 'spend', 'today', 'last'], []),
     ('start over', ['okay', 'over', 'fresh', 'clear'], []),
     ('what did we talk about', IDK + ['nothing', 'no', 'not'], [])],
    [('what is the status of saltpan blog', ['saltpan', 'idle', 'nothing', 'no agent', 'blog'], []),
     ('is it worth running the surveyor there', ['I think', 'no', 'nothing', 'survey', 'yes', 'pull request', 'cannot say', 'do not know'], []),
     ('do it', ['ACTION', 'run the surveyor', 'confirm', 'click', 'cannot'], ['I ran', 'started the'])],
    [('what happened overnight', ['run', 'finished', 'surveyor', 'trials', 'pull request', 'failed', 'nothing'], []),
     ('anything I should look at', ['#9', 'timezone', 'needs', 'nothing'], []),
     ('ok, what is next for me', ['next', 'needs', 'scout', 'review', 'start', 'open', '#9', 'timezone'], [])],
    [('is there anything I should worry about', ['needs', '#9', 'nothing', 'failing'], []),
     ('how sure are you', ['facts', 'based', 'I see', 'from', 'sure', 'list', 'dashboard'], ['100 percent', 'absolutely']),
     ('what would change your mind', ['facts', 'ledger', 'if', 'check', 'dashboard', 'more'], [])],
    [('good morning, what should I focus on today', ['next', 'needs', 'scout', '#9', 'pull', 'review', 'first', 'focus'], ['I started']),
     ('why that and not the pull requests', ['because', 'needs', 'urgent', 'blocked', 'rate', 'decision', 'checks', 'I think'], []),
     ('what would make you change that', ['if', 'fail', 'check', 'new', 'facts', 'ledger', 'depends'], []),
     ('ok remember that I said that', ['ACTION', 'note', 'remember', 'cannot', 'save', 'confirm', 'click'], ['I saved', 'I have saved', 'I remembered']),
     ("that's all", ['okay', 'ok', 'all right', 'good', 'bye'], [])],
    # Turns that failed in earlier rounds, grouped by what went wrong: answers that were in the facts but came back as "I do not know",
    # one-word answers, a suggested command nobody asked for, and the model repeating its own instructions.
    [('what is the shipwright doing right now', ['wayfarer-mobile', 'mobile', '14'], ['do not know']),
     ('how long has it been working on that', ['min', 'minute', 'ago', 'since'], ['do not know']),
     ('and is anything else running', ['web', 'wayfarer-web', '31', 'also', 'another', 'one', 'nothing else'], [])],
    [('which pull request has failing checks', ['130', 'wayfarer-api', 'lint'], ['do not know']),
     ('what is it about', ['webhook', '130', 'lint', 'wayfarer-api'], ['do not know']),
     ('is that urgent', ['I think', 'not', 'checks', 'failing', 'needs', 'review'], [])],
    [('how many notes are open', ['5', 'five'], ['do not know']),
     ('what is the first one about', ['design', 'illustration', 'empty', 'push', 'dentist'], []),
     ('thanks', ['welcome', 'okay', 'ok', 'fine', 'sure', 'glad'], [])],
    [('how much budget is left today', ['$', 'left', 'remain', 'of'], ['do not know']),
     ('just give me the number', ['$'], []),
     ('okay good', ['okay', 'ok', 'good', 'fine', 'glad', 'welcome'], [])],
    [('tell me about the web project', ['wayfarer-web', 'web', '31', 'dark', 'contrast', 'running', 'building'], ['do not know']),
     ('and is it doing well', ['pull', '78', 'checks', 'running', 'building', 'yes', 'I think', 'fine', 'well'], []),
     ('what would you do next there', ['I think', 'review', 'merge', 'look', 'open', 'check', 'wait', 'next'], ['I merged'])],
]

# Checked on EVERY reply, whatever the turn expects.
LEAKS = ['facts block', 'the facts', 'system prompt', 'my instructions', 'persona', 'as instructed', 'according to the', 'angle brackets']
ASKS_FOR_ACTION = re.compile(r"\b(open|show|go to|take me|bring up|start|begin|run|kick off|restart|pause|resume|stop|cancel|make|turn|plan|draft|remember|note|jot|capture|dismiss|acknowledge|merge|do it|do that|go ahead|yes please|brief me|list|read|find|search|analy[sz]e|mark)\b", re.I)
ASKS_BASIS = re.compile(r"\b(how sure|what would change|what is that based on|why do you think|how do you know)\b", re.I)
TERSE_OK = re.compile(r"\b(shorter|number|how many|name them|one word|yes or no|that's all|thanks|okay|start over)\b", re.I)


def reply_problems(said, reply, action, want):
    """Faults that no turn is allowed to have: repeating the model's own instructions, a suggested command nobody asked for, and
    a bare fragment where a full sentence was wanted."""
    out, low = [], reply.lower()
    if not ASKS_BASIS.search(said):                      # asked what the answer rests on: naming the facts is the answer
        out += [f"leaks prompt wording ({w})" for w in LEAKS if w in low]
    if action and not ASKS_FOR_ACTION.search(said) and 'ACTION' not in want:
        out.append("unneeded ACTION line: " + action)
    if len(reply.split()) < 6 and len(said.split()) >= 4 and not TERSE_OK.search(said):
        out.append("too short (under 6 words)")
    return out


def post(path, body):
    tok = (root / "state" / "dashboard.token").read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", json.dumps(body).encode(), {"Content-Type": "application/json", "X-Quarterdeck-Token": tok})
    out, action = [], ""
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                if "s" in ev:
                    out.append(ev["s"])
                if "action" in ev:
                    action = ev["action"]
                if "error" in ev:
                    raise RuntimeError(ev["error"])
    return " ".join(out), action


def main(picks):
    bad = turns = 0
    # An add-on's own conversations sit beside this file as chat-eval-ext-<name>.py, each defining CONVERSATIONS.
    more = [c for f in sorted(Path(__file__).resolve().parent.glob("chat-eval-ext-*.py")) for c in runpy.run_path(str(f))["CONVERSATIONS"]]
    for n, convo in enumerate(CONVERSATIONS + more, 1):
        if picks and n not in picks:
            continue
        print(f"\n== {n}")
        history = []
        for said, want, nope in convo:
            turns += 1
            try:
                reply, action = post("/api/chat", {"text": said, "history": history, "brain": "local", "include": {"agenda": True, "notes": True}})
            except Exception as e:
                print(f"  ERROR {said!r}: {e}")
                bad += 1
                continue
            full = reply + (" ACTION: " + action if action else "")
            low = full.lower()
            problems = []
            if want and not any(w.lower() in low for w in want):
                problems.append("none of " + ", ".join(want[:5]))
            problems += reply_problems(said, reply, action, want)
            for w in nope:
                if w.lower() in low or (w == "$" and re.search(r"\$\d{3,}", full)):
                    problems.append("must not say " + w)
            print(f"  {'ok  ' if not problems else 'FAIL'}  You: {said}\n        Helm: {full[:200]}" + ("" if not problems else "\n        -> " + "; ".join(problems)))
            bad += bool(problems)
            history += [{"role": "user", "content": said}, {"role": "assistant", "content": reply}]
    print(f"\n{turns - bad} of {turns} turns as hoped")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main({int(a) for a in sys.argv[1:] if a.isdigit()}))
