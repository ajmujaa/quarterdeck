#!/bin/bash
# The harness security checks, each one written to fail on the code as it was before the fix it covers:
#   - the pre-commit hook scans the repository it is installed in, not Quarterdeck itself
#   - every duty that takes a number refuses anything but digits, before it reaches gh, a --jq filter or a path
#   - the data folder is private (0700 dirs, 0600 files), also after a migrate, and a migrate never follows a link
#   - attach takes owner/repo from a folder's .git/config only when it is a plain GitHub name
#   - the fleet hook's backup of ~/.claude/settings.json is 0600
# Later sections (tool lists, outgoing text, checks, git) are added with the fixes they cover.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"

# ---- F7: the pre-commit hook -------------------------------------------------------------------------
FAKEKEY="sk-ant-$(printf 'x%.0s' $(seq 1 30))"
R="$T/hookrepo"; mkdir -p "$R"
git -C "$R" init -q
git -C "$R" config user.name t; git -C "$R" config user.email t@example.invalid
python3 "$REAL/bin/guard.py" install-hook "$R" >/dev/null
printf 'KEY=%s\n' "$FAKEKEY" > "$R/leak.txt"; git -C "$R" add leak.txt
(cd "$R" && git commit -q -m leak >/dev/null 2>&1); hrc=$?
ck "F7 the installed hook refuses a commit that stages a key in the repository it was installed in" '[ "$hrc" != 0 ] && [ -z "$(git -C "$R" log --oneline 2>/dev/null)" ]'
printf 'fine\n' > "$R/ok.txt"; git -C "$R" rm -q --cached leak.txt; git -C "$R" add ok.txt
(cd "$R" && git commit -q -m ok >/dev/null 2>&1); ck "F7 and lets a clean commit through" '[ "$?" = 0 ]'

# ---- R8: a file with a non-ASCII name is scanned (git C-quotes such a name, and the quoted name opened nothing) ----------------------------
NA="$T/nonascii"; mkdir -p "$NA"; git -C "$NA" init -q; git -C "$NA" config user.name t; git -C "$NA" config user.email t@example.invalid
python3 "$REAL/bin/guard.py" install-hook "$NA" >/dev/null
printf 'KEY=%s\n' "$FAKEKEY" > "$NA/clé.txt"; git -C "$NA" add -A
(cd "$NA" && git commit -q -m leak >/dev/null 2>&1); nrc=$?
ck "R8 the pre-commit hook refuses a commit that stages a key in a file named clé.txt" '[ "$nrc" != 0 ] && [ -z "$(git -C "$NA" log --oneline 2>/dev/null)" ]'
scan_out=$(python3 "$REAL/bin/guard.py" "$NA" 2>&1); scan_rc=$?
ck "R8 and the full scan of the repository reports it (and exits non-zero)" '[ "$scan_rc" != 0 ] && grep -q "clé.txt" <<<"$scan_out"'
git -C "$NA" -c core.hooksPath=/dev/null commit -q -m leak >/dev/null 2>&1
hist_out=$(python3 "$REAL/bin/guard.py" --history "$NA" 2>&1); hist_rc=$?
ck "R8 and the history scan finds it under its real name" '[ "$hist_rc" != 0 ] && grep -q "clé.txt" <<<"$hist_out"'

# ---- LOW: a number is digits and nothing else, in every duty -----------------------------------------
st_init assayer caulker infra lookout inspector pilot panel marshal shipwright quartermaster surveyor purser trials
st_registry '["surveyor"]'; st_repo
bad=""
for d in assayer caulker infra lookout inspector pilot marshal quartermaster surveyor; do
  for v in 'x;touch pwn' '1 2' '-1' '7)|(.' '' '0'; do
    : > "$T/claude-calls"; rm -f "$T/gh-calls"
    st_duty "$d" --pr "$v"
    { [ "$RC" != 0 ] && grep -q "takes a number" <<<"$OUT" && [ ! -s "$T/claude-calls" ] && [ ! -e "$T/gh-calls" ] && [ ! -e "$T/work/pwn" ]; } || bad="$bad $d:--pr:[$v]"
  done
