#!/bin/bash
# Plan-gated Terraform authoring, first slice (ticket #101). A plan item's Where field may name ONE Terraform folder (`infra/net/`, in backticks,
# the strict form of a file path). That unlocks only *.tf files and *.tfvars files without a secret-looking value under that folder; the never-unlock
# list still wins, and state, .terraform/, .terraformrc, credentials and a secret-looking file stay protected. The harness runs `terraform fmt -check`
# and `terraform validate` (validate only with a prefetched provider plugin folder) through project_exec, with no cloud credential and no network,
# against a fake terraform that fails loudly on anything else and records its argv. The infra duty then reviews the diff against the AWS pack.
# Written to fail on the code before the change.
source "$(dirname "${BASH_SOURCE[0]}")/selftest-lib.sh"

# ---- protect.py: the folder form of Where ---------------------------------------------------------------------------------
pt=$(python3 - "$REAL/bin" "$T/ptroot" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1]); import protect as p
root = sys.argv[2]
for d in ["infra/net/sub", "infra/other", "infra/net/.terraform/providers", ".github/tf"]:
    os.makedirs(os.path.join(root, d), exist_ok=True)
def w(rel, text):
    with open(os.path.join(root, rel), "w") as f: f.write(text)
w("infra/net/main.tf", 'resource "aws_vpc" "v" {}\n')
w("infra/net/clean.tfvars", 'region = "eu-west-1"\ncidr = "10.0.0.0/16"\nadmin_password = ""\n')
w("infra/net/pw.tfvars", 'db_password = "hunter2"\n')
w("infra/net/key.tfvars", 'access = "AKIA' + 'IOSFODNN7EXAMPLE"\n')          # spelt apart: the publish scan reads this file
w("infra/net/pem.tfvars", 'cert = <<EOT\n-----BEGIN ' + 'PRIVATE KEY-----\nabc\nEOT\n')
w("infra/net/token.tfvars", 'api_token = "x"\n')
os.symlink("clean.tfvars", os.path.join(root, "infra/net/link.tfvars"))
os.symlink(os.path.join(root, "infra/other"), os.path.join(root, "infra/linked"))
bad = []
def un(plan, path, r=root): return not p.violations([path], [], plan, root=r)
PLAN = "# plan\n\n## 1. widen the VPC\n\n**Where.** `infra/net/`\n\n**Do this.** Change the CIDR.\n"
# INFRA/NET/ is the named folder only on a volume that compares names without case (a Mac's); on Linux it is another folder and stays locked
ci = os.path.isdir(os.path.join(root, "INFRA/NET"))
for ok in ["infra/net/main.tf", "infra/net/sub/x.tf", "infra/net/clean.tfvars", "./infra/net/main.tf"] + (["INFRA/NET/MAIN.TF"] if ci else []):
    if not un(PLAN, ok): bad.append("folder Where did not unlock " + ok)
if not ci and un(PLAN, "INFRA/NET/MAIN.TF"): bad.append("folder Where unlocked INFRA/NET/MAIN.TF on a case-sensitive volume")
for no in ["infra/other/main.tf", "infra/main.tf", "infra/net/x.tf.json", "infra/net/terraform.tfstate", "infra/net/terraform.tfstate.backup",
           "infra/net/.terraform/providers/x.tf", "infra/net/.terraform/terraform.tfstate", "infra/net/.terraformrc", "infra/net/terraform.rc",
           "infra/net/credentials.tfrc.json", "infra/net/.terraform.lock.hcl", "infra/net/Makefile", "infra/net/scripts/x.sh", "infra/net/.env",
           "infra/net/pw.tfvars", "infra/net/key.tfvars", "infra/net/pem.tfvars", "infra/net/token.tfvars", "infra/net/link.tfvars"]:
    if un(PLAN, no): bad.append("folder Where unlocked " + no)
# never without a plan: state, the provider cache, the CLI config and its credentials are protected at all
for h in ["terraform.tfstate", "a/b/terraform.tfstate.backup", "x/.terraform/plugins/p", ".terraformrc", "terraform.rc", "credentials.tfrc.json", ".terraform.lock.hcl"]:
    if not p.violations([h], [], ""): bad.append("not protected without a plan: " + h)
