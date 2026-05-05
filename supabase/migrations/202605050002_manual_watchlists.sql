create table if not exists public.manual_watchlists (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.manual_watchlist_items (
    id uuid primary key default gen_random_uuid(),
    watchlist_id uuid not null references public.manual_watchlists(id) on delete cascade,
    ticker_code text not null,
    ticker_name text,
    market text not null default 'KR',
    memo text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (watchlist_id, ticker_code)
);

create index if not exists idx_manual_watchlists_user
    on public.manual_watchlists (user_id);
create index if not exists idx_manual_watchlist_items_watchlist
    on public.manual_watchlist_items (watchlist_id);
create index if not exists idx_manual_watchlist_items_ticker
    on public.manual_watchlist_items (ticker_code);

alter table public.manual_watchlists enable row level security;
alter table public.manual_watchlist_items enable row level security;

drop policy if exists "users manage own watchlists" on public.manual_watchlists;
create policy "users manage own watchlists"
on public.manual_watchlists
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own watchlist items" on public.manual_watchlist_items;
create policy "users manage own watchlist items"
on public.manual_watchlist_items
for all
using (
    exists (
        select 1
        from public.manual_watchlists wl
        where wl.id = manual_watchlist_items.watchlist_id
          and wl.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.manual_watchlists wl
        where wl.id = manual_watchlist_items.watchlist_id
          and wl.user_id = auth.uid()
    )
);
