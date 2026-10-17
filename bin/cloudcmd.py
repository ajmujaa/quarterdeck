#!/usr/bin/env python3
"""Does a model reply tell anyone to run a cloud command? Used by duties/infra.sh, which is files only and refuses such a reply whole.

    python3 bin/cloudcmd.py < reply        # prints the command it found and exits 1; exits 0 when the reply is prose

The reply is read as a person would see it once the Markdown report renders it: escapes decoded, Markdown emphasis and links and HTML tags and
comments taken out, zero-width and control characters removed (and, as a second reading, turned into spaces), every other kind of white space made
one space (a line break stays one), backslashes dropped, letters folded. Quotes and backticks are read twice: dropped (`terra"form"`), and as the
edge of a field or a code span. A tool may be named by its path (`/usr/local/bin/terraform`, `node_modules/.bin/cdk`) and be followed by options
before its verb (`terraform -chdir=prod destroy`, `aws --profile prod s3 rm`).

Only an INSTRUCTION to run a command counts (audit 7, L3): the command starts a line, a field or a code span (copy-paste form, a shell prompt or a
list marker before it allowed), or it follows a word that tells someone to run it (run, execute, then, please ...). A review sentence that names a
tool and a subcommand ("the new terraform import block", "the cdk diff would show", "Supabase db migrations") is prose. The verbs that are also
ordinary words need their own subcommand (`terraform workspace select`, `vercel env add`, `aws s3 rm`), an all-capitals AWS or AZ is kept apart
before the fold ("the AWS IAM role"), and `terraform state` counts only with a state subcommand after it.
"""
import html
import re
import sys
import unicodedata

_VERBS = {
    "terraform|tofu|terragrunt": r"plan|apply|destroy|import|taint|untaint|force-unlock|refresh|workspace\s+(?:new|select|delete)|state\s+(?:list|show|rm|mv|pull|push|replace-provider)",
    "pulumi": r"up|destroy|preview|refresh|import|cancel|login|stack\s+(?:rm|init|import|select)|state\s+(?:delete|rename|unprotect)",
    "cdk": r"deploy|destroy|diff|synth|bootstrap|--?[a-z]",
    "sam": r"deploy|delete|sync|build|local|--?[a-z]",
    "sls|serverless": r"deploy|remove|invoke|logs|login|--?[a-z]",
    "vercel": r"deploy|remove|rm|link|pull|env\s+(?:add|rm|remove|pull|ls)|logs|login|promote|rollback|--?[a-z]",
    "supabase": r"db\s+(?:push|reset|pull|remote|dump)|deploy|link|login|functions\s+(?:deploy|delete|serve|download)|secrets\s+(?:set|unset|list)|migration\s+(?:new|up|repair|squash|fetch)|--?[a-z]",
    "aws": r"s3\s+(?:rm|cp|mv|sync|ls|mb|rb|presign|website)|(?:s3api|iam|ec2|rds|lambda|cloudformation|sts|ssm|secretsmanager|kms|dynamodb|sqs|sns|route53|logs|ecr|ecs|eks|apigateway|organizations|cloudfront)\s+[a-z][a-z-]*|configure|--?[a-z]",
    "wrangler": r"deploy|publish|dev|secret|d1|kv|r2|delete|login|tail|rollback|versions|pages|types|whoami",
    "flyctl|fly": r"deploy|launch|secrets|scale|volumes?|ssh|apps?|machines?|postgres|proxy|console|destroy|auth|logs|status|ips|certs|releases|regions|redeploy|restart",
    "gcloud": r"run|compute|iam|projects|storage|sql|functions|app|secrets|auth|config|services|container|builds|deploy|kms|logging|pubsub|artifacts|organizations|alpha|beta",
    "gsutil": r"cp|mv|rm|iam|acl|ls|mb|rb|rsync|defacl",
    "bq": r"query|mk|rm|load|extract|update",
    "azd": r"up|deploy|provision|down|auth|env|init|pipeline",
    "az": r"login|account|group|deployment|storage|keyvault|role|webapp|functionapp|resource|vm|network|sql|cosmosdb|monitor|ad|acr|bicep|containerapp|--?[a-z]",
    "kubectl": r"apply|delete|create|replace|patch|scale|rollout|drain|cordon|uncordon|exec|edit|set|label|annotate|port-forward|cp|run|expose|autoscale|taint|config",
    "helm": r"install|uninstall|upgrade|rollback|delete|push|repo\s+(?:add|remove|update)|plugin\s+(?:install|uninstall)",
    "firebase": r"deploy|login|init|use|[a-z]+:[a-z:-]+",
    "netlify": r"deploy|link|unlink|login|init|[a-z]+:[a-z:-]+",
    "heroku": r"create|destroy|login|run|logs|ps|config|releases|addons|apps|pg|[a-z]+:[a-z:-]+",
    "doctl": r"compute|apps|kubernetes|databases|registry|auth|account|projects|serverless|spaces|monitoring",
    "eksctl": r"create|delete|upgrade|scale|utils|set|unset|drain|enable",
    "gh": r"workflow\s+(?:run|enable|disable)|secret\s+(?:set|delete|remove)|variable\s+(?:set|delete)|release\s+(?:create|delete|upload)|repo\s+(?:delete|archive|edit)",
    "docker": r"push|rm|rmi|login|system\s+prune|image\s+(?:push|rm|prune)|volume\s+(?:rm|prune)|compose\s+(?:down|push|rm)",
}
# between the tool and its verb: any number of options, each with or without a value (`-chdir=prod`, `--profile prod`, `-no-color`)
_OPTS = r"(?:\s+-[^\s]+(?:\s+[^\s-][^\s]*)?)*"
# what makes it an instruction: the start of a line, a field or a code span (after a shell prompt or a list marker), or a word that says to run it
_START = r"(?:^|\n)[ \t]*(?:(?:[$>#%]|[-*+]|\d+[.)])[ \t]*)?"
_TELL = r"\b(?:run|rerun|re-run|execute|exec|type|enter|invoke|try|do|then|first|next|now|please|just|via)[ \t]+"
_OPT_VERB = "|--?[a-z]"            # a verb list ending in this: the tool followed straight by an option (`vercel --prod`) counts too


