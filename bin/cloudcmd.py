#!/usr/bin/env python3
"""Does a model reply tell anyone to run a cloud command? Used by duties/infra.sh, which is files only and refuses such a reply whole.

    python3 bin/cloudcmd.py < reply        # prints the command it found and exits 1; exits 0 when the reply is prose

The reply is read as a person would see it: escapes decoded, zero-width and control characters removed (and, as a second reading, turned into
spaces), every kind of white space and line break made one space, quotes and backslashes dropped, letters folded. A tool may be followed by options
before its verb (`terraform -chdir=prod destroy`, `aws --profile prod s3 rm`). Prose that only names a tool ("the AWS IAM role", "the terraform
state is not in these files") is not a command: an all-capitals AWS or AZ is kept apart before the fold, and `terraform state` counts only with a
state subcommand after it.
"""
import html
import re
import sys
import unicodedata

_VERBS = {
    "terraform|tofu|terragrunt": r"plan|apply|destroy|import|taint|untaint|force-unlock|refresh|workspace|state\s+(?:list|show|rm|mv|pull|push|replace-provider)",
    "pulumi": r"up|destroy|preview|refresh|import|cancel|login|stack\s+(?:rm|init|import)|state\s+(?:delete|rename|unprotect)",
    "cdk": r"deploy|destroy|diff|synth|bootstrap|-",
    "sam": r"deploy|delete|sync|build|local|-",
    "sls|serverless": r"deploy|remove|invoke|logs|login|-",
    "vercel": r"deploy|remove|link|pull|env|logs|login|promote|rollback|--prod|-",
    "supabase": r"db\s+(?:push|reset|pull|remote)|deploy|link|login|functions|secrets|migration|push|pull|db|-",
    "aws": r"s3api|s3|iam|ec2|rds|lambda|cloudformation|sts|ssm|secretsmanager|kms|dynamodb|sqs|sns|route53|logs|ecr|ecs|eks|apigateway|configure|--",
    "wrangler": r"deploy|publish|dev|secret|d1|kv|r2|delete|login|tail|rollback|versions|pages|types|whoami",
    "flyctl|fly": r"deploy|launch|secrets|scale|volumes?|ssh|apps?|machines?|postgres|proxy|console|destroy|auth|logs|status|ips|certs|releases|regions|redeploy|restart",
    "gcloud": r"run|compute|iam|projects|storage|sql|functions|app|secrets|auth|config|services|container|builds|deploy|kms|logging|pubsub|artifacts|organizations|alpha|beta",
    "gsutil": r"cp|mv|rm|iam|acl|ls|mb|rb|rsync|defacl",
    "bq": r"query|mk|rm|load|extract|update",
    "azd": r"up|deploy|provision|down|auth|env|init|pipeline",
    "az": r"login|account|group|deployment|storage|keyvault|role|webapp|functionapp|resource|vm|network|sql|cosmosdb|monitor|ad|acr|bicep|containerapp|--",
}
# between the tool and its verb: any number of options, each with or without a value (`-chdir=prod`, `--profile prod`, `-no-color`)
_OPTS = r"(?:\s+-[^\s]+(?:\s+[^\s-][^\s]*)?)*"
CLOUD_CMD = re.compile(r"(?:^|[^a-z0-9_./-])(?:" + "|".join(f"(?:{t})(?:{_OPTS})\\s+(?:{v})(?![a-z0-9_])" if not v.endswith("-") and not v.endswith("--")
                                                                else f"(?:{t})(?:{_OPTS})\\s+(?:{v})" for t, v in _VERBS.items()) + ")")


def _decode(t):
    for _ in range(2):
        t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), t)
        t = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), t)
        t = re.sub(r"\\[tnrfv]", " ", t)
        t = html.unescape(t)
    return unicodedata.normalize("NFKC", t)


def readings(text):
    """The reply as a reader would see it, in the ways a hidden character can be read."""
    t = _decode(text)
    out = []
    for hidden in ("", " "):            # a zero-width or control character vanishes ("terra<ZWSP>form") or stands for a space ("terraform<ZWSP>destroy")
        s = "".join(" " if c.isspace() else (hidden if unicodedata.category(c)[0] in "ZC" else c) for c in t)
        # an all-capitals AWS or AZ is the cloud named in prose ("the AWS IAM role"), not the command, so it is kept apart before folding case
        s = re.sub(r"\b(AWS|AZ|AZD)\b", r"\1_", s)
        s = re.sub(r"[\"'`\\]", "", s).casefold()
        out.append(re.sub(r" +", " ", s))
    out.append(re.sub(r"\s+", " ", text))
    return out


def find(text):
    for s in readings(text):
        m = CLOUD_CMD.search(s)
        if m:
            return m.group(0).lstrip(" ,;:([{")
    return None


if __name__ == "__main__":
    hit = find(sys.stdin.read())
    if hit:
        print(hit)
    sys.exit(1 if hit else 0)
