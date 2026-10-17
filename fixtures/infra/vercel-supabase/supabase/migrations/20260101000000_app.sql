-- FIXTURE: invented, planted risks. No real project.
create table public.notes (id uuid primary key, user_id uuid, body text);
grant all on public.notes to anon;

create table public.profiles (id uuid primary key, display_name text, is_admin boolean default false);
alter table public.profiles enable row level security;
create policy "anyone updates profiles" on public.profiles for update using (true);
create policy "admins by metadata" on public.profiles for select using ((auth.jwt() -> 'user_metadata' ->> 'role') = 'admin');

create view public.note_counts as select user_id, count(*) from public.notes group by user_id;

create function public.reset_user(target uuid) returns void language plpgsql security definer as $$
begin delete from public.notes where user_id = target; end $$;

insert into storage.buckets (id, name, public) values ('invoices', 'invoices', true);

select cron.schedule('nightly', '0 3 * * *', $$ select net.http_post('https://example.invalid/run', headers := '{"Authorization": "Bearer sb_secret_FIXTUREKEY123"}'::jsonb) $$);

alter table public.legacy drop column owner_id;
