#!/bin/bash
# infra — read the rigging.
#
# Reads a change to infrastructure FILES (Terraform, AWS CDK, CloudFormation and SAM, a serverless config, Vercel and Supabase
# config and migrations) and writes a change report: what changes, how risky, how far it reaches, how to undo it, and what a
# person must decide. The rigger (a crew seat) does the judging; the harness does everything else.
#
# FILES ONLY. This duty never runs anything against a cloud. It holds no credentials (every cloud credential variable is
# removed from its environment before anything starts), the model gets Read, Grep and Glob and no shell, and no cloud tool
# is ever called by the harness either. It reads the files in the change. It cannot see the live account, so it cannot see
# drift between the files and what is running, and its report says so in the harness's own words, not the model's.
#
# The harness finds the infrastructure files itself (the same names the project scan uses: bin/scan.py), builds the diff and
# the file text (bounded), and picks the stack notes of the packs that fit (bin/packs.py). Files that may hold secrets
# (Terraform state and variable files, .env files, keys) are named and never opened. The model returns a contract; the
# harness validates it, refuses a reply that tells anyone to run a cloud command, and records the verdict itself.
#
#   quarterdeck run <p> infra --pr 218              report only
#   quarterdeck run <p> infra --diff main           the checked-out HEAD against a base branch or commit (committed changes only)
#   ... --apply                                 also write the change report into workspace/ (never into the project)
#
# Contract:
#   INFRA_JSON: [{"resource","change","risk":"low|medium|high","why","blast_radius","rollback","needs_human":true|false}]   [] when nothing needs saying
#   VERDICT: CLEAN | REVIEWED <n>
# Recorded: REVIEWED n | CLEAN | NOT_INFRA (no infrastructure file changed: no model is asked) | ERROR
set -uo pipefail
# quarterdeck: read-whole-file
# Everything below is one brace group, so bash reads this whole file before it
# runs any of it. Without that, bash reads a script as it goes, and a script
# edited while it runs resumes somewhere inside the new text. The group closes
# on the last line of this file.
{
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)/lib.sh"

# No credentials, ever: whatever the owner's shell holds for a cloud is dropped before any model or git command starts.
for v in $(env | cut -d= -f1 | grep -E '^(AWS_|TF_|ARM_|VERCEL_|SUPABASE_|CDK_|SAM_|SERVERLESS_|PULUMI_|GOOGLE_|AZURE_|CLOUDFLARE_|CF_|WRANGLER_|FLY_|CLOUDSDK_|GCLOUD_|GCP_|ARM_|AZD_)[A-Za-z0-9_]*$'); do unset "$v"; done

PROJECT="${QUARTERDECK_PROJECT:?run me through: quarterdeck run <project> infra --pr <n>}"
SOURCE_REPO_DIR="${QUARTERDECK_WORKDIR:?}"
LOG_FILE="$QUARTERDECK_HOME/logs/infra-$PROJECT.log"
REPO=$(project_get "$PROJECT" repo)
BASE=$(project_get "$PROJECT" default_branch main)
GH="${QUARTERDECK_GH:-gh}"
PER_RUN="${QUARTERDECK_INFRA_MAX_ITEMS:-20}"            # items in one report (its own cap: the fleet-wide QUARTERDECK_MAX_ITEMS is small, and a cut list would hide risks)
MAX_FILES=40 MAX_DIFF=60000 MAX_TEXT=100000 MAX_ONE=30000

APPLY=0 PR="" DBASE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --pr)    PR="${2:-}"; need_num "--pr" "$PR"; shift ;;
    --diff)  DBASE="${2:-}"; shift ;;
    *) die "infra: unknown argument '$1'" ;;
  esac
  shift
done
[ "${QUARTERDECK_DRY_RUN:-1}" = 0 ] && APPLY=1
if [ -n "$PR" ] && [ -n "$DBASE" ]; then die "infra takes --pr <number> or --diff <base>, not both"; fi
if [ -n "$PR" ]; then [[ "$PR" =~ ^[0-9]+$ ]] || die "infra: --pr needs a number"
elif [ -n "$DBASE" ]; then [[ "$DBASE" =~ ^[A-Za-z0-9][A-Za-z0-9._/@~^-]*$ ]] || die "infra: --diff needs a branch or commit name"
else die "infra needs a pull request (--pr <number>) or a base to compare with (--diff <base>)"; fi

