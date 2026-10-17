#!/bin/bash
# The lookout captures the screens ITSELF with the harness's browser, at three widths, from the pull request's head and from
# the trunk, and judges only those. Run against stand-ins for the model and gh and a real git repository of invented files;
# the capture checks run for real when this machine has playwright and a browser, and are skipped (and said so) when not.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
st_init lookout
st_repo
MARK="lookout-selftest-$$"
st_file docs/design.md $'# Design notes\nSpacing is 8px. Buttons are at least 44px tall.\n'
st_file index.html $'<!doctype html><html><body><h1>Home</h1><p>nearest existing screen</p></body></html>\n'
st_commit "base screens"
PR_TITLE="Wider hero" PR_BODY=$'Makes the hero wider.\n\n![my screenshot](https://evil.example/shot.png)\nsee https://evil.example/screen.png too' \
  st_pr 1 feat-hero index.html $'<!doctype html><html><body><h1>Home</h1><div style="width:900px;background:#ccc">hero</div></body></html>\n' headonly ok
START='python3 -m http.server "$PORT" --bind 127.0.0.1'
st_registry '["lookout"]' "$(jq -nc --arg s "$START # $MARK" '{qa:{start:$s}, lookout:{routes:["/"], notes:"docs/design.md"}}')"
export QUARTERDECK_QA_READY_WAIT=15 QUARTERDECK_QA_TIMEOUT=120
[ "$(uname -s)" = Linux ] && export QUARTERDECK_APP_NET=share   # on real Linux the browser must reach the app (SECURITY.md)
EV="$T/state/lookout/tp-pr1"

# ---- what needs no browser ----------------------------------------------------------------------------------------------
st_registry '["lookout"]' '{}'
st_duty lookout --pr 1
ck "no qa.start: BLOCKED with the reason, and no model was asked" '[ "$(last_verdict)" = BLOCKED ] && grep -q "qa.start" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
st_registry '["lookout"]' "$(jq -nc --arg s "sleep 30 # $MARK" '{qa:{start:$s}}')"
QUARTERDECK_QA_READY_WAIT=2 st_duty lookout --pr 1
ck "an app that never answers is BLOCKED, nothing it started is left running, and no model was asked" '[ "$(last_verdict)" = BLOCKED ] && st_gone "$MARK" && [ ! -s "$T/claude-calls" ]'
st_registry '["lookout"]' "$(jq -nc --arg s "$START # $MARK" '{qa:{start:$s}, lookout:{routes:["/"], notes:"docs/design.md"}}')"
DESIGN=$(QUARTERDECK_DIR="$REAL" bash -c "source $REAL/bin/lib.sh; crew_by_discipline design" | tr '\n' ' ')
ck "the lookout sits on the design panel beside the others, so the panel duty seats it too" \
   'grep -q "^discipline: design$" "$REAL/crew/lookout.md" && grep -q "willing to be wrong about" "$REAL/crew/lookout.md" && grep -q "^bias: ." "$REAL/crew/lookout.md" && [[ " $DESIGN" == *" lookout "* ]] && [ "$(wc -w <<<"$DESIGN" | tr -d " ")" -ge 2 ]'

