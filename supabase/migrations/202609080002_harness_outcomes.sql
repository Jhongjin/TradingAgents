-- Realised 5D/20D returns and benchmark alpha for harness picks (stage = ordered).
-- Rows are computed from market data after the horizon elapses; never from orders.

create table if not exists public.harness_outcomes (
    id uuid primary key default gen_random_uuid(),
    harness_decision_id uuid not null references public.harness_decisions(id) on delete cascade,
    harness_run_id uuid not null references public.harness_runs(id) on delete cascade,
    ticker_code varchar(12) not null,
    ticker_name varchar(120),
    market varchar(32) not null default 'KR',
    entry_date date not null,
    evaluated_at date not null,
    horizon_days integer not null,
    actual_holding_days integer,
    benchmark_symbol varchar(32),
    raw_return double precision,
    benchmark_return double precision,
    alpha_return double precision,
    confirmation_rating varchar(32),
    confirmation_source varchar(32),
    status varchar(32) not null default 'pending',
    error text,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (harness_decision_id, horizon_days)
);

create index if not exists idx_harness_outcomes_decision
    on public.harness_outcomes (harness_decision_id);

create index if not exists idx_harness_outcomes_run
    on public.harness_outcomes (harness_run_id);

create index if not exists idx_harness_outcomes_ticker_date
    on public.harness_outcomes (ticker_code, entry_date desc);

create index if not exists idx_harness_outcomes_status_date
    on public.harness_outcomes (status, entry_date desc);

alter table public.harness_outcomes enable row level security;

drop policy if exists "public harness outcomes are readable" on public.harness_outcomes;
create policy "public harness outcomes are readable"
on public.harness_outcomes
for select
using (
    exists (
        select 1 from public.harness_runs r
        where r.id = harness_run_id and r.visibility = 'public'
    )
);
