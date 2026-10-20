#!/bin/bash
# Connections: the instructions on every card are right and fit, and (below) several accounts of one service. Fake services only: no network,
# no credential, a temp data folder with the .quarterdeck-home marker and a temp secrets folder, never the real home.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/data" "$T/secrets"; : > "$T/data/.quarterdeck-home"
export QUARTERDECK_HOME="$T/data" QUARTERDECK_SECRETS_DIR="$T/secrets" HOME="$T/home"; mkdir -p "$HOME"
unset QUARTERDECK_DIR
fails=0
ck() { local label=$1 cond=$2; if eval "$cond"; then printf '  ok    %s\n' "$label"; else printf '  FAIL  %s\n' "$label"; fails=$((fails+1)); fi; }
py() { python3 -I -c "import sys; sys.path.insert(0, '$HERE'); $1" 2>&1; }

echo "connections: instructions"
ck "no manifest step is longer than the 240 characters the page keeps (a longer one would be cut short)" \
   '[ "$(python3 - "$HERE/integrations/services" <<PY
import json, sys, pathlib
bad = [f"{f.stem}: {len(s)}" for f in pathlib.Path(sys.argv[1]).glob("*.json") for s in json.loads(f.read_text()).get("steps", []) if len(s) > 240]
print(len(bad))
PY
)" = 0 ]'
ck "Gmail says the token expires after 7 days while the app is in Testing, and tells you to publish it to production first" \
   'py "from integrations import manifest; s = [x for x in manifest.load_services() if x[\"id\"] == \"gmail\"][0][\"steps\"]; t = \" \".join(s); assert \"7 days\" in t and \"In production\" in t and \"Testing\" in t; assert [i for i, x in enumerate(s) if \"In production\" in x][0] < [i for i, x in enumerate(s) if \"google_oauth.py\" in x][0]" >/dev/null'
ck "Site analytics has a property id field, and its steps name the exact data folder path of integrations.json" \
   'py "from integrations import manifest, common; r = [x for x in manifest.status(have=set(), cfg=common.load_config(), recorded={}) if x[\"id\"] == \"ga4\"][0]; assert \"GA4_PROPERTY_ID\" in [c[\"key\"] for c in r[\"credentials\"]]; assert any(str(common.HOME) + \"/config/integrations.json\" in s for s in r[\"steps\"]), r[\"steps\"]" >/dev/null'
ck "Site analytics reads the property id from the page field first, then from the config file" \
   'py "from integrations import ga4, common; import inspect; src = inspect.getsource(ga4.fetch); assert src.index(\"GA4_PROPERTY_ID\") < src.index(\"property_id\")" >/dev/null'
ck "Slack asks for the eight narrowest scopes (no channel or private channel history) and the steps agree" \
   'py "from integrations import manifest; m = [x for x in manifest.load_services() if x[\"id\"] == \"slack\"][0]; assert sorted(m[\"scopes\"]) == sorted([\"im:read\",\"im:history\",\"mpim:read\",\"mpim:history\",\"channels:read\",\"groups:read\",\"users:read\",\"search:read\"]); t = \" \".join(m[\"steps\"]); assert \"eight\" in t and \"channels:history\" in t" >/dev/null'
ck "Slack, run against a fake workspace, reads history only of direct messages and never of a channel where you were mentioned" \
   'py "
from integrations import slack, common
import json
calls = []
def fake(method, url, headers, data, timeout):
    from urllib.parse import urlparse, parse_qs
    u = urlparse(url); m = u.path.rsplit(\"/\", 1)[-1]; q = {k: v[0] for k, v in parse_qs(u.query).items()}
    calls.append((m, q.get(\"channel\", \"\")))
    out = {\"auth.test\": {\"ok\": True, \"user_id\": \"U1\"},
           \"conversations.list\": {\"ok\": True, \"channels\": [{\"id\": \"D1\", \"is_im\": True}]},
           \"conversations.info\": {\"ok\": True, \"channel\": {\"last_read\": \"100.0\"}},
           \"conversations.history\": {\"ok\": True, \"messages\": [{\"user\": \"U2\", \"text\": \"hi\", \"ts\": \"200.0\"}]},
           \"users.info\": {\"ok\": True, \"user\": {\"name\": \"sam\"}},
           \"chat.getPermalink\": {\"ok\": True, \"permalink\": \"https://example.slack.com/x\"},
           \"search.messages\": {\"ok\": True, \"messages\": {\"matches\": [{\"channel\": {\"id\": \"C9\", \"name\": \"general\"}, \"ts\": \"300.0\", \"text\": \"ping\", \"permalink\": \"https://example.slack.com/y\"}]}}}[m]
    return 200, json.dumps(out).encode()
common.TRANSPORT = fake; common.SLEEP = lambda s: None
r = slack.fetch({\"SLACK_USER_TOKEN\": \"xoxp-fake\"}, common.load_config())
hist = [c for m, c in calls if m == \"conversations.history\"]
assert hist == [\"D1\"], hist
assert r[\"slack\"][\"unread\"] == 2
" >/dev/null'
ck "the calendar helper is named QuarterdeckAgenda.app and built with bash tools/agenda/build.sh" \
   'py "from integrations import manifest; t = \" \".join([x for x in manifest.load_services() if x[\"id\"] == \"calendar\"][0][\"steps\"]); assert \"QuarterdeckAgenda.app\" in t and \"bash tools/agenda/build.sh\" in t" >/dev/null && grep -q "QuarterdeckAgenda.app" "$HERE/../tools/agenda/build.sh"'

echo
[ "$fails" = 0 ] && echo "  all checks passed" || { echo "  $fails check(s) failed"; exit 1; }