# prose, lists, bare values, a second Where, an escape, a link, a missing folder, no root: nothing
for name, plan in [("prose", "## 1. x\n\n**Where.** `src/app.js`\n\n**Do this.** Edit `infra/net/` and infra/net/main.tf.\n"),
                   ("list", "## 1. x\n\n**Where.** `infra/net/, src/`\n"), ("two in backticks", "## 1. x\n\n**Where.** `infra/net/` `infra/other/`\n"),
                   ("bare", "## 1. x\n\n**Where.** infra/net/\n"), ("second Where", "## 1. x\n\n**Where.** `infra/net/`\n**Where.** `src/`\n"),
                   ("escape", "## 1. x\n\n**Where.** `infra/../infra/net/`\n"), ("absolute", "## 1. x\n\n**Where.** `" + root + "/infra/net/`\n"),
                   ("root folder", "## 1. x\n\n**Where.** `./`\n")]:
    if un(plan, "infra/net/main.tf"): bad.append(name + " unlocked infra/net/main.tf")
if un("## 1. x\n\n**Where.** `infra/linked/`\n", "infra/linked/main.tf"): bad.append("a folder that is a symlink unlocked")
if un("## 1. x\n\n**Where.** `infra/gone/`\n", "infra/gone/main.tf"): bad.append("a folder not in the checkout unlocked")
if un(PLAN, "infra/net/main.tf", r=""): bad.append("a folder Where unlocked without a worktree to check it against")
# the never-unlock list still wins
if un("## 1. x\n\n**Where.** `.github/tf/`\n", ".github/tf/main.tf"): bad.append("a folder under .github unlocked")
# the folder list the harness runs the checks on
if p.tf_folders(PLAN, root) != ["infra/net/"]: bad.append("tf_folders: %r" % p.tf_folders(PLAN, root))
if p.tf_folders("## 1. x\n\n**Where.** `infra/gone/`\n", root) != []: bad.append("tf_folders listed a missing folder")
if p.plan_folders("## 1. x\n\n**Where.** `infra/gone/`\n") != ["infra/gone/"]: bad.append("plan_folders")
# protected_allow still unlocks what the owner names, and a plain file Where still works as before
if p.violations(["infra/net/main.tf"], ["infra/net/*.tf"], ""): bad.append("protected_allow")
if not p.violations(["infra/net/pw.tfvars"], [], "## 1. x\n\n**Where.** `infra/net/pw.tfvars`\n", root=root): bad.append("a file Where unlocked a secret-looking tfvars")
# review r9 T1: the JSON variable files and the backend file Terraform also loads are protected, and no plan unlocks them
for f in ["infra/net/terraform.tfvars.json", "infra/net/x.auto.tfvars.json", "infra/net/prod.tfbackend"]:
    w(f, "{}\n")
    if not p.violations([f], [], ""): bad.append("not protected without a plan: " + f)
    if un(PLAN, f): bad.append("folder Where unlocked " + f)
    if un("## 1. x\n\n**Where.** `" + f + "`\n", f): bad.append("a file Where unlocked " + f)
# review r9 T2: on a case-sensitive volume a folder Where unlocks the folder as spelled, not another whose name differs only in case
cs = os.path.join(os.path.dirname(root), "csroot")
os.makedirs(os.path.join(cs, "Infra/Net")); w2 = lambda rel: open(os.path.join(cs, rel), "w").write("x\n")
w2("Infra/Net/main.tf")
if not os.path.exists(os.path.join(cs, "infra/net")):          # case-sensitive: the other spelling is another folder
    os.makedirs(os.path.join(cs, "infra/net")); w2("infra/net/main.tf")
    cplan = "## 1. x\n\n**Where.** `Infra/Net/`\n"
    if un(cplan, "infra/net/main.tf", r=cs): bad.append("a Where of Infra/Net/ unlocked infra/net/main.tf")
    if not un(cplan, "Infra/Net/main.tf", r=cs): bad.append("a Where of Infra/Net/ did not unlock Infra/Net/main.tf")
elif not un("## 1. x\n\n**Where.** `Infra/Net/`\n", "infra/net/main.tf", r=cs):
    bad.append("on a case-insensitive volume infra/net/ is the folder Infra/Net/ and was not unlocked")