done
for d in assayer inspector panel shipwright purser trials; do
  for v in 'x;touch pwn' '1 2' '.id)' '-5'; do
    : > "$T/claude-calls"; rm -f "$T/gh-calls"
    st_duty "$d" --issue "$v"
    { [ "$RC" != 0 ] && grep -q "takes a number" <<<"$OUT" && [ ! -s "$T/claude-calls" ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad $d:--issue:[$v]"
  done
done
ck "every duty that takes --pr or --issue stops on anything but digits, before gh, a model or a shell sees it${bad:+ ($bad)}" '[ -z "$bad" ]'
ck "a number given to bin/fix and bin/cycle is checked too" 'grep -q "need_num \"--issue\"" "$REAL/bin/fix" && grep -q "need_num \"--issue\"" "$REAL/bin/cycle"'

# ---- F8: the data folder is private ---------------------------------------------------------------------
H="$T/privhome"; mkdir -p "$H"
( umask 022; mkdir -p "$H/state" "$H/logs/runs" "$H/workspace" "$H/config"; cp "$REAL/bin/lib.sh" "$H/lib-probe.sh" )
out=$(env -i HOME="$T" PATH="$PATH" QUARTERDECK_DIR="$T" QUARTERDECK_HOME="$H" QUARTERDECK_SECRETS_DIR="$T/nosecrets" bash -c 'umask 022; source "$QUARTERDECK_DIR/bin/lib.sh"; log probe; echo x > "$QUARTERDECK_HOME/logs/runs/r.json"; echo "$(umask)"' 2>&1 | tail -1)
modeof() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }   # GNU first: GNU `stat -f FMT FILE` prints the file system's details for FILE before it fails on FMT
ck "F8 after lib.sh runs, the data folder and its working folders are 0700 and a file it writes is 0600 (even from umask 022)" '[ "$(modeof "$H")" = 700 ] && [ "$(modeof "$H/state")" = 700 ] && [ "$(modeof "$H/logs/runs")" = 700 ] && [ "$(modeof "$H/workspace")" = 700 ] && [ "$(modeof "$H/logs/runs/r.json")" = 600 ] && [ "$(modeof "$H/logs/quarterdeck.log")" = 600 ] && [ "$out" = 0077 ]'

M="$T/oldprog"; mkdir -p "$M/state" "$M/workspace" "$M/config" "$M/outside"
echo '{"a":1}' > "$M/state/runs.json"; chmod 644 "$M/state/runs.json"; chmod 755 "$M/state"
echo "TOPSECRET_FROM_LINK" > "$M/outside/secret.txt"
ln -s "$M/outside/secret.txt" "$M/state/linked.txt"; ln -s "$M/outside" "$M/workspace/linkdir"
echo '{}' > "$M/config/projects.json"; ln -sf "$M/outside/secret.txt" "$M/config/integrations.json"
mig=$(python3 - "$REAL/bin" "$M" "$T/newhome" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import home
ok, lines = home.migrate(sys.argv[2], sys.argv[3], apply=True, force=True)
print(ok)
PY
)
N="$T/newhome"
ck "F8 migrate: the data folder is 0700, copied folders are 0700 and copied files 0600, whatever the old modes were" '[ "$mig" = True ] && [ "$(modeof "$N")" = 700 ] && [ "$(modeof "$N/state")" = 700 ] && [ "$(modeof "$N/state/runs.json")" = 600 ]'
ck "LOW migrate does not follow a symlink: a linked secret is not copied (file, folder, or a listed config file)" '[ ! -e "$N/state/linked.txt" ] && [ ! -e "$N/workspace/linkdir" ] && [ ! -e "$N/config/integrations.json" ] && ! grep -rq TOPSECRET_FROM_LINK "$N"'

# ---- F6 (part): attach takes the repo name from untrusted text only when it is a plain GitHub name -------------
bad=$(python3 - "$REAL/bin" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import attach
def r(url): return attach.repo_of({"git": {"origin": url}})
good = {"https://github.com/acme/widget.git": "acme/widget", "git" + "@github.com:acme/widget": "acme/widget", "https://github.com/a-b/c.d_e": "a-b/c.d_e"}
evil = ["https://github.com/-Rx/y", "https://github.com/acme/$(touch pwn)", "https://github.com/acme/w;id", "https://github.com/ac\"me/w", "https://github.com/acme/-x",
        "https://github.com/../etc", "https://github.com/a/b'c", "https://github.com/" + "a" * 40 + "/r", "https://github.com/acme/" + "r" * 101, "https://github.com/ac me/x"]
bad = [u for u, w in good.items() if r(u) != w] + [u for u in evil if r(u) != ""]
print(" ".join(bad))
PY
)
ck "F6 attach: repo_of accepts plain owner/name and returns nothing for a leading dash, quote, \$, ;, .., or an over-long name${bad:+ ($bad)}" '[ -z "$bad" ]'

# ---- F8: the fleet hook's backup of the settings file is private -------------------------------------------------
S="$T/claude-settings.json"; echo '{}' > "$S"; chmod 644 "$S"
( umask 022; CLAUDE_SETTINGS_FILE="$S" QUARTERDECK_HOME="$T" bash "$REAL/bin/fleet-hook.sh" install >/dev/null 2>&1 )
bk=$(ls "$S".quarterdeck-bak-* 2>/dev/null | head -1)
ck "F8 fleet-hook install: the backup of the settings file is 0600 (it can hold tokens), as is the file itself" '[ -n "$bk" ] && [ "$(modeof "$bk")" = 600 ] && [ "$(modeof "$S")" = 600 ]'


# ---- F3 / F4 / F9: what a model call may read, write and run ---------------------------------------------------
st_init surveyor
st_registry '["surveyor"]'; st_repo
DH="$T/datahome"; mkdir -p "$DH/state" "$DH/config" "$DH/logs/runs" "$DH/workspace"; cp "$T/config/projects.json" "$DH/config/"
WP="$(cd "$T/work" && pwd -P)"
cr() { # cr <tools> [deny] — claude_run from lib.sh with a data folder of its own; the call lands in claude-calls
  : > "$T/claude-calls"
  ( export QUARTERDECK_HOME="$DH"; source "$T/bin/lib.sh"; claude_run "$T/work" "the prompt" "$@" >/dev/null 2>&1 ); CRRC=$?
}
last() { tail -1 "$T/claude-calls"; }

cr; c=$(last)
ck "F3 a default call has Read, Grep and Glob and no shell at all; Read is the working folder only; Grep and Glob get no allow rule that would lift them off it" \
   'jq -e --arg w "$WP" ".tools == \"Read,Grep,Glob\" and .allow == (\"Read(/\" + \$w + \"/**)\")" <<<"$c" >/dev/null'
ck "F9 the default tool list holds no git and no gh (the harness fetches what the model reads)" '! jq -r .allow <<<"$c" | grep -qE "git|gh "'

# the deny rules: every private path under the data folder AND the program folder, home secrets, secret file names
rules_ok=$(python3 - "$c" "$DH" "$T" <<'PY'
import json, os, sys
c = json.loads(sys.argv[1]); dh, prog = sys.argv[2], sys.argv[3]; home = os.environ["HOME"]
deny = set(c["deny"].split(","))
need = []
for base in (dh, prog):
    for p in ("state/connectors/**", "state/capture.jsonl", "state/agenda-status.json", "state/attention.json*", "state/intent.jsonl*", "state/hand-runs.jsonl*", "state/rhythm-tasks.json*", "state/project-status.json*", "state/dashboard.token", "state/dashboard.sessions.json*", "state/pair/**"):
        need.append(f"Read(/{base}/{p})")
for p in (".config/quarterdeck", ".config/gh", ".ssh", ".aws", ".gnupg", ".npmrc", ".netrc", ".docker/config.json", "Library/Keychains"):
    need.append(f"Read(/{home}/{p})")
need += ["Read(**/.env*)", "Read(**/*.pem)", "Read(**/*.key)", "Read(**/*.p12)", "Edit(**/.env*)", "Edit(**/.git/**)", "Edit(**/.claude/**)", "Edit(**/.mcp.json)",
         "Bash(git*)", "Bash(gh*)", "Bash(curl*)", "Bash(ssh*)", "Bash(security*)", "WebFetch", "WebSearch", "NotebookEdit"]
print(" ".join(n for n in need if n not in deny))
PY
)
ck "F4 the deny list holds the data folder's private files (not only the program folder's), ~/.ssh ~/.aws ~/.gnupg ~/.config/gh ~/.npmrc ~/.netrc ~/.docker Keychains, .env* *.pem *.key *.p12, and git, gh, curl, ssh${rules_ok:+ — MISSING: $rules_ok}" '[ -z "$rules_ok" ]'

cr "Read,Edit,Write,Grep,Glob,Bash(npm run*),Bash(node*)"; cb=$(last)
parity=$(python3 - "$cb" "$WP" <<'PY'
import json, sys
c = json.loads(sys.argv[1]); wd = sys.argv[2]
strip = lambda p: p[:-3] if p.endswith("/**") else p
rules = {strip(r[len("Read(/"):-1]) for r in c["deny"].split(",") if r.startswith("Read(//")}
sb = json.loads(c["settings"])["sandbox"]
home = __import__("os").environ["HOME"]
broad = ("Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Public")
# the sandbox alone also denies the personal folders (only where the working folder is not inside them) and the secret names under the home folder: those are not Read rules on purpose
only_sb = lambda p: p.startswith(home + "/") and (p[len(home) + 1:].split("/")[0] in broad or (p[len(home) + 1:].startswith("Library/") and not p.startswith(home + "/Library/Keychains")) or p.startswith(home + "/**/"))
sand = {strip(p) for p in sb["filesystem"]["denyRead"] if not p.startswith(wd) and not only_sb(p)}
print("rules-only: " + " ".join(sorted(rules - sand)) + " | sandbox-only: " + " ".join(sorted(sand - rules)) if rules != sand else "same")
print("escape-closed" if sb["enabled"] is True and sb["allowUnsandboxedCommands"] is False else "ESCAPE-OPEN")
print("wd-secrets" if all(any(p.startswith(wd) and n in p for p in sb["filesystem"]["denyRead"]) for n in (".env*", "*.pem", "*.key")) else "NO-WD-SECRETS")
PY
)
ck "F4 the Read deny rules and the sandbox's denyRead are the same list (they differ if either is built from one folder only)" '[ "$(sed -n 1p <<<"$parity")" = same ]'
# round 4: the add-on folder (code the dashboard imports) is on the deny-write rules AND the sandbox's denyWrite: one list, two renderings, neither may lack it
wparity=$(python3 - "$cb" "$DH" <<'PY'
import json, sys
c = json.loads(sys.argv[1]); dh = sys.argv[2]
rules = {r[len("Edit(/"):-1][:-3] if r.endswith("/**)") else r[len("Edit(/"):-1] for r in c["deny"].split(",") if r.startswith("Edit(//") and "/addons" in r}
sb = {p for p in json.loads(c["settings"])["sandbox"]["filesystem"]["denyWrite"] if p.endswith("/addons")}
print("same" if rules == sb and (dh + "/addons") in sb else "differ: " + repr(sorted(rules)) + " vs " + repr(sorted(sb)))
PY
)
ck "R4 the add-on folder is in the model's Edit deny rules and in the sandbox's denyWrite, the same path in both${wparity:+ ($wparity)}" '[ "$wparity" = same ]'
ck "F9 a call with a shell runs in the sandbox with no unsandboxed escape, and the working folder's own .env/*.pem/*.key are hidden from its commands" '[ "$(sed -n 2p <<<"$parity")" = escape-closed ] && [ "$(sed -n 3p <<<"$parity")" = wd-secrets ]'
ck "R4/R-LOW the sandbox fails closed (failIfUnavailable), the worktree's own .git file is closed to sandboxed writes, and Edit/Write are denied on it (a linked worktree's .git is a file; Edit(**/.git/**) does not match it)" \
   'jq -e --arg w "$WP" "(.settings | fromjson | .sandbox | .failIfUnavailable == true and (.filesystem.denyWrite | index(\$w + \"/.git\") != null)) and (.deny | split(\",\") | (index(\"Edit(/\" + \$w + \"/.git)\") != null) and (index(\"Edit(**/.git)\") != null))" <<<"$cb" >/dev/null'
cr "Read,Edit,Write,Grep,Glob,Bash(npm run*)"; cc=$(last)
ck "F9 the sandbox is on for every call that has a shell: the gh exception is gone" 'jq -e ".settings | fromjson | .sandbox.enabled" <<<"$cc" >/dev/null '
ck "F3 Edit and Write are scoped to the working folder, not the disk" 'jq -e --arg w "$WP" ".allow | contains(\"Edit(/\" + \$w + \"/**)\") and contains(\"Write(/\" + \$w + \"/**)\")" <<<"$cc" >/dev/null'

bad=""
for t in 'Read,Bash(git diff*)' 'Read,Bash(git log*)' 'Read,Bash(gh pr view*)' 'Read,Bash' 'Read,Bash(curl x*)' 'Read,Bash(ssh h)' 'Read,WebFetch' 'Read,Bash(*)' 'Read,Bash(sudo ls)' 'Read,Bash(security find-generic-password*)'; do
  cr "$t"; { [ "$CRRC" != 0 ] && [ ! -s "$T/claude-calls" ]; } || bad="$bad [$t]"
done
ck "F9 a tool list that hands the model git, gh, curl, ssh, sudo, WebFetch or an open shell is refused before any model runs${bad:+ (not refused:$bad)}" '[ -z "$bad" ]'

# the model's environment: no secret from ~/.config/quarterdeck/env, no GH_TOKEN, no QUARTERDECK_*
mkdir -p "$T/sec"; printf 'export DECOY_FROM_ENVFILE=leak-1\nexport GH_TOKEN=ghp_decoy\n' > "$T/sec/env"
printf '#!/bin/bash\nenv | sort > "%s/stub-env"\njq -n %s\n' "$T" "'{result:\"ok\", total_cost_usd:0, num_turns:1, usage:{}, modelUsage:{}}'" > "$T/envstub"; chmod +x "$T/envstub"
( unset QUARTERDECK_CLAUDE_ENV; export QUARTERDECK_HOME="$DH" QUARTERDECK_SECRETS_DIR="$T/sec" CLAUDE_BIN="$T/envstub" QD_DECOY_SECRET=leak-2 QUARTERDECK_NOTIFY_CMD='curl evil' ANTHROPIC_API_KEY=keep-me AWS_SECRET_ACCESS_KEY=leak-3
  source "$T/bin/lib.sh"; claude_run "$T/work" p >/dev/null 2>&1 )
ck "F3 the model's process gets no secret: nothing from ~/.config/quarterdeck/env, no GH_TOKEN, no QUARTERDECK_*, no cloud keys; it keeps HOME, PATH and the subprocess scrub, and (ticket #38) a call billed to the plan gets no ANTHROPIC_API_KEY from the owner's shell" \
   '[ -s "$T/stub-env" ] && ! grep -qE "DECOY_FROM_ENVFILE|GH_TOKEN|QD_DECOY_SECRET|^QUARTERDECK_|AWS_SECRET|leak-|keep-me" "$T/stub-env" && grep -q "^HOME=" "$T/stub-env" && grep -q "^PATH=" "$T/stub-env" && ! grep -q "^ANTHROPIC_API_KEY=" "$T/stub-env" && grep -q "^CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1" "$T/stub-env"'

# ---- outgoing text ------------------------------------------------------------------------------------------------
SK="sk-ant-$(printf 'q%.0s' $(seq 1 30))"; GHP="ghp_$(printf 'a%.0s' $(seq 1 36))"
gp() { rm -f "$T/gh-calls"; ( export QUARTERDECK_HOME="$DH"; source "$T/bin/lib.sh"; gh_post 10 "$@" >/dev/null 2>&1 ); GPRC=$?; }
bad=""
for body in "found $SK in .env" "token $GHP here" "$(printf AKIA%s ABCDEFGHIJKLMNOP) is the key" "-----BEGIN OPENSSH PRIV""ATE KEY-----" "see https://user:hunter2xyz@example.com/x" "password = Abcdefghij1234567890Klmnopqr" "Authorization: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"; do
  gp pr comment 5 -R x/tp --body "$body"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [body:${body:0:18}]"
done
gp issue create -R x/tp --title "leak $SK" --body fine; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [title]"
printf 'ok\n%s\n' "$GHP" > "$T/bodyfile"; gp pr create -R x/tp --title t --body-file "$T/bodyfile"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [body-file]"
gp pr comment 5 -R x/tp --body-file -; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [stdin body]"
ck "F3 gh_post refuses a body, title or body file that holds an Anthropic/GitHub/AWS key, a private key, a JWT, a password in a URL or a labelled secret, and calls gh not at all${bad:+ — NOT REFUSED:$bad}" '[ -z "$bad" ]'
# R-LOW: the other spellings of the same arguments, labels and branch names, and what goes into a commit
bad=""
gp pr comment 5 -R x/tp "--body=found $SK in .env"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [--body=]"
gp issue create -R x/tp "--title=leak $SK" --body fine; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [--title=]"
gp pr comment 5 -R x/tp "-bfound $SK"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [-bTEXT]"
printf 'ok\n%s\n' "$GHP" > "$T/bodyfile2"
gp pr create -R x/tp --title t "--body-file=$T/bodyfile2"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [--body-file=]"
gp pr create -R x/tp --title t "-F$T/bodyfile2"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [-FPATH]"
gp pr create -R x/tp --title t --body fine --label "bug-$SK"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [label]"
gp pr create -R x/tp --title t --body fine --head "feat-$GHP"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [head branch]"
gp pr create -R x/tp --title t --body fine --label bug; { [ "$GPRC" = 0 ] && grep -q "pr create" "$T/gh-calls"; } || bad="$bad [clean one refused]"
ck "R-LOW gh_post also refuses --body=..., --title=..., -bTEXT, --body-file=PATH, -FPATH, and a credential in a label or a branch name; a clean call goes through${bad:+ — WRONG:$bad}" '[ -z "$bad" ]'
CR="$T/commitrepo"; git init -q -b main "$CR"; git -C "$CR" config user.name t; git -C "$CR" config user.email t@example.invalid; echo a > "$CR/a"; git -C "$CR" add a
( source "$T/bin/lib.sh"; safe_git -C "$CR" commit -q -m "fix: handles $SK" >/dev/null 2>&1; echo $? > "$T/cm-rc1"; safe_git -C "$CR" commit -q -m "fix: a clean message" >/dev/null 2>&1; echo $? > "$T/cm-rc2"
  safe_git_guard 20 -C "$CR" push -q origin "HEAD:refs/heads/x-$GHP" >/dev/null 2>&1; echo $? > "$T/cm-rc3" )
ck "R-LOW a commit message or a pushed branch name that holds a credential is refused (rc 3, nothing committed); a clean message commits" \
   '[ "$(cat "$T/cm-rc1")" = 3 ] && [ "$(cat "$T/cm-rc2")" = 0 ] && [ "$(cat "$T/cm-rc3")" = 3 ] && [ "$(git -C "$CR" log --format=%s | tr "\n" "|")" = "fix: a clean message|" ]'
echo "api = $SK" > "$CR/leaky.txt"; git -C "$CR" add leaky.txt
( source "$T/bin/lib.sh"; safe_git -C "$CR" commit -q -m "chore: add a file" >/dev/null 2>&1; echo $? > "$T/cm-rc4" )
ck "R-LOW and a commit whose staged lines add a credential is refused whatever its message says (nothing is committed)" '[ "$(cat "$T/cm-rc4")" = 3 ] && ! git -C "$CR" log --format=%s | grep -q "add a file"'
git -C "$CR" rm -q --cached leaky.txt; rm -f "$CR/leaky.txt"
# round 8 (L7): gh takes F inside a group of short flags too; (L8) git takes a message file in stuck, grouped and abbreviated spellings
bad=""
gp pr create -R x/tp --title t --head h -dF "$T/bodyfile2"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [-dF PATH]"
gp pr create -R x/tp --title t --head h "-dF$T/bodyfile2"; { [ "$GPRC" = 3 ] && [ ! -e "$T/gh-calls" ]; } || bad="$bad [-dFPATH]"
printf 'a clean body\n' > "$T/okbody2"; gp pr create -R x/tp --title t --head h -dF "$T/okbody2"; { [ "$GPRC" = 0 ] && grep -q "pr create" "$T/gh-calls"; } || bad="$bad [clean -dF refused]"
ck "L7 gh_post scans a body file named after combined short flags (-dF PATH, -dFPATH), and a clean one goes through${bad:+ — WRONG:$bad}" '[ -z "$bad" ]'
CR8="$T/commitrepo8"; git init -q -b main "$CR8"; git -C "$CR8" config user.name t; git -C "$CR8" config user.email t@example.invalid; echo a > "$CR8/a"; git -C "$CR8" add a
printf 'fix: handles %s\n' "$SK" > "$T/msgfile"; printf 'fix: a clean message\n' > "$T/okmsg"; bad=""
for form in "-F$T/msgfile" "-qF:$T/msgfile" "-qF$T/msgfile" "--fil=$T/msgfile" "--fil:$T/msgfile" "-t$T/msgfile" "--te=$T/msgfile"; do
  case "$form" in -qF:*) args=(-qF "${form#-qF:}") ;; --fil:*) args=(--fil "${form#--fil:}") ;; *) args=("$form") ;; esac
  ( source "$T/bin/lib.sh"; safe_git -C "$CR8" commit -q "${args[@]}" >/dev/null 2>&1; echo $? > "$T/cmrc" )
  { [ "$(cat "$T/cmrc")" = 3 ] && [ -z "$(git -C "$CR8" log --oneline 2>/dev/null)" ]; } || bad="$bad [${form%%/*}]"
