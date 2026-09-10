-- One row per day for the harness paper account.
-- The account itself is derived by replaying recorded fills, which can only
-- ever produce "now". Without a daily row there is no equity curve, no drawdown
-- and no benchmark comparison, and a day that passes unrecorded cannot be
-- recovered. Rows hold no order, no member data and no instruction.

create table if not exists public.paper_account_snapshots (
    id uuid primary key default gen_random_uuid(),
    snapshot_date date not null,
    account_key varchar(32) not null default 'harness',
    cash numeric(18, 4) not null,
    holdings_value numeric(18, 4) not null,
    equity numeric(18, 4) not null,
    initial_cash numeric(18, 4) not null,
    total_return double precision,
    realized_pnl numeric(18, 4),
    position_count integer not null default 0,
    priced_count integer not null default 0,
    benchmark_symbol varchar(32),
    benchmark_close double precision,
    benchmark_return double precision,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (account_key, snapshot_date)
);

create index if not exists idx_paper_account_snapshots_date
    on public.paper_account_snapshots (account_key, snapshot_date desc);

alter table public.paper_account_snapshots enable row level security;

drop policy if exists "paper account snapshots are readable" on public.paper_account_snapshots;
create policy "paper account snapshots are readable"
on public.paper_account_snapshots
for select
using (true);
