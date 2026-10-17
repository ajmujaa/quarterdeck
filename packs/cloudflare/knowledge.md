Reading Cloudflare Workers files (wrangler.toml, wrangler.json or wrangler.jsonc, Worker code, R2, D1, KV). You see files, not the account: say what the files would do, never what is running.

**Configuration and environments**
- Wrangler reads TOML or JSON/JSONC configuration. Top-level keys apply to the whole Worker; named environments (`[env.production]`) do not inherit bindings and `vars`, so each environment must repeat what it uses. A binding missing from an environment, or the same ID in staging and production, is a finding.
- Resource IDs (KV namespace `id`, D1 `database_id`, R2 `bucket_name`) decide which data a Worker touches. Check that a non-production environment does not point at the production ID.

**Secrets**
- `vars` in the configuration are plain text and sit in the repo. API keys, tokens and passwords go in secrets, stored as per-environment secrets. Secrets cannot be read back once set.
- Local secrets belong in `.dev.vars`, which must be git-ignored. A committed `.dev.vars` or a secret in `vars` is a finding.

**Exposure**
- `workers_dev = true` publishes the Worker on a workers.dev address; `routes` or custom domains attach it to your own zone. Check that a Worker meant to be private, or one that sits behind Cloudflare Access or WAF rules, is not also reachable through workers.dev or a broader route pattern such as `*example.com/*`.
- Nothing in wrangler configuration adds authentication: a Worker answers anyone who can reach it unless its code checks. Look for handlers that read or write bindings with no check on the caller.
- R2: the managed `r2.dev` address makes a bucket public; Cloudflare says it is meant for testing, not production, and is rate limited. A custom domain is the production route, and if you use WAF or Access you should disable r2.dev, or the bucket stays public through it.
- Service bindings and Durable Objects expose internal Workers to the calling Worker: check what the caller can reach.

**Data: D1, KV, R2**
- D1 migrations are SQL files; read them as you would any database migration: `DROP TABLE`, `DROP COLUMN`, a rewritten table without a copy of the data. Check what an existing database holds before approving a change of `database_id` or `database_name`.
- Binding names in config must match the names the code uses; a rename breaks the Worker at runtime, not at deploy.
- KV is eventually consistent, so code that reads right after writing may see old values. R2 object deletion is permanent unless you keep copies; lifecycle rules on a bucket that delete objects need a stated reason.
- KV and R2 resources created from the dashboard have IDs that are not written back to your repository, so config and account can disagree.

**Deployment and rollback**
- `compatibility_date` and `compatibility_flags` change runtime behavior; moving the date forward is a code change in disguise.
- Cron triggers (`[triggers]`) run code on a schedule without a request: check what they write.
- Code rollback is simple; data changes in D1, KV and R2 are not undone by it.

**Cost traps**
- Workers have request and CPU limits by plan; a loop between Workers, a cron that fans out, or an unbounded R2 or KV write pattern can run up usage. Check any retry or recursion.

**Reading the diff**
- Start at routes and domains, then bindings and IDs, then secrets and `vars`, then D1 migrations, then code. Say how to roll back from the files, and when you cannot (dropped table, deleted objects), say so plainly.

**What you may do.** You read files and write a report. Never run a command against any cloud or service, never ask anyone to run one as a step of this review, and never ask for, read or repeat a credential, key or token. If a file seems to hold one, name the file and say it must be rotated; do not quote the value. The harness refuses a whole reply that contains a command line, even one quoted to describe a file or a fix, so write it in words: say "set it as a secret" or "the build step that deploys the service", never the tool name followed by a verb.