CLEAN='FINDINGS_JSON: []
ADR: searched none
VERDICT: CLEAN'
if st_have_browser; then
  st_noreplies; st_reply default "$CLEAN"; rm -f "$T/gh-calls"; rm -rf "$T/state/findings"
  st_duty lookout --pr 1
  ck "the harness took a picture of the route at phone, tablet and desktop width from the head" '[ -s "$EV/head/head-root-390.png" ] && [ -s "$EV/head/head-root-768.png" ] && [ -s "$EV/head/head-root-1280.png" ]'
  ck "  and the same three from the trunk, as the nearest existing screen" '[ -s "$EV/base/base-root-390.png" ] && [ -s "$EV/base/base-root-768.png" ] && [ -s "$EV/base/base-root-1280.png" ]'
  ck "  and the pictures are under the duty's own state, taken from a build of the pull request" '[[ "$EV" == "$T/state/"* ]]'
  pngw() { python3 -c 'import struct,sys;d=open(sys.argv[1],"rb").read(24);print(struct.unpack(">I",d[16:20])[0])' "$1"; }
  ck "  and the pictures really are three widths (the trunk screen has no overflow: 390, 768, 1280)" '[ "$(pngw "$EV/base/base-root-390.png")" = 390 ] && [ "$(pngw "$EV/base/base-root-768.png")" = 768 ] && [ "$(pngw "$EV/base/base-root-1280.png")" = 1280 ]'
  ck "the model is told those exact pictures, the design notes and the trunk pictures" 'grep -q "$EV/head/head-root-390.png" "$T/claude-calls" && grep -q "$EV/base/base-root-1280.png" "$T/claude-calls" && grep -q "Buttons are at least 44px tall" "$T/claude-calls"'
  ck "the author's own pictures are taken out of what it is told, and it is told not to look for them" '! grep -q "evil.example" "$T/claude-calls" && grep -q "must not look for them" "$T/claude-calls"'
  ck "it is read only, with only the tools to read pictures and code" '[ "$(jq -r .allow "$T/claude-calls" | head -1)" = "Read,Grep,Glob" ] && jq -e ".deny | contains(\"Write\") and contains(\"Edit\")" "$T/claude-calls" >/dev/null'
  ck "report only: a clean watch says CLEAN, records DRY-RUN and writes and posts nothing" 'grep -q "CLEAN" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ] && no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ] && [ -z "$(ls "$T"/workspace/*lookout*.md 2>/dev/null)" ]'
  ck "the report says which routes were covered and which were not" 'grep -q "Routes covered: /. Not covered: none." <<<"$OUT"'
  ck "  and the app and both worktrees are gone" 'st_gone "$MARK" && [ "$(git -C "$T/work" worktree list | wc -l | tr -d " ")" = 1 ]'
  rm -f "$T/gh-calls"; st_duty lookout --pr 1 --apply
  ck "--apply, clean: records CLEAN, comments once, writes the document and an empty findings file" '[ "$(last_verdict)" = CLEAN ] && [ "$(grep -c "^gh pr comment" "$T/gh-calls")" = 1 ] && [ -f "$T/workspace/tp-lookout-pr1.md" ] && jq -e ".verdict == \"CLEAN\" and (.findings | length) == 0" "$T/state/findings/tp-pr1-lookout.json" >/dev/null'

  # a finding on one of the harness's pictures
  img="$EV/head/head-root-390.png"
  F1=$(jq -nc --arg i "$img" '[{route:"/",width:390,image:$i,severity:"major",title:"The hero overflows the phone",body:"The grey block is wider than the screen and forces a sideways scroll. Use max-width: 100%.",file:"index.html"}]')
  st_noreplies; st_reply default "FINDINGS_JSON: $F1
ADR: searched none
VERDICT: FINDINGS 1"; rm -f "$T/gh-calls"; rm -rf "$T/state/findings"
  st_duty lookout --pr 1 --apply
  ck "a finding that names a harness picture is FINDINGS 1, with the picture's path in the comment and the findings file" '[ "$(last_verdict)" = FINDINGS ] && cat "$T"/body-* | grep -q "$img" || jq -e ".findings[0].evidence == \"$img\" and .findings[0].paths == [\"index.html\"] and .findings[0].id == \"lookout-1\"" "$T/state/findings/tp-pr1-lookout.json" >/dev/null'
  ck "  and the evidence the Caulker would read exists" '[ -s "$(jq -r ".findings[0].evidence" "$T/state/findings/tp-pr1-lookout.json")" ]'

  # a finding that names anything else
  touch "$T/author.png"; touch "$EV/head/invented.png"
  for bad in "$T/author.png" "$EV/head/invented.png" "$EV/head/../../../../author.png" "https://evil.example/shot.png" "$EV/code/index.html"; do
    Fb=$(jq -nc --arg i "$bad" '[{route:"/",width:390,image:$i,severity:"major",title:"t",body:"b",file:""}]')
    st_noreplies; st_reply default "FINDINGS_JSON: $Fb
