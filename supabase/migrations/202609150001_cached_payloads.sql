-- Somewhere to park an answer that costs real time to work out and is the same
-- for everyone who asks. The first tenant is the screener: ranking the whole
-- KOSPI and KOSDAQ tape means pulling every listed name from the vendors, which
-- takes around half a minute, and every visitor was paying it. A cron works it
-- out three times a session and the public endpoint reads the parked copy.
--
-- Only the newest row per key is ever read; the writer deletes the rest in the
-- same transaction. This is a cache, not a history.

create table if not exists public.cached_payloads (
    id uuid primary key default gen_random_uuid(),
    cache_key varchar(64) not null,
    as_of_date date,
    payload_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_cached_payloads_key_created
    on public.cached_payloads (cache_key, created_at desc);

alter table public.cached_payloads enable row level security;

-- Readable by anyone: every row here is something the public API already
-- serves. Writing is the worker's job and goes through the service role.
drop policy if exists "cached payloads are readable" on public.cached_payloads;
create policy "cached payloads are readable"
on public.cached_payloads
for select
using (true);