# review r9 T3: pass, pwd, passphrase, salt, seed, bearer, jwt, webhook and signing names are secret names; a key in a map is read too
for txt in ['db_pass = "x"\n', 'pwd = "x"\n', 'db_passphrase = "x"\n', 'jwt_salt = "x"\n', 'seed = "x"\n', 'bearer = "x"\n', 'slack_webhook = "x"\n',
            'signing = "x"\n', 'creds = {\n  db_pass = "x"\n}\n', 'creds = {\n  "pwd": "x"\n}\n', 'db = {\n  name = "app"\n  user_pass = "x"\n}\n']:
    if not p.tfvars_secret(txt): bad.append("tfvars_secret missed " + txt.replace("\n", " "))
for txt in ['region = "eu-west-1"\n', 'compass_heading = "north"\n', 'db = {\n  name = "app"\n}\n']:
    if p.tfvars_secret(txt): bad.append("tfvars_secret flagged an innocent " + txt.replace("\n", " "))
print("; ".join(bad) or "CLEAN")
PY
)
ck "T1 protect.py: a folder Where unlocks *.tf and clean *.tfvars under it only; state, .terraform/, .terraformrc, credentials, the lock file and secret-looking tfvars stay protected; prose, lists, escapes, links and missing folders unlock nothing${pt:+ ($pt)}" '[ "$pt" = CLEAN ]'

# ---- the fake terraform: records argv, fails loudly on anything but fmt, validate and an offline init ---------------------------
# outside $T: the duties run with QUARTERDECK_DIR=$T, and bubblewrap never mounts the program folder, a PATH entry in it included
TFB=$(mktemp -d); trap 'rm -rf "$T" "$TFB"' EXIT; mkdir -p "$TFB/tfbin"
cat > "$TFB/tfbin/terraform" <<FAKE
#!/bin/bash
printf '%s\n' "\$*" >&7
env | grep -E '^(AWS_|TF_VAR|GOOGLE_|ARM_|AZURE_)' >&8
dir=.; args=("\$@")
case "\${args[0]:-}" in -chdir=*) dir="\${args[0]#-chdir=}"; args=("\${args[@]:1}") ;; esac
loud() { echo "FAKE TERRAFORM: REFUSED \$*" >&9; echo "FAKE TERRAFORM: \$1 must never be run by the harness" >&2; exit 97; }
case "\${args[0]:-}" in
  fmt)      cd "\$dir" || exit 1; bad=\$(grep -rl BADFMT --include='*.tf' . 2>/dev/null); [ -z "\$bad" ] || { echo "\$bad"; exit 3; }; exit 0 ;;
  validate) cd "\$dir" || exit 1; [ -d .terraform ] || { echo "Error: Missing required provider"; exit 1; }; grep -rq BROKEN --include='*.tf' . && { echo "Error: Unsupported argument"; exit 1; }; echo "Success! The configuration is valid."; exit 0 ;;
  init)     a=" \${args[*]} "; pd=""
            for x in "\${args[@]}"; do case "\$x" in -plugin-dir=*) pd="\${x#-plugin-dir=}" ;; esac; done
            case "\$a" in *" -backend=false "*) ;; *) loud "init with a backend" ;; esac
            case "\$a" in *" -get=false "*) ;; *) loud "init that fetches modules" ;; esac
            [ -n "\$pd" ] && [ -f "\$pd/provider-marker" ] || loud "init without an offline plugin folder (it would reach the network)"
            cd "\$dir" && mkdir -p .terraform && exit 0 ;;
  *)        loud "\${args[0]:-nothing}" ;;
esac
FAKE
chmod +x "$TFB/tfbin/terraform"
export PATH="$TFB/tfbin:$PATH" QUARTERDECK_TERRAFORM="$TFB/tfbin/terraform"   # lib.sh puts the system folders first on PATH: a real terraform there would win
mkdir -p "$T/plugins/registry.terraform.io/hashicorp/aws"; echo marker > "$T/plugins/provider-marker"
export AWS_ACCESS_KEY_ID=AKIAFIXTUREKEY AWS_SECRET_ACCESS_KEY=fixture-secret-value TF_VAR_db_password=fixture-pw GOOGLE_APPLICATION_CREDENTIALS=/fixture/gcp.json
tfreset() { : > "$T/tf-argv"; : > "$T/tf-env"; : > "$T/tf-forbidden"; }
# The stand-in writes to descriptors 7, 8 and 9, opened here and inherited through the harness, not to paths: on Linux bubblewrap mounts nothing of
# $T but the PATH folder (read-only), so a path write would land in the sandbox's private /tmp and be lost. The sandbox is the one that ships.
tfreset; exec 7>>"$T/tf-argv" 8>>"$T/tf-env" 9>>"$T/tf-forbidden"
only_fmt_validate() { [ ! -s "$T/tf-forbidden" ] && ! grep -vE '^-chdir=[^ ]+ (fmt -check -recursive -no-color|validate -no-color|init -backend=false -get=false -input=false -no-color -plugin-dir=[^ ]+)$' "$T/tf-argv"; }

