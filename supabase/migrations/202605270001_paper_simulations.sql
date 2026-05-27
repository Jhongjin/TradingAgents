-- Paper simulation persistence for member-only AI paper trades.
-- These tables store virtual fills only. They must never be wired to broker
-- order placement or live trading credentials.

create table if not exists public.paper_simulation_accounts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null default 'AI 모의투자',
    base_currency text not null default 'KRW',
    initial_cash numeric(18, 4) not null default 10000000,
    cash_balance numeric(18, 4) not null default 10000000,
    status text not null default 'active',
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, name)
);

create table if not exists public.paper_simulation_positions (
    id uuid primary key default gen_random_uuid(),
    account_id uuid not null references public.paper_simulation_accounts(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    analysis_run_id uuid references public.analysis_runs(id) on delete set null,
    analysis_request_id uuid references public.analysis_refresh_requests(id) on delete set null,
    ticker_code varchar(12) not null,
    ticker_name varchar(120),
    market varchar(32) not null default 'KR',
    status varchar(24) not null default 'open',
    quantity integer not null default 0,
    entry_date date,
    entry_price numeric(18, 4),
    average_price numeric(18, 4),
    target_price numeric(18, 4),
    stop_price numeric(18, 4),
    exit_date date,
    exit_price numeric(18, 4),
    exit_reason text,
    realized_pnl numeric(18, 4),
    realized_return double precision,
    decision_rating varchar(64),
    decision_action varchar(64),
    target_weight double precision,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.paper_simulation_events (
    id uuid primary key default gen_random_uuid(),
    account_id uuid not null references public.paper_simulation_accounts(id) on delete cascade,
    position_id uuid references public.paper_simulation_positions(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    analysis_run_id uuid references public.analysis_runs(id) on delete set null,
    event_type varchar(32) not null,
    side varchar(8),
    event_date date not null,
    ticker_code varchar(12) not null,
    price numeric(18, 4),
    quantity integer,
    notional numeric(18, 4),
    commission numeric(18, 4) not null default 0,
    transaction_tax numeric(18, 4) not null default 0,
    reason text,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_paper_sim_accounts_user
    on public.paper_simulation_accounts (user_id);

create index if not exists idx_paper_sim_positions_user_status
    on public.paper_simulation_positions (user_id, status, updated_at desc);

create index if not exists idx_paper_sim_positions_ticker_status
    on public.paper_simulation_positions (ticker_code, status, updated_at desc);

create index if not exists idx_paper_sim_events_position_date
    on public.paper_simulation_events (position_id, event_date desc);

create index if not exists idx_paper_sim_events_user_date
    on public.paper_simulation_events (user_id, event_date desc);

alter table public.paper_simulation_accounts enable row level security;
alter table public.paper_simulation_positions enable row level security;
alter table public.paper_simulation_events enable row level security;

drop policy if exists "users manage own paper simulation accounts" on public.paper_simulation_accounts;
create policy "users manage own paper simulation accounts"
on public.paper_simulation_accounts
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own paper simulation positions" on public.paper_simulation_positions;
create policy "users manage own paper simulation positions"
on public.paper_simulation_positions
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own paper simulation events" on public.paper_simulation_events;
create policy "users manage own paper simulation events"
on public.paper_simulation_events
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
