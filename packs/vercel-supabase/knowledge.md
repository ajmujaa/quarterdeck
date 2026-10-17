Reading Vercel and Supabase files (`vercel.json`, `supabase/config.toml`, `supabase/migrations/*.sql`, `supabase/functions/**`). You see files, not the hosted projects: say what the files would do, never what is live.

**Supabase: row level security (look here first)**
- Every table in an exposed schema (usually `public`) needs `enable row level security`. Without it anyone holding the public anon key can read and write the table through the auto-generated API. With it enabled and no policy, access is denied (the service role still bypasses).
- A policy has `using` (which existing rows are visible or changeable) and `with check` (what a new or updated row may look like). Insert needs `with check`; update needs both. A write policy with only `using`, or `with check (true)`, lets a user write rows they should not.
- `using (true)` is public. `auth.uid() is not null` means "signed in", not "owner": ownership is `user_id = (select auth.uid())`. Name the role with `to authenticated` or `to anon`.
- Never base a policy on `auth.jwt() -> 'user_metadata'`: users can edit it. `app_metadata` is server-controlled.
- Also look for: `alter table ... disable row level security`, `grant ... to anon` (or `to public`) on a table, a policy `for all` or `to public` with `using (true)`, and a table in a non-`public` schema that the API exposes (`[api] schemas` in config.toml). `force row level security` makes the owner obey policies too.
- A view runs with its owner's rights and skips RLS unless created with `security_invoker = true`. A `security definer` function also skips RLS: it needs a fixed `search_path`, and `revoke execute ... from public, anon` unless meant to be public.
- Tables in a realtime publication need the same policies.

**Keys and environment variables**
- The service-role (secret) key bypasses RLS. It must never reach client code: not in a `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_` or `EXPO_PUBLIC_` variable, not in a committed file, not hard-coded in a migration or function. The anon (publishable) key is public by design and is safe only if RLS is right.
- Vercel variables are scoped to Production, Preview and Development, and a change reaches only new deployments. Check that Preview does not point at the production database or use production keys; a preview deployment that can write to production data is a finding.
- A variable with a browser-exposed prefix is public. Secrets belong in server-only variables. Signs of a service-role key: a name containing `SERVICE_ROLE` or `sb_secret_`, or a long `eyJ...` token whose payload says `service_role`. Check `.env.example`, `vercel.json` (`env`, `build.env`), `config.toml` `env(...)` use, workflows and frontend code that builds a client with it.
- Environment variables are not in the files: say that Vercel's scopes, "sensitive" setting and the Preview database cannot be checked here and need a person.

**Migrations**
- They run in filename order, once. Never edit one that has been applied: add a new one. A new file dated earlier than an applied one is out of order.
- Irreversible with no down step: `drop table`, `drop column`, `truncate`, `delete` without a narrow `where`, narrowing a column type, `drop ... cascade` (it drops dependent objects too). Say what data is lost.
- Risky on a populated table: `not null` without a default or backfill, a type change that rewrites the table, a plain `create index` that blocks writes (`concurrently` avoids that, but cannot run inside a transaction block).
- `seed.sql` is for local and branch databases; do not read it as production data.
- Schema changes and policies should land together: a table created in one migration and given RLS in a later one is exposed in between.

**Edge functions**
- `verify_jwt = false` in `config.toml` (or deploying with the no-verify flag) lets anyone call the function. It is right for webhooks only if the function checks the sender itself (a signature). Look for that check.
- A function using the service-role key acts with full rights: it must authenticate the caller and limit what it does. Secrets come from function secrets, never from code. Look at CORS: `Access-Control-Allow-Origin: *` on an endpoint that uses cookies or tokens.
- In the function code: is the caller identified (`auth.getUser(token)` with the request's `Authorization` header) before anything is read or written? A client built with the service-role key that then trusts a `user_id` from the request body lets any caller act as any user. Reading the `Authorization` header without verifying it is not authentication. Check for input validation, and that errors do not echo secrets. The code may be a stub: say so and judge only what is there.

**Storage**
- Public buckets show up two ways: `insert into storage.buckets ... public` set to `true` in a migration, and `[storage.buckets.<name>] public = true` in config.toml. Either serves every object to anyone with the URL.
- A bucket with `public = true` serves every object to anyone with the URL. Private buckets are governed by policies on `storage.objects`; check `bucket_id` is in each policy and that write policies have `with check`. Look at `file_size_limit` and `allowed_mime_types`.

**Auth settings**
- `site_url` and `additional_redirect_urls`: no wildcard that matches foreign hosts, no `http://` for production. Look at `enable_signup`, email confirmation, `minimum_password_length`, and `jwt_expiry`.

**Cron, webhooks, and Vercel config**
- `cron.schedule(...)` in a migration runs in the production database; an HTTP call there with an `Authorization` header holding a literal key puts a secret in git. Use Vault or a function secret.
- `crons` in `vercel.json` call a path on the production deployment: the endpoint is publicly reachable unless it checks the `CRON_SECRET` bearer token. Check schedule frequency and the function `maxDuration`.
- `headers`, `rewrites`, `redirects`: a redirect built from user input is an open redirect; a rewrite to an external host sends traffic and headers there (an API proxy that adds a secret header makes that host reachable by anyone); `Access-Control-Allow-Origin: *` on API routes; `Cache-Control: public` on a private response; a changed or removed security header (`Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`) is a finding, a tidy-up of one is not. A rewrite or redirect placed above another one can shadow it.
- Other `vercel.json` keys: `public: true` serves the source files; `functions` memory and `maxDuration` raise cost; `regions` move compute away from the database; `ignoreCommand` and `github.enabled` change what deploys; a literal value in `env` or `build.env` is committed in plain text.
- Webhook receivers must verify the sender's signature.

For each item say how to undo it from the files, and when you cannot (dropped data, a leaked key that must be rotated), say so plainly.


**What you may do.** You read files and write a report. Never run a command against any cloud or service, never ask anyone to run one as a step of this review, and never ask for, read or repeat a credential, key or token. If a file seems to hold one, name the file and say it must be rotated; do not quote the value. The harness refuses a whole reply that contains a command line, even one quoted to describe a file or a fix, so write it in words: say "set it as a secret" or "the build step that deploys the service", never the tool name followed by a verb.