# This machine has no bubblewrap and no sandbox-exec, so project_exec refuses to run a project command with the sandbox on (that refusal is
# itself checked below). The rest of these checks run the commands with QUARTERDECK_CHECK_SANDBOX=off, the owner's explicit opt-out.
SBX=on; [ "$(uname -s)" = Linux ] && ! command -v bwrap >/dev/null 2>&1 && SBX=off
NESTED=""; st_can_nest_sandbox || NESTED=1   # inside the sandbox, where a second one cannot start: the same opt-out as a machine without one
[ -n "$NESTED" ] && SBX=off && st_skip "T2 the sandboxed run of terraform: this suite is already inside the sandbox and a sandbox cannot start inside it; checked with QUARTERDECK_CHECK_SANDBOX=off"
[ "$SBX" = off ] && st_skip "T2 the sandboxed run of terraform on this machine (Linux without bubblewrap): checked with QUARTERDECK_CHECK_SANDBOX=off; the refusal with it on is checked instead"

mkdir -p "$T/tfwt/infra/net"; printf 'resource "aws_vpc" "v" {}\n' > "$T/tfwt/infra/net/main.tf"
tfc() { # tfc <sandbox on|off> <plugin dir or ""> -> the tf_checks JSON lines, then the checks_summary text
  ( export QUARTERDECK_HOME="$T/tfdata" QUARTERDECK_CHECK_SANDBOX=$1; mkdir -p "$T/tfdata/workspace" "$T/tfdata/logs"; source "$REAL/bin/lib.sh"
    out=$(tf_checks "$T/tfwt" "$2" "infra/net/" 2>/dev/null); printf '%s\n' "$out"; echo ---; checks_summary "$out" ) 2>/dev/null
}
tfreset; r=$(tfc "$SBX" "")
ck "T2 with no plugin folder: fmt runs, validate is reported 'not run: no provider plugins available offline', never passed" \
   'grep -q "\"name\":\"terraform fmt infra/net/\"" <<<"$r" && grep -q "\"rc\":0" <<<"$(grep "terraform fmt" <<<"$r")" && grep -q "not run: no provider plugins available offline" <<<"$r" && ! grep -q "\"name\":\"terraform validate infra/net/\".*\"rc\":0" <<<"$r"'
ck "  and terraform was called with fmt only" 'only_fmt_validate && grep -q " fmt " "$T/tf-argv" && ! grep -qE " (validate|init) " "$T/tf-argv"'
tfreset; r=$(tfc "$SBX" "$T/plugins")
ck "T2 with a prefetched plugin folder: init offline (no backend, no module fetch, the copied plugin folder) and validate run and pass" \
   'grep -q "\"name\":\"terraform validate infra/net/\"" <<<"$r" && grep "terraform validate" <<<"$r" | grep -q "\"rc\":0" && grep -q " validate " "$T/tf-argv" && grep -q " init " "$T/tf-argv" && only_fmt_validate'
ck "  the plugin folder is a copy in the scratch folder, not the owner's own" '! grep -q -- "-plugin-dir=$T/plugins" "$T/tf-argv"'
ck "  no cloud credential reached terraform (AWS_, TF_VAR_, GOOGLE_ were set in the harness's environment)" '[ ! -s "$T/tf-env" ]'
printf 'resource "aws_vpc" "v" { BADFMT }\n' > "$T/tfwt/infra/net/main.tf"
tfreset; r=$(tfc "$SBX" "$T/plugins")
ck "T2 an unformatted file fails the fmt check (it is not passed)" 'grep "terraform fmt" <<<"$r" | grep -qv "\"rc\":0"'
printf 'resource "aws_vpc" "v" {}\n' > "$T/tfwt/infra/net/main.tf"
ck "T2 the pull request summary names the validate step as not run when it was not run" '(r=$(tfc "$SBX" ""); grep -q "not run: no provider plugins available offline" <<<"${r#*---}")'
# review r9 T6: a link anywhere under the folder (fmt -recursive and validate would follow it out of the worktree) means terraform is not run
mkdir -p "$T/t6-outside"; printf 'resource "x" "T6OUTSIDE" {}\n' > "$T/t6-outside/o.tf"; ln -s "$T/t6-outside" "$T/tfwt/infra/net/mods"
tfreset; r=$(tfc "$SBX" "$T/plugins")
ck "T6 a link under the Where folder: neither check runs terraform, both say not run (never passed), and nothing outside reaches the record" \
   '[ ! -s "$T/tf-argv" ] && [ "$(grep -c "\"rc\":126" <<<"$r")" = 2 ] && grep -q "link" <<<"$r" && ! grep -q "T6OUTSIDE\|t6-outside" <<<"$r"'