done
( source "$T/bin/lib.sh"; safe_git -C "$CR8" commit -q -mtest-with-t >/dev/null 2>&1; echo $? > "$T/cmrc" )
[ "$(cat "$T/cmrc")" = 0 ] || bad="$bad [-mtext refused]"
( source "$T/bin/lib.sh"; safe_git -C "$CR8" commit -q --allow-empty -qF "$T/okmsg" >/dev/null 2>&1; echo $? > "$T/cmrc" )
[ "$(cat "$T/cmrc")" = 0 ] || bad="$bad [clean -qF refused]"
ck "L8 safe_git commit scans a message file in every spelling git takes (-FPATH, -qF PATH, -qFPATH, --fil=, --fil PATH, -tPATH, --te=); -mtext and a clean file commit${bad:+ — WRONG:$bad}" '[ -z "$bad" ]'
printf 'Fixes the crash.\n\nThe code does token =getTokenFromEnvironmentVariable() and then password = options.password || DEFAULT_VALUE.\nSee https://example.com/docs and sk-learn.\n' > "$T/ok-body"
gp pr comment 5 -R x/tp --body "$(cat "$T/ok-body")"; r1=$GPRC; g1=$(grep -c "pr comment" "$T/gh-calls" 2>/dev/null)
gp pr comment 5 -R x/tp --body-file "$T/ok-body"; r2=$GPRC
ck "  and lets ordinary review prose through (code that names a token or password is not a secret)" '[ "$r1" = 0 ] && [ "$g1" = 1 ] && [ "$r2" = 0 ]'

# a duty that posts what the model wrote: the secret the model repeated is not posted
st_pr 1 feat-x app.py 'x = 1'
st_noreplies; st_reply default "FINDINGS_JSON: [{\"file\":\"app.py\",\"line\":1,\"severity\":\"major\",\"title\":\"a key is committed\",\"body\":\"the file holds $SK\"}]
ADR: searched none
VERDICT: FINDINGS 1"
echo '{}' > "$T/state/reviewed.json"; rm -f "$T/gh-calls"
st_duty surveyor --pr 1 --apply
ck "F3 the surveyor, told by the model to post a key it saw, posts nothing: no gh comment, the run is an ERROR, the key is in no log line and not in the run ledger" 'no_gh_writes && [ "$(last_verdict)" = ERROR ] && ! grep -q "$SK" "$T"/logs/*.log "$T/state/runs.json" 2>/dev/null'
ck "F3 the surveyor puts the diff in the prompt as untrusted data (the model has no gh)" 'grep -q "BEGIN UNTRUSTED diff of pull request #1" "$T/claude-calls" && ! grep -q "gh pr diff" <<<"$(jq -r .allow "$T/claude-calls" | head -1)"'