def _verbs(v):
    words = v[:-len(_OPT_VERB)] if v.endswith(_OPT_VERB) else v
    return f"(?:(?:{words})(?![a-z0-9_])" + (_OPT_VERB if v.endswith(_OPT_VERB) else "") + ")"


CLOUD_CMD = re.compile(r"(?:" + _START + "|" + _TELL + r")(?P<cmd>(?:[^\s]*/)?(?:" + "|".join(
    f"(?:{t})(?:{_OPTS})\\s+{_verbs(v)}" for t, v in _VERBS.items()) + "))")

_BREAK = "\n\r\v\f\x1c\x1d\x1e\x85  "


def _decode(t):
    for _ in range(2):
        t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), t)
        t = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), t)
        t = re.sub(r"\\[nrfv]", "\n", t)
        t = re.sub(r"\\t", " ", t)
        t = html.unescape(t)
    return unicodedata.normalize("NFKC", t)


def _rendered(t, hidden):
    """What the Markdown report shows: no comments, tags, emphasis or link targets (each replaced by `hidden`)."""
    t = re.sub(r"<!--.*?(?:-->|\Z)", hidden, t, flags=re.S)
    t = re.sub(r"</?[A-Za-z][^>\n]*>", hidden, t)
    t = re.sub(r"!?\[([^\]\n]*)\]\([^)\n]*\)", r"\1", t)
    return re.sub(r"\*+|~~|(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])", hidden, t)


def readings(text):
    """The reply as a reader would see it, in the ways a hidden character can be read."""
    t = _decode(text)
    out = []
    for hidden in ("", " "):            # a zero-width or control character vanishes ("terra<ZWSP>form") or stands for a space ("terraform<ZWSP>destroy")
        r = _rendered(t, hidden)
        s = "".join("\n" if c in _BREAK else " " if c.isspace() else (hidden if unicodedata.category(c)[0] in "ZC" else c) for c in r)
        # an all-capitals AWS or AZ is the cloud named in prose ("the AWS IAM role"), not the command, so it is kept apart before folding case
        s = re.sub(r"\b(AWS|AZ|AZD)\b", r"\1_", s).replace("\\", "")
        for edge in ("", "\n"):          # quotes and backticks dropped (terra"form"), or the edge of a field or code span ("rollback":"cdk deploy")
            v = re.sub(r"[\"'`]", edge, s).casefold()
            out.append(re.sub(r"[ \t]+", " ", v))
    out.append(text)
    return out


def find(text):
    for s in readings(text):
        m = CLOUD_CMD.search(s)
        if m:
            return m.group("cmd").strip()
    return None


if __name__ == "__main__":
    hit = find(sys.stdin.read())
    if hit:
        print(hit)
    sys.exit(1 if hit else 0)