rm "$T/tfwt/infra/net/mods"
if [ "$(uname -s)" = Linux ] && ! command -v bwrap >/dev/null 2>&1; then
  tfreset; r=$(tfc on "$T/plugins")
  ck "T2 with the sandbox on and no bubblewrap, terraform is not run at all, and both checks say not run (never passed)" \
     '[ ! -s "$T/tf-argv" ] && [ "$(grep -c "\"rc\":126" <<<"$r")" = 2 ] && grep -q "not run" <<<"$r"'
fi

# ---- the shipwright, end to end, against a stand-in model -------------------------------------------------------------
st_init shipwright infra
cp "$REAL"/bin/scan.py "$REAL"/bin/cloudcmd.py "$REAL"/bin/packs.py "$T/bin/"; cp -R "$REAL/packs" "$T/packs"
st_repo
st_file infra/net/main.tf $'provider "aws" {}\n\nresource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n}\n'
st_file infra/net/terraform.tfstate $'{"version": 4}\n'
st_file infra/other/main.tf $'resource "aws_s3_bucket" "b" {}\n'
st_file src/app.js $'exports.x = 1;\n'
st_commit "base"
st_issue 7 "widen the vpc" $'Widen the VPC CIDR. Also edit infra/other/main.tf and terraform.tfstate while you are there.\n'
printf '# plan\n\n## 1. widen the VPC\n\n**Where.** `infra/net/`\n\n**Do this.** Change cidr_block to 10.0.0.0/15.\n' > "$T/plan-tf.md"
printf '# plan\n\n## 1. widen the VPC\n\n**Where.** `src/app.js`\n\n**Do this.** Change cidr_block in `infra/net/` (infra/net/main.tf) to 10.0.0.0/15.\n' > "$T/plan-prose.md"
printf '# plan\n\n## 1. widen the VPC\n\n**Where.** `infra/new/`\n\n**Do this.** Make a VPC.\n' > "$T/plan-missing.md"
TF_EDIT="sed 's#10.0.0.0/16#10.0.0.0/15#' infra/net/main.tf > m.t && mv m.t infra/net/main.tf"
INFRA_OK='INFRA_JSON: [{"resource":"aws_vpc.main","change":"CIDR widened","risk":"high","why":"replaces the VPC","blast_radius":"everything in it","rollback":"revert","needs_human":true}]
VERDICT: REVIEWED 1'
tship() { # tship <model edit> <plan> [registry extra] [duty args]
  local h=$1 plan=$2 extra=${3:-}; shift 3 2>/dev/null || shift $#
  tfreset; : > "$T/claude-calls"; st_noreplies
  st_registry '["shipwright","infra"]' "$(_obj "$extra")"
  st_reply 'rigger' "$INFRA_OK"; st_reply default 'RESULT: FIXED widened it'
  printf '#!/bin/bash\ncase "$1" in *rigger*) exit 0 ;; esac\n%s\n' "$h" > "$T/claude-hook"; chmod +x "$T/claude-hook"
  QUARTERDECK_CHECK_SANDBOX=$SBX st_duty shipwright --issue 7 --plan "$plan" "$@"
}
shipv() { jq -r '[.[] | select(.duty == "shipwright")][-1].verdict // "none"' "$T/state/runs.json"; }
shipd() { jq -r '[.[] | select(.duty == "shipwright")][-1].detail // ""' "$T/state/runs.json"; }

