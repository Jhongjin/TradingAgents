-- What a member wants to see out of the daily picks.
-- One row per member, holding only display preferences: markets, a rating
-- floor, a price ceiling, and tickers they never want shown. No orders, no
-- personal data beyond the Supabase user id.

create table if not exists public.member_preferences (
    user_id uuid primary key,
    markets jsonb not null default '["KOSPI", "KOSDAQ"]'::jsonb,
    exclude_etf boolean not null default true,
    min_rating varchar(24) not null default 'any',
    max_price numeric(18, 4),
    excluded_tickers jsonb not null default '[]'::jsonb,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.member_preferences enable row level security;

drop policy if exists "members read their own preferences" on public.member_preferences;
create policy "members read their own preferences"
on public.member_preferences
for select
using (auth.uid() = user_id);

drop policy if exists "members write their own preferences" on public.member_preferences;
create policy "members write their own preferences"
on public.member_preferences
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