if [ -n "$PR" ]; then KEY="pr$PR"; else KEY="diff-$(printf '%s' "$DBASE" | tr -c 'A-Za-z0-9._-' '_')"; fi
acquire_lock "infra-$PROJECT-$KEY"
export QUARTERDECK_RUN_ID="$(tr '/' '_' <<<"$REPO")-infra-$KEY"
WT="$QUARTERDECK_HOME/workspace/wt-infra-${PROJECT}-${KEY}"
TMP="$(mktemp -d)"
cleanup() {
  [ "${BASH_SUBSHELL:-0}" = 0 ] || return 0
  safe_git -C "$SOURCE_REPO_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
blocked() { say "quarterdeck: BLOCKED — $1"; record_run "$PROJECT" infra BLOCKED "$KEY — $1"; exit 0; }

# ---- what is being read -----------------------------------------------------------------------------------------------
title="" body="" sha="" url=""
if [ -n "$PR" ]; then
  meta=$(guard 60 "$GH" pr view "$PR" -R "$REPO" --json number,title,body,state,headRefOid 2>>"$LOG_FILE") || die "cannot read $REPO#$PR"
  title=$(jq -r .title <<<"$meta"); sha=$(jq -r '.headRefOid // ""' <<<"$meta"); body=$(jq -r '.body // ""' <<<"$meta")
  url="https://github.com/$REPO/pull/$PR"
  guard 180 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "pull/$PR/head" 2>>"$LOG_FILE" || blocked "could not fetch pull/$PR/head"
  worktree_at "$SOURCE_REPO_DIR" "$WT" FETCH_HEAD || blocked "could not create a worktree at $WT"
  guard 120 "${SAFE_GIT[@]}" -C "$SOURCE_REPO_DIR" fetch -q origin "$BASE" 2>>"$LOG_FILE" || true
  baseref="origin/$BASE"; safe_git -C "$SOURCE_REPO_DIR" rev-parse --verify -q "$baseref^{commit}" >/dev/null || baseref="$BASE"
  subject="pull request #$PR"
  working_on "PR #$PR — $title"
else
  safe_git -C "$SOURCE_REPO_DIR" rev-parse --verify -q "$DBASE^{commit}" >/dev/null || die "infra: no such branch or commit: $DBASE"
  worktree_at "$SOURCE_REPO_DIR" "$WT" HEAD || blocked "could not create a worktree at $WT"
  baseref="$DBASE"; title="changes since $DBASE"; subject="the committed changes since $DBASE"
  working_on "infra — $subject"
fi
safe_git -C "$WT" rev-parse --verify -q "$baseref^{commit}" >/dev/null || blocked "the base $baseref is not in this checkout"
say "quarterdeck: infra on $REPO — $subject"

# ---- the infrastructure files, found by the harness ----------------------------------------------------------------------
safe_git -C "$WT" diff --no-ext-diff --no-renames --name-only -z "$baseref"...HEAD 2>>"$LOG_FILE" | tr '\0' '\n' > "$TMP/changed" || blocked "could not list the changed files"
python3 "$QUARTERDECK_DIR/bin/scan.py" --infra-files "$WT" < "$TMP/changed" > "$TMP/infra" 2>>"$LOG_FILE" || blocked "could not classify the changed files"
SECRETS=$(awk -F'\t' '$1 == "secret" {print $2}' "$TMP/infra")
awk -F'\t' '$1 != "secret" && NF == 2' "$TMP/infra" | head -n "$MAX_FILES" > "$TMP/list"
NOTE_SECRETS=""
[ -z "$SECRETS" ] || NOTE_SECRETS="Held back, named only and never opened, because they may hold secrets: $(tr '\n' ' ' <<<"$SECRETS")"
if [ ! -s "$TMP/list" ]; then
  say "quarterdeck: NOT_INFRA — no infrastructure file changed in $subject; no model was asked.${NOTE_SECRETS:+ $NOTE_SECRETS}"
  record_run "$PROJECT" infra NOT_INFRA "$KEY — no infrastructure file changed" "$url"
  exit 0
fi
FILES=(); while IFS=$'\t' read -r k p; do FILES[${#FILES[@]}]="$p"; done < "$TMP/list"
nfiles=${#FILES[@]}
KINDS=$(cut -f1 "$TMP/list" | sort -u | tr '\n' ',' | sed 's/,$//; s/,/, /g')

# the diff of those files only, bounded
safe_git -C "$WT" diff --no-ext-diff --no-textconv --no-renames --unified=6 "$baseref"...HEAD -- "${FILES[@]}" > "$TMP/diff.full" 2>>"$LOG_FILE" || blocked "could not build the diff"
diff=$(head -c "$MAX_DIFF" "$TMP/diff.full")
DIFFNOTE=""; [ "$(wc -c < "$TMP/diff.full" | tr -d ' ')" -gt "$MAX_DIFF" ] && DIFFNOTE="The diff was cut at $MAX_DIFF bytes. Say what you could not see."
# the files as they are at the head, bounded in total
: > "$TMP/text"; used=0; LEFT=""; mkdir -p "$TMP/head"; i=0
for f in "${FILES[@]}"; do
  i=$((i + 1))
  # Read from git, never from the disk (round 6): a folder of the path can be a link (infra/ -> another checkout), which [ -L ] on the last part
  # never saw. A link the commit itself holds (round 5: infra/prod.tf -> ~/.aws/credentials) is named, never followed.
  ent=$(safe_git -C "$WT" ls-tree -z HEAD -- ":(literal)$f" | tr '\0' '\n' | head -1)
  case "$ent" in
    "") printf '\n=== %s (deleted in this change)\n' "$f" >> "$TMP/text"; continue ;;
    120000\ *) printf '\n=== %s (a symbolic link; not read)\n' "$f" >> "$TMP/text"; continue ;;
    *\ blob\ *) ;;
    *) printf '\n=== %s (not a file; not read)\n' "$f" >> "$TMP/text"; continue ;;
  esac
  oid=$(cut -d' ' -f3 <<<"${ent%%	*}")
  safe_git -C "$WT" cat-file blob "$oid" > "$TMP/head/$i" 2>/dev/null || { LEFT="${LEFT:+$LEFT, }$f"; continue; }
  sz=$(wc -c < "$TMP/head/$i" | tr -d ' ')
  if [ "$sz" -gt "$MAX_ONE" ] || [ $((used + sz)) -gt "$MAX_TEXT" ]; then LEFT="${LEFT:+$LEFT, }$f"; continue; fi
  { printf '\n=== %s\n' "$f"; cat "$TMP/head/$i"; } >> "$TMP/text"; used=$((used + sz))