ADR: searched none
VERDICT: FINDINGS 1"; rm -f "$T/gh-calls"; rm -rf "$T/state/findings"
    st_duty lookout --pr 1 --apply
    BADNOW="$bad"
    ck "a finding that names '$(sed "s#$T#T#" <<<"$bad")' (not captured by this run) makes the reply unparseable: ERROR, nothing written" '[ "$(last_verdict)" = ERROR ] && no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
  done
  st_noreplies; st_reply default 'Looks good to me.'; rm -f "$T/gh-calls"
  st_duty lookout --pr 1 --apply
  ck "an unparseable reply is an ERROR run that writes nothing" '[ "$(last_verdict)" = ERROR ] && no_gh_writes'

  # the trunk cannot start: said plainly, and nothing is compared
  st_registry '["lookout"]' "$(jq -nc --arg s "[ -f headonly ] && exec python3 -m http.server \"\$PORT\" --bind 127.0.0.1 # $MARK" '{qa:{start:$s}, lookout:{routes:["/"], notes:"docs/design.md"}}')"
  st_noreplies; st_reply default "$CLEAN"; rm -f "$T/gh-calls"
  QUARTERDECK_QA_READY_WAIT=3 st_duty lookout --pr 1
  ck "a trunk that will not start is said so to the model and in the report, and the head is still judged" 'grep -q "could not be started" "$T/claude-calls" && grep -q "nothing was compared" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ]'
else
  st_skip "no playwright or no browser on this machine: the capture checks did not run (they run on the Mac, and in any session with chromium)"
