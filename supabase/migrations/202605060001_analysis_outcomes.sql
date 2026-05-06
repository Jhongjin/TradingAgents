create extension if not exists pgcrypto;

create table if not exists public.analysis_outcomes (
    id uuid primary key default gen_random_uuid(),
    analysis_run_id uuid not null references public.analysis_runs(id) on delete cascade,
    ticker_code text not null,
    ticker_name text,
    market text not null default 'KR',
    trade_date date not null,
    evaluated_at date not null,
    horizon_days integer not null check (horizon_days > 0),
    actual_holding_days integer check (actual_holding_days is null or actual_holding_days >= 0),
    entry_close numeric(18, 4),
    exit_close numeric(18, 4),
    benchmark_symbol text,
    benchmark_entry_close numeric(18, 4),
    benchmark_exit_close numeric(18, 4),
    raw_return double precision,
    benchmark_return double precision,
    alpha_return double precision,
    decision_rating text,
    decision_action text,
    status text not null default 'pending' check (status in ('pending', 'completed', 'unavailable')),
    error text,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (analysis_run_id, horizon_days)
);

create index if not exists idx_analysis_outcomes_ticker_date
    on public.analysis_outcomes (ticker_code, trade_date desc, horizon_days);

create index if not exists idx_analysis_outcomes_status
    on public.analysis_outcomes (status, evaluated_at desc);

create index if not exists idx_analysis_outcomes_run
    on public.analysis_outcomes (analysis_run_id);

alter table public.analysis_outcomes enable row level security;

drop policy if exists "analysis outcomes follow run visibility" on public.analysis_outcomes;
create policy "analysis outcomes follow run visibility"
on public.analysis_outcomes
for select
using (
    exists (
        select 1
        from public.analysis_runs ar
        where ar.id = analysis_outcomes.analysis_run_id
          and (ar.visibility = 'public' or ar.user_id = auth.uid())
    )
);
