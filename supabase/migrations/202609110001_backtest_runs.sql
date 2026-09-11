-- Rule backtests: the same screening rules replayed over past prices.
-- Kept apart from harness_runs on purpose. Those rows are executed decisions
-- sealed in a hash chain; these are an estimate over history and must never be
-- read as the account's record.

create table if not exists public.backtest_runs (
    id uuid primary key default gen_random_uuid(),
    label varchar(64) not null default 'rules',
    start_date date not null,
    end_date date not null,
    universe_size integer not null default 0,
    total_return double precision,
    benchmark_return double precision,
    excess_return double precision,
    max_drawdown double precision,
    sharpe_ratio double precision,
    hit_rate double precision,
    trade_count integer not null default 0,
    config_json jsonb not null default '{}'::jsonb,
    metrics_json jsonb not null default '{}'::jsonb,
    equity_curve_json jsonb not null default '[]'::jsonb,
    trades_json jsonb not null default '[]'::jsonb,
    notes jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_backtest_runs_label_created
    on public.backtest_runs (label, created_at desc);

alter table public.backtest_runs enable row level security;

drop policy if exists "backtest runs are readable" on public.backtest_runs;
create policy "backtest runs are readable"
on public.backtest_runs
for select
using (true);