# ---- no duty calls plain git on a project folder --------------------------------------------------------------------
raw=$(grep -nE '(^|[ (;&|"{`])git (-C|-c|fetch|push|pull|worktree|rev-parse|clone|add|commit|reset|clean|ls-remote|ls-files|config|status|diff|log|show|for-each-ref|grep|remote|symbolic-ref|branch|merge|apply|stash|init)( |$)' "$REAL"/duties/*.sh "$REAL"/bin/fix "$REAL"/bin/cycle "$REAL"/bin/decisions.sh "$REAL"/bin/qtdeck | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' | grep -vE '(say|die|log|echo|printf) .*git (-C|diff|log|status|config|checkout|commit)' | grep -vE 'Bash\(git' | cut -c1-140)
ck "F6 every git command a duty, bin/fix, bin/cycle or bin/qtdeck runs goes through safe_git or SAFE_GIT (no hooks, no fsmonitor, no repo ssh command or credential helper)${raw:+: $(head -3 <<<"$raw")}" '[ -z "$raw" ]'


# ---- F2/F6: what attaching a folder proposes, and what it says about the folder ----------------------------------
AT="$T/attachme"; mkdir -p "$AT/.claude" "$AT/.github/workflows" "$AT/src"
echo '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"touch x"}]}]}}' > "$AT/.claude/settings.json"
echo '{"mcpServers":{}}' > "$AT/.mcp.json"; echo '{"scripts":{"test":"vitest run"}}' > "$AT/package.json"; echo 'on: push' > "$AT/.github/workflows/ci.yml"
att=$(python3 - "$REAL/bin" "$AT" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import attach, scan
prop = attach.propose(scan.scan(sys.argv[2]))
f = prop["entry"]["forbidden_paths"]
need = [".github/", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", ".npmrc", "tsconfig", "Makefile", ".husky/", "scripts/", "Dockerfile", "docker-compose", "pyproject.toml", "setup.py", "requirements"]
print("missing:" + " ".join(n for n in need if n not in f))
print("warning:" + ("ok" if "influence what runs" in prop["warning"] and ".mcp.json" in prop["warning"] and ".claude/settings.json" in prop["warning"] else "BAD"))
print("agent:" + ("ok" if any(".mcp.json" in a for a in prop["agent_config"]) and any("settings.json" in a for a in prop["agent_config"]) else "BAD"))
PY
)
ck "F2 attach proposes the build, CI and dependency files as forbidden_paths for a new project${att:+ ($(sed -n 1p <<<"$att"))}" '[ "$(sed -n 1p <<<"$att")" = "missing:" ]'
ck "F6 the proposal carries a plain warning that attaching lets the folder influence what runs, and lists the agent set-up it found (.claude/settings.json, .mcp.json) for the page to show" '[ "$(sed -n 2p <<<"$att")" = "warning:ok" ] && [ "$(sed -n 3p <<<"$att")" = "agent:ok" ]'


# ---- F6: a registered folder's own settings, hooks and git config do not run ----------------------------------------
cr; c=$(last)
ck "F6 claude_run loads no settings file and no MCP server from the working folder: --setting-sources is empty and --strict-mcp-config is set" \
   'jq -e "(.argv | index(\"--strict-mcp-config\") != null) and (.argv[(.argv | index(\"--setting-sources\")) + 1] == \"\") and (.argv | index(\"dontAsk\") != null)" <<<"$c" >/dev/null'

# a repository that tries every way git runs the repository's own commands
HR="$T/hostile"; mkdir -p "$HR"; git -C "$HR" init -q; git -C "$HR" config user.name t; git -C "$HR" config user.email t@example.invalid
echo hi > "$HR/a.txt"; git -C "$HR" add a.txt; git -C "$HR" commit -q -m one
mkdir -p "$HR/.git/hooks"
for h in post-checkout post-merge pre-commit reference-transaction; do printf '#!/bin/sh\ntouch "%s/ran-%s"\n' "$T" "$h" > "$HR/.git/hooks/$h"; chmod +x "$HR/.git/hooks/$h"; done
printf '#!/bin/sh\ntouch "%s/ran-fsmonitor"\nprintf "\\0"\n' "$T" > "$HR/fsm.sh"; chmod +x "$HR/fsm.sh"
git -C "$HR" config core.fsmonitor "$HR/fsm.sh"
git -C "$HR" config core.sshCommand "touch $T/ran-ssh; false"
git -C "$HR" config credential.helper "!touch $T/ran-cred; echo"
git -C "$HR" config core.hooksPath "$HR/.git/hooks"
rm -f "$T"/ran-*
( source "$T/bin/lib.sh"; worktree_at "$HR" "$T/hostile-wt" HEAD; safe_git -C "$T/hostile-wt" status >/dev/null 2>&1; safe_git -C "$HR" status >/dev/null 2>&1
  echo more >> "$HR/a.txt"; safe_git -C "$HR" add a.txt; safe_git -C "$HR" commit -q -m two >/dev/null 2>&1; guard 20 "${SAFE_GIT[@]}" -C "$HR" ls-remote ssh://nohost.invalid/x >/dev/null 2>&1; true )
safe_ran=$(ls "$T"/ran-* 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')
rm -f "$T"/ran-*; git -C "$T/hostile-wt" worktree remove --force "$T/hostile-wt" >/dev/null 2>&1; rm -rf "$T/hostile-wt"
git -C "$HR" worktree prune
git -C "$HR" worktree add -q --detach "$T/hostile-wt2" HEAD >/dev/null 2>&1; git -C "$HR" status >/dev/null 2>&1
plain_ran=$(ls "$T"/ran-* 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')
ck "F6 control: plain git on that folder DOES run its hooks and its fsmonitor command (so the next check means something)" 'grep -q ran-post-checkout <<<"$plain_ran" && grep -q ran-fsmonitor <<<"$plain_ran"'
ck "F6 safe_git on the same folder (worktree add, status, add, commit, ls-remote) runs no hook, no fsmonitor command, no ssh command, no credential helper${safe_ran:+ — RAN: $safe_ran}" '[ -z "$safe_ran" ]'
ck "F6 the harness still commits through safe_git (the commit exists)" '[ "$(git -C "$HR" log --format=%s -1)" = two ]'


# ---- R4: a model that repoints the worktree's `.git` file is caught before the harness's next git command ------------------------------
# In a linked worktree `.git` is a FILE ("gitdir: <repo>/.git/worktrees/<name>"). A model that rewrites it points every later harness git command at
# a repository it made, whose config can name a signing program (commit.gpgsign + gpg.program), run outside every sandbox with the owner's environment.
RS="$T/r4src"; git init -q -b main "$RS"; git -C "$RS" config user.name t; git -C "$RS" config user.email t@example.invalid
echo one > "$RS/a.txt"; git -C "$RS" add a.txt; git -C "$RS" commit -q -m one
RW="$T/r4wt"; ( source "$T/bin/lib.sh"; worktree_at "$RS" "$RW" HEAD )
GOODGIT=$(cat "$RW/.git")
printf '#!/bin/sh\ntouch "%s/ran-r4-gpg"\nexit 1\n' "$T" > "$RW/evil.sh"; chmod +x "$RW/evil.sh"
r4_attack() { # r4_attack — what the model could do if it could write the file: a repository of its own, borrowing the real objects
  rm -rf "$RW/.fg"; mkdir -p "$RW/.fg/refs/heads" "$RW/.fg/objects/info"
  echo "ref: refs/heads/x" > "$RW/.fg/HEAD"; echo "$RS/.git/objects" > "$RW/.fg/objects/info/alternates"
  printf '[core]\n\trepositoryformatversion = 0\n[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = %s\n[user]\n\tname = t\n\temail = t@example.invalid\n' "$RW/evil.sh" > "$RW/.fg/config"
  printf 'gitdir: %s/.fg\n' "$RW" > "$RW/.git"
}
r4_attack; rm -f "$T/ran-r4-gpg"
( source "$T/bin/lib.sh"; echo y > "$RW/b.txt"; safe_git -C "$RW" add -A >/dev/null 2>&1; safe_git -C "$RW" commit -q -m evil >/dev/null 2>&1; safe_git -C "$RW" rev-parse HEAD >"$T/r4-rev" 2>&1; echo $? >"$T/r4-rc" )
ck "R4 with the .git file repointed, the harness's next safe_git is REFUSED (nonzero, says so) and runs no signing program" '[ ! -e "$T/ran-r4-gpg" ] && [ "$(cat "$T/r4-rc")" != 0 ] && grep -qi "repointed\|changed" "$T/r4-rev"'
( source "$T/bin/lib.sh"; guard 20 true; safe_git_guard 20 -C "$RW" push -q origin HEAD >"$T/r4-push" 2>&1; echo $? >"$T/r4-push-rc" )
ck "R4 and so is a push through the guarded wrapper" '[ "$(cat "$T/r4-push-rc")" != 0 ] && [ ! -e "$T/ran-r4-gpg" ]'
printf '%s\n' "$GOODGIT" > "$RW/.git"
( source "$T/bin/lib.sh"; safe_git -C "$RW" rev-parse HEAD >"$T/r4-rev2" 2>&1; echo $? >"$T/r4-rc2" )
ck "R4 control: with the .git file as the harness wrote it, safe_git works as before" '[ "$(cat "$T/r4-rc2")" = 0 ]'
# and independent of the pin: signing is off in SAFE_GIT, so a repository whose own config asks for a signing program does not get it run
# (a gpg.program in the repository's config is now refused outright, see R5; this is the other half: commit.gpgsign alone, with a `gpg` on the PATH)
mkdir -p "$T/fakebin"; printf '#!/bin/sh\ntouch "%s/ran-r4-gpg"\nexit 1\n' "$T" > "$T/fakebin/gpg"; chmod +x "$T/fakebin/gpg"
rm -f "$T/ran-r4-gpg"; git -C "$RS" config commit.gpgsign true
( source "$T/bin/lib.sh"; export PATH="$T/fakebin:$PATH"; echo z > "$RW/c.txt"; safe_git -C "$RW" add -A >/dev/null 2>&1; safe_git -C "$RW" -c user.name=t -c user.email=t@e commit -q -m signed >"$T/r4-gpg" 2>&1; echo $? >"$T/r4-gpg-rc" )
ck "R4 SAFE_GIT turns signing off (commit.gpgsign, tag.gpgsign): a repository whose config asks for a signing program does not run it" '[ ! -e "$T/ran-r4-gpg" ] && [ "$(cat "$T/r4-gpg-rc")" = 0 ]'
rm -f "$T/ran-r4-gpg"

# ---- R5: a repository whose own config makes git run programs is refused, in every duty and every tool -------------------------------------
# git runs programs a repository's .git/config and .gitattributes name: clean/smudge filters (add, status, worktree add), textconv (diff, log -p, blame),
# a signing program, an external diff; url.<x>.insteadOf redirects a fetch; a branch name starting with a dash becomes an option (--upload-pack=...).
# SAFE_GIT's -c flags reach hooks, fsmonitor, ssh, ext::, signing and the pager; nothing reaches filters one by one. So such a repository is not touched.
cp "$T/config/projects.json" "$DH/config/projects.json"
r5_repo() { # r5_repo <name> -> a repository with a tracked .txt file modified since its last commit, and .gitattributes naming a filter and a textconv
  local r="$T/r5-$1"; rm -rf "$r"; git init -q -b main "$r"; git -C "$r" config user.name t; git -C "$r" config user.email t@example.invalid
  printf 'hello\n' > "$r/a.txt"; printf '*.txt filter=pwn diff=pwn\n' > "$r/.gitattributes"; git -C "$r" add -A; git -C "$r" commit -q -m one; printf 'more\n' >> "$r/a.txt"
  printf '%s' "$r"
}
r5_gate() { # r5_gate <repo> [project] — acquire_lock's gate for that folder; prints the exit status; the message is in $T/r5-out
  ( export QUARTERDECK_HOME="$DH" QUARTERDECK_PROJECT="${2:-tp}" QUARTERDECK_WORKDIR="$1"; source "$T/bin/lib.sh"; acquire_lock "r5-gate-test" ) >"$T/r5-out" 2>&1; echo $?
}
HG=$(r5_repo gate); ok0=$(r5_gate "$HG")
ck "R5 control: a repository with a plain config passes the gate" '[ "$ok0" = 0 ]'
bad=""
for kv in "filter.pwn.smudge=touch $T/ran-r5-smudge" "filter.pwn.clean=touch $T/ran-r5-clean" "diff.pwn.textconv=touch $T/ran-r5-textconv" "diff.external=$T/evil.sh" \
          "merge.pwn.driver=$T/evil.sh" "gpg.program=$T/evil.sh" "gpg.ssh.program=$T/evil.sh" "gpg.openpgp.program=$T/evil.sh" "gpg.x509.program=$T/evil.sh" \
          "url.https://evil.example/.insteadOf=https://github.com/" "include.path=$T/extra.cfg" "credential.https://github.com.helper=!touch $T/ran-r5-cred" \
          "core.gitProxy=$T/evil.sh" "core.attributesFile=$T/attr" "core.worktree=$T" "remote.origin.uploadpack=$T/evil.sh" "remote.origin.vcs=evil" "pager.diff=$T/evil.sh" "core.editor=$T/evil.sh"; do
  k=${kv%%=*}; v=${kv#*=}
  R=$(r5_repo gate); git -C "$R" config "$k" "$v"
  rc=$(r5_gate "$R"); { [ "$rc" != 0 ] && grep -q "git settings of its own" "$T/r5-out"; } || bad="$bad [$k]"
done
ck "R5 each of filter smudge/clean, textconv, external diff, merge driver, every gpg program, insteadOf, include, a URL credential helper, gitProxy, attributesFile, core.worktree, uploadpack, vcs, pager, editor makes the gate REFUSE the folder${bad:+ — NOT REFUSED:$bad}" '[ -z "$bad" ]'
R=$(r5_repo gate); git -C "$R" config core.hooksPath .husky; git -C "$R" config core.fsmonitor "$T/evil.sh"; git -C "$R" config core.sshCommand "touch $T/ran-r5-ssh"; git -C "$R" config credential.helper "!touch $T/ran-r5-cred"
ck "R5 and keys the SAFE_GIT flags already switch off (hooksPath, fsmonitor, sshCommand, an unscoped credential.helper) are not a reason to refuse (husky sets hooksPath)" '[ "$(r5_gate "$R")" = 0 ]'
R=$(r5_repo gate); git -C "$R" config filter.lfs.clean "git-lfs clean -- %f"; git -C "$R" config filter.lfs.smudge "git-lfs smudge -- %f"; git -C "$R" config filter.lfs.process "git-lfs filter-process"
ck "R5 the three canonical Git LFS filter lines are allowed" '[ "$(r5_gate "$R")" = 0 ]'
R=$(r5_repo gate); git -C "$R" config filter.lfs.clean "git-lfs clean -- %f; touch $T/ran-r5-lfs"
ck "R5 but not an LFS-looking filter with anything else in it" '[ "$(r5_gate "$R")" != 0 ]'
R=$(r5_repo gate); git -C "$R" config filter.pwn.clean "touch $T/ran-r5-clean"
jq '.tp.trusted_git_config = true' "$DH/config/projects.json" > "$T/pj.tmp" && cp "$T/pj.tmp" "$DH/config/projects.json"
ck "R5 the registry's trusted_git_config: true is the owner's explicit opt-out, and the only one" '[ "$(r5_gate "$R")" = 0 ]'
cp "$T/config/projects.json" "$DH/config/projects.json"
# a hostile default branch (from an untrusted .git/HEAD or refs/remotes/origin/HEAD) is not a branch name
bad=""
for b in '--upload-pack=/tmp/evil.sh' '-x' 'a..b' 'a b' 'a;b' 'a$(id)' '/x' 'x/' 'x.lock' ''; do
  python3 "$REAL/bin/safegit.py" branch "$b" >/dev/null 2>&1 && bad="$bad [$b]"
done
for b in main master release/1.2 feature/x-y_z.1 v2; do python3 "$REAL/bin/safegit.py" branch "$b" >/dev/null 2>&1 || bad="$bad [ok:$b]"; done
ck "R5 branch names: a leading dash, .., a space, ; or \$( ), a leading or trailing slash and .lock are refused; ordinary names pass${bad:+ — WRONG:$bad}" '[ -z "$bad" ]'
HB=$(r5_repo base); printf 'ref: refs/remotes/origin/--upload-pack=/tmp/evil.sh\n' > "$HB/.git/HEAD.bak"; mkdir -p "$HB/.git/refs/remotes/origin"; printf 'ref: refs/remotes/origin/--upload-pack=/tmp/evil.sh\n' > "$HB/.git/refs/remotes/origin/HEAD"
atb=$(python3 - "$REAL/bin" "$HB" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import attach
print(attach.default_branch(sys.argv[2], {"git": {"branch": "--upload-pack=/tmp/evil.sh"}}))
PY
)
ck "R5 attach takes a default branch from the folder's .git only when it is a plain branch name (otherwise main)" '[ "$atb" = main ]'
jq '.tp.default_branch = "--upload-pack=/tmp/evil.sh"' "$DH/config/projects.json" > "$T/pj.tmp" && cp "$T/pj.tmp" "$DH/config/projects.json"
rc=$(r5_gate "$HG"); ck "R5 and a registry entry that already holds a hostile default_branch makes the gate refuse before any duty runs git" '[ "$rc" != 0 ] && grep -qi "default branch" "$T/r5-out"'
cp "$T/config/projects.json" "$DH/config/projects.json"
# the filter, the textconv, the signing program: nothing runs through safe_git or any Python tool
HM=$(r5_repo marker); git -C "$HM" config filter.pwn.clean "touch $T/ran-r5-clean; cat"; git -C "$HM" config filter.pwn.smudge "touch $T/ran-r5-smudge; cat"; git -C "$HM" config diff.pwn.textconv "touch $T/ran-r5-textconv; cat"
rm -f "$T"/ran-r5-*; git -C "$HM" status >/dev/null 2>&1; git -C "$HM" diff >/dev/null 2>&1
ck "R5 control: plain git on that folder DOES run its clean filter and its textconv (so the next checks mean something)" '[ -e "$T/ran-r5-clean" ] && [ -e "$T/ran-r5-textconv" ]'
rm -f "$T"/ran-r5-*
( source "$T/bin/lib.sh"; safe_git -C "$HM" status >/dev/null 2>&1; echo $? > "$T/r5-rc1"; safe_git -C "$HM" diff >/dev/null 2>&1; safe_git -C "$HM" add -A >/dev/null 2>&1; worktree_at "$HM" "$T/r5-wt" HEAD >/dev/null 2>&1; safe_git_guard 20 -C "$HM" status >/dev/null 2>&1 )
ck "R5 safe_git itself refuses that folder (status, diff, add, worktree add, the guarded form): nothing ran, rc is not 0" '[ "$(cat "$T/r5-rc1")" != 0 ] && ! ls "$T"/ran-r5-* >/dev/null 2>&1 && [ ! -e "$T/r5-wt" ]'
rm -f "$T"/ran-r5-*
py=$(PYTHONPATH="$REAL/bin" python3 - "$HM" <<'PY'
import sys, safegit, deck, adr, fleetview
repo = sys.argv[1]
out = []
for name, fn in (("deck.git", lambda: deck.git(repo, "status")), ("deck.git blame", lambda: deck.git(repo, "blame", "--line-porcelain", "-L", "1,1", "HEAD", "--", "a.txt")),
                 ("adr.git", lambda: adr.git(repo, "log", "-p")), ("fleetview._git", lambda: fleetview._git(["status", "--porcelain"], repo)),
                 ("safegit.run", lambda: safegit.run(repo, "status"))):
    try:
        res = fn()
        out.append(name + (":RAN" if (res.stdout if hasattr(res, "stdout") else res) else ":empty"))
    except Exception as e:
        out.append(name + ":" + type(e).__name__)
print(" ".join(out))
PY
)
ck "R5 deck.py, adr.py, fleetview.py and safegit.run on that folder: refused or empty, never run ($py)" '! ls "$T"/ran-r5-* >/dev/null 2>&1 && ! grep -q ":RAN" <<<"$py"'
rm -f "$T"/ran-r5-*
: > "$T/hook-in"; ( cd "$HM" && printf '{"hook_event_name":"SessionStart","session_id":"s1","cwd":"%s"}' "$HM" | QUARTERDECK_HOME="$T/hookhome" CLAUDE_SETTINGS_FILE="$T/none.json" bash "$REAL/bin/fleet-hook.sh" >/dev/null 2>&1 )
ck "R5 the fleet hook runs every git command with the SAFE_GIT flags (static check: rev-parse runs no filter, so this one cannot fail on behaviour) and runs no repository filter" '! ls "$T"/ran-r5-* >/dev/null 2>&1 && [ "$(grep -c "GITSAFE\[@\]" "$REAL/bin/fleet-hook.sh")" = 4 ] && ! grep -qE "(^|[^A-Z])git -C" "$REAL/bin/fleet-hook.sh"'


# ---- G11 (#85): a worktree file that holds a credential is denied by what is IN it, whatever it is called -------------------------------------------
printf 'notes\nAWS=%s\n' "AKIA$(printf 'Q%.0s' $(seq 1 16))" > "$T/work/deploy-notes.txt"
printf 'nothing here\n' > "$T/work/readme-notes.txt"
ln -sf "$T/work/deploy-notes.txt" "$T/work/link.txt"
cr; c=$(last)
ck "G11 a file holding a credential shape gets its own Read deny rule, under any name" 'jq -e --arg r "Read(/$WP/deploy-notes.txt)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
ck "G11 and a file without one does not (no blanket denial of the folder)" '! jq -r .deny <<<"$c" | grep -qF "readme-notes.txt"'
ck "R5 G11 a link inside the worktree to that file is denied by its own path too" 'jq -e --arg r "Read(/$WP/link.txt)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
# real CLI 2.1.293 on macOS: Grep with a case-variant folder path (SUB/DEEP for sub/deep) returned a denied file's content; Read did not. So no Grep then.
ck "G11 when the screen denies a file, the call gets no Grep at all (the real CLI's Grep leaked a denied file through a case-variant path); Read and Glob stay" \
   'jq -e ".tools == \"Read,Glob\"" <<<"$c" >/dev/null'
# real CLI 2.1.293: a sandboxed `node -e readFileSync(...)` printed a screened file (the Read rule does not reach the shell). The sandbox must deny it too.
cr "Read,Bash(npm run*)"; c=$(last)
ck "G11 a call with a shell: the screened file is in the sandbox's denyRead as well, not only a Read rule" \
   'jq -e --arg p "$WP/deploy-notes.txt" "(.settings | fromjson | .sandbox.filesystem.denyRead | index(\$p)) != null" <<<"$c" >/dev/null'
cr "Edit,Bash(npm run*)"; c=$(last)
ck "G11 and a shell call with no Read tool is screened too (its commands can read)" \
   'jq -e --arg p "$WP/deploy-notes.txt" "(.settings | fromjson | .sandbox.filesystem.denyRead | index(\$p)) != null" <<<"$c" >/dev/null'
# round 5: a secret-holding file whose name a rule cannot carry used to be left readable (logged only). The call is now refused instead.
for odd in "odd,name.txt" "back\\slash.txt" "notes"$'\n'"creds.txt" "glob[1].txt" "brace{a}.txt"; do
  printf 'k=%s\n' "$FAKEKEY" > "$T/work/$odd"
  cr
  ck "R5 G11 a credential in a file named $(printf '%q' "$odd") that no rule can name: the call is refused, no model runs, and the run record names it" '[ "$CRRC" != 0 ] && [ ! -s "$T/claude-calls" ] && grep -qF "$(head -1 <<<"$odd")" "$DH/logs/runs/run.screen.txt"'
  rm -f "$T/work/$odd" "$DH/logs/runs/run.screen.txt"
done
ck "G11 the run record never holds the secret itself" '! grep -rqF "$FAKEKEY" "$DH/logs/runs/"'
# round 5: what the screen could not read is not called clean
printf 'k=%s\n' "$FAKEKEY" > "$T/work/locked.txt"; chmod 000 "$T/work/locked.txt"
cr; c=$(last)
ck "R5 G11 a file the screen cannot open is denied, not passed as clean" 'jq -e --arg r "Read(/$WP/locked.txt)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
chmod 600 "$T/work/locked.txt"; rm -f "$T/work/locked.txt"
python3 -c 'import sys; open(sys.argv[1], "w").write("x" * 1_500_000 + "\nk=" + sys.argv[2] + "\n")' "$T/work/big.log" "$FAKEKEY"
cr; c=$(last)
ck "R5 G11 a credential past the first megabyte of a big file is still found" 'jq -e --arg r "Read(/$WP/big.log)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
rm -f "$T/work/big.log"
ln -s "$T/r5-outside-secret" "$T/work/out-link.txt"; printf 'k=%s\n' "$FAKEKEY" > "$T/r5-outside-secret"
cr; c=$(last)
ck "R5 G11 a file link that leads out of the worktree is denied by its own path" 'jq -e --arg r "Read(/$WP/out-link.txt)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
rm -f "$T/work/out-link.txt" "$T/r5-outside-secret"
mkdir -p "$T/r5-outside-dir"; printf 'k=%s\n' "$FAKEKEY" > "$T/r5-outside-dir/notes.txt"; ln -s "$T/r5-outside-dir" "$T/work/elsewhere"
cr; c=$(last)
ck "R5 G11 a folder link that leads out of the worktree is denied whole" 'jq -e --arg r "Read(/$WP/elsewhere/**)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
rm -rf "$T/work/elsewhere" "$T/r5-outside-dir"
# at scale: more files than the screen will look at. A credential in the project's own files is never left unscreened behind a big dependency folder.
mkdir -p "$T/work/node_modules/pkg" "$T/work/src"; for i in $(seq 1 60); do echo "x$i" > "$T/work/node_modules/pkg/f$i.js"; done
printf 'k=%s\n' "$FAKEKEY" > "$T/work/src/settings.local.json"
QUARTERDECK_SCREEN_MAX_FILES=30 cr; c=$(last)
ck "R5 G11 past the file cap, the project's own files are still screened first (src/settings.local.json denied) and the unfinished dependency folder is denied whole" 'jq -e --arg r "Read(/$WP/src/settings.local.json)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null && jq -e --arg r "Read(/$WP/node_modules/**)" "(.deny | split(\",\")) | index(\$r) != null" <<<"$c" >/dev/null'
for i in $(seq 1 40); do echo "y$i" > "$T/work/src/g$i.js"; done
QUARTERDECK_SCREEN_MAX_FILES=30 cr
ck "R5 G11 and when the project's own files are past the cap, the call is refused rather than run half screened" '[ "$CRRC" != 0 ] && [ ! -s "$T/claude-calls" ]'
rm -rf "$T/work/node_modules" "$T/work/src"
cp "$T/bin/guard.py" "$T/guard.keep"; printf 'import sys\nsys.exit(5)\n' > "$T/bin/guard.py"
cr
ck "R5 G11 a screen that fails is not read as nothing found: the call is refused" '[ "$CRRC" != 0 ] && [ ! -s "$T/claude-calls" ]'
cp "$T/guard.keep" "$T/bin/guard.py"
cr "Edit,Write"; c=$(last)
ck "G11 a call that cannot read (Edit and Write only) is not screened" '! jq -r .deny <<<"$c" | grep -qF "deploy-notes.txt"'
gs=$(python3 "$T/bin/guard.py" --worktree-secrets "$T/work")
ck "G11 guard.py --worktree-secrets lists the file by relative path and not the clean one" 'grep -qx "deploy-notes.txt" <<<"$gs" && ! grep -q "readme-notes" <<<"$gs"'
# audit 7 (L4): inside a NESTED .git folder only its config was screened, so a key a check wrote to sub/.git/k was readable to the model
mkdir -p "$T/work/sub/.git"; printf 'k=%s\n' "$FAKEKEY" > "$T/work/sub/.git/k"
gz=$(python3 "$T/bin/guard.py" --worktree-secrets -z "$T/work" | tr '\0' '\n')
ck "L4 a nested .git folder is screened or denied whole: a key in sub/.git/k is in the -z output" 'grep -qxE "Fsub/.git/k|Dsub/.git" <<<"$gz"'
rm -rf "$T/work/sub"
rm -f "$T/work/deploy-notes.txt" "$T/work/readme-notes.txt" "$T/work/odd,name.txt" "$T/work/link.txt"

# ---- F11: nothing about a call is in the process arguments --------------------------------------------------------
PROMPTX="PRIVATE-PROMPT-TEXT-$(printf 'z%.0s' $(seq 1 20))"
: > "$T/claude-calls"; ( export QUARTERDECK_HOME="$DH"; source "$T/bin/lib.sh"; claude_run "$T/work" "$PROMPTX" "Read,Edit,Grep,Bash(npm run*)" >/dev/null 2>&1 ); c=$(last)
ck "F11 the prompt goes in on stdin: it is nowhere in the arguments the model's process is started with" 'jq -e --arg p "$PROMPTX" "(.prompt == \$p) and ((.argv | tostring | contains(\$p)) | not)" <<<"$c" >/dev/null'
ck "F11 the sandbox settings are a file only this user can read (0600), not an argument, and the file is gone when the call ends" \
   'jq -e "(.argv | index(\"--settings\")) as \$i | \$i != null and (.argv[\$i + 1] | startswith(\"{\") | not) and .smode == \"600\" and (.settings | fromjson | .sandbox.enabled)" <<<"$c" >/dev/null && [ ! -e "$(jq -r .spath <<<"$c")" ]'


# ---- R9: the sandbox settings file and every duty's scratch folder live in a folder no sandbox profile makes writable ------------------------------
# They were in the system temp folder, which the project-command profile (and any parallel hostile command) can write to: a rewritten settings file could
# switch the model's sandbox off for the next call. Now $QUARTERDECK_HOME/state/tmp (0700): a project command may write only its worktree, its scratch folder and the temp folders.
sp=$(jq -r .spath <<<"$c"); tdir=$(dirname "$sp")
r9=$( ( export QUARTERDECK_HOME="$DH"; source "$T/bin/lib.sh"; mktemp -d; printf '%s' "$TMPDIR" ) 2>&1 | tr '\n' ' ')
ck "R9 the sandbox settings file is under the data folder's state/tmp (0700), not the system temp folder" '[ "$tdir" = "$DH/state/tmp" ] && [ "$(modeof "$DH/state/tmp")" = 700 ]'
ck "R9 and mktemp in a duty lands there too (lib.sh points TMPDIR at it), while the model's own process keeps the system TMPDIR" '[[ "$r9" == "$DH/state/tmp/"* ]]'
( unset QUARTERDECK_CLAUDE_ENV; export QUARTERDECK_HOME="$DH" QUARTERDECK_SECRETS_DIR="$T/sec" CLAUDE_BIN="$T/envstub" TMPDIR="$T/systmp"; mkdir -p "$T/systmp"; source "$T/bin/lib.sh"; claude_run "$T/work" p >/dev/null 2>&1 )
ck "R9 the model's process gets the system TMPDIR it was started with, not the data folder's private one" 'grep -q "^TMPDIR=$T/systmp\$" "$T/stub-env"'

# ---- F8: what attach writes is private, even from a process with umask 022 (the dashboard) -------------------------
AH="$T/attach-home"; mkdir -p "$AH"
( umask 022; QUARTERDECK_HOME="$AH" QUARTERDECK_DIR= python3 "$REAL/bin/attach.py" "$AT" --name decoy --apply >/dev/null 2>&1 )
loose=$(find "$AH" -type f \( -perm -g+r -o -perm -o+r \) 2>/dev/null | head -3 | tr '\n' ' ')
ck "F8 attach --apply leaves the registry, the profile and the record owner-only (0600), not world-readable${loose:+: $loose}" '[ -n "$(find "$AH" -type f -name "*.json" | head -1)" ] && [ -z "$loose" ]'

# ---- commit identity: the account's no-reply address by default, never the checkout's private address ---------------------------
IDH="$T/id-home"; mkdir -p "$IDH/state" "$IDH/config"
cat > "$IDH/config/projects.json" <<'J'
{"p1": {"repo": "a/b", "path": "/x"}, "p2": {"repo": "a/b", "path": "/x", "git_identity": "repo"}, "p3": {"repo": "a/b", "path": "/x", "git": {"name": "Ada", "email": "ada@example.com"}}}
J
cat > "$T/idgh" <<'G'
#!/bin/bash
[ "$1 $2" = "api user" ] && printf 'Ada Lovelace\t12345+adalovelace@users.noreply.github.com\n' && exit 0
exit 1
G
chmod +x "$T/idgh"
IDR="$T/id-repo"; git init -q "$IDR" && git -C "$IDR" config user.email "private@example.org" && git -C "$IDR" config user.name "Private Person"
cid() { ( export QUARTERDECK_HOME="$IDH" QUARTERDECK_GH="$T/idgh"; source "$T/bin/lib.sh"; commit_identity "$1" "$IDR" && printf '%s\n' ${COMMIT_ID[@]+"${COMMIT_ID[@]}"} | tr '\n' ' ' ) 2>/dev/null; }
ck "commit identity: by default a commit is credited to the account's GitHub no-reply address, not the checkout's private address" '[[ "$(cid p1)" == *"user.email=12345+adalovelace@users.noreply.github.com"* ]] && [[ "$(cid p1)" != *private@example.org* ]]'
ck "commit identity: it is applied with -c (nothing is written into the repository's own configuration)" '[ "$(git -C "$IDR" config user.email)" = "private@example.org" ] && [ "$(cid p1 | grep -c -- "-c user.name=Ada Lovelace")" = 1 ]'
ck "commit identity: git_identity repo keeps the checkout's own identity (no options added)" '[ -z "$(cid p2 | tr -d " ")" ]'
ck "commit identity: a name and email in the registry win" '[[ "$(cid p3)" == *"user.email=ada@example.com"* ]]'
ck "commit identity: it is cached once, owner-only" '[ -s "$IDH/state/gh-identity" ] && [ "$(stat -c %a "$IDH/state/gh-identity" 2>/dev/null || stat -f %Lp "$IDH/state/gh-identity")" = 600 ]'

# ---- S2 to S5: what the sandbox profile keeps out, with the real sandbox-exec, real commands and INVENTED decoys (a throwaway HOME, never the real one) ----------
# Each check was run against the profile as it was before round 3 and failed there (resolver reachable, clipboard, other processes, secrets outside the worktree).
if [ "$(uname -s)" = Darwin ] && /usr/bin/sandbox-exec -p '(version 1)(allow default)' /usr/bin/true >/dev/null 2>&1; then
  S5F="$T/s5fake"; S5W="$T/s5wt"; S5S="$T/s5scr"; S5D="$T/s5data"
  mkdir -p "$S5F/.aws" "$S5F/.config/gh" "$S5F/.config/pnpm" "$S5F/Documents/proj" "$S5F/Library/Application Support/App" "$S5F/Projects/app/sub" "$S5F/Library/Application Support/fnm/node-versions/v9/installation/bin" "$S5F/Library/Application Support/fnm/node-versions/v9/installation/lib" "$S5F/Projects/app/node_modules/leftpad" "$S5F/code/other" "$S5F/dev/proj2" "$S5F/src/lib" "$S5F/elsewhere/proj3" "$S5F/code/tools/bin" "$S5F/code/tools/lib" "$S5F/misc" "$S5S/home" "$S5S/tmp" "$S5D/state" "$S5D/config"
  S5F=$(cd "$S5F" && pwd -P); S5S=$(cd "$S5S" && pwd -P); S5D=$(cd "$S5D" && pwd -P)
  echo QDDECOY-aws > "$S5F/.aws/credentials"; echo QDDECOY-gh > "$S5F/.config/gh/hosts.yml"; echo QDDECOY-pnpmrc > "$S5F/.config/pnpm/rc"; echo QDDECOY-doc > "$S5F/Documents/proj/note.txt"
  echo QDDECOY-appsup > "$S5F/Library/Application Support/App/data"; echo QDDECOY-env > "$S5F/Projects/app/.env"; echo QDDECOY-envlocal > "$S5F/Projects/app/sub/.env.local"
  echo PUBLIC=1 > "$S5F/misc/.env.example"; echo QDDECOY-key > "$S5F/Projects/app/server.pem"; echo QDDECOY-topenv > "$S5F/.env"; echo QDDECOY-hist > "$S5F/.zsh_history"; echo QDDECOY-npmrc > "$S5F/.npmrc"
  echo QDDECOY-main > "$S5F/Projects/app/readme.txt"; echo ok-readable > "$S5F/misc/readme.txt"; echo nm-lib > "$S5F/Projects/app/node_modules/leftpad/index.js"
  echo QDDECOY-code > "$S5F/code/other/app.js"; echo QDDECOY-dev > "$S5F/dev/proj2/main.py"; echo QDDECOY-src > "$S5F/src/lib/x.c"; echo QDDECOY-reg > "$S5F/elsewhere/proj3/lib.rb"; echo tool-lib > "$S5F/code/tools/lib/mod.txt"; echo tool-bin > "$S5F/code/tools/bin/tool.txt"; echo QDDECOY-toolsecret > "$S5F/code/tools/secret.txt"
  # A1/A2: the worktree is a linked worktree of the registered project ~/Projects/app (git reads its .git there), with that project's node_modules borrowed
  git -C "$S5F/Projects/app" init -q && git -C "$S5F/Projects/app" add readme.txt && git -C "$S5F/Projects/app" -c user.name=t -c user.email=t@e.invalid commit -q -m base && git -C "$S5F/Projects/app" worktree add -q --detach "$S5W" >/dev/null 2>&1
  S5W=$(cd "$S5W" && pwd -P); mkdir -p "$S5W/test"; ln -s "$S5F/Projects/app/node_modules" "$S5W/node_modules"; printf '%s' "$S5F/Projects/app/node_modules" > "$S5W.nmlink"
  jq -n --arg a "$S5F/Projects/app" --arg b "$S5F/elsewhere/proj3" '{app: {path: $a}, proj3: {path: $b}}' > "$S5D/config/projects.json"
  echo wt-file > "$S5W/file.txt"; echo QDDECOY-wtenv > "$S5W/.env"; echo tool-lib > "$S5F/Library/Application Support/fnm/node-versions/v9/installation/lib/mod.js"
  echo QDDECOY-sibling > "$S5F/Library/Application Support/fnm/other.txt"
  s5gen() { ( export HOME="$S5F" QUARTERDECK_HOME="$S5D"; export PATH="$S5F/Library/Application Support/fnm/node-versions/v9/installation/bin:$S5F/code/tools/bin:$PATH"; source "$T/bin/lib.sh"; _qd_sb_profile "$1" "$S5W" "$S5S" ); }
  s5gen check > "$T/s5c.sb"; s5gen install > "$T/s5i.sb"
  s5() { local pf=$1; shift; env -i PATH="$PATH" HOME="$S5S/home" TMPDIR="$S5S/tmp" LANG=C TERM=dumb /usr/bin/sandbox-exec -f "$pf" "$@"; }

  # S2: the resolver
  ck "S2 the check profile lets no unix socket through (the system resolver's carried hostnames out)" '! grep -q "unix-socket" "$T/s5c.sb" && ! grep -q mDNSResponder "$T/s5c.sb"'
  if python3 -c 'import socket; socket.gethostbyname("example.com")' >/dev/null 2>&1; then
    ck "S2 under the check profile a real name lookup (example.com) fails; outside the sandbox it resolves" '! s5 "$T/s5c.sb" python3 -c "import socket; socket.gethostbyname(\"example.com\")" >/dev/null 2>&1'
  else st_skip "S2 the live lookup (this machine cannot resolve example.com even outside the sandbox: offline); the profile-text check above still ran"; fi
  S2P=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  python3 -m http.server "$S2P" --bind 127.0.0.1 --directory "$S5W" >/dev/null 2>&1 & S2SRV=$!
  if st_http_up "http://127.0.0.1:$S2P/file.txt" "http://localhost:$S2P/file.txt"; then
    s2a=$(s5 "$T/s5c.sb" curl -s -m 6 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$S2P/file.txt"); s2b=$(s5 "$T/s5c.sb" curl -s -m 6 -o /dev/null -w '%{http_code}' "http://localhost:$S2P/file.txt")
    s2c=$(s5 "$T/s5c.sb" python3 -c "import urllib.request as u; print(u.urlopen('http://localhost:$S2P/file.txt', timeout=5).status)" 2>&1 | tail -1)
    ck "S2 and a local server is still reached by address and by the name localhost (curl, python: got $s2a, $s2b, $s2c)" '[ "$s2a" = 200 ] && [ "$s2b" = 200 ] && [ "$s2c" = 200 ]'
  else st_skip "skipped: this runner cannot reach a local server even outside the sandbox (curl to 127.0.0.1 and localhost:$S2P got no 200 in 10s), so S2's loopback check proves nothing here"; fi
  kill "$S2SRV" 2>/dev/null; wait "$S2SRV" 2>/dev/null

  # S3: the clipboard
  ML="$REAL/bin/selftest-machlookup.py"
  ck "S3 the pasteboard service cannot be looked up under the check or the install profile, and pbpaste is not started" \
     'grep -q "com.apple.pasteboard.1 DENIED" <<<"$(s5 "$T/s5c.sb" python3 "$ML" com.apple.pasteboard.1 2>&1)" && grep -q "com.apple.pasteboard.1 DENIED" <<<"$(s5 "$T/s5i.sb" python3 "$ML" com.apple.pasteboard.1 2>&1)" && ! s5 "$T/s5c.sb" pbpaste >/dev/null 2>&1 && ! s5 "$T/s5i.sb" pbpaste >/dev/null 2>&1'

  # S4: other processes, launchd, and the services that start things outside the sandbox
  bash -c 'sleep 90; : qd-marker-s4' & S4P=$!
  sleep 0.5
  for pf in s5c s5i; do
    s4k=$(s5 "$T/$pf.sb" bash -c "kill -0 $S4P 2>&1; echo rc=\$?" | tail -1)
    s4g=$(s5 "$T/$pf.sb" pgrep -l -f qd-marker-s4 2>&1 | head -2)
    s4c=$(s5 "$T/$pf.sb" bash -c 'sleep 30 & c=$!; kill $c; wait $c 2>/dev/null; echo child-rc=$?' 2>&1 | tail -1)
    s4a=$(s5 "$T/$pf.sb" python3 "$REAL/bin/selftest-procs.py" "$S4P" 2>&1)
    ck "S4 ($pf) another process cannot be signalled, listed (pgrep, proc_listpids) or found by path, launchctl is not started; the command's own child can still be signalled" \
       '[ "$s4k" != rc=0 ] && ! grep -q qd-marker-s4 <<<"$s4g" && [ "$s4c" = child-rc=143 ] && grep -q "kill: denied" <<<"$s4a" && grep -q "proc_listpids bytes: 0" <<<"$s4a" && grep -q "pidpath: denied" <<<"$s4a" && ! s5 "$T/$pf.sb" launchctl print "gui/$(id -u)" >/dev/null 2>&1'
  done
  kill "$S4P" 2>/dev/null; wait "$S4P" 2>/dev/null
  ck "S4 open, osascript and security are not started, and Launch Services and Apple events cannot be looked up (nothing opens a URL or drives another app)" \
     '! s5 "$T/s5c.sb" open -b com.qd.nonexistent >/dev/null 2>&1 && ! s5 "$T/s5c.sb" osascript -e "return 1" >/dev/null 2>&1 && ! s5 "$T/s5c.sb" security list-keychains >/dev/null 2>&1 && grep -q "launchservicesd DENIED" <<<"$(s5 "$T/s5c.sb" python3 "$ML" com.apple.coreservices.launchservicesd 2>&1)" && grep -q "appleevents DENIED" <<<"$(s5 "$T/s5c.sb" python3 "$ML" com.apple.coreservices.appleevents 2>&1)"'

  # S5: credentials and personal folders outside the worktree
  s5rd() { local o; o=$(s5 "$1" cat "$2" 2>&1); case "$o" in *QDDECOY*) echo readable ;; *) echo denied ;; esac; }
  s5bad=""
  for f in .aws/credentials .config/gh/hosts.yml .config/pnpm/rc Documents/proj/note.txt "Library/Application Support/App/data" Projects/app/.env Projects/app/sub/.env.local Projects/app/server.pem .env .zsh_history .npmrc "Library/Application Support/fnm/other.txt"; do
    [ "$(s5rd "$T/s5c.sb" "$S5F/$f")" = denied ] || s5bad="$s5bad check:$f"
  done
  for f in .aws/credentials .config/gh/hosts.yml Documents/proj/note.txt "Library/Application Support/App/data" Projects/app/.env Projects/app/server.pem .env .zsh_history; do
    [ "$(s5rd "$T/s5i.sb" "$S5F/$f")" = denied ] || s5bad="$s5bad install:$f"
  done
  ck "S5 under the check and install profiles the decoy credentials, .env* files, keys, history, ~/.config, Documents and Application Support are unreadable${s5bad:+ (READABLE:$s5bad)}" '[ -z "$s5bad" ]'
  s5src=""
  for f in Projects/app/readme.txt code/other/app.js dev/proj2/main.py src/lib/x.c elsewhere/proj3/lib.rb; do
    for pf in s5c s5i; do [ "$(s5rd "$T/$pf.sb" "$S5F/$f")" = denied ] || s5src="$s5src $pf:$f"; done
  done
  ck "A1 the owner's other source trees are unreadable to a project command: the registered project's own main checkout, another registered project, and ~/code ~/dev ~/src${s5src:+ (READABLE:$s5src)}" '[ -z "$s5src" ]'
  ck "A1 and the worktree's own git still reads (status and log through the main checkout's .git), its borrowed node_modules reads, and a toolchain on PATH inside ~/code reads" \
     '[ "$(s5 "$T/s5c.sb" git -C "$S5W" log --format=%s -1 2>&1)" = base ] && s5 "$T/s5c.sb" git -C "$S5W" status --short >/dev/null 2>&1 && [ "$(s5 "$T/s5c.sb" cat "$S5W/node_modules/leftpad/index.js")" = nm-lib ] && [ "$(s5 "$T/s5c.sb" cat "$S5F/code/tools/bin/tool.txt")" = tool-bin ]'
  # round 6: M2 another worktree in the workspace of the data folder, L1 the stash and reflogs of the main checkout, L2 the checkout around a PATH folder
  # inside a source tree, L3 Claude Code's session folders in /private/tmp, L7 a .git file that names the home folder
  mkdir -p "$S5D/workspace/wt-other"; echo QDDECOY-otherwt > "$S5D/workspace/wt-other/x.txt"
  echo stashed > "$S5F/Projects/app/readme.txt"; git -C "$S5F/Projects/app" -c user.name=t -c user.email=t@e.invalid stash -q
  L3D=$(mktemp -d /private/tmp/claude-qd6.XXXXXX); echo QDDECOY-task > "$L3D/task.output"
  r6=""
  [ "$(s5rd "$T/s5c.sb" "$S5D/workspace/wt-other/x.txt")" = denied ] || r6="$r6 M2:other-worktree"
  s5 "$T/s5c.sb" git -C "$S5W" show 'stash@{0}:readme.txt' 2>/dev/null | grep -q stashed && r6="$r6 L1:stash"
  s5 "$T/s5c.sb" cat "$S5F/Projects/app/.git/logs/HEAD" >/dev/null 2>&1 && r6="$r6 L1:reflog"
  [ "$(s5rd "$T/s5c.sb" "$S5F/code/tools/secret.txt")" = denied ] || r6="$r6 L2:tool-parent"
  [ "$(s5rd "$T/s5c.sb" "$L3D/task.output")" = denied ] || r6="$r6 L3:read"
  s5 "$T/s5c.sb" bash -c "echo x > '$L3D/w.txt'" 2>/dev/null; [ -e "$L3D/w.txt" ] && r6="$r6 L3:write"
  rm -rf "$L3D"
  # audit 7 (Info): the same folders under the per-user temp folder ($TMPDIR, /private/var/folders/../T/claude-*) were still readable
  L3T=$(getconf DARWIN_USER_TEMP_DIR); L3T=$(cd "$L3T" && pwd -P); L3T=$(mktemp -d "$L3T/claude-qd7.XXXXXX"); echo QDDECOY-tmpdir > "$L3T/x"
  [ "$(s5rd "$T/s5c.sb" "$L3T/x")" = denied ] || r6="$r6 I7:tmpdir-claude"
  rm -rf "$L3T"
  mkdir -p "$T/l7wt"; echo "gitdir: $S5F" > "$T/l7wt/.git"
  ( export HOME="$S5F" QUARTERDECK_HOME="$S5D"; source "$T/bin/lib.sh"; _qd_sb_profile check "$T/l7wt" "$S5S" ) > "$T/l7.sb"; grep -qF "(allow file-read* file-read-data (subpath \"$S5F\"))" "$T/l7.sb" && r6="$r6 L7:home-let-in"; [ -s "$T/l7.sb" ] || r6="$r6 L7:no-profile"
  ck "R6 a check cannot read another worktree in the workspace, the main checkout's stash or reflogs, the checkout around a PATH folder, or /private/tmp/claude-*; a .git file naming the home folder lets nothing in${r6:+ (FAILED:$r6)}" '[ -z "$r6" ]'
  # the data folder may itself sit in a closed tree (such as ~/Projects/tools): a worktree inside it still works from inside, the tree around it does not read
  IW="$S5F/Projects/qd/workspace/wt"; IS="$S5F/Projects/qd/workspace/scr"; mkdir -p "$S5F/Projects/qd/state" "$IS/home" "$IS/tmp"; echo QDDECOY-qd > "$S5F/Projects/qd/notes.txt"
  git -C "$S5F/Projects/app" worktree add -q --detach "$IW" >/dev/null 2>&1
  ( export HOME="$S5F" QUARTERDECK_HOME="$S5F/Projects/qd" PROJECTS_FILE="$S5D/config/projects.json"; source "$T/bin/lib.sh"; _qd_sb_profile check "$IW" "$IS" ) > "$T/s5in.sb"
  inr() { (cd "$IW" && env -i PATH="$PATH" HOME="$IS/home" TMPDIR="$IS/tmp" LANG=C TERM=dumb /usr/bin/sandbox-exec -f "$T/s5in.sb" "$@"); }
  ck "A1 a worktree inside a closed tree (the data folder in ~/Projects) still works from inside: python, node, git log, a listing; the files around it stay closed" \
     '[ "$(inr python3 -c "import os; print(len(os.getcwd()) > 0)" 2>&1 | tail -1)" = True ] && { ! command -v node >/dev/null || [ "$(inr node -e "console.log(1)" 2>&1)" = 1 ]; } && [ "$(inr git log --format=%s -1 2>&1)" = base ] && inr ls >/dev/null 2>&1 && [ "$(s5rd "$T/s5in.sb" "$S5F/Projects/qd/notes.txt")" = denied ]'
  for pf in s5c s5i; do
    ck "A2 ($pf) a project command cannot write the worktree's .git file (it would repoint the gitdir), and still writes the rest of the worktree" \
       '! s5 "$T/$pf.sb" bash -c "echo gitdir: /tmp/evil > \"$S5W/.git\"" 2>/dev/null && ! s5 "$T/$pf.sb" rm -f "$S5W/.git" 2>/dev/null && [ -f "$S5W/.git" ] && grep -q "^gitdir: $S5F/Projects/app/.git/worktrees/" "$S5W/.git" && s5 "$T/$pf.sb" bash -c "echo x > \"$S5W/written.txt\""'
  done
  ck "S5 and what a build needs still reads: the worktree (even its own .env), .env.example, a plain project file, the install step's pnpm settings and .npmrc, a toolchain on PATH inside a denied folder" \
     '[ "$(s5 "$T/s5c.sb" cat "$S5W/file.txt")" = wt-file ] && [ "$(s5 "$T/s5c.sb" cat "$S5W/.env")" = QDDECOY-wtenv ] && [ "$(s5 "$T/s5c.sb" cat "$S5F/misc/.env.example")" = PUBLIC=1 ] && [ "$(s5 "$T/s5c.sb" cat "$S5F/misc/readme.txt")" = ok-readable ] && [ "$(s5 "$T/s5i.sb" cat "$S5F/.config/pnpm/rc")" = QDDECOY-pnpmrc ] && [ "$(s5 "$T/s5i.sb" cat "$S5F/.npmrc")" = QDDECOY-npmrc ] && [ "$(s5 "$T/s5c.sb" cat "$S5F/Library/Application Support/fnm/node-versions/v9/installation/lib/mod.js")" = tool-lib ]'
  s5j=$( ( export HOME="$S5F" QUARTERDECK_HOME="$S5D"; source "$T/bin/lib.sh"; claude_sandbox_json "$S5W"; claude_sandbox_json "$S5F/Documents/proj" ) 2>&1 )
  s5j1=$(sed -n 1p <<<"$s5j"); s5j2=$(sed -n 2p <<<"$s5j")
  ck "S5 the model's own shell sandbox (denyRead) lists ~/.config, ~/.aws, .env*/*.pem anywhere under the home folder and the personal folders; Documents is left out only when the working folder is in it" \
     'jq -e --arg h "$S5F" "(.sandbox.filesystem.denyRead | index(\$h + \"/.config\")) and (.sandbox.filesystem.denyRead | index(\$h + \"/.aws\")) and (.sandbox.filesystem.denyRead | index(\$h + \"/**/.env*\")) and (.sandbox.filesystem.denyRead | index(\$h + \"/**/*.pem\")) and (.sandbox.filesystem.denyRead | index(\$h + \"/Documents\")) and (.sandbox.filesystem.denyRead | index(\$h + \"/Library/Application Support\"))" <<<"$s5j1" >/dev/null && jq -e --arg h "$S5F" "(.sandbox.filesystem.denyRead | index(\$h + \"/Documents\") | not) and (.sandbox.filesystem.denyRead | index(\$h + \"/Desktop\"))" <<<"$s5j2" >/dev/null'

  # and ordinary builds still work under the very same profiles
  cat > "$S5W/package.json" <<'PJ'
{"name":"t","version":"1.0.0","scripts":{"test":"node --test test/a.test.js"}}
PJ
  cat > "$S5W/test/a.test.js" <<'JS'
const test = require('node:test'), assert = require('node:assert'), http = require('node:http'), cp = require('node:child_process'), fs = require('node:fs');
test('math', () => assert.strictEqual(1 + 1, 2));
test('write the worktree', () => { fs.writeFileSync('out.txt', 'x'); });
test('child process and kill', async () => { const c = cp.spawn('sleep', ['30']); await new Promise(r => setTimeout(r, 100)); c.kill(); await new Promise(r => c.on('exit', r)); });
test('loopback by address and by name', async () => {
  const srv = http.createServer((q, s) => s.end('hi')).listen(0, '127.0.0.1'); await new Promise(r => srv.on('listening', r));
  for (const host of ['127.0.0.1', 'localhost']) await new Promise((res, rej) => http.get({ host, port: srv.address().port, family: 4 }, r => { r.resume(); r.on('end', res); }).on('error', rej));
  srv.close();
});
JS
  printf 'import unittest, subprocess\nclass T(unittest.TestCase):\n    def test_a(self): self.assertEqual(2 + 2, 4)\n    def test_child(self):\n        p = subprocess.Popen(["sleep", "30"]); p.terminate(); p.wait()\nunittest.main()\n' > "$S5W/t_test.py"
  bb=""
  for pf in s5c s5i; do
    if command -v node >/dev/null; then
      s5 "$T/$pf.sb" bash -c "cd '$S5W' && node --test test/a.test.js" >/dev/null 2>&1 || bb="$bb $pf:node-test"
      s5 "$T/$pf.sb" bash -c "cd '$S5W' && npm test" >/dev/null 2>&1 || bb="$bb $pf:npm-test"
    fi
    s5 "$T/$pf.sb" bash -c "cd '$S5W' && python3 t_test.py" >/dev/null 2>&1 || bb="$bb $pf:unittest"
    s5 "$T/$pf.sb" bash -c "mkdir -p '$S5W/fixture-repo' && cd '$S5W/fixture-repo' && rm -rf .git && echo a > f.txt && git init -q . && git -c user.name=t -c user.email=t@e.invalid add -A && git -c user.name=t -c user.email=t@e.invalid commit -q -m x && git diff --stat HEAD && git status --short" >/dev/null 2>&1 || bb="$bb $pf:git"
  done
  ck "S2 to S5 ordinary builds still work under the same profiles: node --test and npm test (child processes, loopback by address and by localhost), python unittest, git add/commit/diff/status${bb:+ (FAILED:$bb)}" '[ -z "$bb" ]'
else st_skip "S2 to S5 sandbox-profile checks (macOS sandbox-exec only)"; fi

# ---- S4: the one-time pairing code is never in a process argument (the real `qtdeck dashboard`, a stand-in `open` that looks at what any process can see) ------------------
if [ "$(uname -s)" = Darwin ]; then
  LH="$T/linkhome"; LHH="$T/linkfakehome"; LS="$T/linkstub"; mkdir -p "$LH/state" "$LH/logs" "$LH/config" "$LH/workspace" "$LHH" "$LS"; touch "$LH/.quarterdeck-home"
  cat > "$LS/open" <<'STUB'
#!/bin/bash
# what a stand-in `open` sees: its own arguments, the page it was handed, and every process's command line as `ps` shows them to any process of this user
echo "$@" > "$STUBDIR/argv"; cp "$1" "$STUBDIR/page" 2>/dev/null; stat -f %Lp "$1" > "$STUBDIR/mode" 2>/dev/null
ps -ww -axo command > "$STUBDIR/ps" 2>/dev/null; pgrep -l -f . > "$STUBDIR/pgrep" 2>/dev/null; echo "$1" > "$STUBDIR/path"
STUB
  chmod +x "$LS/open"
  LPORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
  lenv() { env HOME="$LHH" QUARTERDECK_OPEN_CMD="$LS/open" STUBDIR="$LS" QUARTERDECK_HOME="$LH" QUARTERDECK_DIR="$REAL" QUARTERDECK_DASHBOARD_PORT="$LPORT" QUARTERDECK_OPEN_KEEP=3 "$@"; }
  lout=$(lenv "$REAL/bin/qtdeck" dashboard 2>&1)
  lnonce=$(sed -n 's/.*#pair=\([A-Za-z0-9_-]*\).*/\1/p' <<<"$lout" | head -1)
  lpage=$(cat "$LS/page" 2>/dev/null); lpath=$(cat "$LS/path" 2>/dev/null)
  ck "S4 qtdeck dashboard still prints a one-time link to the owner and hands the browser a page (a path), not the link" '[ -n "$lnonce" ] && grep -q "dashboard: http://127.0.0.1:$LPORT/#pair=" <<<"$lout" && [ -s "$LS/argv" ] && [ "$(cat "$LS/argv")" = "$lpath" ] && [[ "$lpath" == "$LH/state/open."*"/go.html" ]]'
  ck "S4 the pairing code is in no process's arguments while the browser starts (open's own, and every command line ps and pgrep list)" '[ -n "$lnonce" ] && ! grep -qF "$lnonce" "$LS/argv" "$LS/ps" "$LS/pgrep" && ! grep -qF "pair=" "$LS/argv"'
  ck "S4 the page is 0600, is a redirect to the dashboard with the code, and is gone again within seconds" '[ "$(cat "$LS/mode")" = 600 ] && grep -qF "http://127.0.0.1:$LPORT/#pair=$lnonce" <<<"$lpage" && grep -q "location.replace" <<<"$lpage" && { for _ in $(seq 1 40); do [ -e "$lpath" ] || break; sleep 0.25; done; [ ! -e "$lpath" ]; }'
  lenv "$REAL/bin/qtdeck" dashboard stop >/dev/null 2>&1
  lenv "$REAL/bin/qtdeck" dashboard --no-open >/dev/null 2>&1; rm -f "$LS/argv"
  lenv "$REAL/bin/qtdeck" dashboard --no-open >/dev/null 2>&1
  ck "S4 --no-open opens nothing" '[ ! -e "$LS/argv" ]'
  lenv "$REAL/bin/qtdeck" dashboard stop >/dev/null 2>&1
else st_skip "S4 pairing link (macOS open only)"; fi

st_done
