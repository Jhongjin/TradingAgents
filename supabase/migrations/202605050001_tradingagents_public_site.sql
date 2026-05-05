create extension if not exists pgcrypto;

create table if not exists public.analysis_runs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete set null,
    ticker_code text not null,
    ticker_name text,
    market text not null default 'KR',
    trade_date date not null,
    status text not null default 'pending',
    visibility text not null default 'public' check (visibility in ('public', 'private')),
    model_provider text,
    deep_model text,
    quick_model text,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists public.agent_reports (
    id uuid primary key default gen_random_uuid(),
    analysis_run_id uuid not null references public.analysis_runs(id) on delete cascade,
    role text not null,
    title text,
    content text not null,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (analysis_run_id, role)
);

create table if not exists public.trade_decisions (
    id uuid primary key default gen_random_uuid(),
    analysis_run_id uuid not null references public.analysis_runs(id) on delete cascade,
    rating text not null,
    action text not null,
    target_weight double precision,
    rationale text not null default '',
    raw_decision text not null default '',
    created_at timestamptz not null default now(),
    unique (analysis_run_id)
);

create table if not exists public.manual_portfolios (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    base_currency text not null default 'KRW',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.manual_trades (
    id uuid primary key default gen_random_uuid(),
    portfolio_id uuid not null references public.manual_portfolios(id) on delete cascade,
    ticker_code text not null,
    ticker_name text,
    market text not null default 'KR',
    side text not null check (side in ('buy', 'sell')),
    trade_date date not null,
    price numeric(18, 4) not null check (price > 0),
    quantity integer not null check (quantity > 0),
    fee numeric(18, 4) not null default 0 check (fee >= 0),
    tax numeric(18, 4) not null default 0 check (tax >= 0),
    memo text,
    created_at timestamptz not null default now()
);

create table if not exists public.manual_price_targets (
    id uuid primary key default gen_random_uuid(),
    portfolio_id uuid not null references public.manual_portfolios(id) on delete cascade,
    ticker_code text not null,
    target_price numeric(18, 4),
    stop_price numeric(18, 4),
    memo text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (portfolio_id, ticker_code),
    check (target_price is null or target_price > 0),
    check (stop_price is null or stop_price > 0)
);

create index if not exists idx_analysis_runs_ticker_date
    on public.analysis_runs (ticker_code, trade_date desc);
create index if not exists idx_analysis_runs_visibility_date
    on public.analysis_runs (visibility, trade_date desc);
create index if not exists idx_agent_reports_run
    on public.agent_reports (analysis_run_id);
create index if not exists idx_manual_portfolios_user
    on public.manual_portfolios (user_id);
create index if not exists idx_manual_trades_portfolio_date
    on public.manual_trades (portfolio_id, trade_date desc);
create index if not exists idx_manual_trades_ticker
    on public.manual_trades (ticker_code);

alter table public.analysis_runs enable row level security;
alter table public.agent_reports enable row level security;
alter table public.trade_decisions enable row level security;
alter table public.manual_portfolios enable row level security;
alter table public.manual_trades enable row level security;
alter table public.manual_price_targets enable row level security;

drop policy if exists "analysis runs are readable" on public.analysis_runs;
create policy "analysis runs are readable"
on public.analysis_runs
for select
using (visibility = 'public' or auth.uid() = user_id);

drop policy if exists "users can insert own analysis runs" on public.analysis_runs;
create policy "users can insert own analysis runs"
on public.analysis_runs
for insert
with check (auth.uid() = user_id);

drop policy if exists "users can update own analysis runs" on public.analysis_runs;
create policy "users can update own analysis runs"
on public.analysis_runs
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "agent reports follow run visibility" on public.agent_reports;
create policy "agent reports follow run visibility"
on public.agent_reports
for select
using (
    exists (
        select 1
        from public.analysis_runs ar
        where ar.id = agent_reports.analysis_run_id
          and (ar.visibility = 'public' or ar.user_id = auth.uid())
    )
);

drop policy if exists "trade decisions follow run visibility" on public.trade_decisions;
create policy "trade decisions follow run visibility"
on public.trade_decisions
for select
using (
    exists (
        select 1
        from public.analysis_runs ar
        where ar.id = trade_decisions.analysis_run_id
          and (ar.visibility = 'public' or ar.user_id = auth.uid())
    )
);

drop policy if exists "users manage own portfolios" on public.manual_portfolios;
create policy "users manage own portfolios"
on public.manual_portfolios
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own manual trades" on public.manual_trades;
create policy "users manage own manual trades"
on public.manual_trades
for all
using (
    exists (
        select 1
        from public.manual_portfolios mp
        where mp.id = manual_trades.portfolio_id
          and mp.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.manual_portfolios mp
        where mp.id = manual_trades.portfolio_id
          and mp.user_id = auth.uid()
    )
);

drop policy if exists "users manage own manual price targets" on public.manual_price_targets;
create policy "users manage own manual price targets"
on public.manual_price_targets
for all
using (
    exists (
        select 1
        from public.manual_portfolios mp
        where mp.id = manual_price_targets.portfolio_id
          and mp.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.manual_portfolios mp
        where mp.id = manual_price_targets.portfolio_id
          and mp.user_id = auth.uid()
    )
);
