#!/bin/bash
# fleet-hook.sh: lets the Fleet view see which Claude Code sessions are open in a registered repository, and which agent is running.
#
#   bin/fleet-hook.sh              (called by Claude Code) reads one hook event on stdin and, if its folder belongs to a repo-agents source in
#                                  config/fleet.local.json, appends ONE line to state/fleet-events/<source>.jsonl
#   bin/fleet-hook.sh install      adds it to ~/.claude/settings.json (keeps every other hook, makes a backup, safe to repeat)
#   bin/fleet-hook.sh uninstall    removes only its own entries
#   bin/fleet-hook.sh status       says whether it is installed
#
# What it records, and nothing else: the time, the kind of event (session started or ended, a prompt was sent, the turn finished, an agent
# started or stopped), the session id, the worktree folder name, the branch and the agent's name. It never reads or writes the prompt, the
# reply, a tool's input or output, a file name or a transcript: those fields are in the input and are simply never looked at.
# A session in any folder that is not one of the registered repositories leaves no trace at all. It is quiet, quick and can never block,
# change or slow a session (async, always exits 0). Standing owner rule: no keystrokes, screens, apps, clipboard or location.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
SELF="$HERE/fleet-hook.sh"
# Where your data lives: the same four rules as bin/home.py (Claude Code starts this without Quarterdeck's environment).
if [ -n "${QUARTERDECK_HOME:-}" ]; then DHOME="$QUARTERDECK_HOME"
elif [ -n "${QUARTERDECK_DIR:-}" ]; then DHOME="$QUARTERDECK_DIR"
elif [ -f "$HOME/.quarterdeck/.quarterdeck-home" ]; then DHOME="$HOME/.quarterdeck"
else DHOME="$ROOT"; fi
CONFIG="$DHOME/config/fleet.local.json"
REGISTRY="$DHOME/config/projects.json"      # a registered project is watched too, with no fleet file at all
EVENTS="$DHOME/state/fleet-events"
SETTINGS="${CLAUDE_SETTINGS_FILE:-$HOME/.claude/settings.json}"

settings_edit() { # settings_edit <jq filter>: rewrite the settings file with a backup, keeping everything else
  mkdir -p "$(dirname "$SETTINGS")"
  [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
  jq -e . "$SETTINGS" >/dev/null 2>&1 || { echo "fleet-hook: $SETTINGS is not valid JSON, not touching it" >&2; return 1; }
  cp "$SETTINGS" "$SETTINGS.quarterdeck-bak-$(date +%Y%m%d-%H%M%S)" || return 1
  local tmp; tmp="$(mktemp)"
  jq --arg cmd "$SELF" "$1" "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS" && chmod 600 "$SETTINGS"
}

case "${1:-}" in
  install)
    command -v jq >/dev/null || { echo "fleet-hook: jq is needed" >&2; exit 1; }
    settings_edit '
      .hooks = (.hooks // {})
      | reduce ("SessionStart", "SessionEnd", "UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop") as $k (.;
          .hooks[$k] = ((.hooks[$k] // [])
            | map(.hooks = ((.hooks // []) | map(select((.command // "") != $cmd)))) | map(select((.hooks | length) > 0))
            + [{"hooks": [{"type": "command", "command": $cmd, "async": true, "timeout": 10}]}]))' \
      && echo "installed: Claude Code now tells Quarterdeck when a session starts, stops and which agent runs, for the registered repositories only. Backup beside $SETTINGS" ;;
  uninstall)
    settings_edit '
      if .hooks then .hooks |= with_entries(.value |= (map(.hooks = ((.hooks // []) | map(select((.command // "") != $cmd)))) | map(select((.hooks | length) > 0)))
                                          | select((.value | length) > 0)) else . end
      | if (.hooks // {}) == {} then del(.hooks) else . end' \
      && echo "removed: only Quarterdeck's own entries" ;;
  status)
    if [ -f "$SETTINGS" ] && jq -e --arg cmd "$SELF" '[.hooks[]?[]?.hooks[]? | select(.command == $cmd)] | length > 0' "$SETTINGS" >/dev/null 2>&1; then
      echo "installed"; else echo "not installed"; fi ;;
  "")
    # ---- an event ----------------------------------------------------------------------------------------------------------------
    umask 077
    in="$(cat 2>/dev/null)" || exit 0
    kind=""
    IFS=$'\x1f' read -r name sess cwd agent < <(printf '%s' "$in" | jq -r '[(.hook_event_name // ""), (.session_id // ""), (.cwd // ""), (.agent_type // "")] | map(tostring | gsub("\n"; " ") | gsub("\r"; " ") | gsub("\u001f"; " ")) | join("\u001f")' 2>/dev/null) || exit 0
    case "$name" in
      SessionStart) kind=session_start ;; SessionEnd) kind=session_end ;; UserPromptSubmit) kind=prompt ;; Stop) kind=stop ;;
      SubagentStart) kind=agent_start ;; SubagentStop) kind=agent_stop ;; *) exit 0 ;;
    esac
    case "$sess" in ""|*[!A-Za-z0-9_-]*) exit 0 ;; esac
    [ -n "$cwd" ] && [ -d "$cwd" ] && { [ -r "$CONFIG" ] || [ -r "$REGISTRY" ]; } || exit 0
    common="$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
    common="$(cd "$common" 2>/dev/null && pwd -P)" || exit 0
    src=""
    while IFS=$'\t' read -r id path; do
      p="${path/#\~/$HOME}"
      c="$(git -C "$p" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || continue
      c="$(cd "$c" 2>/dev/null && pwd -P)" || continue
      [ "$c" = "$common" ] && { src="$id"; break; }
    done < <({ jq -r '.sources[]? | select(.kind == "repo-agents") | [.id, .path] | @tsv' "$CONFIG" 2>/dev/null
               jq -r 'to_entries[]? | select(.value | type == "object") | [.key, (.value.path // "")] | @tsv' "$REGISTRY" 2>/dev/null; })
    [ -n "$src" ] || exit 0
    case "$src" in *[!a-z0-9_-]*|"") exit 0 ;; esac
    top="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)"
    branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    mkdir -p "$EVENTS" && chmod 700 "$EVENTS" 2>/dev/null
    f="$EVENTS/$src.jsonl"
    jq -nc --arg e "$kind" --arg s "$sess" --arg w "$(basename "${top:-$cwd}")" --arg b "$branch" --arg a "$agent" \
      '{t: now, event: $e, session: $s, worktree: $w, branch: $b, agent: (if ($e | startswith("agent_")) then $a else "" end)}' >> "$f" 2>/dev/null
    chmod 600 "$f" 2>/dev/null
    # keep the file small: past two megabytes keep the newest three thousand events
    sz="$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)"
    if [ "${sz:-0}" -gt 2000000 ]; then tail -n 3000 "$f" > "$f.tmp" 2>/dev/null && mv "$f.tmp" "$f"; fi
    exit 0 ;;
  *) echo "usage: fleet-hook.sh [install|uninstall|status]" >&2; exit 2 ;;
esac