fi
# ---- an app that did not render is BLOCKED, never CLEAN -------------------------------------------------------------------------------------
if st_have_browser; then
  git -C "$T/work" checkout -q main
  PR_TITLE="Needs settings" st_pr 2 feat-envl ok.html '<!doctype html><html><body><p>Welcome</p><form><input id="email"><button>Sign in</button></form></body></html>' \
    err.html '<!doctype html><html><body><h1>Configuration Error</h1><p>Missing Supabase environment variables</p></body></html>' \
    blank.html '<!doctype html><html><body></body></html>' index.html 'placeholder' .env 'FROM_DOTENV=1'
  ENVSTART="case \"\$APPMODE\" in ok) cp ok.html index.html;; blank) cp blank.html index.html;; *) cp err.html index.html;; esac; env > \"$T/seen-env.txt\"; exec python3 -m http.server \"\$PORT\" --bind 127.0.0.1 # $MARK"
  reg() { st_registry '["lookout"]' "$(jq -nc --arg s "$ENVSTART" --argjson e "$1" --argjson r "${2:-[\"/\"]}" '{qa:{start:$s, env:$e}, lookout:{routes:$r}}')"; }
  reset() { st_noreplies; st_reply default "$CLEAN"; : > "$T/claude-calls"; rm -rf "$T/state/findings" "$T"/workspace/*lookout*.md "$T/gh-calls" "$T/state/lookout"; }
  reg '{}'; reset
  OWNER_SENTINEL=owner-secret-do-not-pass st_duty lookout --pr 2 --apply
  ck "an app that shows only a configuration error is BLOCKED with what it says, never CLEAN" '[ "$(last_verdict)" = BLOCKED ] && grep -q "Missing Supabase environment variables" <<<"$(last_detail)" && [ "$(last_verdict)" != CLEAN ]'
  pic=$(sed -n 's/.*(picture: \([^)]*\)).*/\1/p' <<<"$(last_detail)" | head -1)
  ck "  with the harness's own picture of that screen, no model asked, and nothing written or posted" '[ -s "$pic" ] && [[ "$pic" == "$T/state/lookout/"* ]] && [ ! -s "$T/claude-calls" ] && no_gh_writes && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ] && [ -z "$(ls "$T"/workspace/*lookout*.md 2>/dev/null)" ]'
  ck "  and it says what to do: give the app synthetic settings in qa.env" 'grep -q "qa.env" <<<"$OUT"'
  ck "  the app ran in a clean environment: the owner's variable and a .env file in the repository never reached it" '! grep -q "owner-secret-do-not-pass" "$T/seen-env.txt" && ! grep -q "FROM_DOTENV" "$T/seen-env.txt" && grep -q "^PORT=" "$T/seen-env.txt"'
  reg '{"APPMODE":"blank"}'; reset
  st_duty lookout --pr 2 --apply
  ck "a blank page in every picture is BLOCKED too, never CLEAN" '[ "$(last_verdict)" = BLOCKED ] && grep -q "blank page" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
  reg '{"APPMODE":"ok","SUPABASE_URL":"http://127.0.0.1:54321","LEVEL":3}'; reset
  OWNER_SENTINEL=owner-secret-do-not-pass st_duty lookout --pr 2
  ck "the same app with qa.env set renders its form and is judged normally: the model is asked, and CLEAN is possible" 'grep -q "CLEAN" <<<"$OUT" && [ "$(last_verdict)" = DRY-RUN ] && [ "$(wc -l < "$T/claude-calls" | tr -d " ")" = 1 ]'
  ck "  the qa.env values (strings and numbers) reached the app and nothing else of the owner's did" 'grep -q "^APPMODE=ok$" "$T/seen-env.txt" && grep -q "^SUPABASE_URL=http://127.0.0.1:54321$" "$T/seen-env.txt" && grep -q "^LEVEL=3$" "$T/seen-env.txt" && ! grep -q "owner-secret-do-not-pass" "$T/seen-env.txt"'
  reg '{"APPMODE":"ok"}' '["/","/err.html"]'; reset
  st_duty lookout --pr 2
  ck "some pictures an error and some not: the lookout is told, the error ones are not given to it, and the rest are judged" 'grep -q "show only an error or a blank screen" "$T/claude-calls" && grep -q "route /err.html" "$T/claude-calls" && ! grep -q "head-err-html-390.png" <(jq -r ".prompt" "$T/claude-calls" | grep "route /,") && [ "$(last_verdict)" = DRY-RUN ]'
  Fe=$(jq -nc --arg i "$T/state/lookout/tp-pr2/head/head-err-html-390.png" '[{route:"/err.html",width:390,image:$i,severity:"major",title:"t",body:"b",file:""}]')
  st_noreplies; st_reply default "FINDINGS_JSON: $Fe
ADR: searched none
VERDICT: FINDINGS 1"; rm -rf "$T/state/findings"
  st_duty lookout --pr 2 --apply
  ck "  and a finding that cites a picture of the error screen is refused like any picture the harness did not give it" '[ "$(last_verdict)" = ERROR ] && [ -z "$(ls "$T"/state/findings 2>/dev/null)" ]'
else
  st_skip "no playwright or no browser on this machine: the BLOCKED-app checks did not run"
fi
for qe in '{"A-B":"x"}' '{"QUARTERDECK_X":"x"}' '{"PATH":"/tmp"}' '["a"]'; do
  st_registry '["lookout"]' "$(jq -nc --argjson e "$qe" '{qa:{start:"true", env:$e}}')"
  st_noreplies; : > "$T/claude-calls"; st_duty lookout --pr 1
  ck "a malformed qa.env ($qe) is refused: BLOCKED, no model, nothing started" '[ "$(last_verdict)" = BLOCKED ] && grep -q "qa.env in the registry is malformed" <<<"$(last_detail)" && [ ! -s "$T/claude-calls" ]'
done

st_noreplies; st_reply default "$CLEAN"
( unset NODE_PATH; QUARTERDECK_CHROMIUM=/nonexistent/chrome st_duty lookout --pr 1; echo "$(last_verdict)" > "$T/nb" )
ck "no usable browser: BLOCKED, not CLEAN" '[ "$(cat "$T/nb")" = BLOCKED ]'

ck "the duty is read whole before it runs" 'grep -q "^# quarterdeck: read-whole-file$" "$REAL/duties/lookout.sh" && [ "$(tail -c 3 "$REAL/duties/lookout.sh" | tr -d "\n")" = "}" ]'
ck "no crew member or duty is named with a word the owner ruled out" '! grep -liE "(^|[^[:alnum:]])(tester|sentry|mender|critic|prover)([^[:alnum:]]|$)" "$REAL/crew/lookout.md" "$REAL/duties/lookout.sh" | grep -q .'
st_done