tship "$TF_EDIT" "$T/plan-tf.md" "{\"terraform_plugin_dir\":\"$T/plugins\"}"
ck "T3 a plan naming infra/net/ in its Where field lets the shipwright change infra/net/main.tf (DRY-RUN, nothing refused)" '[ "$(shipv)" = DRY-RUN ]'
ck "  the harness ran terraform fmt and validate on the folder, before and after, and nothing else" 'only_fmt_validate && [ "$(grep -c " fmt " "$T/tf-argv")" = 2 ] && [ "$(grep -c " validate " "$T/tf-argv")" = 2 ]'
ck "  the Terraform builder had no shell: Read, Edit, Write, Grep and Glob only" '[ "$(jq -r "select(.prompt | test(\"rigger\") | not) | .tools" "$T/claude-calls" | head -1)" = "Read,Edit,Write,Grep,Glob" ]'
ck "  the infra duty reviewed the diff: the rigger was asked, given the changed line and the AWS stack notes" 'grep -q "rigger" "$T/claude-calls" && jq -r "select(.prompt | test(\"rigger\")) | .prompt" "$T/claude-calls" | grep -q "10.0.0.0/15" && jq -r "select(.prompt | test(\"rigger\")) | .prompt" "$T/claude-calls" | grep -q "Stack notes: AWS infrastructure files"'
ck "  its report carries the experimental label and says no plan was run by Quarterdeck" 'grep -q "Experimental" <<<"$OUT" && grep -q "No plan was run by Quarterdeck" <<<"$OUT" && grep -q "HIGH: aws_vpc.main" <<<"$OUT"'
ck "  the terraform state was never read into a prompt" '! grep -q "\"version\": 4" "$T/claude-calls"'

tship "$TF_EDIT" "$T/plan-tf.md" '' --apply
ck "T3 with --apply the branch is pushed and the pull request is a draft whose body says a person applies and carries the review" \
   '[ "$(shipv)" = PR ] && grep -q "^gh pr create" "$T/gh-calls" && grep -q -- "--draft$" "$T/gh-calls" && grep -q "apply through your own process" "$T/gh-calls" && grep -q "No plan was run by Quarterdeck" "$T/gh-calls" && grep -q "not run: no provider plugins available offline" "$T/gh-calls"'

tship "$TF_EDIT; echo '{\"version\": 5}' > infra/net/terraform.tfstate" "$T/plan-tf.md"
ck "T4 a .tfstate in the Where folder is never editable: REFUSED before any check" '[ "$(shipv)" = REFUSED ] && grep -q "terraform.tfstate" <<<"$(shipd)" && [ "$(grep -c " fmt " "$T/tf-argv" 2>/dev/null)" = 1 ]'
tship "$TF_EDIT; printf 'db_password = \"hunter2-fixture\"\\n' > infra/net/prod.tfvars" "$T/plan-tf.md"
ck "T4 a secret-looking tfvars is refused" '[ "$(shipv)" = REFUSED ] && grep -q "prod.tfvars" <<<"$(shipd)"'
tship "$TF_EDIT; printf 'region = \"eu-west-1\"\\n' > infra/net/prod.tfvars" "$T/plan-tf.md"
ck "T4 a tfvars with no secret-looking value in the folder is let through" '[ "$(shipv)" = DRY-RUN ]'
tship "$TF_EDIT; mkdir -p infra/net/.terraform; echo x > infra/net/.terraform/x.tf" "$T/plan-tf.md"
ck "T4 the .terraform folder is never editable" '[ "$(shipv)" = REFUSED ] && grep -q ".terraform/x.tf" <<<"$(shipd)"'
tship "sed 's/aws_s3_bucket/aws_s3_bucket /' infra/other/main.tf > m.t && mv m.t infra/other/main.tf" "$T/plan-tf.md"
ck "T4 a .tf file outside the Where folder stays protected" '[ "$(shipv)" = REFUSED ] && grep -q "infra/other/main.tf" <<<"$(shipd)"'
tship "$TF_EDIT" "$T/plan-prose.md"
ck "T4 a plan that names the folder only in its prose unlocks nothing: REFUSED, and no terraform check was offered" '[ "$(shipv)" = REFUSED ] && grep -q "infra/net/main.tf" <<<"$(shipd)" && [ ! -s "$T/tf-argv" ]'
tship "$TF_EDIT" "$T/plan-missing.md"
ck "T4 a plan naming a folder that is not in the checkout stops before the model is asked" '[ "$RC" != 0 ] && [ ! -s "$T/claude-calls" ] && grep -q "infra/new/" <<<"$OUT"'

st_done