done
filetext=$(cat "$TMP/text")
FILENOTE=""; [ -z "$LEFT" ] || FILENOTE="Not included because of size (read them from your working folder if you need them): $LEFT"

# stack notes of the packs that fit the kinds of file in THIS change (not everything else in the checkout). Terraform counts as AWS only when
# a changed .tf file names the AWS provider or an aws_ resource: Terraform alone says nothing about the cloud.
PACKIDS=$(python3 - "$QUARTERDECK_DIR" "$TMP" "$TMP/list" 2>>"$LOG_FILE" <<'PY'
import os, re, sys
sys.path.insert(0, sys.argv[1] + "/bin")
import packs
rows = [l.rstrip("\n").split("\t", 1) for l in open(sys.argv[3]) if "\t" in l]
prof = {"infrastructure": [], "deploy_targets": []}
for i, (kind, path) in enumerate(rows, 1):
    if kind == "Terraform":
        # the head's text as git holds it, saved above ($TMP/head/<n>); absent for a link, a deleted file or a non-file (round 6)
        try:
            tf = open(sys.argv[2] + "/head/" + str(i), errors="replace").read(400000)
        except OSError:
            continue
        # Terraform alone names no cloud: the provider or resource names in the changed file do
        if re.search(r'hashicorp/google|provider\s+"google|\bgoogle_[a-z_]+"', tf):
            prof["deploy_targets"].append({"name": "Google Cloud", "evidence": [path]})
        if re.search(r'hashicorp/azurerm|provider\s+"azurerm|\bazurerm_[a-z_]+"', tf):
            prof["deploy_targets"].append({"name": "Azure", "evidence": [path]})
        if not re.search(r'aws_|hashicorp/aws|provider\s+"aws"', tf):
            continue
    key = "deploy_targets" if kind in ("Vercel", "Supabase", "Cloudflare", "Fly.io", "Azure Functions") or kind.startswith("Google Cloud") else "infrastructure"
    prof[key].append({"name": kind, "evidence": [path]})
    if kind in ("AWS CDK", "AWS CloudFormation / SAM", "Serverless Framework"):
        prof["deploy_targets"].append({"name": "AWS", "evidence": [path]})
    if kind in ("Azure Functions", "Azure ARM template"):
        prof["deploy_targets"].append({"name": "Azure", "evidence": [path]})
print(" ".join(p["id"] for p, _ in packs.select(prof)))
PY
)
PACKTEXT=""; [ -z "$PACKIDS" ] || PACKTEXT=$(python3 "$QUARTERDECK_DIR/bin/packs.py" text $PACKIDS 2>/dev/null)
say "  $nfiles infrastructure file(s): $KINDS${PACKIDS:+; stack notes: $PACKIDS}"

