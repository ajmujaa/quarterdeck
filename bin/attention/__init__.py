"""Where the owner's attention goes: an honest signal, collected locally, free, private, timestamps and counts only.

The collector never reads or stores what was said, written or changed: not a prompt, a message, a diff, a title or a
file name. It keeps, per project and per day, how many commits he made, how many pull requests and notes, and how many
meetings his calendar holds. It reads nothing outside the registered projects and Quarterdeck's own state/ (never session
files of any tool, apps, screens, keystrokes, the clipboard or location). Everything stays in state/attention.json
(mode 0600, which no agent may read).
"""
