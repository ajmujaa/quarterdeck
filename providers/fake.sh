# The fake provider: an adapter for tests (docs/design-providers.md, "A fake provider for tests"). Sourced by bin/lib.sh when a call names
# it; never on its own. No network and no model: providers/fake.py answers from a script the test wrote and records exactly what the
# harness handed the adapter, so a test can check claude_run's inputs at the seam, for any provider, and its cost, cap, limit and
# failure paths, for nothing.
#
#   QUARTERDECK_FAKE_SCRIPT   a JSON file: one reply, or a list of replies where the first whose "match" (a regular expression) is found
#                             in the prompt answers, and one without "match" answers anything. A reply's keys, all optional:
#                               text, cost_usd (0), cost_known (true), input_tokens, output_tokens, turns (1), model ("fake-model"),
#                               stop (null | "cap" | "limit" | "error"), exit (0), output ("json" | "empty" | "malformed"), sleep (seconds)
#   QUARTERDECK_FAKE_REPLIES  or a folder in the stand-in model's layout (bin/selftest-lib.sh): NNN.match / NNN.reply pairs, first match
#                             wins, then default.reply; the cost is QUARTERDECK_FAKE_COST (0.05)
#   QUARTERDECK_FAKE_RECORD   where each call is recorded, one JSON object per line (default: state/fake-calls.jsonl in the data folder)
#   QUARTERDECK_FAKE_HOOK     an executable run in the working folder after the call is recorded, with the prompt as its argument: a
#                             model that obeys what it read, to show what the harness then refuses
#
# With neither a script nor a replies folder it refuses: a seat put on the fake by mistake fails instead of answering nonsense.

provider_status_fake() { # for doctor
  if [ -n "${QUARTERDECK_FAKE_SCRIPT:-}${QUARTERDECK_FAKE_REPLIES:-}" ]; then printf 'available (tests only; replies from %s)' "${QUARTERDECK_FAKE_SCRIPT:-$QUARTERDECK_FAKE_REPLIES}"
  else printf 'present, for tests only: answers only when QUARTERDECK_FAKE_SCRIPT or QUARTERDECK_FAKE_REPLIES is set'; return 1; fi
}

provider_call_fake() {
  [ -n "${QUARTERDECK_FAKE_SCRIPT:-}${QUARTERDECK_FAKE_REPLIES:-}" ] \
    || { log "the fake provider is for tests: set QUARTERDECK_FAKE_SCRIPT or QUARTERDECK_FAKE_REPLIES"; return 1; }
  # Its own minimal environment, always (QUARTERDECK_CLAUDE_ENV=inherit is for the claude stand-in's fixtures): what a program needs to
  # start, and nothing of the owner's. Everything the helper needs is an argument; the prompt is not one.
  local k sfile="" rc=0
  local -a fenv=()
  while IFS= read -r k; do
    case "$k" in
      TMPDIR) fenv+=("TMPDIR=$_QD_SYSTMP") ;;
      HOME|PATH|USER|LOGNAME|SHELL|LANG|LC_*|TERM|TZ) fenv+=("$k=${!k}") ;;
    esac
  done < <(compgen -e)
  if [ -n "$QD_CALL_SANDBOX" ]; then
    sfile=$(mktemp "${TMPDIR:-/tmp}/quarterdeck-settings.XXXXXX") && chmod 600 "$sfile" && printf '%s' "$QD_CALL_SANDBOX" > "$sfile" \
      || { log "claude_run: could not write the sandbox settings file"; rm -f "$sfile"; return 1; }
  fi
  local out
  out=$(cd "$QD_CALL_WORKDIR" && guard "$QD_CALL_TIMEOUT" env -i "${fenv[@]}" python3 "$QUARTERDECK_DIR/providers/fake.py" \
        --workdir="$QD_CALL_WORKDIR" --tools="$QD_CALL_TOOLS" --allow="$QD_CALL_ALLOW" --deny="$QD_CALL_DENY" \
        --model="$QD_CALL_MODEL" --effort="$QD_CALL_EFFORT" --budget="$QD_CALL_BUDGET" --sources="$QD_CALL_SOURCES" --settings="$sfile" \
        --record="${QUARTERDECK_FAKE_RECORD:-$QUARTERDECK_HOME/state/fake-calls.jsonl}" --script="${QUARTERDECK_FAKE_SCRIPT:-}" \
        --replies="${QUARTERDECK_FAKE_REPLIES:-}" --cost="${QUARTERDECK_FAKE_COST:-0.05}" --hook="${QUARTERDECK_FAKE_HOOK:-}" \
        2>>"${LOG_FILE:-$QUARTERDECK_HOME/logs/quarterdeck.log}") || rc=$?
  [ -z "$sfile" ] || rm -f "$sfile"
  [ -n "$out" ] || return "$rc"
  printf '%s' "$out" > "$QD_CALL_ENVELOPE"     # its raw reply is already the reply envelope
  printf '%s' "$out"
  return "$rc"
}