# ---- the rigger judges -------------------------------------------------------------------------------------------------------
prompt="$(preamble "$PROJECT")

You are the rigger on the infrastructure crew. Your seat: $(crew_meta rigger seat).

$(crew_role rigger)

--- THIS WATCH ---

You are reading $subject. This is a files-only review: you have no credentials, no shell and no network, and you must not
try to run, plan, apply or deploy anything. You cannot see the live account, so you cannot see drift between these files and
what is running; do not claim to.
$(printf 'Title: %s\n\n%s\n' "$title" "$body" | untrusted "pull request text")

The harness found these infrastructure files in the change (kind, then path):
$(untrusted "changed infrastructure file names" < "$TMP/list")
${SECRETS:+
These files changed too, but may hold secrets, so they are named only. You must not open them:
$(printf '%s\n' "$SECRETS" | untrusted "names of files held back")
}
The change, as a diff of those files:
$(printf '%s\n' "$diff" | untrusted "diff of infrastructure files")
${DIFFNOTE:+$DIFFNOTE
}
The same files as they are at the head:
$(printf '%s\n' "$filetext" | untrusted "infrastructure files at the head")
${LEFT:+Not included because of size (Read them from your working folder if you need them):
$(printf '%s\n' "$LEFT" | untrusted "names of files not included")
}${PACKTEXT:+
The harness picked these stack notes for what it found in this checkout. They are guidance for what to look for, not facts about this change:
$PACKTEXT
}
You may Read, Grep and Glob other files in your working folder (variables, modules, other stacks) to see what a change refers to.
Report at most $PER_RUN items, fewer if that is the honest number; zero is a normal outcome. One item per thing that changes.
Put EVERY item that matters in INFRA_JSON, including the lower-risk ones: the harness reads only the contract lines, and anything
you write outside them is thrown away, so do not keep a second list in prose.
Write plain words. Do not write a command line for anyone to run and do not name a tool invocation: the harness refuses a reply
that does. Say what a person should check in words.

