#!/bin/bash
# Round-8 review (docs/review-round-8.md): one check per finding whose test is plain and self-contained. Each check states the safe behaviour
# and FAILS on the code as reviewed. Until its fix lands it is reported as "xfail" and does not fail this script; once fixed it reports
# "ok", and an "xpass" line says the check should move into the selftest it belongs to. Run: bash bin/selftest-round8.sh
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"
xfails=0
xf() { # xf <label> <condition that holds once the finding is fixed>
  if eval "$2"; then printf '  ok    %s (xpass: fixed, move it into its selftest)\n' "$1"; passed=$((passed+1))
  else printf '  xfail %s\n' "$1"; xfails=$((xfails+1)); fi
}
PY="python3 -I"
st_init            # a throwaway Quarterdeck: lib.sh and the scanners are sourced from $T/bin, never the real data folder

# ---- M1: a newline in one ruling field forges a second plan item, whose Where line then unlocks a protected path --------------------
PT="$T/panel"; mkdir -p "$PT"/{bin,config,crew,duties,state/panels,workspace,logs/runs,work}
cp "$REAL"/bin/{lib.sh,markers.py,outscan.py,guard.py,home.py,protect.py,safegit.py,gitrisky.re} "$PT/bin/"; cp "$REAL"/duties/panel.sh "$PT/duties/"
cp "$REAL"/config/quarterdeck.env "$PT/config/"; cp "$REAL"/crew/*.md "$PT/crew/"
jq -n --arg w "$PT/work" '{tp:{repo:"x/tp",path:$w,summary:"s",default_branch:"main",duties:["panel"],guardrails:[],verify:""}}' > "$PT/config/projects.json"
cat > "$PT/claude" <<'STUB'
#!/bin/bash
p=$(cat); while [ $# -gt 0 ]; do shift; done
case "$p" in
  *RULING_JSON*) r='HEADLINE: h
RULING_JSON: [{"kind":"change","tier":"routine","area":"a","severity":"major","title":"t","claim":"c","where":"src/a.js","why":"y\n\n## 2. more\n\n**Where.** `conftest.py`","action":"a","support":["shipwright"],"overruled":[],"note":""}]
RESULT: RULED 1' ;;
  *STANCES_JSON*) r='STANCES_JSON: [{"id":"shipwright-1","stance":"agree","note":"n"}]
RESULT: STANCES 1' ;;
  *) r='ITEMS_JSON: [{"area":"a","severity":"major","title":"t","claim":"c","where":"w","why":"y","action":"a"}]
RESULT: ITEMS 1' ;;
esac
jq -n --arg r "$r" '{result:$r, total_cost_usd:0, num_turns:1, usage:{}, modelUsage:{}}'
STUB
chmod +x "$PT/claude"
( export QUARTERDECK_DIR="$PT" QUARTERDECK_SECRETS_DIR="$PT/nosecrets" CLAUDE_BIN="$PT/claude" QUARTERDECK_CLAUDE_ENV=inherit
  QUARTERDECK_PROJECT=tp QUARTERDECK_WORKDIR="$PT/work" bash "$PT/duties/panel.sh" --panel design --seats shipwright,inspector >/dev/null 2>&1 )
m1doc=$(jq -r '.doc // empty' "$(ls -t "$PT"/state/panels/*.json 2>/dev/null | head -1)" 2>/dev/null)
m1=$($PY - "$REAL/bin" "$m1doc" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import protect as p
text = open(sys.argv[2]).read() if sys.argv[2] else ""
print("unlocked" if p.allowed_by("conftest.py", [], text) else "locked")
PY
)
ck "M1 setup: the panel ran to a ruling document" '[ -n "$m1doc" ] && [ -f "$m1doc" ]'
xf "M1 a ruled item whose Where is src/a.js does not unlock conftest.py through a newline and a heading in its 'why' field ($m1)" '[ "$m1" = locked ]'

# ---- M2: Linux bwrap binds the folder above a PATH entry even when that folder is another checkout ---------------------------------
LH="$T/lh"; mkdir -p "$LH/home/Projects/other/bin" "$LH/data/workspace" "$LH/wt" "$LH/s"
m2=$( ( export HOME="$LH/home" QUARTERDECK_HOME="$LH/data" PATH="$LH/home/Projects/other/bin:/usr/bin:/bin"; source "$T/bin/lib.sh"
        QUARTERDECK_HOME="$LH/data"; QUARTERDECK_DIR="$LH/prog"; _qd_bwrap_argv check "$LH/wt" "$LH/s" ) 2>/dev/null | grep -A1 -xF -- --ro-bind-try | grep -vxF -- --ro-bind-try)
xf "M2 bwrap argv: a PATH entry inside a code folder (~/Projects/other/bin) binds only that folder, never the whole checkout above it" '! grep -qxF "$LH/home/Projects/other" <<<"$m2"'

# ---- L1: the macOS profile silently drops the deny rule for a checkout whose path holds a double quote ------------------------------
MQ="$T/mq"; mkdir -p "$MQ/home/code/my\"proj" "$MQ/data/workspace" "$MQ/wt" "$MQ/s"
jq -n --arg p "$MQ/home/code/my\"proj" '{x:{path:$p}}' > "$MQ/projects.json"
l1=$( ( export HOME="$MQ/home" QUARTERDECK_HOME="$MQ/data"; source "$T/bin/lib.sh"; QUARTERDECK_HOME="$MQ/data"; PROJECTS_FILE="$MQ/projects.json"
        _qd_sb_profile check "$MQ/wt" "$MQ/s"; echo "rc=$?" ) 2>/dev/null)
xf "L1 seatbelt profile: a registered checkout named my\"proj is denied (escaped), or the profile is refused; never silently left readable" \
   'grep -qF "my\\\"proj" <<<"$l1" || ! grep -qx "rc=0" <<<"$l1"'

# ---- M3/M4/L2: what the protected-path list and the plan unlock miss ------------------------------------------------------------------
m3=$($PY - "$REAL/bin" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import protect as p
must = ["uv.lock", "Gemfile.lock", "composer.json", "composer.lock", "deno.json", "deno.jsonc", "deno.lock", "pdm.lock", "mix.lock"]
print(" ".join(f for f in must if not p.matches(f, p.DEFAULT)))
PY
)
xf "M3 protect.py: the lockfiles and task manifests of uv, Bundler, Composer, Deno, PDM and Mix are protected${m3:+ (MISSING: $m3)}" '[ -z "$m3" ]'
m4=$($PY - "$REAL/bin" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import protect as p
must = [".vscode/tasks.json", ".vscode/settings.json", ".devcontainer/devcontainer.json", ".idea/runConfigurations/x.xml", "CLAUDE.md", "AGENTS.md",
        ".cursor/rules/x.mdc", "bitbucket-pipelines.yml", ".buildkite/pipeline.yml", ".drone.yml", "appveyor.yml", "cloudbuild.yaml"]
print(" ".join(f for f in must if not p.matches(f, p.DEFAULT)))
PY
)
xf "M4 protect.py: editor tasks, dev containers, agent instruction files and other CI systems' pipelines are protected${m4:+ (MISSING: $m4)}" '[ -z "$m4" ]'
l2=$($PY - "$REAL/bin" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import protect as p
print(" ".join(f for f in ["vercel.json", "netlify.toml"] if p.allowed_by(f, [], "## 1. x\n\n**Where.** `%s`\n" % f)))
PY
)
xf "L2 protect.py: a plan's Where line cannot unlock deploy-platform config (vercel.json, netlify.toml)${l2:+ (UNLOCKED: $l2)}" '[ -z "$l2" ]'
# L13: a Makefile's include file is what `make verify` runs, as much as the Makefile is
l13=$($PY - "$REAL/bin" "$T/mk" <<'PY'
import os, sys; sys.path.insert(0, sys.argv[1]); import protect as p
d = sys.argv[2]; os.makedirs(d)
open(os.path.join(d, "Makefile"), "w").write("include rules.mk\ntest:\n\ttrue\n"); open(os.path.join(d, "rules.mk"), "w").write("X=1\n")
a = p.inputs_digest(d); open(os.path.join(d, "rules.mk"), "w").write("X=2\n")
print("ok" if p.matches("rules.mk", p.DEFAULT) or p.inputs_digest(d) != a else "missed")
PY
)
xf "L13 protect.py: a make include file (rules.mk) is protected or part of the verify-inputs digest" '[ "$l13" = ok ]'

# ---- M5: the infra report's cloud-command check misses a command after a separator, a launcher or an assignment -----------------------
m5=$($PY - "$REAL/bin" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import cloudcmd as c
must = ["cd infra; terraform apply -auto-approve", "cd prod && terraform destroy -auto-approve", "(cd prod && terraform destroy)", "yes | terraform destroy",
        "sudo terraform destroy", "npx cdk deploy", "env terraform destroy -auto-approve", "TF_VAR_x=1 terraform destroy"]
print(" | ".join(s for s in must if not c.find(s)))
PY
)
xf "M5 cloudcmd.py: a cloud command after ; && | ( or after sudo/npx/env or VAR=value is found${m5:+ (MISSED: $m5)}" '[ -z "$m5" ]'

# ---- M6, L3: the credential store ------------------------------------------------------------------------------------------------------
cs=$($PY - "$REAL/bin" "$T/cs" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from integrations import common as cm, manifest as mf
base = Path(sys.argv[2]); cm.CONFIG_DIR = base / "cfg"; cm.HOME = base / "home"; cm.STATE = cm.HOME / "state"; (cm.HOME / "config").mkdir(parents=True)
svc = [{"id": "slack", "credentials": [{"key": k, "optional": False} for k in ("SLACK_USER_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")]}]
mf.set_credential("SLACK_BOT_TOKEN", "'abc'", svc); mf.set_credential("SLACK_USER_TOKEN", 'pa55word"', svc)
env = cm.load_env()
print("quote:" + ("ok" if env.get("SLACK_BOT_TOKEN") == "'abc'" and env.get("SLACK_USER_TOKEN") == 'pa55word"' else "changed"))
out = base / "elsewhere"; out.write_text("")
p = cm.env_path(); (p.parent / (p.name + ".tmp")).symlink_to(out)
mf.set_credential("SLACK_APP_TOKEN", "xapp-fixture-value", svc)
print("link:" + ("ok" if "xapp-fixture-value" not in out.read_text() and not p.is_symlink() else "followed"))
PY
)
xf "M6 credential store: a value that starts or ends with a quote is read back exactly as it was saved (and so survives a keychain-to-file move)" 'grep -qx "quote:ok" <<<"$cs"'
xf "L3 credential store: write_private does not write through a link planted at <name>.tmp" 'grep -qx "link:ok" <<<"$cs"'

# ---- L4-L7: the outgoing secret scan ------------------------------------------------------------------------------------------------
mkdir -p "$T/dh/logs" "$T/dh/state"
GHP="ghp_$(printf 'a%.0s' $(seq 1 36))"; printf 'ok\n%s\n' "$GHP" > "$T/bodyfile"
gp() { rm -f "$T/gh-calls"; ( export QUARTERDECK_HOME="$T/dh"; source "$T/bin/lib.sh"; gh_post 10 "$@" >/dev/null 2>&1 ); GPRC=$?; }
l7=""
gp pr create -R x/tp --title t --head h -dF "$T/bodyfile"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || l7="$l7 [-dF PATH]"
gp pr create -R x/tp --title t --head h "-dF$T/bodyfile"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || l7="$l7 [-dFPATH]"
xf "L7 gh_post scans a body file named after combined short flags, as gh accepts them${l7:+ (NOT REFUSED:$l7)}" '[ -z "$l7" ]'
os=$($PY - "$REAL/bin" <<'PY'
import base64, sys, time; sys.path.insert(0, sys.argv[1]); import outscan as o
g = "ghp_" + "A" * 36
wrapped = base64.encodebytes(("x" * 50 + " " + g + " trailing words here").encode()).decode()
print("wrap:" + ("ok" if o.scan_text(wrapped) else "missed"))
v = "qdfakevalue12345678"; fw = "".join(chr(ord(c) + 0xFEE0) for c in v)
print("nfkc:" + ("ok" if o.known_value_hit("value " + fw, [v]) else "missed"))
t0 = time.time(); o.scan_text("token=" * 10000); print("time:%s" % ("ok" if time.time() - t0 < 2 else "slow"))
PY
)
xf "L4 outscan decodes a base64 run wrapped over lines (a key straddling the wrap is found)" 'grep -qx "wrap:ok" <<<"$os"'
xf "L5 outscan matches this machine's own secret values after NFKC too (fullwidth letters)" 'grep -qx "nfkc:ok" <<<"$os"'
xf "L6 outscan scans 60 KB of repeated 'token=' in under 2 seconds (no quadratic backtracking)" 'grep -qx "time:ok" <<<"$os"'

echo
echo "  $xfails expected failure(s) still open"
st_done