Every item must carry all seven keys, rollback included, even a low one: an item with a key missing makes the harness throw the whole reply away.
End your reply with exactly these lines and nothing after them:
INFRA_JSON: <one-line JSON array; [] when there is nothing to say. Each item: {\"resource\":\"the resource or, if none, the file\",\"change\":\"what changes, in plain words\",\"risk\":\"low|medium|high\",\"why\":\"why it is that risk, pointing at the file\",\"blast_radius\":\"what is affected if this is wrong\",\"rollback\":\"how to undo it from the files, or that it cannot be undone from the files\",\"needs_human\":true or false}>
VERDICT: CLEAN
  or
VERDICT: REVIEWED <count>"

DENY="$QUARTERDECK_DENY_TOOLS,Bash,Read(**/*.tfstate*),Read(**/*.tfvars*),Read(**/.env*),Read(**/*.pem)"
result=$(claude_run "$WT" "$prompt" "Read,Grep,Glob" "$DENY"); rc=$?
[ $rc = 2 ] && { say "quarterdeck: usage limit reached — nothing written"; exit 0; }
[ $rc = 3 ] && { record_run "$PROJECT" infra ERROR "$KEY stopped at the per-call cap"; die "infra: the model call hit its per-call cap — nothing written"; }
[ $rc = 0 ] && [ -n "$result" ] || { record_run "$PROJECT" infra ERROR "$KEY run failed"; die "infra run failed"; }

# A reply that tells anyone to run a cloud command is refused whole. The harness is files only; nothing in a reply is ever run.
CLOUD_CMD='(^|[^[:alnum:]_./-])((terraform|tofu|terragrunt|pulumi)[[:space:]]+(plan|apply|destroy|import|taint|untaint|force-unlock)|(cdk|sam|sls|serverless|vercel|supabase)[[:space:]]+(deploy|destroy|diff|synth|bootstrap|remove|invoke|logs|login|link|push|pull|migrate|db|functions|secrets|env|--prod|--force|--stage|--profile|-)|aws[[:space:]]+(s3api|s3|iam|ec2|rds|lambda|cloudformation|sts|ssm|secretsmanager|kms|dynamodb|sqs|sns|route53|logs|ecr|ecs|eks|apigateway|configure|--)|wrangler[[:space:]]+(deploy|publish|dev|secret|d1|kv|r2|delete|login|tail|rollback|versions|pages|types|whoami)|(flyctl|fly)[[:space:]]+(deploy|launch|secrets|scale|volumes?|ssh|apps?|machines?|postgres|proxy|console|destroy|auth|logs|status|ips|certs|releases|regions|redeploy|restart)|gcloud[[:space:]]+(run|compute|iam|projects|storage|sql|functions|app|secrets|auth|config|services|container|builds|deploy|kms|logging|pubsub|artifacts|organizations|alpha|beta)|gsutil[[:space:]]+(cp|mv|rm|iam|acl|ls|mb|rb|rsync|defacl)|bq[[:space:]]+(query|mk|rm|load|extract|update)|azd[[:space:]]+(up|deploy|provision|down|auth|env|init|pipeline)|az[[:space:]]+(login|account|group|deployment|storage|keyvault|role|webapp|functionapp|resource|vm|network|sql|cosmosdb|monitor|ad|acr|bicep|containerapp|--))'
# Matched on the reply as a reader would see it once decoded (round 5: "terraform destroy" inside the JSON passed the raw text): escapes
# ( , \t, \x20, &nbsp;) decoded, every unicode space, control and invisible character made a plain space, quotes and backslashes dropped
# ("terra\"form\""), letter case folded.
plain=$(python3 -c '
import html, re, sys, unicodedata
t = sys.stdin.read()
for _ in range(2):
    t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), t)
    t = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), t)
    t = re.sub(r"\\[tnrfv]", " ", t)
    t = html.unescape(t)
t = unicodedata.normalize("NFKC", t)
t = "".join(" " if unicodedata.category(c)[0] in "ZC" and c != "\n" else c for c in t)
# ponytail: an all-capitals AWS or AZ is the cloud named in prose ("the AWS IAM role"), not the command, so it is kept apart before folding case
t = re.sub(r"\b(AWS|AZ|AZD)\b", r"\1_", t)
t = re.sub(r"[\"'"'"'`\\]", "", t).casefold()
print(re.sub(r"[ ]+", " ", t))' <<<"$result") || plain="$result"
if grep -Eq "$CLOUD_CMD" <<<"$result"$'\n'"$plain"; then
  say "  refused: the reply tells someone to run a cloud command: $(grep -Eo "$CLOUD_CMD" <<<"$result
$plain" | head -1 | sed 's/^[^[:alnum:]]//')"
  record_run "$PROJECT" infra ERROR "$KEY the reply suggested running a cloud command"
  die "infra: the reply suggested running a cloud command — refused, nothing written (see logs/runs/$QUARTERDECK_RUN_ID.json)"
fi

raw=$(grep -o '^INFRA_JSON: .*' <<<"$result" | tail -1 | sed 's/^INFRA_JSON: //')
vline=$(grep -Eo '^VERDICT: (CLEAN|REVIEWED[ 0-9]*)' <<<"$result" | tail -1)
valid='type == "array" and all(.[]; type == "object"
  and (.resource | type == "string" and length > 0) and (.change | type == "string" and length > 0)
  and (.risk | IN("low", "medium", "high"))
  and (.why | type == "string") and (.blast_radius | type == "string") and (.rollback | type == "string")
  and (.needs_human | type == "boolean"))'
if ! jq -e "$valid" <<<"$raw" >/dev/null 2>&1 || [ -z "$vline" ]; then
  record_run "$PROJECT" infra ERROR "$KEY unparseable contract"
  die "contract did not parse — nothing written (see logs/runs/$QUARTERDECK_RUN_ID.json)"
fi
items=$(jq -c --argjson n "$PER_RUN" '[.[0:$n][] | {resource, change, risk, why, blast_radius, rollback, needs_human: (.needs_human or .risk == "high")}]
  | sort_by({high:0, medium:1, low:2}[.risk])' <<<"$raw")
nraw=$(jq length <<<"$raw"); n=$(jq length <<<"$items"); high=$(jq '[.[] | select(.risk == "high")] | length' <<<"$items"); human=$(jq '[.[] | select(.needs_human)] | length' <<<"$items")
if { [ "$n" = 0 ] && [[ "$vline" != *CLEAN* ]]; } || { [ "$n" != 0 ] && [[ "$vline" != *REVIEWED* ]]; }; then
  record_run "$PROJECT" infra ERROR "$KEY the verdict line does not match the items"
  die "the verdict line does not match the items — nothing written"
fi
if [ "$n" = 0 ]; then verdict="CLEAN"; detail="no item in $nfiles infrastructure file(s)"; else verdict="REVIEWED $n"; detail="$n finding(s), $high high, $human for a person"; fi

CUTNOTE=""; [ "$nraw" -le "$n" ] || CUTNOTE="The reply held $nraw items; this report keeps the first $n (the cap is $PER_RUN, set by QUARTERDECK_INFRA_MAX_ITEMS)."
report="**Rigger — $subject**

**$verdict.** $detail. Files read: $KINDS ($nfiles file(s)).

**What this review cannot see.** It read files only. It ran nothing against any cloud and holds no credentials, so it cannot see drift: changes made by hand in the live account, resources the files do not mention, or state that no longer matches the files. A person who can see the live account must check the items marked for a person.${NOTE_SECRETS:+

$NOTE_SECRETS.}${FILENOTE:+

$FILENOTE.}${DIFFNOTE:+

$DIFFNOTE}${CUTNOTE:+

$CUTNOTE}
$(jq -r '.[] | "\n### \(.risk | ascii_upcase): \(.resource)\(if .needs_human then "  (needs a person)" else "" end)\n**Change:** \(.change)\n\n**Why:** \(.why)\n\n**Blast radius:** \(.blast_radius)\n\n**Rollback:** \(.rollback)"' <<<"$items")

<sub>Quarterdeck rigger. Files only: the harness found the files and wrote the verdict; the rigger judged. Nothing was run, posted or changed.</sub>"
say ""; say "$report" >&2; say ""

if [ "$APPLY" != 1 ]; then
  say "quarterdeck: report only — pass --apply to write the change report into workspace/"
  record_run "$PROJECT" infra "DRY-RUN" "$KEY — $verdict" "$url"
  exit 0
fi
DOC="$QUARTERDECK_HOME/workspace/${PROJECT}-infra-${KEY}.md"
printf '%s\n' "$report" > "$DOC"
record_run "$PROJECT" infra "$verdict" "$KEY — $detail" "$url"
say "quarterdeck: wrote $DOC"

exit
}
